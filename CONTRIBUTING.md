# Contributing to Cloak

Thanks for helping improve Cloak. Keep changes focused, explain the privacy impact, and include tests for new behavior.

## Development setup

```bash
./scripts/setup.sh
source .venv/bin/activate
pytest -q
```

On Windows, create a Python 3.10+ virtual environment, install `.[dev]`, install Tesseract 5, and install the
`en_core_web_lg` spaCy model described in the README.

## Pull requests

1. Create a focused branch and keep unrelated changes out of the pull request.
2. Add or update tests, documentation, and measured results when behavior changes.
3. Run `pytest -q` and `ruff check src tests` before submitting.
4. Describe changes to recall, precision, extraction coverage, release behavior, or threat boundaries.

## Privacy rules

- Use only synthetic or explicitly public test data.
- Never commit real employee, customer, credential, or production documents.
- Never log raw detected values or add them to audit output.
- Never add a network call that can receive unsanitized document content.
- Do not claim accuracy that was not produced by the evaluation harness.

By contributing, you agree that your contribution is licensed under the MIT License.
