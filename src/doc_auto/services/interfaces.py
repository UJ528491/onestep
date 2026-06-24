from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from doc_auto.domain.job import WorkItem
from doc_auto.services.image_pipeline import ImagePipelineResult
from doc_auto.services.image_resizer import ResizeResult
from doc_auto.services.input_preparation import PreparedInput
from doc_auto.services.ocr_runner import OcrData
from doc_auto.services.pdf_converter import PdfConversionResult


class InputPreparer(Protocol):
    def prepare_items(self, items: Iterable[WorkItem]) -> list[PreparedInput]:
        ...


class ImageNormalizer(Protocol):
    def normalize(self, image_path: Path) -> ImagePipelineResult:
        ...


class OcrService(Protocol):
    def run(self, image_path: Path) -> OcrData:
        ...


class ImageResizeService(Protocol):
    def resize_in_place(self, image_path: Path) -> ResizeResult:
        ...


class PdfBuildService(Protocol):
    def convert_single_to(self, image_path: Path, output_path: Path) -> PdfConversionResult:
        ...

    def convert_bundle(self, image_paths: list[Path], output_path: Path) -> PdfConversionResult:
        ...


class HwpPdfService(Protocol):
    def convert_to_pdf(
        self,
        hwp_path: Path,
        output_path: Path,
        *,
        permission_hwp_path: Path | None = None,
    ) -> PdfConversionResult:
        ...
