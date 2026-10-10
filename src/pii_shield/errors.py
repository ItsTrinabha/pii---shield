"""Typed errors. Every one of these turns into Status.BLOCKED (fail-closed). Messages never contain document text."""


class PiiShieldError(Exception):
    code = "ERROR"

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class UnsupportedFileError(PiiShieldError):
    code = "UNSUPPORTED_FILE"


class SecurityError(PiiShieldError):
    """Upload looks hostile (zip bomb, traversal, type confusion, ...)."""

    code = "SECURITY_REJECTED"


class ExtractionError(PiiShieldError):
    code = "EXTRACTION_FAILED"


class OcrError(PiiShieldError):
    code = "OCR_FAILED"


class BlockedError(PiiShieldError):
    """Raised when downstream code tries to use a result that has not been released."""

    code = "BLOCKED"
