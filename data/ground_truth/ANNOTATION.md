# Ground-truth annotation protocol

One JSONL file per sample, one line per distinct PII value: `{"type", "value", ...}`. The eval matches each value
wherever it occurs in the extracted text (whitespace- and case-insensitive), so a value is listed once even if it appears
on many pages. Extra keys (`pages`, `where`, `note`, `source`) are provenance only; the eval ignores them.

## Independence

| File | How the GT was made | Use |
|---|---|---|
| PPTX | Annotated independently of the detector (phase 0). | accuracy |
| PDF | 2026-10-11: every page rendered from the PDF and read by eye, figures and screenshots zoomed; PDF metadata author added. Detector output and the old GT were not opened before or during annotation. | accuracy |
| DOCX | 2026-10-11: native text dumped straight from the OOXML parts (body, tables, headers, footers, footnotes, core properties, alt text), all 41 embedded images (PNG, EMF, SVG) rendered and read by eye. Detector output and the old GT were not opened. | accuracy |

The previous DOCX/PDF files were built from detector output and hand-pruned. They are kept as
`data/ground_truth_regression/` for regression comparison only (`--truth data/ground_truth_regression`).

## What counts

- **PERSON:** every written form of a natural person's name as printed: full names, names with middle initials, initials
  plus surname (`A. B. Surname`), a surname with a title (`Ms Surname` -> the surname), a surname inside a file path. Each
  distinct form is its own line, because each form must be masked where it appears.
- **EMAIL:** personal mailboxes (`first.last@...`) including external vendor contacts.
- **PHONE:** direct, mobile and personal numbers in every printed format. Each format is its own line.
- **EMPLOYEE_ID:** `EMP-`, `DIR-`, contingent-worker IDs (`XXX-CC-nnnn`) and the badge serial that embeds an employee ID.
- **SSN, TAX_ID (PAN, PESEL), PASSPORT, DATE_OF_BIRTH, ADDRESS (home), FINANCIAL_ACCOUNT (card/account last digits,
  masked card numbers), IP_ADDRESS** (user source IPs in an audit log).
- Partly masked identifiers that still identify in context (`890412xxxxx`, `4111-XXXX-XXXX-1111`, `ending 2218`).

## What does not count (decisions)

- Role and distribution mailboxes (board chair mailbox, committee lists, a vendor operations inbox).
- Organisational numbers: a confidential hotline, corporate switchboards.
- Business addresses (the consultancy letterhead offices).
- A first name used alone as a possessive for a person already listed in full.
- Values cut off at a screenshot edge or a truncated e-mail local part (not legible as a whole value).
- Reference numbers that are not personal (`INC-`, `ISS-`, `LOS-`, `EXC-`, `SPK-`, `PBR-`, `GRP-POL-`, `OP-`).

## Known uncertainty

- Two PDF values come from a small, low-resolution screenshot (page 9) and are marked `"note": "low_legibility"`.
- A single annotator, one pass. No inter-annotator agreement was measured.
