"""Exception types shared across pdf_worker features."""


class PdfWorkerError(Exception):
    """Base class for all errors raised deliberately by pdf_worker."""


class PdfOpenError(PdfWorkerError):
    """The input file is missing, unreadable, or not a valid PDF."""
