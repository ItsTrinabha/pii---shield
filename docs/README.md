# Cloak

A local, fail-closed gateway between business documents and an LLM. It extracts text from PDFs (including scanned ones),
PowerPoint and Word files, finds and classifies personal data, replaces it with stable tokens, verifies the result with
independent logic, and releases text only when it is sure, or when a named human approves.

Originally developed for a document-privacy case study. All included sample data is synthetic.

## What it does

- **Reads everything in the file:** body text, tables, text boxes, headers/footers, footnotes, slide notes, masters,
  alt text, hyperlinks, document metadata, and the text inside images and scanned pages (OCR).
- **Detects personal data:** names, e-mails, phone numbers, employee IDs, SSNs, tax IDs, passports, dates of birth, home
  addresses, financial account numbers, IP addresses. Rules and validators first; spaCy/Presidio NER and a names layer add
  recall.
- **Masks with stable tokens:** `[PERSON_3]` is the same person everywhere in the document, so an LLM keeps the meaning.
- **Verifies independently:** a second rule set that shares no code with the detectors re-scans the output; residual hits
  are force-redacted or hold the document.
- **Decides:** PASS (released), REVIEW (released only with a named approver), BLOCKED (never released).
- **Explains:** an audit report lists what was found where (page/slide, block, character span, detectors, confidence)
  without ever showing the values.

Design: `ARCHITECTURE.md`, `FUNCTIONAL_DESIGN.md`. Security: `THREAT_MODEL.md`, `SECURITY.md`. Measured results:
`RESULTS.md` (definitions in `METRICS.md`). Known gaps: `LIMITATIONS.md`. Choices: `DECISIONS.md`. The sample files:
`FILE_ANALYSIS.md`. Demo script: `WALKTHROUGH.md`.

## Setup

Requirements: Python 3.10+; Tesseract OCR 5; optional LibreOffice (renders EMF/WMF images and enables the OCR-vs-native
evaluation).

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
python -m spacy download en_core_web_lg     # NER model (one-time download)
```

- **Tesseract:** Windows installer from UB Mannheim, or `apt install tesseract-ocr`. Cloak finds it on `PATH`, in the
  default Windows install folders, or via `CLOAK_TESSERACT` (`PII_SHIELD_TESSERACT` remains a compatibility alias).
- **LibreOffice (optional):** found on `PATH` or in the default install folder.
- **Fingerprint key (optional):** set `CLOAK_KEY` to make audit fingerprints comparable across runs; otherwise a random
  per-process key is used (`PII_SHIELD_KEY` remains a compatibility alias).

Check: `pytest -q` (the `slow` marker runs OCR on the real samples).

## Use

**Web app**

```bash
python -m pii_shield.app
```

Open `http://127.0.0.1:8765` and upload a PDF/PPTX/DOCX. You get the status and reasons, a findings table (no raw values
by default), review controls, verifier hits, audit downloads, sanitized text, and verified redacted-file output.

**Command line**

```bash
cloak scan data/samples/*.pptx --out out/
cloak scan report.docx --out out/ --approve "Reviewer Name"   # release a REVIEW document
```

Writes `<name>.audit.json`, `<name>.audit.html` and, if released, `<name>.sanitized.txt`. Exit code: 0 released,
1 held for review, 2 blocked.

**Python**

```python
from pii_shield.pipeline import process_path, release
from pii_shield.gateway import ask_llm

result = process_path("report.docx")
print(result.status, result.reasons)
text = release(result)                      # raises for BLOCKED, or for REVIEW without approved_by=...
answer = ask_llm(text, "Summarise the risks.", llm=my_model_call)   # my_model_call: Callable[[str], str]
```

`ask_llm` only accepts the sealed object that `release()` returns, and checks the instruction for personal data too.

**Evaluation**

```bash
python -m pii_shield.eval --only pptx --out docs/eval_pptx.json        # one file at a time keeps memory low
python -m pii_shield.eval --only docx --render-ocr --out docs/eval_ocr_docx.json   # OCR-vs-native (needs LibreOffice)
```

## Repository layout

```
src/pii_shield/
  extraction/    router, pdf, pptx, docx, ooxml helpers, ocr, vector (EMF/WMF)
  detection/     normalize, patterns, ner, names, fusion, engine
  masking/       stable tokens, sanitised-to-original mapping
  verification/  independent verifier
  pipeline.py    extract -> detect -> mask -> verify -> heal -> gate; release()
  gateway.py     the only door to an LLM
  reporting/     audit JSON / HTML
  eval/          metrics, structure retention, OCR-vs-native rendering, CLI
  app/           Starlette API + static browser UI; legacy Streamlit demo
data/samples/            synthetic demonstration documents
data/ground_truth/       independent value-based ground truth (+ ANNOTATION.md)
tests/                   unit, security, fail-closed, privacy, regression, app smoke tests
scripts/demo_check.py    drives the legacy Streamlit demo headlessly
```

## Privacy rules for contributors

Never log or print raw values; tests and fixtures use synthetic data only; no network calls with unsanitised text; never
put real employee or customer documents into a coding-assistant session.
