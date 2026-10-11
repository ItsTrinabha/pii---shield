# File analysis: the three Cadence samples

Deliverable 1 of the brief: what each file really is, where personal data sits in it, and which extraction path that
forces. Structure facts below were read from the files themselves (zip parts, XML, PDF objects); the PII inventory is the
independent ground truth in `data/ground_truth/` (protocol: `data/ground_truth/ANNOTATION.md`). All content is synthetic.

## Summary

| File | Format reality | Extraction path | Where the PII is |
|---|---|---|---|
| Group Risk Management Policy v6.0 (PDF) | 35 pages, US Letter; every page is one embedded JPEG scan (28 at 1654x2339, 7 at 1659x2346 px, about 200 ppi); the text layer is empty; metadata `author` holds a personal name | OCR only, plus metadata scan | Everywhere: register tables, an org chart figure, narrative prose, a customer letter, screenshots, a scanned form, a terminal log, an ID badge, approval tables |
| Organizational Reference Pack (PPTX) | 9 slides, one layout, one picture per slide, 3 tables (slides 6-8), 9 notes slides that carry only the slide-number placeholder; core properties filled | Native: shapes (incl. groups), tables, notes, masters/layouts, alt text, metadata | Shape text of org charts and contact blocks (names, e-mails, phones), RACI/contact tables |
| TPRM Training (DOCX) | About 84 pages; 16 tables (221 rows), 2,633 paragraphs, 2 text boxes, 4 header and 2 footer parts, no comments; 41 media files (35 PNG screenshots, 5 EMF, 1 SVG); core properties `creator` and `lastModifiedBy` hold personal names | Native for text, tables, headers/footers, metadata; OCR for the PNG screenshots and the rendered EMF images | User-group tables (names only, one per line in a cell), a version-control table, screenshots of the configured tool, document metadata |

## PDF: Group Risk Management Policy

- **No text layer.** Every page is an image, so OCR is the only route to the text. OCR quality drives everything:
  small figure captions, light grey text, white-on-navy table headers and a dark terminal screenshot are the hard regions.
  The pipeline records per-page OCR confidence and ink coverage and holds weak pages for review.
- **Personal data in many forms:**
  - register and contact tables (issues, incidents, losses, exceptions, training, breaches, appetite owners);
  - narrative prose without field labels (an incident case study mixing names, employee IDs, a date of birth, an SSN,
    a passport number, a national tax ID, a home address, an external e-mail and a phone number);
  - customer correspondence (card and account last digits, last four of an SSN, a spouse's name, a home address);
  - images inside the scan: an org chart, an identity-record screenshot, a user-list screenshot, a scanned attestation
    form, a terminal audit log with user e-mails and source IPs, a staff ID badge;
  - the PDF metadata author.
- **Many surface forms per person:** full name, name with middle initial, initials plus surname, surname inside a file
  path. Each form must be masked where it appears, and the stable token should be shared across forms.
- **Phone formats:** at least eight national formats, with numbers wrapped across lines or split by table layout.
- **Not PII by decision:** role and committee mailboxes, a confidential hotline, reference numbers such as `INC-`, `ISS-`,
  `LOS-`, `EXC-`, `GRP-POL-`.

## PPTX: Organizational Reference Pack

- Native text in shapes, so extraction is exact; the risk is coverage, not reading: shapes in groups, table cells,
  masters/layouts, notes, alt text and core properties all have to be read.
- Org-chart shapes hold a name, a title, an e-mail and a phone each, with no sentence context, so name detection relies
  on patterns and the names layer rather than on NER.
- Slides 6-7 carry RACI matrices: many one-letter cells, which is why reading-order checks need exact matching.
- One picture per slide is OCR'd; a rendered-and-OCR'd variant of the deck is used in the OCR-vs-native comparison.

## DOCX: TPRM Training

- Mostly configuration prose and rule tables with no personal data; the personal data concentrates in a few places:
  the user-group tables (names only, several per cell separated by line breaks), the version-control table, screenshots
  of the configured platform (user lists, "created by" columns), and the core properties.
- Two-letter initials used as first names (`AA Surname` shape) and a person whose name reads like a UI label appear in
  the data: both are hard cases for name detection.
- The 5 EMF images are vector graphics (a letterhead, logos, a background); they need a renderer before OCR. Without
  LibreOffice the document is held for review (`UNSUPPORTED_MEDIA`).
- The consultancy letterhead carries office addresses and switchboard numbers: business contact data, not PII by
  decision.

## Consequences for the design

1. One router, three extractors, and OCR as a first-class path (not a fallback).
2. Locators down to page/slide, part (table cell, notes, image) and block, so every finding is traceable.
3. A names layer that works without sentence context (tables, org charts, user lists) and keeps one identity across
   name variants.
4. Metadata and hidden structures scanned like body text.
5. An independent verifier and a review state, because OCR and name detection cannot be complete.
