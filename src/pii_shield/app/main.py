"""PII Shield demo UI.  Run:  streamlit run src/pii_shield/app/main.py

Privacy rules for this UI: original text is hidden unless the operator deliberately turns on "reveal"; the sanitised
download goes through release() (the same gate an LLM integration uses); audit downloads carry no raw values."""

from __future__ import annotations

import html
import re
from collections import Counter
from pathlib import Path

import streamlit as st

from pii_shield import process_bytes
from pii_shield.errors import BlockedError
from pii_shield.models import CLASSIFICATION, PipelineResult, Status
from pii_shield.pipeline import release
from pii_shield.reporting import audit_html, audit_json
from pii_shield.security import sha256_hex
from pii_shield.settings import Settings

SAMPLES = Path(__file__).resolve().parents[3] / "data" / "samples"
_TOKEN = re.compile(r"\[[A-Z_]+_\d+\]")
_BANNER = {
    Status.PASS: ("success", "PASS: sanitised and independently verified. Safe to release to an LLM."),
    Status.REVIEW: ("warning", "REVIEW: sanitised, but a human must approve before release."),
    Status.BLOCKED: ("error", "BLOCKED: this document will not be released."),
}

st.set_page_config(page_title="PII Shield", page_icon=":shield:", layout="wide")


@st.cache_resource(show_spinner=False, max_entries=8)
def _run(digest: str, data: bytes, name: str, use_ner: bool, strict: bool) -> PipelineResult:
    # `digest` is part of the cache key; results live only in this server process's memory
    return process_bytes(data, name, Settings(use_ner=use_ner, strict_verifier=strict))


def _mark_original(text: str, spans: list[tuple[int, int, str]]) -> str:
    out, pos = [], 0
    for s, e, typ in sorted(spans):
        if s < pos:
            continue
        out.append(html.escape(text[pos:s]))
        out.append(f'<mark title="{html.escape(typ)}" style="background:#ffd8a8">{html.escape(text[s:e])}</mark>')
        pos = e
    out.append(html.escape(text[pos:]))
    return "".join(out).replace("\n", "<br>")


def _mark_tokens(text: str) -> str:
    esc = html.escape(text)
    return _TOKEN.sub(lambda m: f'<span style="background:#c3fae8;font-weight:600">{m.group(0)}</span>', esc).replace("\n", "<br>")


# ---- sidebar: input + settings -------------------------------------------------------------------------------
with st.sidebar:
    st.title(":shield: PII Shield")
    st.caption("Fail-closed PII gateway between documents and an LLM. Processing is local; nothing leaves this machine.")
    src = st.radio("Input", ["Upload a file", "Cadence sample"], horizontal=True)
    data: bytes | None = None
    name = ""
    if src == "Upload a file":
        up = st.file_uploader("PDF, PPTX or DOCX", type=["pdf", "pptx", "docx"])
        if up is not None:
            data, name = up.getvalue(), up.name
    else:
        samples = sorted(p.name for p in SAMPLES.glob("*") if p.suffix.lower() in (".pdf", ".pptx", ".docx"))
        if samples:
            pick = st.selectbox("Sample", samples)
            data, name = (SAMPLES / pick).read_bytes(), pick
        else:
            st.info("No samples found in data/samples.")
    st.divider()
    use_ner = st.toggle("NER layer (spaCy + Presidio)", value=True, help="Off = deterministic rules only (faster, lower name recall)")
    strict = st.toggle("Strict verifier", value=False, help="Soft verifier hits BLOCK instead of REVIEW")
    reveal = st.toggle("Reveal original text", value=False,
                       help="Shows raw PII on screen. Keep off during screen-sharing unless you mean to show it.")

if data is None:
    st.header("Upload a document to begin")
    st.markdown(
        "**Pipeline:** extract (native / OCR) → normalise → detect (rules + NER + names) → fuse → mask with stable "
        "tokens → **independent verifier** → heal → **gate**: PASS / REVIEW / BLOCKED."
    )
    st.stop()

digest = sha256_hex(data)
with st.spinner(f"Processing {name} … (scanned PDFs are OCR'd page by page; this can take a minute)"):
    r = _run(digest, data, name, use_ner, strict)

# ---- status banner --------------------------------------------------------------------------------------------
kind, msg = _BANNER[r.status]
getattr(st, kind)(f"**{msg}**")
for reason in r.reasons:
    st.markdown(f"- `{reason}`")

doc = r.document
if doc is None:
    st.caption("Extraction failed, so nothing was analysed or released. The audit report records why.")
    st.download_button("Audit report (JSON)", audit_json(r), f"{Path(name).stem}.audit.json", "application/json")
    st.stop()

ver = r.verification
c = st.columns(6)
c[0].metric("Findings", len(r.findings))
c[1].metric("Distinct values", len({(f.type, f.fingerprint) for f in r.findings}))
c[2].metric("Blocks", doc.stats.block_count or len(doc.blocks))
c[3].metric("OCR pages / mean conf.", f"{doc.stats.ocr_pages} / {doc.stats.mean_ocr_confidence or '–'}")
c[4].metric("Forced by verifier", r.notes.get("forced_redactions", 0))
c[5].metric("Time (s)", r.timings.get("total", "–"))

tab_find, tab_side, tab_exp, tab_ver, tab_dl = st.tabs(
    ["Findings", "Original vs sanitised", "Exposure summary", "Verification", "Release & downloads"])

# ---- findings table (no raw values) -------------------------------------------------------------------------
with tab_find:
    types = sorted({f.type for f in r.findings})
    sel = st.multiselect("Types", types, default=types)
    rows = [
        {"id": f.id, "type": f.type, "class": CLASSIFICATION.get(f.type, ("", ""))[0], "token": f.token,
         "location": f.locator.label(), "block": f.block_id, "chars": f"{f.start}–{f.end}",
         "confidence": round(f.confidence, 2), "detectors": ", ".join(f.detectors), "OCR": f.ocr_derived}
        for f in r.findings if f.type in sel
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption("Values are never shown here: each row is traceable via file → location → block → char span → detector.")

# ---- side by side ------------------------------------------------------------------------------------------
with tab_side:
    san = {b.id: b for b in r.sanitized_blocks}
    by_block: dict[str, list] = {}
    for f in r.findings:
        by_block.setdefault(f.block_id, []).append(f)
    units = list(dict.fromkeys(b.locator.label().split(" / ")[0] for b in doc.blocks))
    cc = st.columns([2, 1])
    unit = cc[0].selectbox("Location", units)
    only = cc[1].checkbox("Only blocks with findings", value=True)
    if not reveal:
        st.info("Original text is hidden. Turn on **Reveal original text** in the sidebar to compare.")
    for b in doc.blocks:
        if b.locator.label().split(" / ")[0] != unit or (only and b.id not in by_block):
            continue
        st.caption(f"{b.locator.label()} · block `{b.id}` · {b.source}"
                   + (f" · OCR conf {b.ocr_confidence}" if b.ocr_confidence is not None else ""))
        left, right = st.columns(2)
        if reveal:
            left.markdown(_mark_original(b.text, [(f.start, f.end, f.type) for f in by_block.get(b.id, [])]),
                          unsafe_allow_html=True)
        else:
            left.markdown("<span style='color:#888'>(hidden)</span>", unsafe_allow_html=True)
        if b.id in san:
            right.markdown(_mark_tokens(san[b.id].text), unsafe_allow_html=True)

# ---- exposure ---------------------------------------------------------------------------------------------
with tab_exp:
    a, b2 = st.columns(2)
    a.subheader("By type")
    a.bar_chart(dict(Counter(f.type for f in r.findings).most_common()), horizontal=True)
    b2.subheader("By classification")
    b2.bar_chart(dict(Counter(CLASSIFICATION.get(f.type, ("Unclassified", ""))[0] for f in r.findings).most_common()),
                 horizontal=True)
    st.subheader("By location")
    loc_counts = Counter(f.locator.label().split(" / ")[0] for f in r.findings)
    st.dataframe([{"location": k, "findings": v} for k, v in loc_counts.most_common()], hide_index=True,
                 use_container_width=True)
    with st.expander("Extraction statistics"):
        st.json(doc.stats.model_dump())
        if doc.warnings:
            st.write(doc.warnings)

# ---- verification -----------------------------------------------------------------------------------------
with tab_ver:
    if ver is None:
        st.write("Verifier did not run (extraction failed).")
    else:
        st.markdown(f"Independent verifier: **{len(ver.hard_hits)} hard** / **{len(ver.soft_hits)} soft** hits "
                    f"after healing; {r.notes.get('forced_redactions', 0)} item(s) force-redacted.")
        st.caption("The verifier shares no code with the detectors, so a detector blind spot is not repeated here.")
        hits = [{"severity": h.severity, "rule": h.rule, "location": h.locator.label(), "block": h.block_id,
                 "chars": f"{h.start}–{h.end}"} for h in ver.hard_hits + ver.soft_hits]
        st.dataframe(hits, hide_index=True, use_container_width=True)
        st.write("Rules run:", ", ".join(ver.rules_run))
    cands = r.notes.get("review_candidates", [])
    if cands:
        st.subheader("Low-confidence candidates (not masked)")
        st.dataframe(cands, hide_index=True, use_container_width=True)

# ---- release + downloads ----------------------------------------------------------------------------------
with tab_dl:
    stem = Path(doc.file_name).stem
    d1, d2 = st.columns(2)
    d1.download_button("Audit report (JSON)", audit_json(r), f"{stem}.audit.json", "application/json")
    d2.download_button("Audit report (HTML)", audit_html(r), f"{stem}.audit.html", "text/html")
    st.divider()
    approver = None
    if r.status == Status.REVIEW:
        st.warning("Release requires a named reviewer who has checked the reasons above.")
        approver = st.text_input("Reviewer name") or None
        if approver and not st.checkbox("I reviewed the flagged items and approve release"):
            approver = None
    try:
        released = release(r, approved_by=approver)
    except BlockedError as e:
        st.error(f"Sanitised text not released: {e}")
    else:
        st.success("Released through the gate" + (f" (approved by {approver})" if approver else "") + ".")
        txt = released.to_text()
        st.download_button("Sanitised text (LLM-safe)", txt, f"{stem}.sanitized.txt", "text/plain")
        with st.expander("Preview sanitised text"):
            st.text(txt[:20000])
