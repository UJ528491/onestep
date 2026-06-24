from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import uuid
import zlib

from doc_auto.services.file_replace import replace_file_with_retry


@dataclass(frozen=True)
class PdfConversionOptions:
    max_long_side: int = 1920
    jpeg_quality: int = 95


@dataclass(frozen=True)
class PdfConversionResult:
    output_path: Path
    source_paths: list[Path]
    page_count: int


class PdfConverter:
    def __init__(
        self,
        options: PdfConversionOptions | None = None,
        temp_dir: Path | None = None,
    ) -> None:
        self.options = options or PdfConversionOptions()
        self.temp_dir = Path(temp_dir) if temp_dir is not None else None

    def convert_individual(self, image_paths: list[Path]) -> list[PdfConversionResult]:
        results: list[PdfConversionResult] = []
        for image_path in image_paths:
            image_path = Path(image_path)
            if not image_path.exists():
                continue
            output_path = self._unique_path(image_path.with_suffix(".pdf"))
            results.append(self.convert_single_to(image_path, output_path))
        return results

    def convert_single_to(self, image_path: Path, output_path: Path) -> PdfConversionResult:
        image_path = Path(image_path)
        output_path = self._unique_path(Path(output_path))
        self._save_pdf([image_path], output_path)
        return PdfConversionResult(output_path=output_path, source_paths=[image_path], page_count=1)

    def convert_bundle(self, image_paths: list[Path], output_path: Path) -> PdfConversionResult:
        existing = [Path(path) for path in image_paths if Path(path).exists()]
        if not existing:
            raise ValueError("No images to bundle")
        output_path = Path(output_path)
        self._save_pdf(existing, output_path)
        return PdfConversionResult(output_path=output_path, source_paths=existing, page_count=len(existing))

    def _save_pdf(self, image_paths: list[Path], output_path: Path) -> None:
        pages = [self._prepare_pdf_page(path) for path in image_paths]
        if not pages:
            raise ValueError("No PDF pages")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._temp_output_path(output_path)
        try:
            self._write_pdf(pages, temp_path)
            replace_file_with_retry(temp_path, output_path)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def _prepare_pdf_image(self, image_path: Path):
        from PIL import Image

        with Image.open(image_path) as source:
            image = source.copy()
        if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")

        return image

    def _prepare_pdf_page(self, image_path: Path) -> dict:
        from PIL import Image

        image_path = Path(image_path)
        with Image.open(image_path) as image:
            width, height = image.size
            mode = image.mode
        if image_path.suffix.lower() in {".jpg", ".jpeg"} and mode in {"RGB", "L", "CMYK"}:
            color_space = {
                "RGB": "/DeviceRGB",
                "L": "/DeviceGray",
                "CMYK": "/DeviceCMYK",
            }[mode]
            return {
                "width": width,
                "height": height,
                "color_space": color_space,
                "filter": "/DCTDecode",
                "data": image_path.read_bytes(),
            }

        image = self._prepare_pdf_image(image_path)
        try:
            if image.mode != "RGB":
                image = image.convert("RGB")
            return {
                "width": image.size[0],
                "height": image.size[1],
                "color_space": "/DeviceRGB",
                "filter": "/FlateDecode",
                "data": zlib.compress(image.tobytes()),
            }
        finally:
            image.close()

    def _write_pdf(self, pages: list[dict], output_path: Path) -> None:
        objects: list[bytes] = []

        def add_object(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        catalog_id = add_object(b"<< /Type /Catalog /Pages 2 0 R >>")
        pages_id = add_object(b"")
        page_ids: list[int] = []
        for index, page in enumerate(pages, start=1):
            image_id = add_object(self._image_object(page))
            content = f"q\n{page['width']} 0 0 {page['height']} 0 0 cm\n/Im{index} Do\nQ\n".encode("ascii")
            content_id = add_object(
                b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"endstream"
            )
            page_body = (
                f"<< /Type /Page /Parent {pages_id} 0 R "
                f"/MediaBox [0 0 {page['width']} {page['height']}] "
                f"/Resources << /XObject << /Im{index} {image_id} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode("ascii")
            page_ids.append(add_object(page_body))

        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids).encode("ascii")
        objects[pages_id - 1] = b"<< /Type /Pages /Kids [ " + kids + b" ] /Count " + str(len(page_ids)).encode("ascii") + b" >>"
        assert catalog_id == 1

        output_path.parent.mkdir(parents=True, exist_ok=True)
        offsets: list[int] = []
        with output_path.open("wb") as handle:
            handle.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
            for object_id, body in enumerate(objects, start=1):
                offsets.append(handle.tell())
                handle.write(f"{object_id} 0 obj\n".encode("ascii"))
                handle.write(body)
                handle.write(b"\nendobj\n")
            xref_offset = handle.tell()
            handle.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
            handle.write(b"0000000000 65535 f \n")
            for offset in offsets:
                handle.write(f"{offset:010d} 00000 n \n".encode("ascii"))
            handle.write(
                f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
            )

    @staticmethod
    def _image_object(page: dict) -> bytes:
        data = page["data"]
        header = (
            f"<< /Type /XObject /Subtype /Image /Width {page['width']} /Height {page['height']} "
            f"/ColorSpace {page['color_space']} /BitsPerComponent 8 /Filter {page['filter']} "
            f"/Length {len(data)} >>\nstream\n"
        ).encode("ascii")
        return header + data + b"\nendstream"

    def _temp_output_path(self, output_path: Path) -> Path:
        if self.temp_dir is not None:
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            return self.temp_dir / f"{uuid.uuid4().hex}{output_path.suffix}"
        return output_path.with_name(f".{output_path.stem}.{uuid.uuid4().hex}{output_path.suffix}")

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        for index in range(1, 1000):
            candidate = path.with_name(f"{path.stem}_{index:02d}{path.suffix}")
            if not candidate.exists():
                return candidate
        raise FileExistsError(f"Unable to allocate output path for {path}")
