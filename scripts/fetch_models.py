"""One-off model download (online). Scans run offline afterwards: python scripts/fetch_models.py"""
from gliner import GLiNER

from pii_shield.settings import Settings

GLiNER.from_pretrained(Settings().gliner_model)
print("ok")
