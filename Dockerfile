# Cloak: local document PII gateway. Build: docker compose up --build   then open http://localhost:8765
FROM python:3.12-slim

ARG INSTALL_LIBREOFFICE=false
ARG INSTALL_DEEP=false
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_OFFLINE=1 \
    HF_HOME=/opt/hf \
    CLOAK_TRUTH_DIR=/app/data/ground_truth

# Tesseract is the main OCR engine; LibreOffice (optional, large) lets DOCX/PPTX EMF/WMF drawings be OCR'd too.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libglib2.0-0 libgl1 libgomp1 \
 && if [ "$INSTALL_LIBREOFFICE" = "true" ]; then apt-get install -y --no-install-recommends libreoffice-core libreoffice-draw libreoffice-writer libreoffice-impress; fi \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first (cached unless pyproject.toml changes), then the pinned spaCy model, then the code.
COPY pyproject.toml README.md LICENSE ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
 && pip install -r /tmp/requirements.txt \
 && pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl

# Optional deep mode (--deep / UI "deep"): GLiNER on CPU-only torch (the default wheel drags in ~2 GB of CUDA). The
# weights are fetched here, at build time, so scans stay offline (HF_HUB_OFFLINE=1) and read them from HF_HOME.
RUN if [ "$INSTALL_DEEP" = "true" ]; then \
      pip install torch --index-url https://download.pytorch.org/whl/cpu \
   && pip install "gliner>=0.2" \
   && HF_HUB_OFFLINE=0 python -c "from gliner import GLiNER; GLiNER.from_pretrained('urchade/gliner_multi_pii-v1')" \
   && chmod -R a+rX /opt/hf; \
    fi

COPY src ./src
RUN pip install --no-deps .

# Synthetic sample documents and their ground truth (powers the accuracy panel for these files).
COPY data/samples ./data/samples
COPY data/ground_truth ./data/ground_truth

RUN useradd --create-home --uid 10001 cloak
USER cloak

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/docs', timeout=4)" || exit 1
CMD ["python", "-m", "pii_shield.app", "--host", "0.0.0.0", "--no-browser"]
