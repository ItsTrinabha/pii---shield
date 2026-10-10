# Status handoff

## Done
- Extraction: PDF (native + scanned OCR), PPTX, DOCX (+ images, EMF/WMF via LibreOffice), safe-parsing checks.
- Detection: regex+validators, Presidio/spaCy NER, name context + gazetteer layer, noisy-OR fusion.
- Masking (stable tokens, HMAC fingerprints), independent verifier (HARD/SOFT), heal loop, PASS/REVIEW/BLOCKED gate.
- CLI: `python -m pii_shield scan FILE --out out/`; audit JSON/HTML (no raw PII).
- Eval: `python -m pii_shield.eval` (value-based GT in data/ground_truth); BLOCKED documents are reported, not crashed on.
- 2026-10-11: line-wrapped phone bug fixed in `patterns._unwrap` and verifier `_PHONE_A/_PHONE_B`
  (regression: `tests/test_phone_wrap.py`, fails on the old code, passes now).
- 2026-10-11: `tests/` created: security (zip bomb, traversal, XXE, type confusion, encrypted, corrupt, empty, size),
  fail-closed gate, no PII in logs/reports, no network (with and without NER), unicode evasion, prompt-injection text,
  stable tokens, gateway, Streamlit smoke. `pytest -q` green (fast + slow markers).
- 2026-10-11: Streamlit app `src/pii_shield/app/main.py` (+ `.streamlit/config.toml`: telemetry off, 100 MB limit).
- 2026-10-11: `gateway.ask_llm` accepts only a sealed `SanitizedText` from `release()`; instruction also verified.
- 2026-10-11: `docs/SECURITY.md` checklist.

## Environment notes (Windows)
- venv at `.venv`; Tesseract is auto-found in `C:\Program Files\Tesseract-OCR` (or set `PII_SHIELD_TESSERACT`).
- LibreOffice optional (EMF/WMF); auto-found in `C:\Program Files\LibreOffice\program`.
- Without Tesseract all three samples are BLOCKED (OCR_FAILED): every sample contains images. This is intended.

## Known caveats
- PPTX GT is independent. DOCX and PDF GT were built from detector output then hand-pruned => CIRCULAR; regression only.
- Eval NOT yet re-run after the phone fix (needs Tesseract). Do not quote numbers until it is.

## TODO (in order)
1. Install Tesseract, re-run `python -m pii_shield.eval`; leak must be 0. Record in docs/RESULTS.md.
2. Independent GT for DOCX/PDF (annotate from page images). 3. OCR-vs-native eval + structure-retention metric.
4. Visual redaction of scanned PDFs (burn boxes from WordBox geometry). 5. pip-audit.
6. Benchmarks on ai4privacy/Kaggle/Mendeley (download locally, check licences).
7. THREAT_MODEL.md, README, RESULTS.md, FILE_ANALYSIS.md, DECISIONS.md, Mermaid diagrams, walkthrough, Optiv deck (14 Oct 2026).
