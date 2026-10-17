# Decision log

Short records of choices that shape behaviour or results. Format: context -> decision -> consequence.

## D1. Fail closed
Uncertainty is the normal case with OCR and names. **Any** extraction or security error, unexpected exception, empty
extraction, or verifier HARD hit that cannot be healed ends in BLOCKED; softer signals end in REVIEW. Nothing is passed
through "best effort". Consequence: more documents need a reviewer; none is silently released.

## D2. Deterministic base, ML for recall
Regex + validators + context rules are the base layer (reproducible, explainable); Presidio/spaCy NER and the names
layer add recall. Same input and settings give the same output; `Settings.digest()` is stored with each result.

## D3. Independent verifier
The verifier imports nothing from `detection` and uses its own, deliberately over-sensitive rules and gazetteer, so a
detector blind spot is not repeated. HARD hits are force-redacted and the document goes to REVIEW; unmappable HARD hits
block it.

## D4. Stable tokens, no vault
`[TYPE_n]` per document, same entity -> same token, so an LLM keeps relationships. The value-to-token mapping is not
stored; there is no de-masking feature. Audit fingerprints are keyed HMACs (`CLOAK_KEY`).

## D5. Text output, not visual redaction
The product releases sanitised **text** for an LLM. Visual redaction of scanned pages (burning boxes into images) is not
built yet; word boxes are kept in the block geometry so it can be added.

## D6. What is not PII (annotation and allow-list policy)
Not masked by policy and not counted in the GT: organisation and regulator names, corporate/office addresses and
switchboards, role and distribution mailboxes, organisational hotlines, non-personal reference numbers (`INC-`, `ISS-`,
`LOS-`, `EXC-`, `SPK-`, `PBR-`, `GRP-POL-`, `OP-`). The detector still masks some of these (e.g. role mailboxes); that
over-redaction is counted against precision. Allow-lists live in `config/allowlist.json` and are a deliberate hole
in the filter, so they are kept short.

## D7. Partly masked identifiers are PII
A national ID with its tail replaced by `x`, a card number shown as `NNNN-XXXX-XXXX-NNNN`, "card ending NNNN", "the last
four digits of your social security number (NNNN)": partial identifiers still identify in context, so they are in the GT
and should be masked.

## D8. Lone country codes stay readable (2026-10-11)
When the rest of a number is tokenised, a bare `+1` / `+44` may remain. It identifies a country, not a person, and
masking every `+<digits>` would hit scores and percentages. Recorded in SECURITY.md.

## D9. Numbers split by layout (2026-10-11)
OCR splits numbers across lines, table cells and paragraphs. The detector joins prefix and continuation within and across
adjacent blocks of the same page; the verifier checks adjacent blocks independently and flags any `+cc area` prefix with
4+ digits.

## D10. OCR-noise names are auto-redacted, with exceptions (2026-10-11)
SOFT name hits in OCR-derived blocks are force-redacted (counted as forced redactions, status stays REVIEW, reason
`OCR_NAME_REDACTION`). Never in native text. Hits containing a UI label or business word are skipped.
Measured cost (`docs/RESULTS.md`): one person named like a UI label still leaks in a screenshot, and on a fully scanned
document the rule over-redacts heavily. Revisit with a hold-out set.

## D11. Independent ground truth (2026-10-11)
The first DOCX/PDF GT was built from detector output (circular). It was replaced by a manual reading of every page and
image without looking at detector output; the old files are kept for regression only. The independent GT immediately
exposed leaks the circular one had hidden.

## D12. Measure, don't claim
No number appears in docs or slides unless the eval command printed it (`python -m pii_shield.eval`); leaked values are
the headline, with Wilson intervals on recall and counts next to rates.

## D13. Memory-bounded evaluation
The full three-file run was killed by the OS for low memory once. The eval defaults to 2 OCR threads, frees each result
before the next file, and is run one file at a time (`--only`).

## D14. OCR vs native via LibreOffice + rasterisation
To measure the cost of OCR on the same content, PPTX/DOCX are rendered to PDF with a local LibreOffice (throwaway
profile) and rasterised to image-only pages at 200 dpi, then scored against the same GT (`--render-ocr`).

## D15. Structure retention defined on independent source units
Units (paragraphs, table-cell paragraphs, headers/footers, slides' shapes and tables; pages for PDFs) are enumerated by
the eval's own XML walk, not by the extractors, and a unit counts only if found, correctly located and in order
(`docs/METRICS.md`).

## D16. Demo privacy defaults
"Reveal original" is off by default; sanitised blocks that still carry a verifier HARD hit are hidden too unless reveal
is on; the sanitised download goes through `release()`.
