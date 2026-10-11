# Architecture

PII Shield is a local, fail-closed gateway between business documents and an LLM. It turns a PDF (native or scanned),
PPTX or DOCX into sanitised text in which every detected personal value is replaced by a stable token, verifies that
output with independent logic, and releases it only through a sealed gate.

## Component view

```mermaid
flowchart LR
    subgraph Input["Untrusted input"]
        F[PDF / PPTX / DOCX]
    end
    subgraph Gateway["PII Shield (local process, no network)"]
        R[router + security checks<br/>extraction/router.py, security.py]
        X[extractors<br/>pdf.py · pptx.py · docx.py · ooxml.py]
        O[OCR<br/>ocr.py · vector.py]
        N[normaliser<br/>detection/normalize.py]
        D1[patterns + validators<br/>patterns.py]
        D2[Presidio + spaCy NER<br/>ner.py]
        D3[names layer<br/>names.py]
        FU[fusion<br/>fusion.py · engine.py]
        M[stable-token masking<br/>masking/tokens.py]
        V[independent verifier<br/>verification/verifier.py]
        G{gate<br/>pipeline.py}
        A[audit report<br/>reporting/audit.py]
    end
    subgraph Out["Outputs"]
        S[SanitizedText<br/>sealed]
        AU[audit JSON / HTML<br/>no raw values]
        LLM[LLM via gateway.ask_llm]
    end
    F --> R --> X
    X -- images, scanned pages --> O --> X
    X -- blocks + locators --> N --> D1 & D2 & D3 --> FU --> M --> V
    V -- HARD hit --> M
    V --> G
    G -- PASS, or REVIEW + named approver --> S --> LLM
    G -- BLOCKED --> AU
    G --> AU
```

## Pipeline stages

| Stage | Module | Contract |
|---|---|---|
| Route and validate | `extraction/router.py`, `security.py` | Real type from magic bytes; size, zip-entry count, ratio and total size, path traversal, encryption and XXE checks before any parsing. Any violation raises a typed error. |
| Extract | `extraction/pdf.py`, `pptx.py`, `docx.py`, `ooxml.py` | Produces `Block`s (text + `Locator` = file, unit, page/slide, part, block id). Covers body, tables, text boxes, headers/footers, footnotes, notes, masters/layouts, alt text, hyperlinks, document metadata, and an XML completeness sweep for anything the structured walk missed. |
| OCR | `extraction/ocr.py`, `vector.py` | Scanned pages and embedded images go through Tesseract with per-word boxes and confidence; a second pass reads glyph ink the first pass missed; EMF/WMF are rendered with a local LibreOffice when present. Page OCR confidence and ink coverage are recorded. |
| Normalise | `detection/normalize.py` | Unicode folding (zero-width, full-width, look-alikes), whitespace and line-wrap repair, with an offset map back to the original text. |
| Detect | `patterns.py`, `ner.py`, `names.py` | Deterministic patterns with validators (e-mail, phone, IDs, SSN, tax IDs, passport, DOB, address, financial, IP), Presidio + spaCy NER as an independent recall layer, and a names layer (gazetteers, context patterns, per-document registry of name variants). |
| Fuse | `fusion.py`, `engine.py` | Merges overlapping candidates, resolves type conflicts by priority, combines evidence (noisy-OR), applies thresholds: >= mask threshold is masked, the review band becomes a REVIEW candidate. Cross-block pass for numbers split by OCR layout. |
| Mask | `masking/tokens.py` | Replaces each finding with a stable per-document token (`[PERSON_3]`); the same entity gets the same token everywhere. No reversible vault; the audit fingerprint is a keyed HMAC. |
| Verify | `verification/verifier.py` | Separate, deliberately over-sensitive rule set that imports nothing from `detection`. HARD hits = residual PII almost certain; SOFT hits = a human should look. |
| Heal | `pipeline.py` | HARD hits are mapped back to source text (piecewise around existing tokens) and force-redacted; up to four rounds. SOFT name hits in OCR-derived blocks are force-redacted too (decision of 2026-10-11). |
| Gate | `pipeline.py` | **PASS** only if no HARD hits remain and no review signal exists. **REVIEW** for forced redactions, SOFT hits, low-confidence candidates, weak OCR, unsupported media. **BLOCKED** for any extraction/security error, an unexpected exception, empty extraction, or HARD hits that could not be healed. |
| Release | `pipeline.release`, `gateway.py` | The only way to get LLM-facing text: returns a sealed `SanitizedText`. BLOCKED never releases; REVIEW needs a named approver. `gateway.ask_llm` accepts only a sealed object and verifies the caller's instruction too. |
| Report | `reporting/audit.py` | Audit JSON/HTML: status, reasons, counts by type and classification, locators, offsets, tokens, fingerprints, verifier rules. Never values. |

## Data model (`models.py`)

```mermaid
classDiagram
    class Block { id; text; locator; source: native|ocr|metadata|sweep; ocr_confidence; geometry }
    class Locator { file; unit: page|slide|body|header|footer|notes|metadata|...; index; part; block_id }
    class Finding { id; type; block_id; start; end; confidence; detectors; token; fingerprint; ocr_derived }
    class SanitizedBlock { id; locator; text }
    class Verification { passed; hard_hits; soft_hits; rules_run }
    class PipelineResult { status: PASS|REVIEW|BLOCKED; reasons; document; findings; sanitized_blocks; verification }
    class SanitizedText { document; blocks; approved_by; seal }
    PipelineResult --> Block
    PipelineResult --> Finding
    PipelineResult --> SanitizedBlock
    PipelineResult --> Verification
    Block --> Locator
    Finding --> Locator
    SanitizedText --> SanitizedBlock
```

Traceability: every finding resolves to `file -> page/slide/section -> block id -> char span -> detectors -> confidence`.

## Trust boundaries

1. **Document -> gateway:** the file is hostile until the router and parsers accept it (zip bombs, XXE, traversal,
   decompression bombs, encryption, type confusion).
2. **Gateway -> LLM:** only a sealed `SanitizedText` crosses; anything else is refused in `gateway.ask_llm`.
3. **Gateway -> operator (UI, CLI, audit):** no raw values in logs, reasons, audit files or the findings table; the
   original text is shown only when the operator turns "reveal" on, and sanitised blocks that still carry a verifier HARD
   hit are hidden the same way.

There is no network use while processing (enforced by tests that make socket creation fail).

## Determinism and configuration

`settings.py` holds every threshold and limit; `Settings.digest()` is recorded in each result. Rules are deterministic,
the NER model is pinned by name (`en_core_web_lg`), and the same input with the same settings gives the same findings.
Deployment-specific allow-lists (organisations, corporate addresses, business vocabulary, UI labels) live in
`config/allowlist.json`.

## Evaluation harness (`eval/`)

`python -m pii_shield.eval` runs the pipeline on the samples, scores it against value-based ground truth, and reports
leaks, recall, precision and structure retention; `--render-ocr` runs the OCR-vs-native comparison. Definitions:
`docs/METRICS.md`; results: `docs/RESULTS.md`.
