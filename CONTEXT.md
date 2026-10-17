# CONTEXT - read this first (Claude Code)

## Who / what
- User: "Jedi", pre-final-year B.Tech CS (Cybersecurity), VIT Vellore. Targeting SWE internships.
- Task: Optiv Consulting x VIT internship recruitment, **Case Study 2: Text Analysis and PII Detection** for Cadence Financial Group documents.
- Team submission. Clarification session 1 Oct 2026. **Presentation 14 Oct 2026**: PPTX deck, 10-15 min walkthrough, live demo.
- User wants the project COMPLETE and real (a cybersecurity product), not just a demo. Timeline is not the focus.

## Optiv brief (summary - re-read original if available)
- Input: three Cadence docs: scanned PDF (Group Risk Management Policy v6.0), PPTX (Organizational Pack), DOCX (TPRM Training).
- Deliver: file structure analysis; text extraction from scanned PDF/PPTX/DOCX; PII detection + classification
  (employee IDs, full names, contact details, government IDs); transparent tags; source traceability (file/page/slide);
  exposure reporting; functional design diagram + architecture diagram; >=80% structure retention; PII coverage approaching 100%; live demo.
- Roles in brief: Cadence (client), Optiv consultants. All data is synthetic.

## Product framing
A fail-closed security gateway between business documents and an LLM:
extract -> normalise -> detect -> fuse -> mask -> INDEPENDENT verify -> heal -> release gate (PASS / REVIEW / BLOCKED).
`SanitizedText` can only be created by `release()`. No reversible vault. No network at runtime. Never log PII values.

## Key design decisions (and why)
- Hybrid detection: regex+validators (deterministic base), Presidio+spaCy en_core_web_lg NER (recall), name context patterns,
  Faker first/last-name gazetteers + wordfreq (to reject common words), document lexicon expansion ("R. E. Duarte"/"Duarte"/"Rafael").
  Noisy-OR fusion by detector family.
- Verifier must NOT import detection code (independent blind spots). HARD hits -> forced redaction -> REVIEW; persistent -> BLOCKED.
- OCR: Tesseract image_to_data, 250 dpi, recovery pass for white-on-navy text, ink-coverage completeness diagnostic. Threads not processes
  (spawn pools broke on __main__ re-import).
- OOXML: python-pptx/python-docx plus independent XML completeness sweep (headers, footers, footnotes, comments, tracked deletions,
  text boxes, alt text, hyperlinks, metadata). EMF/WMF rendered via LibreOffice. XXE / zip-bomb / path-traversal / type-confusion guards.
- Unicode normalisation with exact offset map (zero-width, NFKC, Cyrillic/Greek confusables).
- tldextract forced offline (Presidio otherwise fetches the suffix list).
- Stable per-document tokens [PERSON_1]; HMAC fingerprints (key from `CLOAK_KEY` or random per run).

## Bugs already fixed (do not reintroduce)
Spawn ProcessPool crash; tldextract network fetch; flawed ink-coverage metric; EMF unsupported; NER false positives
("Denver Office", "Final Due", "Peer Reviewer"); lexicon learning common words as first names ("Taxonomy Lindqvist");
verifier DOB regex matching lowercase; verifier noise on reference numbers (INC-2026-0417, PH-2214); phone spans with trailing digits.

## Measured so far (python -m pii_shield.eval)
- PPTX: independent GT (61 values) -> recall 1.0, precision 1.0, leak 0. Status PASS.
- DOCX: ~21 persons + 2 phones; REVIEW (1 soft hit "Mark Read" = UI button, false alarm). GT is circular.
- PDF (~70 s, 29+ pages OCR): ~890 findings; 3 forced redactions; GT is circular.
- Do NOT quote DOCX/PDF numbers as accuracy until independent GT exists (CLAUDE.md rule 6: measure, don't claim).

## OPEN BUG (fix first)
PDF phones split across lines ("+1 (704)\n555-0166", "+46 8\n5555 0121", "+49 69\n5555 0177") remain readable in sanitized text;
detector AND verifier miss them. See docs/STATUS.md.

## Datasets the user picked (not yet used; sandbox could not reach them)
- Kaggle alejopaullier/pii-external-dataset
- HF ai4privacy/pii-masking-200k
- Mendeley data tzrjx692jy/1
Check licences + label mapping before use. Use for benchmarking/fine-tuning only AFTER the deterministic+NER pipeline is measured.

## User's 25-step plan (condensed)
requirements -> artifact analysis -> Kaggle data -> taxonomy -> architecture -> ingestion -> OCR -> deterministic detection ->
ML/NLP -> hybrid fusion -> confidence -> classification -> stable masking -> traceability -> independent verification (fail-closed) ->
eval framework -> benchmark (Kaggle + Cadence) -> metrics (P/R/F1, OCR vs native, FP/FN) -> improve from failures -> fine-tune last ->
Streamlit demo -> audit report -> security/edge-case tests -> architecture/results/limitations/walkthrough -> final packaging.

## Remaining work
Streamlit app (upload, locators, original vs sanitized with reveal OFF by default, downloads, status banner, maxUploadSize, telemetry off);
tests (zip bomb, traversal, XXE, type confusion, corrupt/empty/encrypted, unicode obfuscation, prompt-injection text, no PII in logs,
no network, fail-closed); independent GT for DOCX/PDF; OCR-vs-native eval (render PPTX/DOCX via LibreOffice->PDF->OCR);
structure-retention metric (native: text-unit coverage vs raw XML count; OCR: ink coverage + mean conf); visual redaction of scanned PDF
(burn boxes from WordBox geometry); gateway demo with SanitizedText-typed LLM call; THREAT_MODEL.md, SECURITY.md, README, RESULTS.md,
FILE_ANALYSIS.md, DECISIONS.md; Mermaid architecture + functional diagrams; limitations; walkthrough script; final Optiv .pptx deck.
