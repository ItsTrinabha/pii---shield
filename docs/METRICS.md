# Metrics

All numbers in the docs come from `python -m pii_shield.eval` (code: `src/pii_shield/eval/`). This page defines them.

## Detection and safety (`eval/metrics.py`)

Ground truth (GT) is value-based: one line per distinct PII value (`data/ground_truth/*.jsonl`, protocol in
`data/ground_truth/ANNOTATION.md`).

| Metric | Definition |
|---|---|
| occurrence | a place where a GT value appears in one extracted block (whitespace- and case-insensitive, word-bounded) |
| recall | occurrences covered by a finding that overlaps >= 50% of the occurrence / all occurrences; Wilson 95% interval |
| precision | findings that overlap a GT occurrence, or whose identity fingerprint equals a GT value's (numbers split by layout) / all findings |
| **leaked values** (headline) | GT values still readable anywhere in the sanitised text, after deleting other entities' tokens (`+NN NN [PERSON_3] NNNN NNNN` counts as a leak) |
| not_extracted | GT values that never appear in the extracted text (OCR misread or unread region); they can be neither detected nor leaked in annotated form |

## Structure retention (`eval/structure.py`)

The brief asks that at least 80% of the document structure is retained. "Structure" is measured on **source units**:

| Format | Units (reference) | Expected locator |
|---|---|---|
| DOCX | every non-empty body paragraph, every non-empty paragraph of every table cell (nested tables included), text-box paragraphs, paragraphs of headers/footers referenced by a section, footnotes, endnotes | `body` + exact part (`""`, `table rRcC`, `... textbox`), `header`, `footer`, `footnote`, `endnote` |
| PPTX | every non-empty paragraph of every text shape (groups included), every non-empty paragraph of every table cell (merged cells skipped), the notes body, per slide in presentation order | `slide` + slide number + part kind (`shape:`, `table:`, `notes`) |
| PDF | every page that carries ink (blank pages excluded) | `page` + page number |

The reference list is built **independently of the extractors**: `structure.py` walks the OOXML parts with its own lxml
code and does not import the extraction package, python-docx or python-pptx (enforced by
`tests/test_structure.py::test_reference_does_not_reuse_extractors`). Embedded images are not units: their OCR text is
scored by detection recall and `not_extracted` instead.

A unit is:

- **found** if its normalised text (NFKC, lower case, whitespace collapsed) equals an extracted block or is contained in
  one (exact matches are preferred, so a one-letter table cell does not match inside a longer cell);
- **locator-correct** if that block's locator is the expected one (above);
- **in order** if it belongs to the longest subsequence of found units whose block positions increase in source order.

**retention = units that are found, locator-correct and in order / all units.** The eval also reports the three
component rates (found, locator among found, order among found) and a per-kind breakdown. Target: >= 0.80.

Limits:

- For PDFs the unit is the page, a much coarser test: a scanned page has no native structure to compare against.
  Text completeness on scans is covered separately by OCR ink coverage (share of glyph ink inside OCR word boxes) and by
  `not_extracted`.
- Sweep blocks (text found only by the XML completeness sweep) never count as retained: they have no structural locator.
- Retention measures the extraction. Masking replaces only finding spans, so the text around every masked span is kept by
  construction (`masking/tokens.apply_masking`); no separate context metric is reported.
