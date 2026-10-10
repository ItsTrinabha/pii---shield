# PII Shield — Full Project Plan

Scope: build the complete system, not a cut-down demo. Timeline is secondary; correctness and honesty of results come first.

## 1. What the Optiv brief actually requires
| # | Requirement | How we prove it |
|---|---|---|
| 1 | Analyse file structures, choose extraction per type | `docs/FILE_ANALYSIS.md` + router code |
| 2 | Extract text from PDF (scanned), PPTX, DOCX | extractors + OCR |
| 3 | Detect and classify PII (employee IDs, full names, contact details, government IDs, ...) | taxonomy + hybrid detector |
| 4 | Apply transparent tags | stable tokens like `[PERSON_3]`, `[EMAIL_7]` |
| 5 | Summarise PII found, keep source traceability | audit report (type counts + locators) |
| 6 | Keep PII from reaching the LLM | fail-closed gate + independent verifier |
| 7 | >= 80% structure retained, context preserved | defined structure metric (section 6) |
| 8 | PII detection "approaching 100% coverage" | measured recall on labelled data, with intervals |
| 9 | Deck: blueprint, architecture, extraction logic, outcomes, live demo | deliverables in section 8 |

## 2. What the sample files really contain (inspected)
| File | Format reality | Extraction consequence |
|---|---|---|
| Group Risk Management Policy v6.0 (PDF, 35 pp, 13 MB) | Every page is a JPEG image (~220 ppi); text layer is empty. Metadata `Author` field holds a personal name. | OCR is the only path; metadata must be scanned too; OCR noise (e.g. `cadencefg` read as `cadencetg`) must not break detection. |
| Organizational Reference Pack (PPTX, 9 slides) | Native text; org-chart shapes, tables, RACI matrices; speaker notes exist; footer says "Contains personal data (synthetic sample)". | Recurse into group shapes and tables; read notes, masters, alt text, core properties. |
| TPRM Training (DOCX, ~14.8k words) | Native text and tables, headers/footers/footnotes, 41 embedded images (likely screenshots). User-group tables list people by name only (no emails in body). | Read body + tables + headers/footers + footnotes; OCR the 41 images; names without any label are the main risk. |

Hard cases already seen in the PDF (pages 22-23): identifiers inside narrative prose with no field labels, mixing full name, employee ID, date of birth, SSN, passport, national tax ID (PAN), home address, external email and phone; a customer letter with card last-4, account last-4, SSN last-4, DOB, a spouse's name, a street address.

## 3. PII taxonomy v0 (refine after the full inventory in Phase 1)
| Type | Examples seen | Primary detector | Watch-outs |
|---|---|---|---|
| PERSON | `Miriam T. Achebe`, `Okonkwo-Bell`, `Ms Prieto-Ramos` | NER (spaCy transformer via Presidio) + title/ID context rules + name list from tables | hyphenated and non-Western names; names in org charts have no sentence context; org/vendor names are not PII |
| EMPLOYEE_ID | `EMP-38104`, `DIR-0042` | regex | `EMP-` and `DIR-` prefixes only; do not confuse with `INC-2026-0417`, `LOS-2026-0088`, `GRP-POL-001`, `OP-4545941` (not PII) |
| EMAIL | `m.achebe@cadencefg.com`, `...@cadencefg.example`, external vendor addresses | regex | OCR typos in domain; split across line breaks |
| PHONE | `+1 (212) 555-0147`, `+44 20 7555 0171`, `+91 80 4555 0182`, `+33 1 5555 0144`, `+46 8 5555 0121`, `+48 22 555 0164`, `+65 6555 0172`, `M +1 (555) 0114` | regex + libphonenumber-style parsing | many national formats; synthetic 555 numbers will fail strict validity checks, so accept by shape |
| SSN | `900-55-2043`, last-4 in prose | regex + context | synthetic SSNs start with 9xx, which real validators reject; do not over-validate |
| PASSPORT | `TK4820913` | regex + context word "passport" | bare alphanumerics need context |
| NATIONAL_TAX_ID (PAN) | `AQBPR7741L` | regex `[A-Z]{5}[0-9]{4}[A-Z]` + context | collides with random 10-char codes |
| DATE_OF_BIRTH | `14 July 1991`, `3 August 1996`, `DOB 14 July 1991` | date regex + DOB/birth context | do NOT mask ordinary dates (approval dates, effective dates) |
| ADDRESS | `1180 Ashwood Lane, Apartment 4C, Jersey City, NJ 07302`, `2214 Palmetto Crescent, Coral Gables, FL 33134` | NER + street/zip patterns | corporate address `245 Hudson Street` is business, decide and document policy |
| PAYMENT_CARD / ACCOUNT_FRAGMENT | `card ending 2218`, `account ending 7741` | context regex | partial numbers are still sensitive in context |
| METADATA_PERSON | PDF `Author` field, DOCX/PPTX core properties | metadata scan | easy to forget |
Decision log for borderline items (job titles, corporate addresses, public regulators, company names) goes in `docs/DECISIONS.md`.

## 4. Architecture
```
upload -> router (type sniff, size/zip-bomb/encryption checks)
  -> extractor (PDF->OCR | PPTX | DOCX) -> Blocks with Locators (file, page/slide, block, bbox/offset)
  -> normaliser (unicode, OCR fixes, whitespace; keeps offset map)
  -> detectors in parallel: patterns+validators | Presidio+spaCy | context rules | metadata scan
  -> fusion (merge overlaps, type priority, confidence calibration, low-confidence -> REVIEW/BLOCK)
  -> masking (stable per-document tokens, same entity => same token)
  -> independent verifier (separate rule set, deliberately over-sensitive) -> PASS or BLOCK
  -> outputs: sanitized text (+ structure), audit report, findings JSON
  -> UI (Streamlit) and optional API
```
Design decisions:
- The verifier must not reuse the detector's logic, otherwise it only repeats its mistakes. Use looser heuristics (any `@`, long digit runs, capitalised name-like tokens next to titles/IDs, known-name list built from this document's own findings).
- Stable tokens keep meaning (`[PERSON_1] approved ... [PERSON_2] reviewed`) without a reversible vault. Do not build a de-masking feature unless a requirement appears.
- LLM use is optional and only for context validation of already-masked or low-risk text; never on raw text.

## 5. Phases (your 25 items mapped; each phase ends with an exit criterion)
Phase 0 - Repo and foundations
 - [ ] Understand and decompose Optiv requirements (section 1)
 - [ ] Project skeleton, `CLAUDE.md`, pyproject, CI (pytest, ruff, mypy)
 - Exit: `pytest` runs green on an empty suite; the three sample files sit in `data/samples`.

Phase 1 - Artifact analysis and taxonomy
 - [ ] Analyse the three artifacts and PII categories (full inventory, all 35 pages, DOCX images, PPTX notes/masters/metadata)
 - [ ] Define PII taxonomy and detection rules (section 3, finalised)
 - [ ] Write `docs/FILE_ANALYSIS.md` (deliverable 1 of the brief)
 - Exit: inventory table per file/type/page; every borderline type has a decision in `DECISIONS.md`.

Phase 2 - Ingestion and OCR
 - [ ] Multi-format ingestion with locators
 - [ ] OCR pipeline for scanned PDF pages and DOCX/PPTX images (render at 300 dpi, deskew/denoise if needed, per-word confidence, post-OCR normalisation)
 - Exit: every page of every sample yields blocks; extraction report shows OCR confidence per page; structure-retention metric computed.

Phase 3 - Detection core
 - [ ] Deterministic detectors with validators
 - [ ] ML/NLP contextual detection (Presidio + spaCy transformer)
 - [ ] Hybrid detection + entity fusion
 - [ ] Confidence scoring and false-positive controls (allow-lists such as `INC-`, `GRP-POL-`, company/regulator names; context requirements)
 - [ ] PII classification into the taxonomy
 - Exit: runs end-to-end on all samples; per-detector contribution table.

Phase 4 - Masking, traceability, safety
 - [ ] Stable-token masking and redaction preserving structure
 - [ ] Source traceability on every finding
 - [ ] Independent verification and fail-closed gate
 - Exit: adversarial tests (corrupt file, empty file, password-protected, huge file, OCR garbage page) all end BLOCKED, never "safe".

Phase 5 - Evaluation framework
 - [ ] Ground-truth format and annotation tool/process (JSONL spans: file, page, start, end, type)
 - [ ] Annotate Cadence artifacts (start with pp. 1-4, 22-23, 32; then everything; second pass to check labels)
 - [ ] Metrics: precision, recall, F1 per type, leak rate (surviving PII spans / total), OCR-vs-native recall, false positives and negatives lists
 - [ ] Benchmark on the Kaggle PII dataset (check licence and domain fit first) and on the Cadence artifacts
 - Exit: `python -m pii_shield.eval` prints a reproducible results table and writes `docs/RESULTS.md`.

Phase 6 - Improve from failure cases
 - [ ] Error analysis loop: read every false negative, fix at the right layer, re-run, record before/after
 - [ ] Only then consider fine-tuning or a custom model (needs enough labelled data; otherwise state it as future work)

Phase 7 - Product surface
 - [ ] Streamlit demo (upload, file info, findings table with locators, side-by-side original vs sanitized, download, status BLOCKED/PASS)
 - [ ] Audit/report generation (JSON + readable HTML/PDF)
 - Exit: a stranger can run the demo from the README in minutes.

Phase 8 - Hardening
 - [ ] Security and edge-case testing (upload validation, no PII in logs, temp files deleted, size/time limits, malformed OOXML/PDF, zip bombs, prompt-injection text inside documents)
 - Exit: security checklist in `docs/SECURITY.md` all ticked or consciously accepted.

Phase 9 - Submission
 - [ ] Architecture and results documents, limitations, live-walkthrough script
 - [ ] Final deck and package (code, README, results, demo recording)

## 6. Evaluation design (the part that makes claims honest)
- Entity-level matching: a span counts as found if the detector span overlaps the gold span by >= 50% and the type is right; also report a stricter exact-match number.
- Primary safety metric: **leak rate** = gold PII spans still readable in sanitized output. Recall alone can hide partial masking (e.g. only the first name masked).
- Small data: report counts, not just percentages, plus Wilson confidence intervals; never write "100%" from a sample.
- Structure retention (define it in the deck): share of source blocks (paragraphs, table cells, shapes) recovered in reading order with correct locator, plus a check that text before/after every masked span survived. Target >= 80% as the brief states.
- OCR-vs-native: run the same documents natively and through OCR to quantify the OCR penalty.
- Hold-out: never tune on the pages you report on. Tune on a dev subset, report on the rest.

## 7. Honest limits to state up front
- Names are the hardest class; expect misses on unusual names and org-chart fragments.
- OCR errors can hide identifiers (`l`/`1`, `O`/`0`); mitigations reduce but do not remove this.
- Sample set is small and synthetic; results do not transfer to real Cadence data without re-validation.
- Verifier is a safety net, not a proof.

## 8. Mapping to Optiv deliverables
Blueprint = section 4 diagram; Architecture = detailed component diagram from code; Extraction logic = `FILE_ANALYSIS.md` + detector table; Reliable outcomes = `RESULTS.md`; Live walkthrough = Streamlit demo on the three provided files.

## 9. Working with real data
The three sample files are synthetic and fine to use with Claude Code. Never put real employee or customer documents into a coding assistant session; build and test on synthetic data and keep any real-data testing inside your own environment.
