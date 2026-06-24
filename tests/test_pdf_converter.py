from pathlib import Path

from PIL import Image

from doc_auto.services import file_replace
from doc_auto.services.pdf_converter import PdfConverter
from tests.pdf_assertions import assert_pdf_page_count


def _make_image(path: Path, size: tuple[int, int], color: str = "white") -> None:
    Image.new("RGB", size, color).save(path)


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def test_pdf_converter_creates_individual_pdf_without_mutating_source(tmp_path):
    image_path = tmp_path / "large.jpg"
    _make_image(image_path, (3000, 2000))

    results = PdfConverter().convert_individual([image_path])

    assert len(results) == 1
    assert results[0].output_path == tmp_path / "large.pdf"
    assert results[0].output_path.exists()
    assert _image_size(image_path) == (3000, 2000)
    assert_pdf_page_count(results[0].output_path, 1)


def test_pdf_converter_creates_bundle_pdf(tmp_path):
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    _make_image(first, (1200, 800), "white")
    _make_image(second, (800, 1200), "black")
    output = tmp_path / "bundle.pdf"

    result = PdfConverter().convert_bundle([first, second], output)

    assert result.output_path == output
    assert result.page_count == 2
    assert_pdf_page_count(output, 2)


def test_pdf_converter_embeds_jpeg_without_reencoding(tmp_path):
    image_path = tmp_path / "photo.jpg"
    Image.new("RGB", (64, 32), "white").save(image_path, "JPEG", quality=87)
    original_bytes = image_path.read_bytes()
    output = tmp_path / "photo.pdf"

    PdfConverter().convert_bundle([image_path], output)

    pdf_bytes = output.read_bytes()
    assert b"/DCTDecode" in pdf_bytes
    assert original_bytes in pdf_bytes


def test_pdf_converter_uses_unique_name_when_pdf_exists(tmp_path):
    image_path = tmp_path / "scan.jpg"
    _make_image(image_path, (100, 100))
    (tmp_path / "scan.pdf").write_bytes(b"existing")

    results = PdfConverter().convert_individual([image_path])

    assert results[0].output_path == tmp_path / "scan_01.pdf"


def test_pdf_converter_retries_transient_permission_error_on_replace(tmp_path, monkeypatch):
    image_path = tmp_path / "scan.jpg"
    output_path = tmp_path / "scan.pdf"
    _make_image(image_path, (100, 100))
    calls = 0

    def flaky_replace(source_path, target_path):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise PermissionError("transient lock")
        Path(target_path).write_bytes(Path(source_path).read_bytes())
        Path(source_path).unlink()

    monkeypatch.setattr(file_replace.os, "replace", flaky_replace)

    result = PdfConverter().convert_bundle([image_path], output_path)

    assert calls == 3
    assert result.output_path == output_path
    assert_pdf_page_count(output_path, 1)


def test_pdf_converter_uses_configured_temp_folder_not_output_folder(tmp_path):
    image_path = tmp_path / "scan.jpg"
    temp_dir = tmp_path / "app" / "data" / "temp" / "pdf_output"
    _make_image(image_path, (100, 100))

    results = PdfConverter(temp_dir=temp_dir).convert_individual([image_path])

    assert results[0].output_path == tmp_path / "scan.pdf"
    assert results[0].output_path.exists()
    assert list(tmp_path.glob(".*.pdf")) == []
    assert temp_dir.exists()
    assert list(temp_dir.iterdir()) == []
