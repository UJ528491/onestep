from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import uuid

from doc_auto.services.file_replace import replace_file_with_retry
from doc_auto.services.temp_storage import PortableStorage


@dataclass(frozen=True)
class ResizeOptions:
    resize_enabled: bool = True
    png_to_jpg_enabled: bool = True
    max_long_side: int = 1920
    png_to_jpg_threshold_bytes: int = 1_000_000
    jpeg_quality: int = 95


@dataclass(frozen=True)
class ResizeResult:
    input_path: Path
    output_path: Path
    original_size: tuple[int, int]
    final_size: tuple[int, int]
    resized: bool
    converted_to_jpg: bool


class ImageResizer:
    def __init__(self, storage: PortableStorage, options: ResizeOptions | None = None) -> None:
        self.storage = storage
        self.options = options or ResizeOptions()

    def resize_in_place(self, image_path: Path) -> ResizeResult:
        from PIL import Image

        image_path = Path(image_path)
        with Image.open(image_path) as image:
            image = image.copy()
        original_size = image.size
        resized = False
        target_path = image_path

        long_side = max(image.size)
        if self.options.resize_enabled and long_side > self.options.max_long_side:
            scale = self.options.max_long_side / long_side
            new_size = (
                max(1, int(round(image.size[0] * scale))),
                max(1, int(round(image.size[1] * scale))),
            )
            image = image.resize(new_size, Image.Resampling.LANCZOS)
            resized = True

        converted = self._should_convert_png_to_jpg(image_path)
        if converted:
            target_path = self._unique_output_path(image_path.with_suffix(".jpg"))
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
        elif image_path.suffix.lower() in {".jpg", ".jpeg"} and image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")

        final_size = image.size
        if resized or converted:
            temp_path = self._temp_output_path(target_path.suffix)
            save_kwargs = {}
            if target_path.suffix.lower() in {".jpg", ".jpeg"}:
                save_kwargs = {"quality": self.options.jpeg_quality, "optimize": True}
                image.save(temp_path, "JPEG", **save_kwargs)
            else:
                image.save(temp_path)
            replace_file_with_retry(temp_path, target_path)
            if converted and image_path.exists() and image_path != target_path:
                image_path.unlink()

        return ResizeResult(
            input_path=image_path,
            output_path=target_path,
            original_size=original_size,
            final_size=final_size,
            resized=resized,
            converted_to_jpg=converted,
        )

    def _should_convert_png_to_jpg(self, image_path: Path) -> bool:
        if not self.options.png_to_jpg_enabled:
            return False
        return image_path.suffix.lower() == ".png"

    def _temp_output_path(self, suffix: str) -> Path:
        temp_dir = self.storage.temp_dir / "originals"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir / f".tmp_{uuid.uuid4().hex}{suffix}"

    @staticmethod
    def _unique_output_path(path: Path) -> Path:
        if not path.exists():
            return path
        for index in range(1, 1000):
            candidate = path.with_name(f"{path.stem}_{index:02d}{path.suffix}")
            if not candidate.exists():
                return candidate
        raise FileExistsError(f"Unable to allocate output path for {path}")
