Paste this as your first message in your coding assistant, from the unzipped Cloak folder:

Read CLAUDE.md, docs/CONTEXT.md, docs/STATUS.md and docs/PLAN.md. Then:
1. Set up the venv and run `python -m pii_shield scan` on the three files in data/samples to confirm it works.
2. Fix the open bug (phones split across lines) in detection/patterns.py AND verification/verifier.py, add a regression test, and re-run
   `python -m pii_shield.eval`. Leak must be 0.
3. Then work through the remaining-work list in docs/CONTEXT.md one item at a time, starting with tests, then the Streamlit app.
Plan first, then implement. Never print raw PII. Do not quote any metric not produced by the eval module.
