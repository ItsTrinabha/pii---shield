"""Web UI API: CSRF, no raw values by default, the release gate, page renders and downloads. Synthetic data only."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from pii_shield.app import server
from pii_shield.settings import Settings

from .fixtures import SYN_VALUES, docx_bytes, pdf_bytes


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(server, "Settings", lambda use_gliner=False: Settings(use_ner=False))
    server.DOCS.clear()
    c = TestClient(server.create_app())
    assert c.get("/").status_code == 200  # sets the CSRF cookie
    return c


def _scan(c: TestClient, data: bytes, name: str) -> dict:
    r = c.post("/api/scan", files={"file": (name, data)}, headers={"x-csrf-token": c.cookies["pii_csrf"]})
    assert r.status_code == 200, r.text
    return r.json()


def _no_raw(text: str) -> None:
    for v in SYN_VALUES:
        assert v not in text, v


def test_scan_requires_csrf(client) -> None:
    r = client.post("/api/scan", files={"file": ("a.docx", docx_bytes())})
    assert r.status_code == 403


def test_default_responses_carry_no_raw_values(client) -> None:
    d = _scan(client, docx_bytes(), "a.docx")
    assert d["counts"]["findings"] > 0 and d["accuracy"] is None and d["quality"]["mean_confidence"]
    _no_raw(client.get("/api/docs").text)
    _no_raw(client.get(f"/api/docs/{d['id']}").text)
    _no_raw(client.get(f"/api/docs/{d['id']}/blocks").text)
    _no_raw(client.get(f"/api/docs/{d['id']}/download/audit.json").text)
    _no_raw(client.get(f"/api/docs/{d['id']}/download/audit.html").text)
    revealed = client.get(f"/api/docs/{d['id']}/blocks?reveal=1").text  # explicit reviewer request only
    assert any(v in revealed for v in SYN_VALUES)


def test_release_gate_and_downloads(client) -> None:
    d = _scan(client, docx_bytes(), "a.docx")
    did, tok = d["id"], client.cookies["pii_csrf"]
    if d["status"] == "REVIEW":
        assert client.get(f"/api/docs/{did}/download/sanitized.txt").status_code == 409
        assert client.post(f"/api/docs/{did}/approve", json={"name": ""}, headers={"x-csrf-token": tok}).status_code == 400
        assert client.post(f"/api/docs/{did}/approve", json={"name": "Tester"}).status_code == 403
        r = client.post(f"/api/docs/{did}/approve", json={"name": "Tester"}, headers={"x-csrf-token": tok})
        assert r.status_code == 200 and r.json()["released"]
    s = client.get(f"/api/docs/{did}/download/sanitized.txt")
    assert s.status_code == 200
    _no_raw(s.text)
    red = client.get(f"/api/docs/{did}/download/redacted")
    assert red.status_code == 200 and red.content[:2] == b"PK"


def test_pdf_page_render(client) -> None:
    d = _scan(client, pdf_bytes(), "a.pdf")
    assert d["has_pages"]
    for reveal in (0, 1):
        r = client.get(f"/api/docs/{d['id']}/page/1?reveal={reveal}")
        assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/api/docs/{d['id']}/page/99").status_code == 404


def test_unknown_document(client) -> None:
    assert client.get("/api/docs/nope").status_code == 404


def test_manual_redaction_and_reapproval(client) -> None:
    d = _scan(client, docx_bytes(["Project codename Bluefinch launches next quarter."]), "m.docx")
    did, tok = d["id"], client.cookies["pii_csrf"]
    b = next(x for x in client.get(f"/api/docs/{did}/blocks").json() if "Bluefinch" in x["text"])
    s = b["text"].index("Bluefinch")
    r = client.post(f"/api/docs/{did}/redact", headers={"x-csrf-token": tok},
                    json={"block_id": b["id"], "start": s, "end": s + 9, "coords": "sanitized", "type": "UNCLASSIFIED"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "REVIEW" and not r.json()["released"] and r.json()["added"] == 1
    assert "Bluefinch" not in client.get(f"/api/docs/{did}/blocks").text
    assert client.get(f"/api/docs/{did}/download/sanitized.txt").status_code == 409  # an edit needs a named approval
    again = client.post(f"/api/docs/{did}/redact", headers={"x-csrf-token": tok},
                        json={"block_id": b["id"], "start": s, "end": s + 9, "coords": "original", "type": "UNCLASSIFIED"})
    assert again.status_code == 409  # already masked
    ok = client.post(f"/api/docs/{did}/approve", json={"name": "Tester"}, headers={"x-csrf-token": tok})
    assert ok.status_code == 200
    out = client.get(f"/api/docs/{did}/download/sanitized.txt").text
    assert "Bluefinch" not in out and "[UNCLASSIFIED_1]" in out


def test_redact_requires_csrf_and_valid_span(client) -> None:
    d = _scan(client, docx_bytes(), "a.docx")
    did, tok = d["id"], client.cookies["pii_csrf"]
    bid = client.get(f"/api/docs/{did}/blocks").json()[0]["id"]
    assert client.post(f"/api/docs/{did}/redact", json={"block_id": bid, "start": 0, "end": 3}).status_code == 403
    assert client.post(f"/api/docs/{did}/redact", headers={"x-csrf-token": tok}, json={"block_id": bid}).status_code == 400
    det = client.get(f"/api/docs/{did}").json()
    assert "attention" in det


def test_selection_across_a_token(client) -> None:
    d = _scan(client, docx_bytes(["Reach her at o.brennagh@example.test before Friday."]), "t.docx")
    did, tok = d["id"], client.cookies["pii_csrf"]
    b = next(x for x in client.get(f"/api/docs/{did}/blocks").json() if "[EMAIL_" in x["text"])
    s, e = b["text"].index("her"), b["text"].index("Friday") + len("Friday")
    r = client.post(f"/api/docs/{did}/redact", headers={"x-csrf-token": tok},
                    json={"block_id": b["id"], "start": s, "end": e, "coords": "sanitized", "type": "UNCLASSIFIED"})
    assert r.status_code == 200, r.text
    after = next(x for x in client.get(f"/api/docs/{did}/blocks").json() if x["id"] == b["id"])["text"]
    assert "Friday" not in after and "her at" not in after and "[EMAIL_" in after
