from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class OcrData:
    text: str
    tokens: list[dict]
    width: int
    height: int
    error: str = ""


class OcrRunner(Protocol):
    def run(self, image_path: Path) -> OcrData:
        ...


class WindowsOcrRunner:
    def run(self, image_path: Path) -> OcrData:
        from doc_auto.services.ocr import OcrEngine

        result = OcrEngine().run(Path(image_path), None, force=True)
        return OcrData(
            text=result.text or "",
            tokens=result.tokens or [],
            width=int(result.image_width or 0),
            height=int(result.image_height or 0),
            error=result.error or "",
        )
