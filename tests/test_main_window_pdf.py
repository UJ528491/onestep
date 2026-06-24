import time
from dataclasses import replace
from pathlib import Path

from PIL import Image
from tests.pdf_assertions import assert_pdf_page_count


def _wait_until(condition, timeout_seconds: float = 2.0) -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    deadline = time.perf_counter() + timeout_seconds
    while time.perf_counter() < deadline:
        if condition():
            return
        if app is not None:
            app.processEvents()
        time.sleep(0.01)
    assert condition()


def test_main_window_pdf_button_creates_individual_pdf(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    image_path = tmp_path / "scan.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")

    window._add_paths([image_path])
    window._run_pdf_convert()

    _wait_until(lambda: window.stage_label.text() == "PDF 변환 완료")
    assert (tmp_path / "scan.pdf").exists()
    assert not image_path.exists()
    assert window.file_table.table.item(0, 0).text() == "완료"
    assert window.file_table.table.item(0, 1).text() == "scan.pdf"


def test_main_window_pdf_button_deletes_current_work_file(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    original = tmp_path / "origin.jpg"
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    current = work_dir / "page.jpg"
    Image.new("RGB", (100, 100), "white").save(original)
    Image.new("RGB", (100, 100), "black").save(current)
    window = MainWindow(app_root=tmp_path / "app")
    item = WorkItem(source_path=original, current_path=current)
    window.work_list.items = [item]
    window.work_list.rebuild_seen_paths()
    window.file_table.set_items(window.work_list.items)

    window._run_pdf_convert()

    _wait_until(lambda: window.stage_label.text() == "PDF 변환 완료")
    assert (work_dir / "page.pdf").exists()
    assert not current.exists()
    assert original.exists()


def test_main_window_pdf_button_skips_existing_pdf_when_mixed_with_image(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui import main_window
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    image_path = tmp_path / "scan.jpg"
    pdf_path = tmp_path / "already.pdf"
    Image.new("RGB", (100, 100), "white").save(image_path)
    pdf_path.write_bytes(b"%PDF-1.4")
    window = MainWindow(app_root=tmp_path / "app")
    image_item = WorkItem(source_path=image_path, current_path=image_path)
    pdf_item = WorkItem(source_path=pdf_path, current_path=pdf_path)
    window.work_list.items = [image_item, pdf_item]
    window.file_table.set_items(window.work_list.items)
    window.file_table.select_item_ids({image_item.item_id, pdf_item.item_id})
    captured: list[WorkItem] = []

    class FakeWorkflow:
        def __init__(self, **_kwargs):
            pass

        def convert_individual(self, items, **_kwargs):
            captured.extend(items)
            return []

    monkeypatch.setattr(main_window, "PdfConversionWorkflow", FakeWorkflow)
    monkeypatch.setattr(window, "_start_background_task", lambda _text, work, _finish: work())

    window._run_pdf_convert()

    assert captured == [image_item]


def test_main_window_pdf_button_noops_when_only_pdf_selected(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    pdf_path = tmp_path / "already.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    window = MainWindow(app_root=tmp_path / "app")
    pdf_item = WorkItem(source_path=pdf_path, current_path=pdf_path)
    window.work_list.items = [pdf_item]
    window.file_table.set_items(window.work_list.items)
    window.file_table.select_item_ids({pdf_item.item_id})
    started = False

    def start_background_task(_text, _work, _finish):
        nonlocal started
        started = True

    monkeypatch.setattr(window, "_start_background_task", start_background_task)

    window._run_pdf_convert()

    assert not started
    assert window.stage_label.text() == "PDF 변환할 이미지 없음"


def test_main_window_pdf_bundle_button_creates_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    Image.new("RGB", (100, 100), "white").save(first)
    Image.new("RGB", (100, 100), "black").save(second)
    window = MainWindow(app_root=tmp_path / "app")

    window._add_paths([first, second])
    window._run_pdf_bundle()

    _wait_until(lambda: window.stage_label.text() == "PDF 묶음 완료: 2페이지")
    output = tmp_path / "a.pdf"
    assert output.exists()
    assert_pdf_page_count(output, 2)
    assert not first.exists()
    assert not second.exists()
    assert [window.file_table.table.item(row, 1).text() for row in range(window.file_table.table.rowCount())] == [
        "a.pdf"
    ]


def test_main_window_pdf_bundle_deletes_current_work_files(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    originals = [tmp_path / "origin_a.jpg", tmp_path / "origin_b.jpg"]
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    currents = [work_dir / "a.jpg", work_dir / "b.jpg"]
    for path in originals + currents:
        Image.new("RGB", (100, 100), "white").save(path)
    window = MainWindow(app_root=tmp_path / "app")
    window.work_list.items = [
        WorkItem(source_path=originals[0], current_path=currents[0]),
        WorkItem(source_path=originals[1], current_path=currents[1]),
    ]
    window.work_list.rebuild_seen_paths()
    window.file_table.set_items(window.work_list.items)

    window._run_pdf_bundle()

    _wait_until(lambda: window.stage_label.text() == "PDF 묶음 완료: 2페이지")
    assert (work_dir / "a.pdf").exists()
    assert not currents[0].exists()
    assert not currents[1].exists()
    assert originals[0].exists()
    assert originals[1].exists()


def test_main_window_document_processing_splits_tiff_and_deletes_container(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    tiff_path = tmp_path / "scan.tiff"
    first = Image.new("RGB", (100, 100), "white")
    second = Image.new("RGB", (100, 100), "black")
    first.save(tiff_path, save_all=True, append_images=[second])
    window = MainWindow(app_root=tmp_path / "app")
    window.settings = replace(window.settings, rotation_enabled=False, resize_enabled=False)

    window._add_paths([tiff_path])
    window._run_document_processing()

    _wait_until(lambda: window._active_future is None)
    outputs = sorted(path for path in tmp_path.glob("scan_*") if path.suffix.lower() in {".jpg", ".png"})
    assert [path.stem for path in outputs] == ["scan_001", "scan_002"]
    assert not tiff_path.exists()
    assert [item.current_path for item in window.work_list.items] == outputs


def test_main_window_pdf_bundle_keeps_sources_when_delete_option_off(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    Image.new("RGB", (100, 100), "white").save(first)
    Image.new("RGB", (100, 100), "black").save(second)
    window = MainWindow(app_root=tmp_path / "app")
    window.settings = replace(window.settings, pdf_bundle_delete_source=False)

    window._add_paths([first, second])
    window._run_pdf_bundle()

    _wait_until(lambda: window.stage_label.text() == "PDF 묶음 완료: 2페이지")
    output = tmp_path / "a.pdf"
    assert output.exists()
    assert first.exists()
    assert second.exists()
    assert [window.file_table.table.item(row, 1).text() for row in range(window.file_table.table.rowCount())] == [
        "a.jpg",
        "a.pdf",
        "b.jpg",
    ]


def test_main_window_pdf_bundle_uses_current_file_folder_and_name(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.domain.job import WorkItem
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    original = tmp_path / "origin.png"
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    current = work_dir / "page_001.png"
    Image.new("RGB", (100, 100), "white").save(original)
    Image.new("RGB", (100, 100), "black").save(current)
    window = MainWindow(app_root=tmp_path / "app")
    item = WorkItem(source_path=original, current_path=current)

    assert window._default_bundle_pdf_path([item]) == work_dir / "page_001.pdf"


def test_main_window_has_no_global_restore_action(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    window = MainWindow(app_root=tmp_path / "app")

    assert not hasattr(window, "undo_button")
    assert not hasattr(window, "restore_button")
    assert not hasattr(window, "_restore_selected")
