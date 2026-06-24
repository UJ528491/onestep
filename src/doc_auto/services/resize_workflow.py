from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import shutil
from typing import Any, Callable
import uuid

from doc_auto.domain.job import WorkItem, WorkStatus
from doc_auto.domain.options import ProcessingMode
from doc_auto.services.interfaces import ImageResizeService, InputPreparer
from doc_auto.services.file_replace import replace_file_with_retry
from doc_auto.services.shell_notify import notify_path_changed


class ResizeOnlyWorkflow:
    def __init__(
        self,
        *,
        input_pipeline: InputPreparer,
        resizer: ImageResizeService,
    ) -> None:
        self.input_pipeline = input_pipeline
        self.resizer = resizer

    def run(
        self,
        items: Iterable[WorkItem],
        *,
        cancel_event: Any | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> list[WorkItem]:
        results: list[WorkItem] = []
        item_list = list(items)
        total = max(1, len(item_list) * 3)
        done = 0

        def step(text: str) -> None:
            nonlocal done
            done += 1
            if progress_callback is not None:
                progress_callback(min(99, int(done / total * 100)), text)

        for item in item_list:
            item.last_mode = ProcessingMode.RESIZE_ONLY
            if self._cancel_requested(cancel_event):
                results.append(self._stopped(item))
                continue
            try:
                prepared_inputs = self.input_pipeline.prepare_items([item])
                step(f"원본 준비 {item.original_name}")
                if not prepared_inputs:
                    item.status = WorkStatus.FAILED
                    item.detail = "no supported image input"
                    results.append(item)
                    continue
                for index, prepared in enumerate(prepared_inputs):
                    if self._cancel_requested(cancel_event):
                        target_item = item if index == 0 else WorkItem(source_path=prepared.source_path)
                        target_item.last_mode = ProcessingMode.RESIZE_ONLY
                        results.append(self._stopped(target_item))
                        continue
                    target_item = item if index == 0 else WorkItem(source_path=prepared.source_path)
                    target_item.cached_source_path = prepared.restore_path
                    work_path = self._create_temp_work_file(prepared.path)
                    result = self.resizer.resize_in_place(work_path)
                    step(f"리사이징 {target_item.original_name}")
                    target_item.current_path = self._finalize_output(prepared.output_path, result.output_path)
                    target_item.status = WorkStatus.COMPLETED
                    target_item.last_mode = ProcessingMode.RESIZE_ONLY
                    target_item.detail = self._detail(result.resized, result.converted_to_jpg)
                    step(f"저장 {target_item.current_name}")
                    results.append(target_item)
                    self._cleanup_work_file(result.output_path, prepared.path)
            except Exception as exc:
                item.status = WorkStatus.FAILED
                item.detail = f"{type(exc).__name__}: {exc}"
                results.append(item)
        return results

    @staticmethod
    def _detail(resized: bool, converted_to_jpg: bool) -> str:
        details = []
        if resized:
            details.append("resized")
        if converted_to_jpg:
            details.append("png_to_jpg")
        return ", ".join(details) if details else "unchanged"

    @staticmethod
    def _cancel_requested(cancel_event: Any | None) -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    @staticmethod
    def _stopped(item: WorkItem) -> WorkItem:
        item.status = WorkStatus.STOPPED
        item.detail = "stopped"
        return item

    @staticmethod
    def _create_temp_work_file(source: Path) -> Path:
        source = Path(source)
        target = ResizeOnlyWorkflow._unique_path(source.with_name(f".work_{uuid.uuid4().hex}{source.suffix}"))
        shutil.copy2(source, target)
        return target

    @staticmethod
    def _finalize_output(output_path: Path | None, work_path: Path) -> Path:
        work_path = Path(work_path)
        target = Path(output_path) if output_path is not None else work_path
        original_target = target
        if target.suffix.lower() != work_path.suffix.lower():
            target = target.with_suffix(work_path.suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        replace_file_with_retry(work_path, target)
        if original_target != target and original_target.exists():
            original_target.unlink(missing_ok=True)
            notify_path_changed(original_target.parent)
        notify_path_changed(target.parent)
        return target

    @staticmethod
    def _cleanup_work_file(work_path: Path, original_path: Path) -> None:
        work_path = Path(work_path)
        original_path = Path(original_path)
        if work_path.exists() and work_path != original_path:
            work_path.unlink(missing_ok=True)

    @staticmethod
    def _unique_path(path: Path) -> Path:
        for index in range(1, 1000):
            candidate = path.with_name(f"{path.stem}_{index:02d}{path.suffix}")
            if not candidate.exists():
                return candidate
        raise FileExistsError(f"Unable to allocate work path for {path}")
