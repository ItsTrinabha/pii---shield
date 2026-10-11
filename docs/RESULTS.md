# Results

Every number here was printed by `python -m pii_shield.eval`. Raw output: `docs/eval.json` (merged from
`docs/eval_pptx.json`, `docs/eval_docx.json`, `docs/eval_pdf.json`). Types, locators, offsets and tokens only; no values.

## How to read this

- **Leaked values is the headline.** A ground-truth (GT) value counts as leaked if it is still readable anywhere in the
  sanitised text. Since `3a180ae` other entities' tokens are deleted before the search, so `+44 20 [PERSON_3] 7555 0171`
  counts as a leak of `+44 20 7555 0171`.
- **Since run (b) all three files have independent GT** (see `data/ground_truth/ANNOTATION.md`). Before that, the DOCX and
  PDF GT was built from detector output and hand-pruned, so the first run's DOCX/PDF scores are regression checks only: a
  recall of 1.000 there means "nothing we once found was lost", not "everything was found".
- R = occurrence-level recall (with Wilson 95% interval), P = precision, `not_extracted` = GT values that never appear in the
  extracted text (OCR misreads), so they can be neither detected nor leaked in their annotated form.

## Run 2026-10-11 (Tesseract 5.5.3, Windows, `en_core_web_lg`)

Before = commit `399030d` (full run, default OCR workers). After = commit `3a180ae`, one file per run, `--ocr-workers 2`:

```
python -m pii_shield.eval --only pptx --out docs/eval_pptx.json
python -m pii_shield.eval --only docx --out docs/eval_docx.json
python -m pii_shield.eval --only pdf  --out docs/eval_pdf.json
```

| File | GT | Status | Leaked values | Recall [95% CI] | Precision | PHONE precision | FP | not_extracted |
|---|---|---|---|---|---|---|---|---|
| Organizational Pack (PPTX), before | independent | PASS | 0 / 61 | 1.000 [0.97, 1.0] | 1.000 | 1.000 | 0 | 0 |
| Organizational Pack (PPTX), after | independent | PASS | **0 / 61** | 1.000 [0.97, 1.0] | 1.000 | 1.000 | 0 | 0 |
| TPRM Training (DOCX), before | regression only | REVIEW | 1 / 23 | 0.978 [0.887, 0.996] | 1.000 | n/a | 0 | 3 |
| TPRM Training (DOCX), after | regression only | REVIEW | **0 / 23** | 1.000 [0.923, 1.0] | 1.000 | n/a | 0 | 3 |
| Risk Management Policy (PDF, scanned), before | regression only | BLOCKED | 3 / 260 | 1.000 [0.996, 1.0] | 0.984 | 0.959 | 14 | 7 |
| Risk Management Policy (PDF, scanned), after | regression only | REVIEW | **0 / 260** | 1.000 [0.996, 1.0] | 0.975 | 0.903 | 23 | 7 |

The "before" leak counts used the older leak definition, which did not see a value split by another entity's token. They are
therefore a lower bound: the PDF also had phones split by a `[PERSON_n]` token on page 4, which the old metric missed.

### What changed

- **PDF 3 → 0 leaked, BLOCKED → REVIEW.** Phones split by OCR layout (prefix and continuation separated by a neighbouring
  table cell, or by an OCR paragraph boundary). The verifier only checked one block at a time and would have passed the
  cross-block case; the PDF was BLOCKED only because another page failed. Fixed in the detector, the verifier and the heal
  loop (`dc67c25`). REVIEW, not PASS: the verifier still force-redacts phone pieces the detector misses.
- **DOCX 1 → 0 leaked.** A hyphenated name inside OCR noise of a UI screenshot. SOFT name hits in OCR-derived blocks are now
  auto-redacted as forced redactions (`3a180ae`). The document stays REVIEW by design.
- **PPTX unchanged.**

### Cost: PHONE precision on the PDF (0.959 → 0.903)

The over-sensitive verifier and the split-number detector trade precision for leaks. From `docs/eval_pdf.json`, the 15 PHONE
false positives are:

| Detector | PHONE FP | What they are |
|---|---|---|
| `verifier:forced` | 11 | pieces of split numbers redacted by the verifier, with no contiguous GT occurrence to match |
| `regex:phone-split` | 4 | two split numbers whose OCR digits differ from the GT value (the metric matches by exact digits) |

In diagnostic runs during the fix (shapes and locators only, no values printed), the inspected forced PHONE pieces were parts
of phone numbers, and the two split numbers each differed from their nearest GT phone by 2 digits. That inspection covered an
earlier version of the branch, not every item in this run, so it is not a claim; the metric counts all 15 as false positives
and so does this table.

## Run 2026-10-11 (b): independent ground truth for DOCX and PDF

The DOCX and PDF ground truth was rebuilt by reading the documents directly (rendered PDF pages with zoomed figures and
screenshots; DOCX native text from the OOXML parts plus all 41 embedded images), without opening detector output or the
old GT. Protocol and inclusion decisions: `data/ground_truth/ANNOTATION.md`. The old detector-derived files are kept in
`data/ground_truth_regression/` and their last results in `docs/eval_regression_docx.json` / `docs/eval_regression_pdf.json`.
Code unchanged (commit `3a180ae` + GT only). From now on all three files are accuracy measurements, not regression checks.

| File | GT | Status | Leaked values | Recall [95% CI] | Precision | FP | Missed occurrences | not_extracted |
|---|---|---|---|---|---|---|---|---|
| TPRM Training (DOCX), regression GT | detector-derived | REVIEW | 0 / 23 | 1.000 [0.923, 1.0] | 1.000 | 0 | 0 | 3 |
| TPRM Training (DOCX), **independent GT** | independent | REVIEW | **3 / 23** | 0.920 [0.812, 0.968] | 1.000 | 0 | 4 | 0 |
| Risk Management Policy (PDF), regression GT | detector-derived | REVIEW | 0 / 260 | 1.000 [0.996, 1.0] | 0.975 | 23 | 0 | 7 |
| Risk Management Policy (PDF), **independent GT** | independent | REVIEW | **2 / 264** | 0.997 [0.991, 0.999] | 0.911 | 81 | 2 | 52 |

Per-type on the PDF (independent GT, from `docs/eval_pdf.json`): recall 1.000 for ADDRESS, DATE_OF_BIRTH, EMAIL,
EMPLOYEE_ID, FINANCIAL_ACCOUNT, PASSPORT, PERSON, PHONE; SSN 0.667; TAX_ID 0.800. Precision: EMAIL 0.803, PHONE 0.845,
PERSON 0.941, PASSPORT 0.500, all others 1.000.

**The circular GT hid real leaks.** Both documents stay REVIEW (no automatic release), but the detector misses:

- DOCX: two people whose first name is written as two capital initials without dots (shape `AA Surname`), once in a native
  table cell and once in a screenshot; and one person in a screenshot whose name reads like the UI label "Mark Read". The
  OCR-name auto-redaction deliberately skips UI labels (decision of 2026-10-11), so this leak is a direct cost of that
  filter. The verifier still raises it as a SOFT hit.
- PDF: an SSN given only as its last four digits in brackets in customer correspondence (page 23), and a partly masked
  national ID (PESEL with trailing `x`s, page 25).

**False positives on the PDF (81):** by detector, from the eval JSON: EMAIL `presidio+regex` 30, PHONE `verifier:forced` 11,
PERSON from the names lexicon in several combinations 22, PHONE `presidio+regex:phone-us` 8, PHONE `presidio` 4, others
single digits. The new GT excludes role and distribution mailboxes and organisational hotlines by policy, which the
detector masks anyway; that over-redaction is counted against precision here. Whether every EMAIL FP is such a mailbox
was not checked value by value.

**not_extracted (PDF 52):** GT values that never appear in the extracted text, so they can neither be detected nor
leaked in annotated form. A diagnostic pass (shapes and edit distances only) found two causes: whole screenshot or form
regions OCR did not read (the terminal audit log, the attestation form, the user-list screenshot, small figure captions),
and single-character OCR losses (a dropped first letter, a split across blocks). No annotation typo was confirmed.
Because the output is text, an unread region cannot leak through it, but a visual redaction of the scan would have to
cover these regions (open item).

## Known limits of these numbers

- Three documents, synthetic data, one OCR engine version. Nothing here transfers to real Cadence documents without
  re-validation.
- The first run above used circular DOCX/PDF GT; run (b) replaces it with independent GT (single annotator, one pass,
  no inter-annotator agreement).
- The detector has been tuned on these same three documents. There is no held-out set, so these numbers are optimistic
  for unseen documents.
