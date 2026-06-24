import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest


def test_branding_names_are_versioned():
    from doc_auto import __version__
    from doc_auto.branding import APP_NAME, EMPTY_DROP_TEXT, EXE_NAME, WINDOW_TITLE, ZIP_NAME

    assert APP_NAME == "OneStep"
    assert WINDOW_TITLE.startswith("OneStep v")
    assert EMPTY_DROP_TEXT == "Drop files here"
    assert EXE_NAME == f"OneStep_v{__version__}.exe"
    assert ZIP_NAME == f"OneStep-Windows_v{__version__}.zip"


def test_app_imports_create_app():
    from doc_auto.app import create_app

    assert callable(create_app)


def test_main_window_uses_branding(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    window = MainWindow()

    assert window.windowTitle().startswith("OneStep v")
    assert window.file_table.empty_label.text() == "Drop files here"


def test_app_forces_light_theme(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QPalette

    from doc_auto.app import create_app

    app = create_app([])

    assert app.style().objectName().lower() == "fusion"
    assert app.palette().color(QPalette.ColorRole.Window).name().lower() == "#f8fafc"
    assert app.palette().color(QPalette.ColorRole.WindowText).name().lower() == "#0f172a"


def test_main_window_uses_start_stop_toggle_beside_progress(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    window = MainWindow()

    assert not hasattr(window, "cleanup_button")
    assert window.start_stop_button.text() == "시작"
    assert window.footer_controls_layout.indexOf(window.progress) >= 0
    assert window.footer_controls_layout.indexOf(window.start_stop_button) > window.footer_controls_layout.indexOf(window.progress)


def test_main_window_default_width_fits_toolbar_without_extra_space(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    window = MainWindow()
    window.show()
    app.processEvents()

    assert window.width() == window.minimumWidth()
    assert window.width() == window._list_area_width()
    assert window.width() >= round(window._toolbar_required_width() * 1.2)

    from PySide6.QtWidgets import QPushButton

    removed_file_button_width = QPushButton("파일/폴더 열기").sizeHint().width()
    previous_toolbar_width = window._toolbar_required_width() + removed_file_button_width + window.toolbar_layout.spacing()
    assert window._list_area_width() >= round(previous_toolbar_width * 1.2)


def test_main_window_resting_layout_stays_left_aligned_when_window_grows(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    window = MainWindow()
    window.show()
    app.processEvents()

    window.resize(window.width() + 500, window.height())
    app.processEvents()

    assert window.shell_splitter.x() == 0
    assert window.shell_splitter.width() == window._list_area_width()
    assert window.left_panel.width() == window._list_area_width()


def test_main_window_preview_selection_restores_resting_width_when_cleared(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 140), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    window.work_list.items = [WorkItem(source_path=image_path, current_path=image_path)]
    window.file_table.set_items(window.work_list.items)
    window.show()
    app.processEvents()
    resting_width = window.width()
    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    app.processEvents()
    expanded_width = window.width()

    window.file_table.table.clearSelection()
    window._sync_preview_from_selection()
    app.processEvents()

    assert expanded_width >= resting_width + window.shell_splitter.handleWidth() + window._preview_sidebar_min_width()
    assert window.width() == resting_width


def test_main_window_buttons_use_korean_text(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    window = MainWindow()

    assert [button.text() for button in window.toolbar_buttons] == [
        "PDF 변환",
        "PDF 묶음",
        "⚙",
    ]
    assert not hasattr(window, "file_button")
    assert not hasattr(window, "delete_button")
    assert not hasattr(window, "clear_button")
    assert all("?" not in button.text() for button in window.toolbar_buttons)
    assert window.toolbar_layout.itemAt(window.toolbar_layout.count() - 2).spacerItem() is not None
    assert window.toolbar_layout.itemAt(window.toolbar_layout.count() - 1).widget() is window.settings_button
    expected_height = window.pdf_button.sizeHint().height()
    assert window.settings_button.minimumHeight() == expected_height
    assert window.settings_button.maximumHeight() == expected_height
    assert window.settings_button.font().pointSize() >= window.pdf_button.font().pointSize() + 4
    from PySide6.QtGui import QFontMetrics

    icon_height = QFontMetrics(window.settings_button.font()).tightBoundingRect(window.settings_button.text()).height()
    assert icon_height <= window.settings_button.height() - 2


def test_cleanup_workflow_deletes_expanded_document_containers(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    window = MainWindow()

    workflow = window._create_cleanup_workflow()

    assert {".pdf", ".tif", ".tiff", ".hwp"}.issubset(workflow.delete_source_extensions)
    assert ".zip" not in workflow.delete_source_extensions


def test_cleanup_workflow_deletes_archive_when_archive_delete_enabled(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from dataclasses import replace

    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    window = MainWindow(app_root=tmp_path / "app")
    window.settings = replace(window.settings, archive_delete_source=True)

    workflow = window._create_cleanup_workflow()

    assert ".zip" in workflow.delete_source_extensions


def test_main_window_loads_packaged_window_icon(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    window = MainWindow()

    assert not window.windowIcon().isNull()


def test_main_window_removes_file_folder_picker_entry_points(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    window = MainWindow()

    assert not hasattr(window, "file_button")
    assert not hasattr(window, "_pick_files")
    assert not hasattr(window, "_pick_paths")
    assert not hasattr(window, "_pick_with_windows_dialog")
    assert not hasattr(window, "_pick_with_qt_dialog")
    assert not hasattr(MainWindow, "_parse_windows_dialog_output")
    assert not hasattr(MainWindow, "_normalize_windows_dialog_paths")


def test_main_window_new_drop_replaces_existing_list(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    window = MainWindow(app_root=tmp_path / "app")

    window._add_paths([first])
    window._add_paths([second])

    assert [item.source_path for item in window.work_list.items] == [second]
    assert window.file_table.table.rowCount() == 1


def test_main_window_drop_clears_temp_before_loading_new_batch(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    app_root = tmp_path / "app"
    image_path = tmp_path / "scan.jpg"
    image_path.write_bytes(b"image")
    window = MainWindow(app_root=app_root)
    stale_file = window.storage.temp_dir / "originals" / "stale.tmp"
    stale_file.parent.mkdir(parents=True)
    stale_file.write_text("stale", encoding="utf-8")

    window._drop_paths([image_path])

    assert not stale_file.exists()
    assert [item.source_path for item in window.work_list.items] == [image_path]


def test_main_window_accepts_new_batch_after_completed_items(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkStatus
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    image_path = tmp_path / "scan.jpg"
    image_path.write_bytes(b"image")
    window = MainWindow(app_root=tmp_path / "app")
    window._add_paths([image_path])
    window.work_list.items[0].status = WorkStatus.COMPLETED
    window.file_table.refresh_items(window.work_list.items)

    window._add_paths([image_path])

    assert len(window.work_list.items) == 1
    assert window.work_list.items[0].status.value == "pending"
    assert window.stage_label.text() == "목록 추가: 1개"


def test_main_window_delete_key_removes_selected_items(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    window = MainWindow()
    window.work_list.add_paths([first, second])
    window.file_table.set_items(window.work_list.items)
    window.file_table.table.selectRow(0)

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    app.sendEvent(window.file_table.table, event)

    assert [item.source_path for item in window.work_list.items] == [second]
    assert window.file_table.table.rowCount() == 1


def test_file_table_repeated_row_click_keeps_selection(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.file_table import FileTableWidget

    create_app([])
    path = tmp_path / "scan.jpg"
    path.write_bytes(b"image")
    widget = FileTableWidget()
    item = WorkItem(source_path=path)
    widget.set_items([item])
    widget.table.selectRow(0)

    widget._handle_item_clicked(widget.table.item(0, 0))
    widget._handle_item_clicked(widget.table.item(0, 1))

    assert widget.selected_items() == [item]


def test_file_table_hides_cell_focus_indicator(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.file_table import FileTableWidget

    create_app([])
    widget = FileTableWidget()

    assert "QTableWidget::item:focus" in widget.table.styleSheet()


def test_main_window_ctrl_r_rotates_selected_current_file(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    window.work_list.items = [WorkItem(source_path=image_path, current_path=image_path)]
    window.file_table.set_items(window.work_list.items)
    window.file_table.table.selectRow(0)

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
    app.sendEvent(window, event)

    with Image.open(image_path) as image:
        assert image.size == (80, 100)


def test_main_window_ctrl_r_keeps_selection_and_sidebar_open(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    window.show()
    app.processEvents()
    item = WorkItem(source_path=image_path, current_path=image_path)
    window.work_list.items = [item]
    window.file_table.set_items(window.work_list.items)
    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    app.processEvents()
    assert window.preview_panel is not None
    assert window.preview_panel.isVisible()

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
    app.sendEvent(window, event)
    app.processEvents()

    assert window.file_table.selected_items() == [item]
    assert window.preview_panel is not None
    assert window.preview_panel.isVisible()


def test_main_window_f_key_opens_preview_fullscreen(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    window.show()
    app.processEvents()
    item = WorkItem(source_path=image_path, current_path=image_path)
    window.work_list.items = [item]
    window.file_table.set_items(window.work_list.items)
    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    app.processEvents()

    app.sendEvent(window, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F, Qt.KeyboardModifier.NoModifier))
    app.processEvents()

    assert window.preview_panel is not None
    assert window.preview_panel.fullscreen_window is not None


def test_file_table_f_key_opens_preview_fullscreen(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    window.show()
    app.processEvents()
    item = WorkItem(source_path=image_path, current_path=image_path)
    window.work_list.items = [item]
    window.file_table.set_items(window.work_list.items)
    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    app.processEvents()

    app.sendEvent(window.file_table.table, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F, Qt.KeyboardModifier.NoModifier))
    app.processEvents()

    assert window.preview_panel is not None
    assert window.preview_panel.fullscreen_window is not None


def test_file_table_f_key_with_real_focus_opens_preview_fullscreen(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    window.show()
    app.processEvents()
    item = WorkItem(source_path=image_path, current_path=image_path)
    window.work_list.items = [item]
    window.file_table.set_items(window.work_list.items)
    window.file_table.table.selectRow(0)
    window.file_table.table.setFocus()
    app.processEvents()

    QTest.keyClick(window.file_table.table, Qt.Key.Key_F)
    app.processEvents()

    assert window.preview_panel is not None
    assert window.preview_panel.fullscreen_window is not None


def test_file_table_ctrl_r_keeps_current_row_for_keyboard_navigation(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    paths = []
    for index in range(3):
        path = tmp_path / f"scan_{index}.png"
        Image.new("RGB", (100 + index * 10, 80), "white").save(path)
        paths.append(path)
    window = MainWindow(app_root=tmp_path / "app")
    window.show()
    app.processEvents()
    items = [WorkItem(source_path=path, current_path=path) for path in paths]
    window.work_list.items = items
    window.file_table.set_items(window.work_list.items)
    window.file_table.table.selectRow(1)
    window.file_table.table.setCurrentCell(1, 0)
    window._sync_preview_from_selection()
    window.file_table.table.setFocus()
    app.processEvents()

    QTest.keyClick(window.file_table.table, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()

    assert window.file_table.table.currentRow() == 1
    assert window.file_table.selected_items() == [items[1]]
    with Image.open(paths[1]) as image:
        assert image.size == (80, 110)

    QTest.keyClick(window.file_table.table, Qt.Key.Key_Down)
    app.processEvents()

    assert window.file_table.table.currentRow() == 2
    assert window.file_table.selected_items() == [items[2]]


def test_main_window_ctrl_r_noops_when_multiple_preview_items_selected(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (100, 80), "white").save(first)
    Image.new("RGB", (120, 90), "black").save(second)
    window = MainWindow(app_root=tmp_path / "app")
    first_item = WorkItem(source_path=first, current_path=first)
    second_item = WorkItem(source_path=second, current_path=second)
    window.work_list.items = [first_item, second_item]
    window.file_table.set_items(window.work_list.items)
    window.file_table.select_item_ids({first_item.item_id, second_item.item_id})
    window._sync_preview_from_selection()
    app.processEvents()

    app.sendEvent(window, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier))

    with Image.open(first) as image:
        assert image.size == (100, 80)
    with Image.open(second) as image:
        assert image.size == (120, 90)


def test_main_window_ctrl_r_refreshes_visible_preview(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    item = WorkItem(source_path=image_path, current_path=image_path)
    window.work_list.items = [item]
    window.file_table.set_items(window.work_list.items)
    window.file_table.select_item_ids({item.item_id})
    window._sync_preview_from_selection()
    app.processEvents()
    assert window.preview_panel is not None
    calls = 0

    def count_refresh():
        nonlocal calls
        calls += 1

    monkeypatch.setattr(window.preview_panel, "_refresh_after_image_change", count_refresh)

    window._rotate_selected(clockwise=True)

    assert calls == 1


def test_main_window_manual_save_as_adds_created_image_to_list_and_selection(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    source = tmp_path / "scan.png"
    created = tmp_path / "scan_cut_00.png"
    Image.new("RGB", (100, 80), "white").save(source)
    Image.new("RGB", (50, 40), "white").save(created)
    window = MainWindow(app_root=tmp_path / "app")
    item = WorkItem(source_path=source, current_path=source)
    window.work_list.items = [item]
    window.work_list.rebuild_seen_paths()
    window.file_table.set_items(window.work_list.items)
    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    assert window.preview_panel is not None

    window.preview_panel.image_created.emit(created)
    app.processEvents()

    assert [work_item.source_path for work_item in window.work_list.items] == [source, created]
    assert [work_item.source_path for work_item in window.file_table.selected_items()] == [source, created]


def test_main_window_image_window_arrow_keys_sync_list_selection(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (100, 80), "white").save(first)
    Image.new("RGB", (120, 90), "black").save(second)
    window = MainWindow(app_root=tmp_path / "app")
    first_item = WorkItem(source_path=first, current_path=first)
    second_item = WorkItem(source_path=second, current_path=second)
    window.work_list.items = [first_item, second_item]
    window.file_table.set_items(window.work_list.items)
    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    assert window.preview_panel is not None
    editor = window.preview_panel.open_image_window(first)

    app.sendEvent(editor, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
    app.processEvents()

    assert editor.image_path == second
    assert window.file_table.selected_items() == [second_item]


def test_main_window_close_event_requires_confirmation(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    window = MainWindow()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()


def test_main_window_close_event_closes_preview_child_windows(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    window.show()
    window.work_list.items = [WorkItem(source_path=image_path, current_path=image_path)]
    window.file_table.set_items(window.work_list.items)
    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    assert window.preview_panel is not None
    editor = window.preview_panel.open_image_window(image_path)
    window.preview_panel.toggle_fullscreen()
    app.processEvents()
    fullscreen = window.preview_panel.fullscreen_window

    assert editor is not None and editor.isVisible()
    assert fullscreen is not None and fullscreen.isVisible()

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    event = QCloseEvent()
    window.closeEvent(event)
    app.processEvents()

    assert event.isAccepted()
    assert not editor.isVisible()
    assert not fullscreen.isVisible()


def test_main_window_close_event_clears_temp(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    window = MainWindow(app_root=tmp_path / "app")
    temp_file = window.storage.temp_dir / "originals" / "stale.tmp"
    temp_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file.write_text("stale", encoding="utf-8")

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted()
    assert not temp_file.exists()
    assert window.storage.temp_dir.exists()
    assert window.storage.cache_dir.exists()


def test_main_window_double_click_opens_current_file(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    source = tmp_path / "source.jpg"
    current = tmp_path / "current.jpg"
    source.write_bytes(b"source")
    current.write_bytes(b"current")
    window = MainWindow()
    opened: list[Path] = []
    monkeypatch.setattr(window, "_open_path", lambda path: opened.append(path))
    window.work_list.items = [WorkItem(source_path=source, current_path=current)]
    window.file_table.set_items(window.work_list.items)

    window.file_table.table.itemDoubleClicked.emit(window.file_table.table.item(0, 0))

    assert opened == [current]


def test_file_table_uses_work_queue_columns_and_keeps_drop_enabled(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QMimeData, QUrl, Qt

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem, WorkStatus
    from doc_auto.domain.options import ProcessingMode
    from doc_auto.ui.file_table import FileTableWidget

    create_app([])
    path = tmp_path / "scan.png"
    path.write_bytes(b"")
    table = FileTableWidget()
    table.add_item(
        WorkItem(
            source_path=path,
            current_path=path,
            status=WorkStatus.COMPLETED,
            last_mode=ProcessingMode.PDF_CONVERT,
            page_count=3,
        )
    )

    headers = [table.table.horizontalHeaderItem(index).text() for index in range(table.table.columnCount())]
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])

    assert headers == ["상태", "파일명", "확장자", "페이지", "파일크기"]
    assert [table.table.item(0, column).text() for column in range(table.table.columnCount())] == [
        "완료",
        "scan.png",
        "PNG",
        "3",
        "0 KB",
    ]
    for column in (0, 2, 3):
        assert table.table.item(0, column).textAlignment() & int(Qt.AlignmentFlag.AlignHCenter)
    assert table.table.item(0, 4).textAlignment() & int(Qt.AlignmentFlag.AlignRight)
    assert all(table.table.horizontalHeader().sectionResizeMode(column).name == "Fixed" for column in range(5))
    assert table.table.acceptDrops() is True
    assert table.table.viewport().acceptDrops() is True
    assert table.table.paths_from_mime(mime) == [path]


def test_file_table_column_widths_keep_file_size_readable(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.file_table import FILE_SIZE_COLUMN, FileTableWidget, MIN_COLUMN_WIDTHS

    app = create_app([])
    path = tmp_path / "scan.png"
    path.write_bytes(b"")
    table = FileTableWidget()
    table.add_item(WorkItem(source_path=path, current_path=path))

    def assert_widths() -> None:
        widths = [table.table.horizontalHeader().sectionSize(column) for column in range(table.table.columnCount())]
        total = sum(widths)
        assert abs(widths[1] / total - 0.5) <= 0.08
        assert MIN_COLUMN_WIDTHS[FILE_SIZE_COLUMN] <= 74
        assert widths[FILE_SIZE_COLUMN] >= MIN_COLUMN_WIDTHS[FILE_SIZE_COLUMN]

    table.resize(1000, 400)
    table.show()
    app.processEvents()
    assert_widths()

    table.resize(1400, 400)
    app.processEvents()
    assert_widths()


def test_file_table_displays_archive_member_name_extension_and_size(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    import zipfile

    from doc_auto.app import create_app
    from doc_auto.services.work_list import WorkList
    from doc_auto.ui.file_table import FileTableWidget

    create_app([])
    zip_path = tmp_path / "docs.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("scan_01.jpg", b"x" * 2048)
    item = WorkList().add_paths([zip_path])[0]
    table = FileTableWidget()
    table.set_items([item])

    assert item.current_name == "scan_01.jpg"
    assert [table.table.item(0, column).text() for column in range(table.table.columnCount())] == [
        "대기",
        "scan_01.jpg",
        "JPG",
        "1",
        "2 KB",
    ]


def test_file_table_header_click_sorts_by_column_with_natural_filename(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.file_table import FileTableWidget

    create_app([])
    table = FileTableWidget()
    table.set_items(
        [
            WorkItem(source_path=tmp_path / "scan_10.jpg"),
            WorkItem(source_path=tmp_path / "scan_2.jpg"),
            WorkItem(source_path=tmp_path / "scan_1.jpg"),
        ]
    )

    assert [item.current_name for item in table.items] == ["scan_1.jpg", "scan_2.jpg", "scan_10.jpg"]
    assert [table.table.item(row, 1).text() for row in range(3)] == ["scan_1.jpg", "scan_2.jpg", "scan_10.jpg"]

    table.table.horizontalHeader().sectionClicked.emit(1)

    assert [item.current_name for item in table.items] == ["scan_10.jpg", "scan_2.jpg", "scan_1.jpg"]


def test_file_table_has_no_hover_item_style(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    window = MainWindow()

    assert "QTableWidget::item:hover" not in window.styleSheet()
    assert window.file_table.table.hasMouseTracking() is False
    assert window.file_table.table.viewport().hasMouseTracking() is False


def test_file_table_can_select_rows_from_blank_viewport_drag(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.file_table import FileTableWidget

    app = create_app([])
    table = FileTableWidget()
    table.resize(700, 420)
    table.show()
    for index in range(3):
        path = tmp_path / f"{index}.png"
        path.write_bytes(b"")
        table.add_item(WorkItem(source_path=path, current_path=path))
    app.processEvents()

    QTest.mousePress(table.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 390))
    QTest.mouseMove(table.table.viewport(), QPoint(680, 20))
    QTest.mouseRelease(table.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(680, 20))

    assert len(table.selected_items()) >= 1


def test_main_window_defers_preview_sync_while_table_selection_drag_is_active(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (20, 20), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    item = WorkItem(source_path=image_path, current_path=image_path)
    window.work_list.items = [item]
    window.file_table.set_items(window.work_list.items)
    calls = 0

    def count_sync() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(window, "_sync_preview_from_selection", count_sync)

    window._begin_preview_selection_drag()
    window.file_table.table.selectRow(0)
    window._schedule_preview_sync()

    assert calls == 0

    window._finish_preview_selection_drag()

    assert calls == 1


def test_main_window_preview_panel_follows_selection(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (20, 20), "white").save(image_path)
    window = MainWindow()
    window.resize(window._expanded_window_minimum_width(window._preview_sidebar_min_width()) + 20, 700)
    window.show()
    create_app([]).processEvents()
    initial_window_width = window.width()
    initial_table_width = window.file_table.width()
    item = WorkItem(source_path=image_path, current_path=image_path)

    window.file_table.add_item(item)
    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    create_app([]).processEvents()

    assert window.preview_panel is not None
    assert window.preview_panel.isVisible()
    assert window.width() == initial_window_width
    assert window.preview_panel.width() >= window._preview_sidebar_min_width()
    assert window.preview_panel.height() >= window.centralWidget().height() - 4
    assert abs(window.file_table.width() - initial_table_width) <= 2

    window.file_table.table.clearSelection()
    window._sync_preview_from_selection()

    assert window.preview_panel is not None
    assert not window.preview_panel.isVisible()
    assert window.width() == initial_window_width


def test_main_window_first_selection_opens_preview_without_debounce(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (20, 20), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    window.show()
    app.processEvents()
    window.file_table.add_item(WorkItem(source_path=image_path, current_path=image_path))

    window.file_table.table.selectRow(0)

    assert not window.preview_sync_timer.isActive()
    assert window._preview_sidebar_expanded is True
    assert window.preview_panel is not None
    assert window.preview_panel.paths == [image_path]


def test_main_window_freezes_window_updates_while_first_sidebar_opens(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image
    from PySide6.QtTest import QTest

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (20, 20), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    window.show()
    app.processEvents()
    window.file_table.add_item(WorkItem(source_path=image_path, current_path=image_path))

    window.file_table.table.selectRow(0)

    assert window.updatesEnabled() is False

    QTest.qWait(250)

    assert window.updatesEnabled() is True


def test_main_window_preview_sidebar_does_not_change_list_width(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (20, 20), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    window.show()
    app.processEvents()
    item = WorkItem(source_path=image_path, current_path=image_path)
    window.file_table.add_item(item)
    before = window.file_table.width()

    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    app.processEvents()
    shown_width = window.file_table.width()
    window.file_table.table.clearSelection()
    window._sync_preview_from_selection()
    app.processEvents()

    assert abs(shown_width - before) <= 2
    assert abs(window.file_table.width() - before) <= 2


def test_main_window_preview_selection_does_not_stretch_footer_before_sidebar(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (20, 20), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    window.resize(window._expanded_window_minimum_width(window._preview_sidebar_min_width()) + 200, 700)
    window.show()
    app.processEvents()
    window.file_table.add_item(WorkItem(source_path=image_path, current_path=image_path))
    footer_width = window.progress.width()

    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    app.processEvents()

    assert abs(window.progress.width() - footer_width) <= 2


def test_main_window_preview_selection_reflows_after_sidebar_width_is_set(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow
    from doc_auto.ui.preview_panel import PreviewPanel

    app = create_app([])
    reflow_widths: list[int] = []
    original_reflow = PreviewPanel.reflow

    def traced_reflow(self):
        reflow_widths.append(self.width())
        return original_reflow(self)

    monkeypatch.setattr(PreviewPanel, "reflow", traced_reflow)
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (20, 20), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    window.resize(window._expanded_window_minimum_width(window._preview_sidebar_min_width()) + 200, 700)
    window.show()
    app.processEvents()
    window.file_table.add_item(WorkItem(source_path=image_path, current_path=image_path))
    expected_sidebar_width = (
        window.width() - window._list_area_width() - window.shell_splitter.handleWidth()
    )

    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    app.processEvents()

    assert reflow_widths
    assert all(width == expected_sidebar_width for width in reflow_widths)


def test_main_window_preview_does_not_paint_until_sidebar_geometry_is_final(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image
    from PySide6.QtCore import QObject, QEvent
    from PySide6.QtTest import QTest

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    class SidebarTransitionWatcher(QObject):
        def __init__(self, window, expected_width: int) -> None:
            super().__init__()
            self.window = window
            self.expected_width = expected_width
            self.painted_intermediate_widths: list[int] = []

        def eventFilter(self, obj, event):  # noqa: N802 - Qt override
            preview_panel = self.window.preview_panel
            if (
                preview_panel is not None
                and obj is preview_panel
                and event.type() == QEvent.Type.Paint
                and 0 < preview_panel.width() < self.expected_width
            ):
                self.painted_intermediate_widths.append(preview_panel.width())
            return False

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (20, 20), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    window.show()
    app.processEvents()
    window.file_table.add_item(WorkItem(source_path=image_path, current_path=image_path))
    expected_sidebar_width = window._preview_sidebar_min_width()
    watcher = SidebarTransitionWatcher(window, expected_sidebar_width)
    app.installEventFilter(watcher)

    window.file_table.table.selectRow(0)
    QTest.qWait(250)

    app.removeEventFilter(watcher)
    assert watcher.painted_intermediate_widths == []


def test_main_window_preview_selection_reopen_keeps_list_width(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    paths = []
    for index in range(2):
        path = tmp_path / f"scan_{index}.png"
        Image.new("RGB", (100, 100), "white").save(path)
        paths.append(path)
    window = MainWindow(app_root=tmp_path / "app")
    window.show()
    app.processEvents()
    window.work_list.items = [WorkItem(source_path=path, current_path=path) for path in paths]
    window.file_table.set_items(window.work_list.items)
    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    app.processEvents()
    stable_width = window.file_table.width()

    window.file_table.table.clearSelection()
    window._sync_preview_from_selection()
    app.processEvents()
    window.file_table.table.selectRow(1)
    window._sync_preview_from_selection()
    app.processEvents()

    assert abs(window.file_table.width() - stable_width) <= 2


def test_main_window_preview_sidebar_grows_when_window_width_grows(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 100), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    window.resize(1120, 700)
    window.show()
    app.processEvents()
    window.file_table.add_item(WorkItem(source_path=image_path, current_path=image_path))
    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    app.processEvents()
    assert window.preview_panel is not None
    initial_table_width = window.file_table.width()
    initial_sidebar_width = window.preview_panel.width()

    window.resize(window.width() + 500, window.height())
    app.processEvents()

    assert abs(window.file_table.width() - initial_table_width) <= 2
    assert window.preview_panel.width() >= initial_sidebar_width + 490


def test_main_window_preview_clear_restores_manually_resized_resting_width(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 100), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    window.show()
    app.processEvents()
    manual_resting_width = window._list_area_width() + 140
    window.resize(manual_resting_width, window.height())
    app.processEvents()
    window.file_table.add_item(WorkItem(source_path=image_path, current_path=image_path))

    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    app.processEvents()
    expanded_width = window.width()
    window.file_table.table.clearSelection()
    window._sync_preview_from_selection()
    app.processEvents()

    assert expanded_width >= window._list_area_width() + window.shell_splitter.handleWidth() + window._preview_sidebar_min_width()
    assert window.width() == manual_resting_width


def test_main_window_preview_sidebar_min_width_preserves_list_width(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 100), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    window.show()
    app.processEvents()
    base_list_width = window.left_panel.width()
    base_min_width = window.minimumWidth()

    window.file_table.add_item(WorkItem(source_path=image_path, current_path=image_path))
    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    app.processEvents()

    assert window.preview_panel is not None
    expected_minimum = base_min_width + window.shell_splitter.handleWidth() + window._preview_sidebar_min_width()
    assert window.minimumWidth() >= expected_minimum

    window.resize(base_min_width, window.height())
    app.processEvents()

    assert window.width() >= expected_minimum
    assert window.left_panel.width() >= base_list_width - 2


def test_main_window_preview_sidebar_uses_portrait_friendly_default_and_splitter(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    image_path = tmp_path / "portrait.png"
    Image.new("RGB", (700, 990), "white").save(image_path)
    window = MainWindow()
    window.resize(1120, 700)
    window.show()
    app.processEvents()
    window.file_table.add_item(WorkItem(source_path=image_path, current_path=image_path))
    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    app.processEvents()

    assert window.preview_panel is not None
    assert window.preview_panel.width() >= 480
    assert window.shell_splitter.indexOf(window.preview_panel) >= 0
    assert window.shell_splitter.handleWidth() > 0


def test_main_window_preview_extracts_zip_image_member_for_sidebar_and_manual_crop(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from io import BytesIO

    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow
    from doc_auto.ui.preview_panel import ImagePreviewWindow

    app = create_app([])
    payload = BytesIO()
    Image.new("RGB", (100, 80), "white").save(payload, format="PNG")
    zip_path = tmp_path / "docs.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("scan.png", payload.getvalue())
    window = MainWindow(app_root=tmp_path / "app")
    window._add_paths([zip_path])

    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()
    app.processEvents()

    item = window.work_list.items[0]
    assert item.current_path is not None
    assert item.current_path.exists()
    assert item.current_path.suffix == ".png"
    assert item.current_path != zip_path
    assert window.preview_panel is not None
    assert window.preview_panel.paths == [item.current_path]

    editor = ImagePreviewWindow(item.current_path, storage=window.storage)
    editor.apply_crop((10, 10, 60, 50))
    with Image.open(item.current_path) as image:
        assert image.size == (50, 40)


def test_main_window_single_pdf_selection_shows_all_pages_in_sidebar(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    pages = []
    for index in range(3):
        page = tmp_path / f"page_{index}.png"
        Image.new("RGB", (100, 140), "white").save(page)
        pages.append(page)
    window = MainWindow(app_root=tmp_path / "app")
    item = WorkItem(source_path=pdf_path)
    window.work_list.items = [item]
    window.file_table.set_items(window.work_list.items)
    monkeypatch.setattr(window, "_pdf_preview_pages", lambda _item: pages)

    window.file_table.table.selectRow(0)
    window._sync_preview_from_selection()

    assert window.preview_panel is not None
    assert window.preview_panel.paths == pages
    assert window.preview_panel.scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded


def test_main_window_multi_select_pdf_preview_uses_first_page_with_badge(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (80, 60), "black").save(image_path)
    pages = []
    for index in range(3):
        page = tmp_path / f"page_{index}.png"
        Image.new("RGB", (100, 140), "white").save(page)
        pages.append(page)
    window = MainWindow(app_root=tmp_path / "app")
    pdf_item = WorkItem(source_path=pdf_path)
    image_item = WorkItem(source_path=image_path, current_path=image_path)
    window.work_list.items = [pdf_item, image_item]
    window.file_table.set_items(window.work_list.items)
    monkeypatch.setattr(window, "_pdf_preview_pages", lambda _item: pages)
    window.file_table.select_item_ids({pdf_item.item_id, image_item.item_id})

    window._sync_preview_from_selection()

    assert window.preview_panel is not None
    assert window.preview_panel.paths == [pages[0], image_path]
    assert window.preview_panel.page_badges[pages[0]] == "PDF | 3P"
    thumbnail = window.preview_panel.grid.itemAt(0).widget()
    assert thumbnail.badge_label.text() == "PDF | 3P"


def test_main_window_pdf_preview_is_not_materialized_for_manual_edit(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF")
    preview_page = tmp_path / "preview_page_001.png"
    Image.new("RGB", (80, 120), "white").save(preview_page)
    window = MainWindow(app_root=tmp_path / "app")
    item = WorkItem(source_path=pdf_path)
    window.work_list.items = [item]
    window.file_table.set_items(window.work_list.items)
    monkeypatch.setattr(window, "_pdf_preview_pages", lambda _item: [preview_page])
    monkeypatch.setattr(window, "_cached_pdf_preview_pages", lambda _item: [preview_page])

    editable = window._ensure_editable_preview_path(preview_page)

    assert editable is None
    assert [work_item.source_path for work_item in window.work_list.items] == [pdf_path]


def test_main_window_does_not_prompt_when_pdf_preview_is_clicked_for_edit(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    window = MainWindow(app_root=tmp_path / "app")
    pdf_path = tmp_path / "doc.pdf"
    preview_page = tmp_path / "preview_page.png"
    pdf_path.write_bytes(b"%PDF")
    Image.new("RGB", (80, 120), "white").save(preview_page)
    item = WorkItem(source_path=pdf_path)
    window.work_list.items = [item]
    window.file_table.set_items(window.work_list.items)
    monkeypatch.setattr(window, "_cached_pdf_preview_pages", lambda _item: [preview_page])
    monkeypatch.setattr(
        window,
        "_confirm_materialize_bundle_for_edit",
        lambda _item: (_ for _ in ()).throw(AssertionError("materialize prompt must not open")),
    )

    assert window._ensure_editable_preview_path(preview_page) is None


def test_main_window_uses_selected_items_for_utility_scope(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (20, 20), "white").save(first)
    Image.new("RGB", (20, 20), "black").save(second)
    window = MainWindow()
    first_item = WorkItem(source_path=first, current_path=first)
    second_item = WorkItem(source_path=second, current_path=second)
    window.work_list.items = [first_item, second_item]
    window.file_table.set_items(window.work_list.items)

    assert window._utility_items() == [first_item, second_item]

    window.file_table.table.selectRow(1)

    assert window._utility_items() == [second_item]


def test_main_window_merges_selected_utility_results_without_clearing_list(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem, WorkStatus
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    second_output = tmp_path / "second_work.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    second_output.write_bytes(b"second resized")
    window = MainWindow()
    first_item = WorkItem(source_path=first)
    second_item = WorkItem(source_path=second)
    window.work_list.items = [first_item, second_item]
    window.file_table.set_items(window.work_list.items)
    result = WorkItem(
        source_path=second,
        item_id=second_item.item_id,
        current_path=second_output,
        status=WorkStatus.COMPLETED,
    )

    window._finish_item_results([result], "리사이징 완료", merge_scope=[second_item])

    assert [item.source_path for item in window.work_list.items] == [first, second]
    assert window.work_list.items[0].current_path is None
    assert window.work_list.items[1].current_path == second_output
    assert window.file_table.table.rowCount() == 2


def test_main_window_readded_processed_file_reuses_cache_metadata(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem, WorkStatus
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    app_root = tmp_path / "app"
    source = tmp_path / "scan.jpg"
    current = tmp_path / "영수증_01.jpg"
    cache = app_root / "data" / "cache" / "sources" / "item123" / "scan.jpg"
    source.write_bytes(b"source")
    current.write_bytes(b"current")
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"source")
    window = MainWindow(app_root=app_root)
    processed = WorkItem(
        source_path=source,
        item_id="item123",
        cached_source_path=cache,
        current_path=current,
        status=WorkStatus.COMPLETED,
    )

    window._remember_items([processed])
    window._add_paths([current])

    item = window.work_list.items[0]
    assert item.original_name == "scan.jpg"
    assert item.current_name == "영수증_01.jpg"
    assert item.cached_source_path == cache

    cache.unlink()
    window._add_paths([current])

    item = window.work_list.items[0]
    assert item.original_name == "영수증_01.jpg"
    assert item.cached_source_path is None


def test_main_window_bundle_output_uses_selected_first_item(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "first.png"
    second = second_dir / "second.png"
    Image.new("RGB", (20, 20), "white").save(first)
    Image.new("RGB", (20, 20), "black").save(second)
    window = MainWindow()
    first_item = WorkItem(source_path=first, current_path=first)
    second_item = WorkItem(source_path=second, current_path=second)
    window.work_list.items = [first_item, second_item]
    window.file_table.set_items(window.work_list.items)
    window.file_table.table.selectRow(1)

    assert window._default_bundle_pdf_path(window._utility_items()) == second_dir / "second.pdf"


def test_main_window_notifies_when_item_work_finishes(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem, WorkStatus
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    output = tmp_path / "scan.jpg"
    output.write_bytes(b"image")
    window = MainWindow(app_root=tmp_path / "app")
    messages: list[tuple[str, str]] = []
    window._notify_completed = lambda title, message: messages.append((title, message))
    result = WorkItem(source_path=output, current_path=output, status=WorkStatus.COMPLETED)

    window._finish_item_results([result], "완료", output_basis=True)

    assert messages == [("OneStep", "완료")]


def test_main_window_item_results_show_failure_when_all_failed(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem, WorkStatus
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    source = tmp_path / "broken.hwp"
    source.write_bytes(b"hwp")
    window = MainWindow(app_root=tmp_path / "app")
    messages: list[tuple[str, str]] = []
    window._notify_completed = lambda title, message: messages.append((title, message))
    result = WorkItem(source_path=source, status=WorkStatus.FAILED, detail="RuntimeError")

    window._finish_item_results([result], "PDF 변환 완료")

    assert window.stage_label.text() == "PDF 변환 실패: 1개"
    assert messages == [("OneStep", "PDF 변환 실패: 1개")]


def test_main_window_item_results_use_output_files_as_list_basis(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem, WorkStatus
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    source_pdf = tmp_path / "doc.pdf"
    output_page = tmp_path / "doc_001.png"
    source_pdf.write_bytes(b"%PDF")
    output_page.write_bytes(b"page")
    window = MainWindow(app_root=tmp_path / "app")
    result = WorkItem(source_path=source_pdf, current_path=output_page, status=WorkStatus.COMPLETED)

    window._finish_item_results([result], "완료", output_basis=True)

    assert window.work_list.items[0].source_path == output_page
    assert window.file_table.table.item(0, 1).text() == "doc_001.png"
    assert window.file_table.table.item(0, 1).text() == "doc_001.png"


def test_main_window_archive_results_preview_as_output_grid(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem, WorkStatus
    from doc_auto.ui.main_window import MainWindow

    app = create_app([])
    zip_path = tmp_path / "A.zip"
    zip_path.write_bytes(b"zip")
    first = tmp_path / "A" / "first.png"
    second = tmp_path / "A" / "second.png"
    first.parent.mkdir()
    Image.new("RGB", (40, 30), "white").save(first)
    Image.new("RGB", (40, 30), "black").save(second)
    window = MainWindow(app_root=tmp_path / "app")
    results = [
        WorkItem(source_path=zip_path, archive_member_name="first.png", current_path=first, status=WorkStatus.COMPLETED),
        WorkItem(source_path=zip_path, archive_member_name="second.png", current_path=second, status=WorkStatus.COMPLETED),
    ]

    window._finish_item_results(results, "완료", output_basis=True)
    window.file_table.select_item_ids({item.item_id for item in window.work_list.items})
    window._sync_preview_from_selection()
    app.processEvents()

    assert [item.archive_member_name for item in window.work_list.items] == [None, None]
    assert window.preview_panel is not None
    assert window.preview_panel.paths == [first, second]
    assert window.preview_panel.grid.count() == 2


def test_main_window_image_selection_does_not_render_unselected_pdf_preview(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    pdf_path = tmp_path / "doc.pdf"
    image_path = tmp_path / "scan.png"
    pdf_path.write_bytes(b"%PDF")
    Image.new("RGB", (40, 40), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")
    pdf_item = WorkItem(source_path=pdf_path)
    image_item = WorkItem(source_path=image_path, current_path=image_path)
    window.work_list.items = [pdf_item, image_item]
    window.file_table.set_items(window.work_list.items)
    calls = 0

    def count_pdf_preview(_item):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(window, "_pdf_preview_pages", count_pdf_preview)
    window.file_table.select_item_ids({image_item.item_id})

    window._sync_preview_from_selection()

    assert calls == 0


def test_main_window_notifies_when_pdf_bundle_finishes(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from types import SimpleNamespace

    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    window = MainWindow(app_root=tmp_path / "app")
    messages: list[tuple[str, str]] = []
    window._notify_completed = lambda title, message: messages.append((title, message))

    window._finish_pdf_bundle(SimpleNamespace(page_count=2))

    assert messages == [("OneStep", "PDF 묶음 완료: 2페이지")]


def test_main_window_footer_layout_uses_expanding_progress_and_fixed_start(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QSizePolicy

    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    window = MainWindow()

    assert window.stage_label.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert window.progress.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert window.progress.isTextVisible() is False
    assert window.progress.minimumHeight() >= 22
    assert window.progress_percent_label.text() == "0%"
    assert window.progress_percent_label.minimumWidth() == window.progress_percent_label.maximumWidth()
    assert window.start_stop_button.minimumWidth() == window.start_stop_button.maximumWidth()
    assert not window.stage_time_label.isVisible()
    assert not window.elapsed_label.isVisible()


def test_file_table_uses_middle_elide_for_long_filenames(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt

    from doc_auto.app import create_app
    from doc_auto.ui.file_table import FileTableWidget

    create_app([])
    table = FileTableWidget()

    assert table.table.textElideMode() == Qt.TextElideMode.ElideMiddle


def test_main_window_progress_queue_updates_percent_label_and_elides_stage(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    window = MainWindow()
    long_text = "처리 중 · 12/120 · " + "very_long_filename_" * 20 + ".png · 리사이징"

    window.stage_label.setFixedWidth(220)
    window._queue_progress(42, long_text)
    window._drain_progress_events()

    assert window.progress.value() == 42
    assert window.progress_percent_label.text() == "42%"
    assert window.stage_label.toolTip() == long_text
    assert window.stage_label.text() != long_text


def test_run_py_imports_without_pythonpath_or_project_cwd(tmp_path):
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    run_py = Path(__file__).resolve().parents[1] / "run.py"

    completed = subprocess.run(
        [sys.executable, "-c", f"import runpy; runpy.run_path({str(run_py)!r}, run_name='not_main'); print('ok')"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert "ok" in completed.stdout


def test_run_py_uses_single_doc_auto_package() -> None:
    run_py = Path(__file__).resolve().parents[1] / "run.py"
    project_root = Path(__file__).resolve().parents[1]
    source = run_py.read_text(encoding="utf-8")

    assert "from run_next import main" not in source
    assert "doc_auto.app" in source
    assert "doc_auto_next" not in source
    assert "doc_auto.ui.main_window" not in source
    assert not (project_root / "run_next.py").exists()
    assert not (project_root / "src" / "doc_auto_next").exists()


def test_run_py_resolves_frozen_app_root_to_exe_folder(monkeypatch, tmp_path):
    import run

    exe_path = tmp_path / "OneStep_v1.1.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_path))

    assert run.resolve_app_root() == tmp_path
