from pathlib import Path

from PIL import Image

from doc_auto.services.manual_crop import ManualCropHistory
from doc_auto.services.temp_storage import PortableStorage


def test_manual_crop_history_crops_original_pixels_and_moves_back_forward(tmp_path: Path) -> None:
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    storage = PortableStorage(tmp_path / "app")
    history = ManualCropHistory(storage, image_path)

    history.start()
    cropped = history.crop((10, 20, 60, 70))

    assert cropped == image_path
    with Image.open(image_path) as image:
        assert image.size == (50, 50)

    history.back()
    with Image.open(image_path) as image:
        assert image.size == (100, 80)

    history.forward()
    with Image.open(image_path) as image:
        assert image.size == (50, 50)


def test_manual_crop_history_drops_forward_states_after_new_crop(tmp_path: Path) -> None:
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    storage = PortableStorage(tmp_path / "app")
    history = ManualCropHistory(storage, image_path)

    history.start()
    history.crop((10, 10, 90, 70))
    history.crop((10, 10, 50, 40))
    assert history.can_go_back is True
    assert history.can_go_forward is False

    history.back()
    history.crop((0, 0, 20, 20))

    assert history.can_go_forward is False
    with Image.open(image_path) as image:
        assert image.size == (20, 20)


def test_manual_crop_history_clamps_box_to_current_image(tmp_path: Path) -> None:
    image_path = tmp_path / "scan.jpg"
    Image.new("RGB", (100, 80), "white").save(image_path)
    storage = PortableStorage(tmp_path / "app")
    history = ManualCropHistory(storage, image_path)

    history.start()
    history.crop((-10, -5, 120, 40))

    with Image.open(image_path) as image:
        assert image.size == (100, 40)


def test_manual_crop_history_rotates_with_back_forward_history(tmp_path: Path) -> None:
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    storage = PortableStorage(tmp_path / "app")
    history = ManualCropHistory(storage, image_path)

    history.start()
    history.rotate(clockwise=True)

    with Image.open(image_path) as image:
        assert image.size == (80, 100)

    history.back()
    with Image.open(image_path) as image:
        assert image.size == (100, 80)


def test_manual_crop_history_rotates_degrees_with_back_forward_history(tmp_path: Path) -> None:
    image_path = tmp_path / "scan.png"
    image = Image.new("RGB", (3, 2), "white")
    image.putpixel((0, 0), (255, 0, 0))
    image.save(image_path)
    storage = PortableStorage(tmp_path / "app")
    history = ManualCropHistory(storage, image_path)

    history.start()
    history.rotate_degrees(90.0)

    with Image.open(image_path) as image:
        assert image.size == (2, 3)
        assert image.getpixel((1, 0)) == (255, 0, 0)

    history.back()
    with Image.open(image_path) as image:
        assert image.size == (3, 2)
        assert image.getpixel((0, 0)) == (255, 0, 0)


def test_manual_crop_history_can_save_crop_as_new_file_without_replacing_current(tmp_path: Path) -> None:
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    storage = PortableStorage(tmp_path / "app")
    history = ManualCropHistory(storage, image_path)

    history.start()
    output = history.crop_to_new_file((10, 10, 60, 50))

    assert output == tmp_path / "scan_cut_00.png"
    with Image.open(output) as image:
        assert image.size == (50, 40)
    with Image.open(image_path) as image:
        assert image.size == (100, 80)
