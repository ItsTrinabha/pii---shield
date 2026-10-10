# Status handoff (for Claude Code)

## Done
- Extraction: PDF (native + scanned OCR), PPTX, DOCX (+ images, EMF/WMF via LibreOffice), safe-parsing checks.
- Detection: regex+validators, Presidio/spaCy NER, name context + gazetteer layer, noisy-OR fusion.
- Masking (stable tokens, HMAC fingerprints), independent verifier (HARD/SOFT), heal loop, PASS/REVIEW/BLOCKED gate.
- CLI: `python -m pii_shield scan FILE --out out/`; audit JSON/HTML (no raw PII).
- Eval: `python -m pii_shield.eval` (value-based GT in data/ground_truth).

## Known caveats
- PPTX GT is independent. DOCX and PDF GT were built from detector output then hand-pruned => CIRCULAR; use only as regression, not as accuracy claims.
- OPEN BUG (fix first): PDF phones split across lines (e.g. "+1 (704)\n555-0166", "+46 8\n5555 0121", "+49 69\n5555 0177")
  stay readable in sanitized text; neither detector nor verifier catches them. Fix detection (allow newline between phone groups
  in patterns.detect_phone) AND verifier (_PHONE_A/_PHONE_B must tolerate \n). Then re-run eval; leak must be 0.
- 3 forced redactions on the PDF are OCR-scrambled table phones (expected, fail-closed working).

## TODO
1. Fix the open bug above. 2. Streamlit app (src/pii_shield/app/main.py). 3. Security tests (zip bomb, path traversal, XXE, type
confusion, corrupt/encrypted, unicode obfuscation, no PII in logs, no network). 4. Independent GT for DOCX/PDF (annotate from page images).
5. Benchmarks on ai4privacy/Kaggle/Mendeley (not reachable from my sandbox; download locally, check licences). 6. Visual redaction of
scanned PDFs. 7. THREAT_MODEL.md, SECURITY.md, README, RESULTS.md, diagrams, Optiv deck (14 Oct 2026).
