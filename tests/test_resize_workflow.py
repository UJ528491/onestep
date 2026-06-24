from pathlib import Path
import threading

from PIL import Image

from doc_auto.domain.job import WorkItem, WorkStatus
from doc_auto.domain.options import ProcessingMode
from doc_auto.services.image_resizer import ImageResizer
from doc_auto.services.image_resizer import ResizeResult
from doc_auto.services.input_preparation import InputPreparationPipeline
from doc_auto.services.resize_workflow import ResizeOnlyWorkflow
from doc_auto.services.temp_storage import PortableStorage


def test_resize_workflow_processes_items_in_place(tmp_path):
    image_path = tmp_path / "large.jpg"
    Image.new("RGB", (3000, 2000), "white").save(image_path)
    storage = PortableStorage(tmp_path / "app")
    item = WorkItem(source_path=image_path)

    workflow = ResizeOnlyWorkflow(
        input_pipeline=InputPreparationPipeline(storage),
        resizer=ImageResizer(storage),
    )
    results = workflow.run([item])

    assert len(results) == 1
    assert results[0].status == WorkStatus.COMPLETED
    assert results[0].last_mode == ProcessingMode.RESIZE_ONLY
    assert results[0].current_path == image_path
    with Image.open(results[0].current_path) as resized:
        assert resized.size == (1920, 1280)
    assert results[0].cached_source_path == storage.temp_dir / "originals" / "large.jpg"
    with Image.open(results[0].cached_source_path) as original:
        assert original.size == (3000, 2000)


def test_resize_workflow_caches_source_before_mutation(tmp_path):
    image_path = tmp_path / "large.jpg"
    Image.new("RGB", (3000, 2000), "white").save(image_path)
    storage = PortableStorage(tmp_path / "app")
    item = WorkItem(source_path=image_path, item_id="resize001")

    workflow = ResizeOnlyWorkflow(
        input_pipeline=InputPreparationPipeline(storage),
        resizer=ImageResizer(storage),
    )
    results = workflow.run([item])

    assert results[0].cached_source_path == storage.temp_dir / "originals" / "large.jpg"
    assert results[0].cached_source_path.exists()
    with Image.open(results[0].cached_source_path) as cached:
        assert cached.size == (3000, 2000)


def test_resize_workflow_creates_output_only_after_resizer_finishes(tmp_path):
    class AssertingResizer:
        def __init__(self, source_path: Path) -> None:
            self.source_path = source_path

        def resize_in_place(self, image_path: Path) -> ResizeResult:
            assert image_path != self.source_path
            assert self.source_path.read_bytes() == b"original"
            image_path.write_bytes(b"processed")
            return ResizeResult(
                input_path=image_path,
                output_path=image_path,
                original_size=(100, 100),
                final_size=(100, 100),
                resized=False,
                converted_to_jpg=False,
            )

    image_path = tmp_path / "scan.jpg"
    output_path = tmp_path / "scan.jpg"
    image_path.write_bytes(b"original")
    storage = PortableStorage(tmp_path / "app")

    workflow = ResizeOnlyWorkflow(
        input_pipeline=InputPreparationPipeline(storage),
        resizer=AssertingResizer(output_path),
    )
    results = workflow.run([WorkItem(source_path=image_path)])

    assert results[0].status == WorkStatus.COMPLETED
    assert results[0].current_path == output_path
    assert output_path.read_bytes() == b"processed"


def test_resize_workflow_notifies_output_folder_after_finalize(tmp_path, monkeypatch):
    from doc_auto.services import resize_workflow as workflow_module

    class AssertingResizer:
        def resize_in_place(self, image_path: Path) -> ResizeResult:
            image_path.write_bytes(b"processed")
            return ResizeResult(
                input_path=image_path,
                output_path=image_path,
                original_size=(100, 100),
                final_size=(100, 100),
                resized=False,
                converted_to_jpg=False,
            )

    image_path = tmp_path / "scan.jpg"
    image_path.write_bytes(b"original")
    storage = PortableStorage(tmp_path / "app")
    notified: list[Path] = []
    monkeypatch.setattr(workflow_module, "notify_path_changed", lambda path: notified.append(Path(path)))
    workflow = ResizeOnlyWorkflow(
        input_pipeline=InputPreparationPipeline(storage),
        resizer=AssertingResizer(),
    )

    workflow.run([WorkItem(source_path=image_path)])

    assert tmp_path in notified


def test_resize_workflow_reports_readable_progress_text(tmp_path):
    image_path = tmp_path / "large.jpg"
    Image.new("RGB", (3000, 2000), "white").save(image_path)
    storage = PortableStorage(tmp_path / "app")
    events: list[tuple[int, str]] = []

    workflow = ResizeOnlyWorkflow(
        input_pipeline=InputPreparationPipeline(storage),
        resizer=ImageResizer(storage),
    )
    results = workflow.run(
        [WorkItem(source_path=image_path)],
        progress_callback=lambda percent, text: events.append((percent, text)),
    )

    assert results[0].status == WorkStatus.COMPLETED
    progress_text = " ".join(text for _percent, text in events)
    assert "원본 준비" in progress_text
    assert "리사이징" in progress_text
    assert "저장" in progress_text
    assert not any(token in progress_text for token in ["?먮", "?", "由ъ"])


def test_resize_workflow_marks_failed_items(tmp_path):
    missing = tmp_path / "missing.jpg"
    item = WorkItem(source_path=missing)
    storage = PortableStorage(tmp_path / "app")

    workflow = ResizeOnlyWorkflow(
        input_pipeline=InputPreparationPipeline(storage),
        resizer=ImageResizer(storage),
    )
    results = workflow.run([item])

    assert len(results) == 1
    assert results[0].status == WorkStatus.FAILED
    assert results[0].last_mode == ProcessingMode.RESIZE_ONLY


def test_resize_workflow_stops_before_preparing_when_cancelled(tmp_path):
    class CountingInputPipeline(InputPreparationPipeline):
        def __init__(self, storage: PortableStorage) -> None:
            super().__init__(storage)
            self.calls = 0

        def prepare(self, paths):
            self.calls += 1
            return super().prepare(paths)

    image_path = tmp_path / "large.jpg"
    Image.new("RGB", (3000, 2000), "white").save(image_path)
    storage = PortableStorage(tmp_path / "app")
    input_pipeline = CountingInputPipeline(storage)
    cancel_event = threading.Event()
    cancel_event.set()
    workflow = ResizeOnlyWorkflow(
        input_pipeline=input_pipeline,
        resizer=ImageResizer(storage),
    )

    results = workflow.run([WorkItem(source_path=image_path)], cancel_event=cancel_event)

    assert input_pipeline.calls == 0
    assert results[0].status == WorkStatus.STOPPED
    assert results[0].detail == "stopped"

