# Demo walkthrough (10-15 minutes)

Audience: Optiv / Cadence reviewers. Goal: show that the gateway reads all three sample files, masks the personal data
with traceable tokens, refuses to release what it is not sure about, and reports measured, not claimed, results.

**Before the session**
- `streamlit run src/pii_shield/app/main.py` (first run of the PDF takes a few minutes of OCR; open it once beforehand so
  the result is cached for the session).
- Keep **Reveal original text** off while screen-sharing. Turn it on only for the one moment noted below.
- Have `docs/RESULTS.md` and `docs/ARCHITECTURE.md` open in a second tab.
- Optional backup: `python scripts/demo_check.py` the morning of the demo (drives the app headlessly on all three samples).

## 0. The problem (1 min)
"Teams want to put policies, org packs and training material into an LLM. These files carry names, contact details,
government IDs, sometimes only inside images. The rule we built to: nothing leaves unless an independent check agrees,
and anything uncertain waits for a person."

## 1. Architecture in one picture (2 min)
Show the component diagram in `ARCHITECTURE.md`. Points to make:
- Extraction with locators, OCR as a first-class path (the policy PDF is 35 scanned pages with no text layer).
- Rules first, NER for recall, a names layer for tables and org charts without sentence context.
- An **independent verifier** that shares no code with the detectors, a heal loop, and a three-way gate.
- No network while processing; no raw values in logs or reports.

## 2. PPTX: the clean case (2 min)
Sidebar: *Cadence sample* -> Organizational Reference Pack.
- Status **PASS**. Findings tab: types, tokens, slide and shape locations, detectors, confidence; no values shown.
- *Original vs sanitised*: left column hidden. Right column: org-chart text with `[PERSON_n]`, `[EMAIL_n]`, `[PHONE_n]`.
  Point out that the same person keeps the same token across slides.
- *Release & downloads*: released through the gate; download the sanitised text and the audit HTML.

## 3. DOCX: why REVIEW exists (3 min)
Pick TPRM Training.
- Status **REVIEW**; read the listed reasons aloud and explain each code (`FUNCTIONAL_DESIGN.md`, status logic).
- *Verification* tab: SOFT hits with their locations (table cells, screenshot images).
- *Release & downloads*: no sanitised download yet. The gate demands a reviewer name and an explicit approval.
- Honest point from the evaluation: on this file some names are still missed (two-letter initials, a name that reads
  like a UI label in a screenshot). This is exactly what the reviewer step is for, and why approving without reading the
  flagged locations is the residual risk. (Numbers: `RESULTS.md`, run (b).)

## 4. Scanned PDF: OCR and hard cases (3 min)
Pick the Group Risk Management Policy.
- Header metrics: OCR pages and mean confidence, forced redactions.
- *Original vs sanitised* for page 22 (incident case study): the hardest class, identifiers inside prose without labels.
  If you need to show the original here, switch **Reveal** on for this page only, then off again.
- Pages 4 and 10: phone numbers that OCR split across lines and table cells, masked on both halves with one token.
- Explain BLOCKED vs REVIEW: a verifier hit that cannot be mapped back to the source would block the whole document.

## 5. Measured results (2 min)
Open `RESULTS.md`. Lead with **leaked values**, then recall with confidence intervals, then precision as the cost.
- Ground truth was rebuilt independently by reading every page and image; the earlier circular ground truth had hidden
  real leaks, and the table shows both.
- Structure retention against independent source units (brief target 80%), and the OCR-vs-native comparison: same
  content, rendered and OCR'd, scored against the same ground truth.
- Do not quote any number that is not in that file.

## 6. Limits and next steps (1-2 min)
From `LIMITATIONS.md`: three synthetic files, tuned on the same set (no hold-out yet), names and OCR are the weak spots,
no visual redaction of scans yet. Next: hold-out split, then close the known misses; visual redaction; public benchmark.

## Questions to expect
- *Can it de-mask?* No vault by design; tokens are per document; fingerprints are keyed HMACs for audit correlation only.
- *What if the LLM call is compromised?* It only ever receives text that passed the gate; the instruction is checked too.
- *Why not just use an LLM to find PII?* Unsanitised text would have to leave the boundary first; detection runs locally.
- *Prompt injection in documents?* Passed through as sanitised content; downstream prompts must treat it as data.
