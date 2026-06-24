from __future__ import annotations

from pathlib import Path
import uuid

from PIL import Image

from doc_auto.services.file_replace import replace_file_with_retry


def rotate_image_in_place(image_path: Path, *, clockwise: bool = True, temp_dir: Path | None = None) -> Path:
    image_path = Path(image_path)
    rotation_degrees = -90 if clockwise else 90
    with Image.open(image_path) as image:
        rotated = image.rotate(rotation_degrees, expand=True, fillcolor=(255, 255, 255))
        if image_path.suffix.lower() in {".jpg", ".jpeg"} and rotated.mode not in {"RGB", "L"}:
            rotated = rotated.convert("RGB")
        rotated.load()

    work_dir = Path(temp_dir) if temp_dir is not None else image_path.parent
    work_dir.mkdir(parents=True, exist_ok=True)
    temp_path = work_dir / f".rotate_{uuid.uuid4().hex}{image_path.suffix}"
    rotated.save(temp_path)
    replace_file_with_retry(temp_path, image_path)
    return image_path
