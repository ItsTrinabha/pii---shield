# How Cloak works

Cloak sits between business documents and an LLM. A document goes in; what comes out is either text that has been
checked and is safe to send, or nothing at all. Everything runs on the local machine.

```
 PDF / PPTX / DOCX
        │
 1. Safe intake ─── size, type, zip-bomb, path traversal, XXE, encryption checks ──► BLOCKED on any problem
        │
 2. Extraction ──── text with exact locations; OCR for scanned pages and embedded images
        │
 3. Detection ───── rules + validators  →  language model (spaCy/Presidio)  →  name rules  →  fusion
        │
 4. Masking ─────── each value becomes a stable token: "Dana Whitfield" → [PERSON_3]
        │
 5. Verification ── a second, independent checker re-reads the masked text
        │
 6. Gate ────────── PASS (released) · REVIEW (needs a named person) · BLOCKED (nothing released)
        │
 7. Outputs ─────── sanitised text · audit report · redacted file (re-scanned before it is written)
```

## 1. Safe intake
Uploads are checked before anything is parsed: file type must match the content, size limits apply, Office files are
opened as ZIP packages with limits on entry count, total size and compression ratio, and XML is parsed with external
entities disabled. Encrypted or corrupt files are **BLOCKED** with a reason code. Code: `security.py`.

## 2. Extraction
Every piece of text becomes a *block* with a locator: `file → page/slide/section → part (table cell, notes, image) →
character span`. That locator follows every finding, so any result can be traced back to its exact source.

- **PDF**: the text layer is read with PyMuPDF. Pages without usable text are rendered and OCR'd.
- **PPTX / DOCX**: text, tables, notes, headers, footers and comments are read from the package XML; embedded images
  are OCR'd.
- **OCR**: Tesseract is the main engine, with word boxes and confidence per word. RapidOCR (a second engine) runs when
  Tesseract is missing or reads a page poorly. An ink-coverage check flags pages where ink was found but not read.
  A failed or low-confidence page makes the document fail closed.

Code: `extraction/`.

## 3. Detection
Detection is layered. Deterministic rules come first; models only add recall.

| Layer | What it finds | Why it is there |
|---|---|---|
| Regex + validators | emails, phones, SSN, passports, IBAN/cards (Luhn), IPs, employee IDs, dates of birth | exact, repeatable, explainable |
| spaCy + Presidio | names and entities in context | catches what patterns cannot |
| Name rules | names next to labels ("Owner:"), titles, ID numbers, honorifics, lists of names, e-mail-derived surnames | precision on names, which models over- and under-call |
| Fusion | combines evidence from independent detectors into one confidence | two weak signals that agree beat one strong guess |
| Propagation | once a value is confirmed, every other mention in the document | consistency: "Dana Whitfield" on page 2 and "Whitfield" on page 9 |
| GLiNER (optional, `--deep`) | zero-shot names and IDs | extra recall; slow on CPU, so off by default |

Findings above the mask threshold are masked; findings in the band just below it become **review candidates**.
Code: `detection/`.

## 4. Masking
Each value is replaced by a token such as `[EMAIL_2]`. The same value always gets the same token inside a document,
so the LLM can still reason about "the same person". Tokens carry an HMAC fingerprint of the value, so audits can join
findings without storing the value. There is no lookup table to steal. Code: `masking/tokens.py`.

## 5. Verification
A separate verifier with **different logic** from the detectors re-reads the masked output. A *hard* hit means
something still looks like personal data. The pipeline redacts it and checks again (the heal loop). Anything still
uncertain is a *soft* hit for a person to look at. Code: `verification/`.

## 6. Gate
| Status | Meaning | What is released |
|---|---|---|
| **PASS** | verified clean | sanitised text, automatically |
| **REVIEW** | sanitised, but some items need a person | nothing until a named reviewer approves |
| **BLOCKED** | extraction failed or residual PII remains | nothing, ever |

The only way to get LLM-facing text is `release()`, which returns a sealed object; the LLM gateway refuses anything
else. Code: `pipeline.py`, `gateway.py`.

## 7. Outputs
- **Sanitised text**: the document with tokens in place of values.
- **Audit report** (JSON/HTML): every finding with type, token, location, detector and confidence, never the value.
- **Confidentiality label**: Public, Internal, Confidential or Restricted, from what was found plus markings such as
  "Confidential" or "NDA".
- **Redacted file** in the original format: PDF text is removed and scanned areas are blacked out; DOCX/PPTX text is
  rewritten and metadata stripped. The file is re-scanned before it is returned, and anything the re-scan finds is
  redacted too (up to 3 rounds). If it still is not clean, no file is written.

## The web app
- **Scan**: drop files; see the release decision, accuracy (only for files with ground truth) or confidence signals,
  the confidentiality label, findings by type and hits per page.
- **Review**: scroll the real pages with redactions drawn in, or the text. "Needs attention" lists each uncertain item
  with a snippet and a marker on the page. Redact or dismiss it, or select any text to redact it yourself. Hold the eye
  button to peek at the originals. Any manual edit needs a named approval before release.
- **Audit**: searchable findings table, coverage map per page, extraction quality, and downloads.

## Accuracy
Accuracy is only ever reported where it was measured against hand-labelled ground truth (`data/ground_truth/`), using
`python -m pii_shield.eval`. Current numbers and their history are in [RESULTS.md](RESULTS.md). Other files show
confidence signals, clearly labelled as such.

## Design rules
1. Fail closed: any error, low-confidence page or verifier hit means nothing is released.
2. No raw values in logs, reports or fixtures.
3. No network calls with document text: everything runs locally.
4. Deterministic first; models only add recall.
5. Every finding is traceable to file, page, block, span, detector and confidence.
6. Measure, don't claim.
