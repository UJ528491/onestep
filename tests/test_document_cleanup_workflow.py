from pathlib import Path
import threading

from PIL import Image

from doc_auto.domain.job import WorkItem, WorkStatus
from doc_auto.domain.options import ProcessingMode
from doc_auto.services.document_cleanup_workflow import DocumentCleanupWorkflow
from doc_auto.services.image_pipeline import ImagePipelineResult
from doc_auto.services.image_resizer import ImageResizer, ResizeResult
from doc_auto.services.input_preparation import InputPreparationPipeline, PreparedInput
from doc_auto.services.pdf_converter import PdfConversionResult
from doc_auto.services.temp_storage import PortableStorage


class IdentityNormalizer:
    def normalize(self, image_path: Path) -> ImagePipelineResult:
        return ImagePipelineResult(path=Path(image_path), changed=False, detail="identity")


class NoopResizer:
    def resize_in_place(self, image_path: Path) -> ResizeResult:
        return ResizeResult(
            input_path=image_path,
            output_path=image_path,
            original_size=(100, 100),
            final_size=(100, 100),
            resized=False,
            converted_to_jpg=False,
        )


def test_document_cleanup_workflow_processes_image_without_classification_or_renaming(tmp_path):
    image_path = tmp_path / "scan.jpg"
    Image.new("RGB", (3000, 2000), "white").save(image_path)
    storage = PortableStorage(tmp_path / "app")

    workflow = DocumentCleanupWorkflow(
        input_pipeline=InputPreparationPipeline(storage),
        image_pipeline=IdentityNormalizer(),
        resizer=ImageResizer(storage),
    )
    results = workflow.run([WorkItem(source_path=image_path)])

    assert len(results) == 1
    assert results[0].status == WorkStatus.COMPLETED
    assert results[0].last_mode == ProcessingMode.DOCUMENT_CLEANUP
    assert results[0].current_path == image_path
    assert results[0].cached_source_path == storage.temp_dir / "originals" / "scan.jpg"
    with Image.open(image_path) as resized:
        assert resized.size == (1920, 1280)
    with Image.open(results[0].cached_source_path) as original:
        assert original.size == (3000, 2000)


def test_document_cleanup_workflow_creates_output_only_after_pipeline_finishes(tmp_path):
    class AssertingNormalizer:
        def __init__(self, source_path: Path) -> None:
            self.source_path = source_path

        def normalize(self, image_path: Path) -> ImagePipelineResult:
            assert image_path != self.source_path
            assert self.source_path.read_bytes() == b"original"
            image_path.write_bytes(b"normalized")
            return ImagePipelineResult(path=image_path, changed=True, detail="normalized")

    class AssertingResizer:
        def resize_in_place(self, image_path: Path) -> ResizeResult:
            assert image_path.read_bytes() == b"normalized"
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
    workflow = DocumentCleanupWorkflow(
        input_pipeline=InputPreparationPipeline(storage),
        image_pipeline=AssertingNormalizer(image_path),
        resizer=AssertingResizer(),
    )

    results = workflow.run([WorkItem(source_path=image_path)])

    assert results[0].status == WorkStatus.COMPLETED
    assert results[0].current_path == image_path
    assert image_path.read_bytes() == b"processed"


def test_document_cleanup_workflow_converts_hwp_with_local_converter(tmp_path):
    class FakeHwpConverter:
        def convert_to_pdf(self, hwp_path: Path, output_path: Path, *, permission_hwp_path: Path | None = None):
            output_path.write_bytes(b"%PDF")
            return PdfConversionResult(output_path=output_path, source_paths=[hwp_path], page_count=1)

    hwp_path = tmp_path / "claim.hwp"
    hwp_path.write_bytes(b"hwp")
    storage = PortableStorage(tmp_path / "app")
    workflow = DocumentCleanupWorkflow(
        input_pipeline=InputPreparationPipeline(storage),
        hwp_converter=FakeHwpConverter(),
    )

    results = workflow.run([WorkItem(source_path=hwp_path)])

    assert results[0].status == WorkStatus.COMPLETED
    assert results[0].current_path == hwp_path.with_suffix(".pdf")
    assert results[0].detail == "hwp_pdf_pages=1"


def test_document_cleanup_workflow_deletes_completed_source_container(tmp_path):
    image_path = tmp_path / "scan.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path)
    deleted: list[Path] = []
    storage = PortableStorage(tmp_path / "app")
    workflow = DocumentCleanupWorkflow(
        input_pipeline=InputPreparationPipeline(storage),
        image_pipeline=IdentityNormalizer(),
        delete_source_extensions={".jpg"},
        source_deleter=lambda path: deleted.append(Path(path)),
    )

    workflow.run([WorkItem(source_path=image_path)])

    assert deleted == [image_path]


def test_document_cleanup_workflow_stops_before_preparing_when_cancelled(tmp_path):
    image_path = tmp_path / "scan.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path)
    storage = PortableStorage(tmp_path / "app")
    cancel_event = threading.Event()
    cancel_event.set()
    workflow = DocumentCleanupWorkflow(input_pipeline=InputPreparationPipeline(storage))

    results = workflow.run([WorkItem(source_path=image_path)], cancel_event=cancel_event)

    assert results[0].status == WorkStatus.STOPPED
    assert results[0].detail == "stopped"


def test_document_cleanup_workflow_reports_preparation_and_weighted_processing_progress(tmp_path):
    class MultiPageInputPipeline:
        def __init__(self, pages: int) -> None:
            self.pages = pages

        def prepare_items(self, _items):
            prepared = []
            for index in range(1, self.pages + 1):
                page = tmp_path / f"doc_{index:03d}.png"
                page.write_bytes(b"page")
                prepared.append(
                    PreparedInput(
                        path=page,
                        source_path=tmp_path / "doc.pdf",
                        kind="image",
                        restore_path=page,
                        output_path=tmp_path / f"doc_{index:03d}.png",
                    )
                )
            return prepared

    events: list[tuple[int, str]] = []
    workflow = DocumentCleanupWorkflow(
        input_pipeline=MultiPageInputPipeline(3),
        image_pipeline=IdentityNormalizer(),
        resizer=NoopResizer(),
        max_workers=1,
    )

    workflow.run(
        [WorkItem(source_path=tmp_path / "doc.pdf")],
        progress_callback=lambda percent, text: events.append((percent, text)),
    )

    assert events[0] == (1, "준비 중 · 1/1 · doc.pdf")
    assert events[1] == (15, "준비 완료 · 3개")
    assert any("처리 중 · 1/3 · doc_001.png · 보정" in text for _, text in events)
    assert any("처리 중 · 3/3 · doc_003.png · 저장" in text for _, text in events)
    processing_percents = [percent for percent, text in events if text.startswith("처리 중")]
    assert processing_percents == sorted(processing_percents)
    assert min(processing_percents) >= 15
    assert max(processing_percents) <= 95
