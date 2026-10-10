# Security checklist

Each item names the control and the test that proves it. "Accepted" items are known gaps, stated on purpose.

## Upload handling (`security.py`, `extraction/router.py`)
- [x] Size limit before parsing (`Limits.max_upload_bytes`, Streamlit `maxUploadSize`) - `test_upload_too_large`
- [x] Real type from magic bytes; extension must agree - `test_pdf_named_as_docx`, `test_docx_named_as_pdf`, `test_docx_named_as_pptx`, `test_random_bytes`
- [x] Only pdf/pptx/docx accepted - `test_unsupported_extension`
- [x] File name is display-only, stripped of paths and control characters - `test_hostile_filename_is_neutralised`
- [x] Empty file - `test_empty_file`

## Containers and parsers
- [x] ZIP bomb: entry count, total uncompressed size, per-entry ratio - `test_zip_bomb_ratio`, `test_zip_bomb_total_size`, `test_too_many_entries`
- [x] Path traversal entries (`../`, absolute) - `test_path_traversal`
- [x] Encrypted ZIP entries / encrypted PDF - `test_encrypted_zip_entry`, `test_encrypted_pdf`
- [x] XXE: DTD/ENTITY declarations rejected; lxml parser with `resolve_entities=False, no_network=True` - `test_xxe_rejected_and_not_resolved`
- [x] Corrupt / truncated files - `test_truncated_docx`, `test_corrupt_pdf`, `test_missing_main_part`
- [x] Image decompression bombs (`max_image_pixels`) - enforced in `ocr.load_image`
- [x] Page limit for PDFs (`max_pdf_pages`)

## Fail-closed behaviour (`pipeline.py`)
- [x] Every typed error and every unexpected exception -> BLOCKED; message carries the exception type only - `test_unexpected_exception_blocks_without_leaking`
- [x] BLOCKED never releases, even with an approver - `test_blocked_never_releases`
- [x] REVIEW releases only with a named approver - `test_review_needs_named_approver`
- [x] Low OCR confidence / incomplete OCR ink coverage -> REVIEW - `test_low_ocr_confidence_forces_review`, `test_incomplete_ocr_forces_review`
- [x] Missing OCR engine -> OCR_FAILED -> BLOCKED (not silently skipped)
- [x] Independent verifier (no imports from `detection`) catches detector misses and forces redaction - `test_verifier_does_not_import_detection`, `test_verifier_catches_detector_miss`
- [x] Empty extraction -> BLOCKED - `test_empty_extraction_blocks`

## Privacy of the gateway itself
- [x] No raw PII in logs, audit JSON/HTML or status reasons - `test_no_pii_in_logs_or_reports`
- [x] Findings carry offsets + keyed HMAC fingerprint, never the value - `test_findings_carry_no_raw_value`
- [x] No network while processing (sockets patched to fail) - `test_no_network_during_processing`, `test_no_network_with_ner`
- [x] tldextract forced onto its bundled suffix list (Presidio would otherwise fetch it)
- [x] Streamlit telemetry off, error details hidden, original text hidden until "reveal" is switched on
- [x] No reversible vault: tokens are per-document sequence numbers; fingerprints need `PII_SHIELD_KEY`

## LLM boundary (`gateway.py`)
- [x] Only a sealed `SanitizedText` from `release()` is accepted; plain strings, hand-built or edited objects are refused - `test_gateway.py`
- [x] The caller's instruction is checked by the verifier too - `test_pii_in_instruction_is_refused`
- [ ] Accepted: the seal stops mistakes, not malicious code running in the same process (it could import the key).

## Evasion
- [x] Zero-width characters, full-width digits, Cyrillic/Greek look-alikes, odd hyphens, `[at]/[dot]` e-mails - `test_unicode_and_obfuscation`
- [x] Numbers wrapped across lines - `test_phone_wrap.py`
- [ ] Accepted: text drawn as vector paths in PDFs is only seen if the page is OCR'd; EMF/WMF needs LibreOffice, otherwise the document goes to REVIEW (`UNSUPPORTED_MEDIA`).
- [ ] Accepted: prompt-injection text inside a document is passed through as (sanitised) content. The gateway removes PII; it does not judge instructions. Downstream prompts must treat document text as data.

## Supply chain
- [ ] Run `pip-audit` before submission and record the result here.
- [x] Versions pinned by lower bound in `pyproject.toml`; model `en_core_web_lg` loaded locally.
