# Limitations

Stated up front so results are read correctly. Numbers referenced here are in `docs/RESULTS.md`.

## Detection
- **Not complete.** On the independent ground truth, values still leak on the DOCX and the scanned PDF (both documents
  are held in REVIEW, so release depends on the reviewer). Known missed forms: first names written as two capital
  initials, a person whose name reads like a UI label in a screenshot, an SSN given only as its last four digits in
  prose, a partly masked national ID.
- **Names are the hardest class**: unusual, hyphenated or non-Western names, names without sentence context (tables,
  org charts), and OCR-damaged names.
- **Over-redaction** is the chosen failure direction: role mailboxes, business numbers and OCR noise are sometimes masked,
  which lowers precision, most of all on fully scanned documents (OCR-noise name rule).

## OCR
- OCR can miss whole regions (small captions, dark terminal screenshots, dense forms) or drop single characters. Values in
  those regions never reach the text output; they also cannot be detected there. Weak pages are held in REVIEW by the
  confidence and ink-coverage checks, but the check is a heuristic.
- Rendering and OCR lose document metadata, notes and hidden content by nature; the native path reads them.
- EMF/WMF images need a local LibreOffice; without it the document is held in REVIEW (`UNSUPPORTED_MEDIA`).
- Only English OCR and NER models are configured.

## Evaluation
- Three synthetic documents; one annotator, one pass, no inter-annotator agreement.
- The detector was developed and tuned on the same three documents it is measured on; there is no hold-out set, so the
  numbers are optimistic for unseen documents.
- Structure retention is page-level for PDFs (no native structure in a scan); the PPTX order score is a lower bound
  because identical one-letter cells cannot be told apart.
- No public benchmark has been run yet.

## Product
- Cloak creates redacted PDF and Office copies, but layout preservation is best-effort. PDF redaction depends on native
  text matches or OCR word boxes; Office paragraph formatting can be simplified, and an embedded image containing a
  finding may be blanked as a whole rather than edited pixel by pixel.
- Prompt injection inside documents is passed through as (sanitised) content; downstream prompts must treat document text
  as data.
- The release seal prevents mistakes, not malicious code in the same process.
- `pip-audit` has not been run; dependencies are pinned by lower bound only.
- Results do not transfer to real Cadence data without re-validation in Cadence's own environment. Real personal data
  must never be put into a coding-assistant session.
