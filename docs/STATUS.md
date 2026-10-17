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
- 2026-10-11: eval re-run with Tesseract 5.5.3 found leaks (PDF 3/260 BLOCKED, DOCX 1/23 REVIEW). Fixed phones split by OCR layout
  (prefix and continuation separated by a neighbouring cell, or by an OCR paragraph boundary): detector
  `patterns.split_phone_pair` + cross-block pass in `engine`; verifier cross-block rule and short `+cc area` rule;
  heal loop redacts around existing tokens (`sanitized_to_original_parts`); leak metric ignores tokens inside a value;
  precision counts split halves by identity fingerprint. Regression: `tests/test_split_phone.py`.
- 2026-10-11: SOFT name hits in OCR-derived blocks are auto-redacted as forced redactions (native text never; UI labels
  and business words skipped; status stays REVIEW, reason `OCR_NAME_REDACTION`; audit `forced_ocr_name_candidates`).
  Tests: `tests/test_ocr_name_redaction.py`. Eval OCR memory capped (`--ocr-workers 2`, page images freed after OCR).

- 2026-10-11: demo check (`scripts/demo_check.py`, Streamlit AppTest on all three samples): no exceptions; PPTX PASS and
  released; DOCX and PDF REVIEW, no sanitised download before approval, released after a named approval; reveal off by
  default; audit downloads present. The released DOCX preview contains known leaked values (the leaks in RESULTS.md),
  which is the reviewer's residual risk. Fixed: sanitised blocks with a verifier HARD hit are hidden unless reveal is on;
  deprecated `use_container_width` replaced.

## Environment notes (Windows)
- venv at `.venv`; Tesseract is auto-found in `C:\Program Files\Tesseract-OCR` (or set `CLOAK_TESSERACT`).
- LibreOffice installed 2026-10-11 (EMF/WMF OCR, `--render-ocr`); auto-found in `C:\Program Files\LibreOffice\program`.
- Without Tesseract all three samples are BLOCKED (OCR_FAILED): every sample contains images. This is intended.

## Known caveats
- PPTX GT is independent. DOCX and PDF GT were built from detector output then hand-pruned => CIRCULAR; regression only.
- 2026-10-11 eval (`docs/RESULTS.md`): leaked values PPTX 0/61, DOCX 0/23, PDF 0/260. PPTX PASS; DOCX and PDF REVIEW
  (forced redactions by the verifier, incl. OCR-noise name auto-redaction). PDF PHONE precision 0.903 is the cost.
- 2026-10-11 (b): independent GT for DOCX and PDF (`data/ground_truth/ANNOTATION.md`); old GT in
  `data/ground_truth_regression/`. It exposed leaks the circular GT hid: DOCX 3/23 (two-letter-initial first names; a
  person named like a UI label, skipped by the OCR-name UI filter), PDF 2/264 (SSN last-4 in brackets,
  partly masked PESEL). Both documents stay REVIEW. Not fixed yet (tuning on the reporting set; see TODO).
- Lone country codes (`+1`, `+44`) stay readable when the rest of the number is tokenised: deliberate, see SECURITY.md.
- Eval memory: run one file at a time with `--only`; `--ocr-workers` defaults to 2. A full 3-file run in one process
  was killed by the OS for low memory before these changes; not re-tried.
- The verifier's name bigram uses non-overlapping matching, so a capitalised noise word directly before a name can hide
  it (`Frapenecrmas Dana ...`). Not fixed.

## TODO (in order)
0. Six-step plan of 2026-10-11: [x] 1 independent GT, [x] 2 structure metric, [x] 3 OCR vs native, [x] 4 demo check,
   [x] 5 deliverable docs, [x] 6 RESULTS/STATUS after each.
1. Close the leaks found by the independent GT (two-letter initials, UI-label-like names in OCR, SSN last-4 in prose,
   masked national IDs); needs a hold-out split first, since these documents are also the reporting set.
2. Reduce PDF forced redactions (detector misses split phones whose interleaved cell has standalone numbers, and
   OCR-regrouped digits) so PHONE precision recovers; fix the verifier bigram overlap gap.
3. (done: structure metric docs/METRICS.md, OCR vs native in RESULTS.md) OCR-name auto-redaction costs precision on fully scanned documents; revisit.
4. Visual redaction of scanned PDFs (burn boxes from WordBox geometry). 5. pip-audit.
6. Benchmarks on ai4privacy/Kaggle/Mendeley (download locally, check licences).
7. Optiv deck (14 Oct 2026); demo recording. (Docs done: README, ARCHITECTURE, FUNCTIONAL_DESIGN, THREAT_MODEL, FILE_ANALYSIS, DECISIONS, LIMITATIONS, WALKTHROUGH, METRICS.)
