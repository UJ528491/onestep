from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProcessingMode(str, Enum):
    DOCUMENT_CLEANUP = "document_cleanup"
    RESIZE_ONLY = "resize_only"
    PDF_CONVERT = "pdf_convert"
    PDF_BUNDLE = "pdf_bundle"


@dataclass(frozen=True)
class ProcessingOptions:
    mode: ProcessingMode = ProcessingMode.DOCUMENT_CLEANUP
