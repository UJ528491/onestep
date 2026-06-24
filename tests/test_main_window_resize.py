import time

from PIL import Image


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


def test_main_window_resize_button_processes_work_list(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.main_window import MainWindow

    create_app([])
    image_path = tmp_path / "large.jpg"
    Image.new("RGB", (3000, 2000), "white").save(image_path)
    window = MainWindow(app_root=tmp_path / "app")

    window._add_paths([image_path])
    window._run_resize_only()

    _wait_until(lambda: window.stage_label.text() == "리사이징 완료")
    output = image_path
    assert output.exists()
    with Image.open(output) as resized:
        assert resized.size == (1920, 1280)
    assert window.file_table.table.item(0, 1).text() == "large.jpg"
