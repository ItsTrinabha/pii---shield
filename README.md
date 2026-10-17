# Cloak

Local, fail-closed PII gateway for PDF (including scans), PPTX and DOCX documents. Cloak extracts native and OCR text,
detects and classifies personal data, replaces it with stable tokens, independently verifies the sanitized output, and
holds anything uncertain for review. Document processing runs locally; unsanitized content is never sent to a model.

## Highlights

- Native extraction plus Tesseract/RapidOCR for scans and embedded images.
- Deterministic validators, Presidio/spaCy NER, custom name logic, and optional GLiNER detection.
- Independent residual-PII verifier with automatic healing and fail-closed release control.
- Stable per-document tokens, keyed audit fingerprints, and no reversible value vault.
- Browser UI, CLI, Python API, audit reports, measured evaluation, and verified redacted-file output.
- Defensive handling of encrypted files, ZIP bombs, path traversal, XXE, oversized images, and type confusion.

## Quick start (any machine, Docker)

Needs [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows / macOS) or Docker Engine (Linux).

```bash
git clone <this repo> cloak && cd cloak
docker compose up --build        # first build downloads ~1 GB of dependencies; later starts take seconds
```

Open **http://localhost:8765**, drop in a PDF/PPTX/DOCX (the three samples are in `data/samples/`).
Stop with `Ctrl+C`, or run it in the background with `docker compose up -d --build` and stop with `docker compose down`.

- The port is published on `127.0.0.1` only: other machines on the network cannot reach it.
- Optional: `INSTALL_LIBREOFFICE: "true"` in `docker-compose.yml` also OCRs EMF/WMF drawings inside DOCX/PPTX (+~500 MB).
- Optional: `CLOAK_KEY=<secret> docker compose up` keeps audit fingerprints stable across restarts.

## Try it

1. Open http://localhost:8765 and drop one of the synthetic documents from `data/samples/` on the Scan page.
2. For a **REVIEW** result, open **Review → Needs attention**. Inspect, redact, or dismiss each item, or select any text
   to add a manual redaction.
3. Enter your name and **Approve**, then download the sanitised text or the redacted file.
4. **Audit** shows every finding, a per-page coverage map and the extraction quality, and exports JSON/HTML reports.

## Run the tests

```bash
./scripts/setup.sh && source .venv/bin/activate     # once (needs tesseract-ocr installed)
pytest -q                                            # unit, security, fail-closed, web API tests (~40 s)
python -m pii_shield.eval --corpus data/samples --truth data/ground_truth --only pptx   # accuracy vs ground truth
```

## Without Docker (Linux / macOS / WSL)

```bash
sudo apt-get install -y tesseract-ocr     # macOS: brew install tesseract
./scripts/setup.sh                        # creates .venv, installs dependencies and the spaCy model
source .venv/bin/activate
python -m pii_shield.app                  # web UI on http://127.0.0.1:8765
```

Command line:

```bash
cloak scan data/samples/*.pptx --out out --redact-file --approve "Your Name"
# Equivalent without the installed entry point:
python -m pii_shield scan data/samples/*.pptx --out out --redact-file --approve "Your Name"
```

## More

- **How it works:** [docs/PIPELINE.md](docs/PIPELINE.md)
- **Measured results:** [docs/RESULTS.md](docs/RESULTS.md)
- Setup details: [docs/README.md](docs/README.md)

Architecture, threat model and limitations are in `docs/`. The Python package is `pii_shield`; the old Streamlit demo
is `pip install -e ".[legacy-ui]" && streamlit run src/pii_shield/app/main.py`.

## Security and limitations

Cloak reduces disclosure risk; it does not guarantee that every possible PII value will be detected. Review
[the threat model](docs/THREAT_MODEL.md), [known limitations](docs/LIMITATIONS.md), and
[measured results](docs/RESULTS.md) before using it with sensitive workflows. Report vulnerabilities privately using
[SECURITY.md](SECURITY.md). Never commit or submit real personal data in an issue.

## Contributing and license

Contributions are welcome under the rules in [CONTRIBUTING.md](CONTRIBUTING.md). Cloak is available under the
[MIT License](LICENSE).
