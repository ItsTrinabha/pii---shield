# PII Shield — project rules for Claude Code

Security gateway that sits between business documents (PDF incl. scanned, PPTX, DOCX) and an LLM.
It extracts text with source locators, detects and classifies PII, replaces it with stable tokens,
verifies the output independently, and refuses to release anything it is not sure about.
Origin: Optiv / Cadence case study 2. Full plan: `docs/PLAN.md`. Phase prompts: `docs/PROMPTS.md`.

## Non-negotiable rules
1. **Fail closed.** Any extraction/OCR error, low-confidence page, or verifier hit => output is BLOCKED, never passed through.
2. **Never log or print raw PII values.** Logs carry entity type, token id, file, page/slide, offsets, confidence only. Tests and fixtures use synthetic data only.
3. **No network calls with unsanitized text.** Detection and verification run locally. An LLM may only ever see text that already passed the verifier.
4. **Deterministic first.** Regex/validators and rules are the base layer; ML only adds recall. Same input => same output (pin versions, no randomness without a seed).
5. **Every finding is traceable:** `file -> page/slide/section -> block id -> char span -> detector -> confidence`.
6. **Measure, don't claim.** No coverage/accuracy number in code, docs or slides unless produced by `python -m pii_shield.eval`.

## Layout (target)
```
src/pii_shield/
  models.py            # pydantic: Block, Locator, Finding, Result
  extraction/          # pdf.py pptx.py docx.py ocr.py router.py
  detection/           # patterns.py validators.py presidio_engine.py context_rules.py fusion.py
  masking/             # tokens.py (stable tokens, vault-free)
  verification/        # independent verifier (different logic from detection)
  reporting/           # audit report json/md/html
  eval/                # ground truth loader, metrics, benchmark runners
  app/                 # streamlit UI
tests/                 # unit + golden + adversarial
data/samples/          # the 3 Cadence files (synthetic)
data/ground_truth/     # annotated spans, one JSONL per file
docs/
```

## Commands
- Setup: `python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
- Tests: `pytest -q`   Lint/types: `ruff check . && mypy src`
- Eval: `python -m pii_shield.eval --corpus data/samples --truth data/ground_truth`
- Demo: `streamlit run src/pii_shield/app/main.py`
- System deps: `tesseract-ocr`, `poppler-utils` (PyMuPDF renders pages itself)

## Working style
- One phase per session. Start in plan mode, agree the plan, then implement with tests first.
- Small commits: `phase-N: what changed`. Run `pytest` before every commit.
- When a detector change moves a metric, record before/after in `docs/RESULTS.md`.
- Ask before adding heavy dependencies or downloading models/datasets.

## Definition of done (any phase)
Tests pass, no raw PII in logs/fixtures, fail-closed behaviour covered by a test, `docs/PLAN.md` checkboxes updated.
