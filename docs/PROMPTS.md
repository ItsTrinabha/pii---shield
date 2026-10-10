# Claude Code prompt pack

How to use: open a terminal in the repo, run `claude`, press Shift+Tab to enter plan mode, paste the prompt for the current phase, review the plan, approve, then let it implement. One phase per session; commit at the end. Re-read `CLAUDE.md` rules if a session drifts.

## Phase 0 - skeleton
Read CLAUDE.md and docs/PLAN.md. Create the project skeleton under src/pii_shield with pyproject.toml (extras: dev), pytest, ruff, mypy, and a GitHub Actions workflow. Define pydantic models in models.py: Locator (file, page_or_slide, block_id, bbox optional), Block (text, locator, source: native|ocr, ocr_confidence), Finding (type, start, end, detector, confidence, locator, token), Result (status PASS|BLOCKED, reasons, findings, sanitized_blocks). Do not implement detectors yet. Add tests for the models.

## Phase 1 - inventory
Using data/samples, produce a full PII inventory without printing raw values to the console: write results to data/inventory/*.jsonl and a summary table (file, page/slide, type, count) to docs/INVENTORY.md with values replaced by hashes plus length. Cover all 35 PDF pages (render at 300 dpi and OCR with Tesseract), all DOCX body/tables/headers/footers/footnotes and its 41 images, and all PPTX slides/notes/masters/alt text/core properties, plus PDF and OOXML metadata. Then draft docs/FILE_ANALYSIS.md. Ask me before running anything that takes more than a few minutes.

## Phase 2 - extraction and OCR
Implement extraction/router.py, pdf.py, pptx.py, docx.py, ocr.py. Requirements: every Block has a Locator; PPTX recurses into group shapes and tables; DOCX covers headers/footers/footnotes and OCRs images; PDF pages with no text layer go to OCR; record per-page OCR confidence; any failure raises a typed error that the pipeline turns into BLOCKED. Add a normaliser that keeps an offset map back to the original text. Write tests with small synthetic fixtures, including a corrupt file and an empty file.

## Phase 3 - detection
Implement detection/patterns.py with validators for EMAIL, PHONE (multi-country formats seen in the samples), EMPLOYEE_ID (EMP-, DIR-), SSN, PASSPORT, NATIONAL_TAX_ID (PAN shape), DATE_OF_BIRTH (needs birth context), ADDRESS, partial card/account numbers (needs context). Add Presidio with a spaCy transformer model for PERSON/LOCATION, context rules for names near titles/IDs/table headers, an allow-list for non-PII lookalikes (INC-, LOS-, GRP-POL-, OP-), and fusion.py (merge overlaps, priority by type, calibrated confidence). Write unit tests per type including negatives. Show me a per-detector contribution table, not raw values.

## Phase 4 - masking and safety
Implement masking/tokens.py (stable per-document tokens, same entity => same token, no reversible vault), verification/ (an independent, deliberately over-sensitive verifier that does not import detection code), and the pipeline gate: PASS only if extraction succeeded, OCR confidence is above threshold on every page, and the verifier finds nothing. Write adversarial tests: corrupt, empty, encrypted, oversized, OCR-garbage page, document containing prompt-injection text. All must end BLOCKED or sanitized correctly.

## Phase 5 - evaluation
Create eval/ with the ground-truth JSONL schema (file, page, start, end, type, notes), a small annotation helper that shows page text with candidate spans for me to accept or correct, and metrics: precision/recall/F1 per type, leak rate, exact and overlap matching, OCR-vs-native recall, Wilson intervals, and lists of false positives/negatives (locators only, no raw values by default). Add a dev/test split by page. Do not download any Kaggle data until I confirm the dataset name and licence.

## Phase 6 - improve
Read the false-negative list, group failures by cause (OCR, format, context, new pattern), propose fixes ranked by leak-rate impact, implement the top ones, re-run the eval, and append before/after numbers to docs/RESULTS.md. Do not tune on the test split.

## Phase 7 - app and reports
Build the Streamlit app (upload, file info and extraction method, per-type counts, findings table with locators and confidence, original vs sanitized view, PASS/BLOCKED banner with reasons, downloads) and reporting/ (JSON plus a readable HTML audit report). Never display raw PII in the report unless a clearly labelled "reveal" toggle is on and off by default.

## Phase 8 - hardening
Review the whole repo against docs/SECURITY.md checklist items: upload validation, size/time limits, temp-file cleanup, no PII in logs or exceptions, dependency audit (pip-audit), malformed PDF/OOXML handling. Fix issues and add regression tests.

## Phase 9 - submission
Generate docs for architecture, results, limitations and a live-walkthrough script (timed for 10-15 minutes). Produce diagrams as Mermaid files I can paste into the deck. Do not invent numbers; pull them from docs/RESULTS.md.
