from pathlib import Path
import time

from PIL import Image

from doc_auto.domain.job import WorkStatus


class FakeCleanupWorkflow:
    def __init__(self, output_path: Path, delay_seconds: float = 0.0) -> None:
        self.output_path = output_path
        self.delay_seconds = delay_seconds

    def run(self, items, **_kwargs):
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        item = items[0]
        self.output_path.write_bytes(b"renamed")
        item.current_path = self.output_path
        item.status = WorkStatus.COMPLETED
        return [item]


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


def test_main_window_start_button_updates_table(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    image_path = tmp_path / "scan.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path)
    output_path = tmp_path / "Receipt_01.jpg"
    window = MainWindow(app_root=tmp_path / "app")
    window._create_cleanup_workflow = lambda: FakeCleanupWorkflow(output_path)

    window._add_paths([image_path])
    window._start_or_stop()

    _wait_until(lambda: window.stage_label.text() == "완료")
    assert window.file_table.table.item(0, 1).text() == "Receipt_01.jpg"
    assert window.file_table.table.item(0, 1).text() == "Receipt_01.jpg"


def test_main_window_start_returns_before_workflow_finishes(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    image_path = tmp_path / "scan.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path)
    output_path = tmp_path / "Receipt_01.jpg"
    window = MainWindow(app_root=tmp_path / "app")
    window._create_cleanup_workflow = lambda: FakeCleanupWorkflow(output_path, delay_seconds=0.2)

    window._add_paths([image_path])
    started_at = time.perf_counter()
    window._start_or_stop()

    assert time.perf_counter() - started_at < 0.1
    assert window.stage_label.text() == "처리 중"
    assert window.start_stop_button.text() == "정지"
    assert window.start_stop_button.isEnabled() is True

    _wait_until(lambda: window.stage_label.text() == "완료")


def test_main_window_cleanup_workflow_uses_document_image_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.services.image_pipeline import DocumentImagePipeline
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    window = MainWindow(app_root=tmp_path / "app")

    workflow = window._create_cleanup_workflow()

    assert isinstance(workflow.image_pipeline, DocumentImagePipeline)


def test_main_window_cleanup_workflow_uses_saved_normalization_options(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.services.settings_store import AppSettings, SettingsStore
    from doc_auto.services.temp_storage import PortableStorage
    from doc_auto.ui.main_window import MainWindow

    app_root = tmp_path / "app"
    storage = PortableStorage(app_root)
    SettingsStore(storage).save(
        AppSettings(
            rotation_enabled=False,
        )
    )

    create_app([])
    window = MainWindow(app_root=app_root)
    workflow = window._create_cleanup_workflow()

    assert workflow.image_pipeline.options.exif_orientation_enabled is False
    assert workflow.image_pipeline.options.ocr_orientation_enabled is False
