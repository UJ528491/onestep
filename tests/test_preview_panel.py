from pathlib import Path

import pytest
from PIL import Image


def test_preview_panel_shows_single_large_preview(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.preview_panel import PreviewPanel

    create_app([])
    image_path = tmp_path / "one.png"
    Image.new("RGB", (30, 20), "white").save(image_path)
    panel = PreviewPanel()

    panel.set_paths([image_path])

    assert panel.grid.count() == 1
    label = panel.grid.itemAt(0).widget()
    assert label.styleSheet() == ""
    assert label.width() <= panel.width()


def test_preview_panel_shows_grid_for_multiple_previews(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from doc_auto.app import create_app
    from doc_auto.ui.preview_panel import PreviewPanel

    create_app([])
    paths = []
    for index in range(4):
        path = tmp_path / f"{index}.png"
        Image.new("RGB", (30, 20), "white").save(path)
        paths.append(path)
    panel = PreviewPanel()

    panel.set_paths(paths)

    assert panel.grid.count() == 4
    assert panel.grid_columns == 2
    assert {panel.grid.itemAt(index).widget().styleSheet() for index in range(4)} == {""}
    assert panel.scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert panel.scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_preview_panel_vertical_mode_shows_scroll_and_page_badge(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from doc_auto.app import create_app
    from doc_auto.ui.preview_panel import PreviewPanel

    create_app([])
    paths = []
    for index in range(3):
        path = tmp_path / f"page_{index}.png"
        Image.new("RGB", (30, 40), "white").save(path)
        paths.append(path)
    panel = PreviewPanel()

    panel.set_paths(paths, vertical=True, page_badges={paths[0]: "PDF | 3P"})

    assert panel.grid_columns == 1
    assert panel.scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    thumbnail = panel.grid.itemAt(0).widget()
    assert thumbnail.badge_label.text() == "PDF | 3P"
    assert not thumbnail.badge_label.isHidden()


def test_preview_panel_page_badge_is_large_and_aligned_to_image_top_left(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSize
    from doc_auto.app import create_app
    from doc_auto.ui.preview_panel import PreviewPanel

    app = create_app([])
    image_path = tmp_path / "page.png"
    Image.new("RGB", (100, 140), "white").save(image_path)
    panel = PreviewPanel()
    panel.set_paths([image_path], page_badges={image_path: "PDF | 4P"})
    thumbnail = panel.grid.itemAt(0).widget()
    thumbnail.set_preview_size(QSize(240, 320))
    thumbnail.resize(240, 320)
    thumbnail.show()
    app.processEvents()

    assert thumbnail.badge_label.text() == "PDF | 4P"
    assert thumbnail.badge_label.width() >= 34
    assert thumbnail.badge_label.height() >= 22
    pixmap = thumbnail.image_label.pixmap()
    expected_x = thumbnail.image_label.pos().x() + max(0, (thumbnail.image_label.width() - pixmap.width()) // 2) + 6
    expected_y = thumbnail.image_label.pos().y() + max(0, (thumbnail.image_label.height() - pixmap.height()) // 2) + 6
    assert abs(thumbnail.badge_label.pos().x() - expected_x) <= 1
    assert abs(thumbnail.badge_label.pos().y() - expected_y) <= 1


def test_preview_panel_shows_filename_under_thumbnail(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.preview_panel import PreviewPanel

    create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (30, 20), "white").save(image_path)
    panel = PreviewPanel()

    panel.set_paths([image_path])

    thumbnail = panel.grid.itemAt(0).widget()
    assert thumbnail.name_label.text() == "scan.png"


def test_preview_panel_buttons_use_korean_text(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import ImagePreviewWindow, PreviewPanel

    create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (30, 20), "white").save(image_path)
    panel = PreviewPanel(storage=PortableStorage(tmp_path / "app"))
    editor = ImagePreviewWindow(image_path, storage=PortableStorage(tmp_path / "app"))

    assert panel.rotate_left_button.text() == "↶"
    assert panel.rotate_right_button.text() == "↷"
    assert panel.fullscreen_button.text() == "⛶"
    assert editor.back_button.text() == "←"
    assert editor.forward_button.text() == "→"
    assert editor.rotate_left_button.text() == "↶"
    assert editor.rotate_right_button.text() == "↷"
    assert editor.tilt_button.text() == "기울임"
    assert editor.save_button.text() == "저장"
    assert editor.save_as_button.text() == "새 파일 저장"
    tooltip_text = "\n".join(
        [
            panel.rotate_left_button.toolTip(),
            panel.rotate_right_button.toolTip(),
            panel.fullscreen_button.toolTip(),
            editor.rotate_left_button.toolTip(),
            editor.rotate_right_button.toolTip(),
            editor.tilt_button.toolTip(),
        ]
    )
    assert "왼쪽으로 회전" in tooltip_text
    assert "오른쪽으로 회전" in tooltip_text
    assert "전체화면" in tooltip_text
    assert "기울임 모드" in tooltip_text
    assert not any(token in tooltip_text for token in ["?", "�", "쇱", "꾩", "뚯"])


def test_preview_panel_grid_reflows_to_fit_panel_size(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.preview_panel import PreviewPanel

    create_app([])
    paths = []
    for index in range(6):
        path = tmp_path / f"{index}.png"
        Image.new("RGB", (300, 200), "white").save(path)
        paths.append(path)
    panel = PreviewPanel()
    panel.resize(360, 620)

    panel.set_paths(paths)
    first_columns = panel.grid_columns
    panel.resize(720, 620)
    panel.reflow()

    assert first_columns >= 1
    assert panel.grid_columns > first_columns
    assert panel.scroll.widgetResizable() is True


def test_preview_panel_skips_reflow_for_identical_paths_and_size(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.preview_panel import PreviewPanel

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (30, 20), "white").save(image_path)
    panel = PreviewPanel()
    calls = 0
    original_thumbnail_for = panel._thumbnail_for

    def counted_thumbnail_for(path, size):
        nonlocal calls
        calls += 1
        return original_thumbnail_for(path, size)

    monkeypatch.setattr(panel, "_thumbnail_for", counted_thumbnail_for)

    panel.set_paths([image_path])
    panel.set_paths([image_path])
    app.processEvents()

    assert calls == 1


def test_preview_panel_fullscreen_and_image_window(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.preview_panel import PreviewPanel

    app = create_app([])
    image_path = tmp_path / "large.png"
    Image.new("RGB", (3000, 2000), "white").save(image_path)
    panel = PreviewPanel()
    panel.set_paths([image_path])

    panel.toggle_fullscreen()
    app.processEvents()
    assert panel.fullscreen_window is not None
    assert panel.fullscreen_window.parent() is None
    assert panel.fullscreen_window.isWindow()
    assert panel.fullscreen_window.isFullScreen()

    panel.exit_fullscreen()
    assert panel.fullscreen_window is None

    window = panel.open_image_window(image_path)

    assert window.parent() is None
    assert window.isWindow()
    assert window.preview_size.width() <= 1920
    assert window.preview_size.height() <= 984


def test_preview_panel_reuses_existing_image_window(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.preview_panel import PreviewPanel

    create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (300, 200), "white").save(image_path)
    panel = PreviewPanel()
    panel.set_paths([image_path])

    first = panel.open_image_window(image_path)
    second = panel.open_image_window(image_path)

    assert second is first
    assert len(panel._image_windows) == 1


def test_preview_panel_offsets_multiple_image_windows(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.preview_panel import PreviewPanel

    app = create_app([])
    paths = []
    for index in range(2):
        path = tmp_path / f"scan_{index}.png"
        Image.new("RGB", (320, 220), "white").save(path)
        paths.append(path)
    panel = PreviewPanel()
    panel.set_paths(paths)

    first = panel.open_image_window(paths[0])
    second = panel.open_image_window(paths[1])
    app.processEvents()

    assert first.pos() != second.pos()


def test_preview_panel_fullscreen_keeps_same_storage(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import PreviewPanel

    app = create_app([])
    image_path = tmp_path / "large.png"
    Image.new("RGB", (300, 200), "white").save(image_path)
    storage = PortableStorage(tmp_path / "app")
    panel = PreviewPanel(storage=storage)
    panel.set_paths([image_path])

    panel.toggle_fullscreen()
    app.processEvents()

    assert panel.fullscreen_window is not None
    assert panel.fullscreen_window.panel.storage is storage


def test_image_preview_window_maps_display_selection_to_original_pixels(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRect, QSize
    from doc_auto.app import create_app
    from doc_auto.ui.preview_panel import ImagePreviewWindow

    create_app([])

    box = ImagePreviewWindow.image_box_from_display_rect(
        QRect(10, 20, 50, 40),
        display_rect=QRect(0, 0, 200, 100),
        image_size=QSize(1000, 500),
    )

    assert box == (50, 100, 300, 300)


def test_image_preview_window_default_preview_fits_fhd_portrait_height(monkeypatch) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSize
    from doc_auto.ui.preview_panel import ImagePreviewWindow

    preview_size = ImagePreviewWindow.default_preview_size(
        QSize(3000, 5000),
        available_size=QSize(1920, 1080),
    )

    assert preview_size.height() <= 984
    assert preview_size.width() < preview_size.height()


def test_image_preview_window_can_be_resized_smaller_than_large_image(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import ImagePreviewWindow

    create_app([])
    image_path = tmp_path / "portrait.png"
    Image.new("RGB", (3000, 5000), "white").save(image_path)

    window = ImagePreviewWindow(image_path, storage=PortableStorage(tmp_path / "app"))

    assert window.minimumSizeHint().height() < window.preview_size.height()
    assert window.canvas.minimumSizeHint().height() < window.preview_size.height()


def test_image_preview_window_shows_save_only_after_drag_selection(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import ImagePreviewWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (300, 200), "white").save(image_path)
    window = ImagePreviewWindow(image_path, storage=PortableStorage(tmp_path / "app"))
    window.show()
    app.processEvents()
    click_pos = window.canvas.rect().center()

    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click_pos)
    QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click_pos)
    app.processEvents()

    assert not window.save_button.isVisible()

    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click_pos)
    QTest.mouseMove(window.canvas, click_pos + QPoint(40, 30))
    QTest.mouseRelease(
        window.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        click_pos + QPoint(40, 30),
    )
    app.processEvents()

    assert window.save_button.isVisible()


def test_image_preview_window_hides_pending_save_when_new_click_starts(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import ImagePreviewWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (300, 200), "white").save(image_path)
    window = ImagePreviewWindow(image_path, storage=PortableStorage(tmp_path / "app"))
    window.show()
    app.processEvents()
    click_pos = window.canvas.rect().center()

    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click_pos)
    QTest.mouseMove(window.canvas, click_pos + QPoint(40, 30))
    QTest.mouseRelease(
        window.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        click_pos + QPoint(40, 30),
    )
    app.processEvents()
    assert window.save_button.isVisible()

    QTest.mouseClick(window.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click_pos)
    app.processEvents()

    assert not window.save_button.isVisible()
    assert not window.save_as_button.isVisible()


def test_image_preview_window_crop_save_and_history(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import ImagePreviewWindow

    create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    window = ImagePreviewWindow(image_path, storage=PortableStorage(tmp_path / "app"))

    window.apply_crop((10, 10, 60, 50))
    with Image.open(image_path) as image:
        assert image.size == (50, 40)

    window.go_back()
    with Image.open(image_path) as image:
        assert image.size == (100, 80)

    window.go_forward()
    with Image.open(image_path) as image:
        assert image.size == (50, 40)


def test_image_preview_window_rotate_buttons_update_image_and_history(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import ImagePreviewWindow

    create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    window = ImagePreviewWindow(image_path, storage=PortableStorage(tmp_path / "app"))

    window.rotate_clockwise()

    with Image.open(image_path) as image:
        assert image.size == (80, 100)

    window.go_back()
    with Image.open(image_path) as image:
        assert image.size == (100, 80)


def test_image_preview_window_ignores_rotation_for_non_image_paths(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import ImagePreviewWindow

    create_app([])
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    window = ImagePreviewWindow(pdf_path, storage=PortableStorage(tmp_path / "app"))

    assert window.rotate_clockwise() == pdf_path
    assert not window.rotate_left_button.isEnabled()
    assert not window.rotate_right_button.isEnabled()


def test_preview_panel_does_not_open_editor_for_non_image_paths(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import PreviewPanel

    create_app([])
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    panel = PreviewPanel(storage=PortableStorage(tmp_path / "app"))
    panel.set_paths([pdf_path])

    assert panel.open_image_window(pdf_path) is None
    assert not panel.rotate_left_button.isEnabled()
    assert not panel.rotate_right_button.isEnabled()


def test_image_preview_window_save_selection_as_new_file(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import ImagePreviewWindow

    create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    window = ImagePreviewWindow(image_path, storage=PortableStorage(tmp_path / "app"))
    window._pending_box = (10, 10, 60, 50)

    output = window.save_selection_as()

    assert output == tmp_path / "scan_cut_00.png"
    with Image.open(output) as image:
        assert image.size == (50, 40)
    with Image.open(image_path) as image:
        assert image.size == (100, 80)


def test_preview_panel_reflows_when_child_image_changes(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import PreviewPanel

    create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    panel = PreviewPanel(storage=PortableStorage(tmp_path / "app"))
    panel.set_paths([image_path])
    calls = 0

    def counted_reflow() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(panel, "reflow", counted_reflow)

    window = panel.open_image_window(image_path)
    window.apply_crop((10, 10, 60, 50))

    assert calls == 1


def test_preview_panel_rotates_visible_paths(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import PreviewPanel

    create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    panel = PreviewPanel(storage=PortableStorage(tmp_path / "app"))
    panel.set_paths([image_path])

    panel.rotate_paths(clockwise=True)

    with Image.open(image_path) as image:
        assert image.size == (80, 100)


def test_preview_panel_rotation_is_hidden_for_multiple_paths(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import PreviewPanel

    create_app([])
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (100, 80), "white").save(first)
    Image.new("RGB", (120, 90), "black").save(second)
    panel = PreviewPanel(storage=PortableStorage(tmp_path / "app"))

    panel.set_paths([first, second])
    panel.rotate_paths(clockwise=True)

    assert not panel.rotate_left_button.isVisible()
    assert not panel.rotate_right_button.isVisible()
    with Image.open(first) as image:
        assert image.size == (100, 80)
    with Image.open(second) as image:
        assert image.size == (120, 90)


def test_image_preview_window_escape_cancels_selection_then_closes(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QKeyEvent
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import ImagePreviewWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (300, 200), "white").save(image_path)
    window = ImagePreviewWindow(image_path, storage=PortableStorage(tmp_path / "app"))
    window.show()
    app.processEvents()

    window._selection_finished((10, 10, 80, 80), QPoint(50, 50))
    assert window.save_button.isVisible()

    app.sendEvent(window, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    app.processEvents()

    assert window.isVisible()
    assert not window.save_button.isVisible()
    assert not window.save_as_button.isVisible()
    assert window._pending_box is None

    app.sendEvent(window, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    app.processEvents()

    assert not window.isVisible()


def test_image_preview_window_selection_buttons_stay_inside_canvas(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import ImagePreviewWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (300, 200), "white").save(image_path)
    window = ImagePreviewWindow(image_path, storage=PortableStorage(tmp_path / "app"))
    window.show()
    app.processEvents()

    window._selection_finished(
        (10, 10, 80, 80),
        QPoint(window.canvas.width() + 100, window.canvas.height() + 100),
    )

    assert window.save_button.text() == "저장"
    assert window.save_as_button.text() == "새 파일 저장"
    assert window.save_as_button.width() > window.save_button.width()
    assert window.save_button.isVisible()
    assert window.save_as_button.isVisible()
    assert window.save_button.x() >= 0
    assert window.save_button.y() >= 0
    assert window.save_as_button.x() >= 0
    assert window.save_as_button.y() >= 0
    assert window.save_button.x() + window.save_button.width() <= window.canvas.width()
    assert window.save_as_button.x() + window.save_as_button.width() <= window.canvas.width()
    assert window.save_button.y() + window.save_button.height() <= window.canvas.height()
    assert window.save_as_button.y() + window.save_as_button.height() <= window.canvas.height()
    assert window.save_button.geometry().bottom() < window.save_as_button.geometry().top()


def test_image_preview_window_empty_click_does_not_close(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import ImagePreviewWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (300, 200), "white").save(image_path)
    window = ImagePreviewWindow(image_path, storage=PortableStorage(tmp_path / "app"))
    window.show()
    app.processEvents()

    window.canvas.empty_clicked.emit()
    app.processEvents()

    assert window.isVisible()


def test_manual_crop_history_crops_after_arbitrary_rotation(tmp_path: Path) -> None:
    from doc_auto.services.manual_crop import ManualCropHistory
    from doc_auto.services.temp_storage import PortableStorage

    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 60), "white").save(image_path)
    history = ManualCropHistory(PortableStorage(tmp_path / "app"), image_path)
    history.start()

    history.crop((10, 10, 90, 50), rotation_degrees=8.0)

    with Image.open(image_path) as image:
        assert image.size == (80, 40)


def test_manual_crop_history_applies_rotation_to_saved_pixels(tmp_path: Path) -> None:
    from doc_auto.services.manual_crop import ManualCropHistory
    from doc_auto.services.temp_storage import PortableStorage

    image_path = tmp_path / "scan.png"
    image = Image.new("RGB", (10, 4), "white")
    for x in range(5):
        for y in range(4):
            image.putpixel((x, y), (255, 0, 0))
    for x in range(5, 10):
        for y in range(4):
            image.putpixel((x, y), (0, 0, 255))
    image.save(image_path)
    history = ManualCropHistory(PortableStorage(tmp_path / "app"), image_path)
    history.start()

    history.crop((0, 0, 10, 4), rotation_degrees=180.0)

    with Image.open(image_path) as result:
        assert result.getpixel((0, 0)) == (0, 0, 255)
        assert result.getpixel((9, 3)) == (255, 0, 0)


def test_manual_crop_history_rotates_full_image_before_crop(tmp_path: Path) -> None:
    from doc_auto.services.manual_crop import ManualCropHistory
    from doc_auto.services.temp_storage import PortableStorage

    image_path = tmp_path / "scan.png"
    Image.new("RGB", (10, 4), "white").save(image_path)
    history = ManualCropHistory(PortableStorage(tmp_path / "app"), image_path)
    history.start()

    history.crop((0, 0, 4, 10), rotation_degrees=90.0)

    with Image.open(image_path) as image:
        assert image.size == (4, 10)


def test_manual_crop_history_matches_preview_rotation_direction(tmp_path: Path) -> None:
    from doc_auto.services.manual_crop import ManualCropHistory
    from doc_auto.services.temp_storage import PortableStorage

    image_path = tmp_path / "scan.png"
    image = Image.new("RGB", (3, 2), "white")
    image.putpixel((0, 0), (255, 0, 0))
    image.save(image_path)
    history = ManualCropHistory(PortableStorage(tmp_path / "app"), image_path)
    history.start()

    history.crop((0, 0, 2, 3), rotation_degrees=90.0)

    with Image.open(image_path) as result:
        assert result.size == (2, 3)
        assert result.getpixel((1, 0)) == (255, 0, 0)


def test_crop_canvas_tilt_mode_rotates_display_image(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSize
    from doc_auto.app import create_app
    from doc_auto.ui.preview_panel import _CropCanvas

    create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 60), "white").save(image_path)
    canvas = _CropCanvas()
    canvas.set_image(image_path, QSize(200, 160))

    canvas.set_tilt_mode(True)
    canvas._rotation_angle = 45.0
    canvas._update_scaled_pixmap(QSize(200, 160))

    assert canvas._image_size.width() > 100
    assert canvas._image_size.height() > 60


def test_crop_canvas_tilt_mode_drag_rotates_without_selection(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, QSize, Qt
    from PySide6.QtTest import QTest
    from doc_auto.app import create_app
    from doc_auto.ui.preview_panel import _CropCanvas

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 60), "white").save(image_path)
    canvas = _CropCanvas()
    canvas.resize(200, 160)
    canvas.set_image(image_path, QSize(200, 160))
    canvas.set_tilt_mode(True)
    canvas.show()
    app.processEvents()
    center = canvas.rect().center()

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    QTest.mouseMove(canvas, center + QPoint(80, 0))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center + QPoint(80, 0))
    app.processEvents()

    assert canvas.rotation_angle == 10.0
    assert canvas._selection is None


def test_crop_canvas_normal_mode_drag_selects_after_tilt_off(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, QSize, Qt
    from PySide6.QtTest import QTest
    from doc_auto.app import create_app
    from doc_auto.ui.preview_panel import _CropCanvas

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 60), "white").save(image_path)
    canvas = _CropCanvas()
    canvas.resize(200, 160)
    canvas.set_image(image_path, QSize(200, 160))
    canvas.set_tilt_mode(True)
    canvas._rotation_angle = 15.0
    canvas.set_tilt_mode(False)
    canvas.show()
    app.processEvents()
    center = canvas.rect().center()

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    QTest.mouseMove(canvas, center + QPoint(40, 30))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center + QPoint(40, 30))
    app.processEvents()

    assert canvas.rotation_angle == 15.0
    assert canvas._selection is not None
    assert canvas.image_box_from_selection() is not None


def test_crop_canvas_selection_stays_attached_to_image_after_resize(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, QSize, Qt
    from PySide6.QtTest import QTest
    from doc_auto.app import create_app
    from doc_auto.ui.preview_panel import _CropCanvas

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 50), "white").save(image_path)
    canvas = _CropCanvas()
    canvas.resize(200, 100)
    canvas.set_image(image_path, QSize(200, 100))
    canvas.show()
    app.processEvents()
    image_rect = canvas._pixmap_rect()
    start = QPoint(image_rect.left() + image_rect.width() // 10, image_rect.top() + image_rect.height() // 5)
    end = QPoint(image_rect.left() + image_rect.width() * 3 // 5, image_rect.top() + image_rect.height() * 3 // 5)

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    app.processEvents()
    selected_box = canvas.image_box_from_selection()

    canvas.resize(500, 240)
    app.processEvents()

    assert selected_box is not None
    assert canvas.image_box_from_selection() == selected_box


def test_image_preview_window_selection_buttons_follow_selection_after_resize(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import ImagePreviewWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 50), "white").save(image_path)
    window = ImagePreviewWindow(image_path, storage=PortableStorage(tmp_path / "app"))
    window.show()
    app.processEvents()
    image_rect = window.canvas._pixmap_rect()
    start = QPoint(image_rect.left() + image_rect.width() // 10, image_rect.top() + image_rect.height() // 5)
    end = QPoint(image_rect.left() + image_rect.width() * 3 // 5, image_rect.top() + image_rect.height() * 3 // 5)

    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(window.canvas, end)
    QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    app.processEvents()
    assert window.save_button.isVisible()

    window.resize(500, 400)
    app.processEvents()

    selection = window.canvas._selection.normalized()
    assert window.save_button.x() - selection.right() == 6
    assert window.save_button.y() - selection.bottom() == 6


def test_crop_canvas_rotation_drag_supports_full_turn(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, QSize, Qt
    from PySide6.QtTest import QTest
    from doc_auto.app import create_app
    from doc_auto.ui.preview_panel import _CropCanvas

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 60), "white").save(image_path)
    canvas = _CropCanvas()
    canvas.resize(200, 160)
    canvas.set_image(image_path, QSize(200, 160))
    canvas.set_tilt_mode(True)
    canvas.show()
    app.processEvents()
    center = canvas.rect().center()

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    QTest.mouseMove(canvas, center + QPoint(2880, 0))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center + QPoint(2880, 0))
    app.processEvents()

    assert canvas.rotation_angle == 360.0


def test_image_preview_window_r_toggles_tilt_mode(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import ImagePreviewWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    window = ImagePreviewWindow(image_path, storage=PortableStorage(tmp_path / "app"))

    assert not window.tilt_button.isChecked()

    app.sendEvent(window, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_R, Qt.KeyboardModifier.NoModifier))

    assert window.tilt_button.isChecked()
    assert window.canvas.tilt_mode

    app.sendEvent(window, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_R, Qt.KeyboardModifier.NoModifier))

    assert not window.tilt_button.isChecked()
    assert not window.canvas.tilt_mode


def test_image_preview_window_tilt_off_saves_rotation(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import ImagePreviewWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    image = Image.new("RGB", (3, 2), "white")
    image.putpixel((0, 0), (255, 0, 0))
    image.save(image_path)
    window = ImagePreviewWindow(image_path, storage=PortableStorage(tmp_path / "app"))

    window.tilt_button.setChecked(True)
    window.canvas._rotation_angle = 90.0
    window.tilt_button.setChecked(False)
    app.processEvents()

    with Image.open(image_path) as result:
        assert result.size == (2, 3)
        assert result.getpixel((1, 0)) == (255, 0, 0)
    assert not window.tilt_button.isChecked()
    assert not window.canvas.tilt_mode
    assert window.canvas.rotation_angle == 0.0
    assert window.history.can_go_back is True


def test_image_preview_window_left_right_keys_move_between_panel_paths(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    from doc_auto.app import create_app
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.preview_panel import PreviewPanel

    app = create_app([])
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (100, 80), "white").save(first)
    Image.new("RGB", (120, 90), "black").save(second)
    panel = PreviewPanel(storage=PortableStorage(tmp_path / "app"))
    panel.set_paths([first, second])
    window = panel.open_image_window(first)

    app.sendEvent(window, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))

    assert window.image_path == second

    app.sendEvent(window, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier))

    assert window.image_path == first
