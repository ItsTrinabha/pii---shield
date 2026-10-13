# Cloak

Fail-closed PII gateway between business documents (PDF incl. scanned, PPTX, DOCX) and an LLM. It extracts text
(OCR for scans and images), finds and classifies personal data, replaces it with stable tokens, verifies the result
independently, and refuses to release anything it is not sure about. Everything runs locally.

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
- Optional: `PII_SHIELD_KEY=<secret> docker compose up` keeps tokens stable across restarts.

## Try it

1. Open http://localhost:8765 and drop `data/samples/Cadence_Financial_Group_Organizational_Pack.pptx` on the Scan page.
   It should come back **PASS** with an accuracy panel (these samples have ground truth).
2. Drop `data/samples/Cadence_TPRM_Training.docx`. It comes back **REVIEW**. Open **Review → Needs attention**: each
   item shows the exact text and location. Redact or dismiss it, or select any text to redact it yourself.
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
python -m pii_shield scan data/samples/*.pptx --out out --redact-file --approve "Your Name"
```

## More

- **How it works:** [docs/PIPELINE.md](docs/PIPELINE.md)
- **Measured results:** [docs/RESULTS.md](docs/RESULTS.md)
- Setup details: [docs/README.md](docs/README.md)

Architecture, threat model and limitations are in `docs/`. The Python package is `pii_shield`; the old Streamlit demo
is `pip install -e ".[legacy-ui]" && streamlit run src/pii_shield/app/main.py`.
