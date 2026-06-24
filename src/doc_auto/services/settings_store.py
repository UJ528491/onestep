from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
from pathlib import Path

from doc_auto.services.image_pipeline import ImageNormalizationOptions
from doc_auto.services.image_resizer import ResizeOptions
from doc_auto.services.temp_storage import PortableStorage


@dataclass(frozen=True)
class AppSettings:
    auto_start_on_drop: bool = True
    temp_dir: Path | None = None
    rotation_enabled: bool = True
    resize_enabled: bool = True
    png_to_jpg_enabled: bool = True
    pdf_convert_delete_source: bool = True
    pdf_bundle_delete_source: bool = True
    archive_delete_source: bool = False
    archive_extract_to_current_dir: bool = False
    pdf_tiff_extract_to_current_dir: bool = True
    always_unbundle_for_edit: bool = False
    resize_max_long_side: int = 1920
    png_to_jpg_threshold_bytes: int = 1_000_000
    jpeg_quality: int = 95

    @property
    def normalization(self) -> ImageNormalizationOptions:
        return ImageNormalizationOptions(
            exif_orientation_enabled=self.rotation_enabled,
            ocr_orientation_enabled=self.rotation_enabled,
        )

    @property
    def resize_options(self) -> ResizeOptions:
        return ResizeOptions(
            resize_enabled=self.resize_enabled,
            png_to_jpg_enabled=self.png_to_jpg_enabled,
            max_long_side=self.resize_max_long_side,
            png_to_jpg_threshold_bytes=self.png_to_jpg_threshold_bytes,
            jpeg_quality=self.jpeg_quality,
        )


class SettingsStore:
    def __init__(self, storage: PortableStorage) -> None:
        self.storage = storage
        self.path = self.storage.data_dir / "settings.json"

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AppSettings()

        if not isinstance(data, dict):
            return AppSettings()

        defaults = asdict(AppSettings())
        merged = {**defaults}
        for field in fields(AppSettings):
            if field.name not in data:
                continue
            value = data[field.name]
            if field.name == "temp_dir":
                merged[field.name] = Path(value) if value else None
            elif field.name == "auto_start_on_drop":
                merged[field.name] = True
            else:
                merged[field.name] = value

        return AppSettings(**merged)

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(settings)
        payload["auto_start_on_drop"] = True
        payload["temp_dir"] = str(settings.temp_dir) if settings.temp_dir else None
        payload["normalization"] = asdict(settings.normalization)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
