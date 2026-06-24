from pathlib import Path

from PIL import Image

from doc_auto.services.image_resizer import ImageResizer, ResizeOptions
from doc_auto.services import file_replace
from doc_auto.services.temp_storage import PortableStorage


def _make_image(path: Path, size: tuple[int, int], color: str = "white") -> None:
    image = Image.new("RGB", size, color)
    image.save(path)


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def test_resizer_does_not_upscale_small_images(tmp_path):
    image_path = tmp_path / "small.jpg"
    _make_image(image_path, (800, 600))
    storage = PortableStorage(tmp_path / "app")

    result = ImageResizer(storage).resize_in_place(image_path)

    assert result.output_path == image_path
    assert result.resized is False
    assert _image_size(image_path) == (800, 600)


def test_resizer_downscales_long_side_to_limit(tmp_path):
    image_path = tmp_path / "large.jpg"
    _make_image(image_path, (3000, 2000))
    storage = PortableStorage(tmp_path / "app")

    result = ImageResizer(storage).resize_in_place(image_path)

    assert result.output_path == image_path
    assert result.resized is True
    assert _image_size(image_path) == (1920, 1280)


def test_resizer_can_disable_resize(tmp_path):
    image_path = tmp_path / "large.jpg"
    _make_image(image_path, (3000, 2000))
    storage = PortableStorage(tmp_path / "app")

    result = ImageResizer(storage, ResizeOptions(resize_enabled=False)).resize_in_place(image_path)

    assert result.output_path == image_path
    assert result.resized is False
    assert _image_size(image_path) == (3000, 2000)


def test_png_converts_to_jpg_when_enabled(tmp_path):
    image_path = tmp_path / "scan.png"
    _make_image(image_path, (800, 600))
    storage = PortableStorage(tmp_path / "app")

    result = ImageResizer(storage, ResizeOptions(png_to_jpg_threshold_bytes=10_000_000)).resize_in_place(image_path)

    assert result.output_path == tmp_path / "scan.jpg"
    assert result.converted_to_jpg is True
    assert result.output_path.exists()
    assert not image_path.exists()


def test_png_to_jpg_conversion_can_be_disabled(tmp_path):
    image_path = tmp_path / "scan.png"
    _make_image(image_path, (800, 600))
    storage = PortableStorage(tmp_path / "app")

    result = ImageResizer(
        storage,
        ResizeOptions(png_to_jpg_enabled=False, png_to_jpg_threshold_bytes=1),
    ).resize_in_place(image_path)

    assert result.output_path == image_path
    assert result.converted_to_jpg is False
    assert image_path.exists()


def test_resizer_uses_portable_temp_not_source_folder(tmp_path):
    image_path = tmp_path / "large.jpg"
    _make_image(image_path, (3000, 2000))
    storage = PortableStorage(tmp_path / "app")

    ImageResizer(storage).resize_in_place(image_path)

    source_folder_temp_files = [
        path for path in tmp_path.iterdir() if path.name.startswith(".") or path.suffix == ".tmp"
    ]
    assert source_folder_temp_files == []


def test_resizer_retries_transient_permission_error_on_replace(tmp_path, monkeypatch):
    image_path = tmp_path / "large.jpg"
    _make_image(image_path, (3000, 2000))
    storage = PortableStorage(tmp_path / "app")
    calls = 0

    def flaky_replace(source_path, target_path):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise PermissionError("transient lock")
        Path(target_path).write_bytes(Path(source_path).read_bytes())
        Path(source_path).unlink()

    monkeypatch.setattr(file_replace.os, "replace", flaky_replace)

    result = ImageResizer(storage).resize_in_place(image_path)

    assert calls == 3
    assert result.output_path == image_path
    assert _image_size(image_path) == (1920, 1280)
