# Results

Every number here was printed by `python -m pii_shield.eval`. Raw output: `docs/eval.json` (merged from
`docs/eval_pptx.json`, `docs/eval_docx.json`, `docs/eval_pdf.json`). Types, locators, offsets and tokens only; no values.

## How to read this

- **Leaked values is the headline.** A ground-truth (GT) value counts as leaked if it is still readable anywhere in the
  sanitised text. Since `3a180ae` other entities' tokens are deleted before the search, so `+44 20 [PERSON_3] 7555 0171`
  counts as a leak of `+44 20 7555 0171`.
- **Only the PPTX scores are an accuracy measurement.** Its GT was annotated independently of the detector.
- **DOCX and PDF scores are regression checks only, not accuracy claims.** Their GT was built from detector output and then
  hand-pruned, so a value that every detector misses can be missing from the GT as well. Recall of 1.000 on these files means
  "nothing we once found was lost", not "everything was found".
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

## Known limits of these numbers

- Three documents, synthetic data, one OCR engine version. Nothing here transfers to real Cadence documents without
  re-validation.
- DOCX and PDF GT are circular (see above). Independent GT for both is the next evaluation task.
- No OCR-vs-native comparison and no structure-retention metric yet.
