from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Iterable
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Callable
import uuid

from doc_auto.domain.job import WorkItem, WorkStatus
from doc_auto.domain.options import ProcessingMode
from doc_auto.services.image_pipeline import IdentityImagePipeline
from doc_auto.services.input_preparation import PreparedInput
from doc_auto.services.interfaces import HwpPdfService, ImageNormalizer, ImageResizeService, InputPreparer
from doc_auto.services.pdf_workflow import HwpPdfConverter
from doc_auto.services.file_replace import replace_file_with_retry
from doc_auto.services.shell_notify import notify_path_changed


@dataclass(frozen=True)
class _PreparedWork:
    prepared: PreparedInput
    item: WorkItem


@dataclass(frozen=True)
class _ResultSlot:
    task_index: int | None = None
    item: WorkItem | None = None


class DocumentCleanupWorkflow:
    def __init__(
        self,
        *,
        input_pipeline: InputPreparer,
        image_pipeline: ImageNormalizer | None = None,
        resizer: ImageResizeService | None = None,
        max_workers: int | None = None,
        delete_source_extensions: set[str] | None = None,
        source_deleter: Callable[[Path], None] | None = None,
        hwp_converter: HwpPdfService | None = None,
    ) -> None:
        self.input_pipeline = input_pipeline
        self.image_pipeline = image_pipeline or IdentityImagePipeline()
        self.resizer = resizer
        self.max_workers = self._worker_count(max_workers)
        self.delete_source_extensions = {suffix.lower() for suffix in (delete_source_extensions or set())}
        self.source_deleter = source_deleter
        self.hwp_converter = hwp_converter or HwpPdfConverter()

    def run(
        self,
        items: Iterable[WorkItem],
        *,
        cancel_event: Any | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> list[WorkItem]:
        source_items = list(items)
        tasks: list[_PreparedWork] = []
        slots: list[_ResultSlot] = []
        total_sources = max(1, len(source_items))
        for source_index, item in enumerate(source_items, start=1):
            item.last_mode = ProcessingMode.DOCUMENT_CLEANUP
            if self._cancel_requested(cancel_event):
                slots.append(_ResultSlot(item=self._stopped(item)))
                continue
            try:
                self._emit_progress(
                    progress_callback,
                    self._preparation_percent(source_index, total_sources),
                    f"준비 중 · {source_index}/{total_sources} · {item.original_name}",
                )
                prepared_inputs = self.input_pipeline.prepare_items([item])
            except Exception as exc:
                item.status = WorkStatus.FAILED
                item.detail = f"{type(exc).__name__}: {exc}"
                slots.append(_ResultSlot(item=item))
                continue

            if not prepared_inputs:
                item.status = WorkStatus.FAILED
                item.detail = "no supported input"
                slots.append(_ResultSlot(item=item))
                continue

            for index, prepared in enumerate(prepared_inputs):
                target_item = item if index == 0 else WorkItem(source_path=prepared.source_path)
                target_item.last_mode = ProcessingMode.DOCUMENT_CLEANUP
                target_item.cached_source_path = prepared.restore_path
                task_index = len(tasks)
                tasks.append(_PreparedWork(prepared=prepared, item=target_item))
                slots.append(_ResultSlot(task_index=task_index))

        if tasks:
            self._emit_progress(progress_callback, 15, f"준비 완료 · {len(tasks)}개")
        task_results = self._run_prepared_tasks(tasks, cancel_event=cancel_event, progress_callback=progress_callback)
        self._delete_completed_source_containers(tasks, task_results)
        results: list[WorkItem] = []
        for slot in slots:
            if slot.item is not None:
                results.append(slot.item)
            elif slot.task_index is not None:
                results.append(task_results[slot.task_index])
        return results

    def _delete_completed_source_containers(self, tasks: list[_PreparedWork], task_results: list[WorkItem]) -> None:
        if self.source_deleter is None or not self.delete_source_extensions:
            return
        source_tasks: dict[Path, list[int]] = {}
        for index, task in enumerate(tasks):
            source = Path(task.prepared.delete_source_path or task.prepared.source_path)
            if source.suffix.lower() not in self.delete_source_extensions:
                continue
            source_tasks.setdefault(source, []).append(index)
        for source, indices in source_tasks.items():
            if not source.exists():
                continue
            if not all(task_results[index].status == WorkStatus.COMPLETED for index in indices):
                continue
            try:
                self.source_deleter(source)
                notify_path_changed(source.parent)
            except OSError:
                continue

    def _run_prepared_tasks(
        self,
        tasks: list[_PreparedWork],
        *,
        cancel_event: Any | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> list[WorkItem]:
        if not tasks:
            return []
        progress_total = max(1, len(tasks) * 3)
        progress_done = 0
        progress_lock = threading.Lock()

        def make_step(task_number: int, item_name: str) -> Callable[[str], None]:
            def step(stage: str) -> None:
                nonlocal progress_done
                with progress_lock:
                    progress_done += 1
                    percent = min(95, max(15, 15 + int(progress_done / progress_total * 80)))
                self._emit_progress(
                    progress_callback,
                    percent,
                    f"처리 중 · {task_number}/{len(tasks)} · {item_name} · {stage}",
                )

            return step

        def task_name(task: _PreparedWork) -> str:
            path = Path(task.prepared.output_path or task.prepared.path)
            return path.name

        def step_for(index: int, task: _PreparedWork) -> Callable[[str], None]:
            return make_step(index + 1, task_name(task))

        worker_count = min(self.max_workers, len(tasks))
        if worker_count <= 1:
            return [
                self._process_prepared(task, cancel_event=cancel_event, progress_step=step_for(index, task))
                for index, task in enumerate(tasks)
            ]

        results: list[WorkItem | None] = [None] * len(tasks)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    self._process_prepared,
                    task,
                    cancel_event=cancel_event,
                    progress_step=step_for(index, task),
                ): index
                for index, task in enumerate(tasks)
            }
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        return [item for item in results if item is not None]

    @staticmethod
    def _worker_count(max_workers: int | None) -> int:
        if max_workers is None:
            return max(1, min(4, os.cpu_count() or 4))
        return max(1, int(max_workers))

    def _process_prepared(
        self,
        task: _PreparedWork,
        *,
        cancel_event: Any | None = None,
        progress_step: Callable[[str], None] | None = None,
    ) -> WorkItem:
        target_item = task.item
        work_path: Path | None = None
        if self._cancel_requested(cancel_event):
            return self._stopped(target_item)
        try:
            timings: list[str] = []
            if task.prepared.kind == "hwp":
                output_path = self._hwp_output_path(task.prepared)
                conversion = self.hwp_converter.convert_to_pdf(
                    task.prepared.path,
                    output_path,
                    permission_hwp_path=task.prepared.source_path,
                )
                target_item.current_path = conversion.output_path
                notify_path_changed(Path(conversion.output_path).parent)
                target_item.status = WorkStatus.COMPLETED
                target_item.page_count = conversion.page_count
                target_item.detail = f"hwp_pdf_pages={conversion.page_count}"
                self._emit_step(progress_step, "HWP 변환")
                self._emit_step(progress_step, "저장")
                return target_item

            if task.prepared.kind != "image":
                final_path = self._copy_prepared_output(task.prepared)
                target_item.current_path = final_path
                target_item.status = WorkStatus.COMPLETED
                target_item.detail = "copied"
                self._emit_step(progress_step, "저장")
                return target_item

            work_path = self._create_temp_work_file(task.prepared)
            normalized = self.image_pipeline.normalize(work_path)
            timings.extend(self._format_pipeline_stages(normalized.stages))
            self._emit_step(progress_step, "보정")
            if self._cancel_requested(cancel_event):
                target_item.current_path = normalized.path
                return self._stopped(target_item)

            output_path = normalized.path
            if self.resizer is not None:
                resize_start = time.perf_counter()
                resize_result = self.resizer.resize_in_place(output_path)
                output_path = resize_result.output_path
                timings.append(f"resize={time.perf_counter() - resize_start:.2f}s")
            self._emit_step(progress_step, "리사이징")

            final_path = self._finalize_output(task.prepared, output_path)
            timings.append("finalize=0.00s")
            target_item.current_path = final_path
            target_item.status = WorkStatus.COMPLETED
            target_item.detail = self._detail_with_timings("processed", timings)
            self._emit_step(progress_step, "저장")
        except Exception as exc:
            target_item.status = WorkStatus.FAILED
            target_item.detail = f"{type(exc).__name__}: {exc}"
        finally:
            if work_path is not None and work_path.exists() and work_path != task.prepared.path:
                work_path.unlink(missing_ok=True)
        return target_item

    @classmethod
    def _create_temp_work_file(cls, prepared: PreparedInput) -> Path:
        source = Path(prepared.path)
        target = cls._unique_path(source.with_name(f".work_{uuid.uuid4().hex}{source.suffix}"))
        shutil.copy2(source, target)
        return target

    def _finalize_output(self, prepared: PreparedInput, work_path: Path) -> Path:
        output_path = Path(prepared.output_path) if prepared.output_path is not None else Path(work_path)
        if output_path.suffix.lower() != Path(work_path).suffix.lower():
            output_path = output_path.with_suffix(Path(work_path).suffix)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        replace_file_with_retry(work_path, output_path)
        original_output = Path(prepared.output_path) if prepared.output_path is not None else output_path
        if original_output != output_path and original_output.exists():
            original_output.unlink(missing_ok=True)
            notify_path_changed(original_output.parent)
        notify_path_changed(output_path.parent)
        return output_path

    def _copy_prepared_output(self, prepared: PreparedInput) -> Path:
        source = Path(prepared.path)
        output_path = Path(prepared.output_path) if prepared.output_path is not None else source
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self._same_file(source, output_path):
            return output_path
        shutil.copy2(source, output_path)
        notify_path_changed(output_path.parent)
        return output_path

    @staticmethod
    def _hwp_output_path(prepared: PreparedInput) -> Path:
        output_path = Path(prepared.output_path) if prepared.output_path is not None else Path(prepared.path)
        return output_path.with_suffix(".pdf")

    @staticmethod
    def _same_file(first: Path, second: Path) -> bool:
        try:
            return first.resolve() == second.resolve()
        except OSError:
            return first.absolute() == second.absolute()

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        for index in range(1, 1000):
            candidate = path.with_name(f"{path.stem}_{index:02d}{path.suffix}")
            if not candidate.exists():
                return candidate
        raise FileExistsError(f"Unable to allocate work path for {path}")

    @staticmethod
    def _format_pipeline_stages(stages) -> list[str]:
        return [f"{stage.name}={stage.elapsed_seconds:.2f}s" for stage in stages]

    @staticmethod
    def _preparation_percent(index: int, total: int) -> int:
        if total <= 1:
            return 1
        return min(14, max(1, 1 + int((index - 1) / total * 14)))

    @staticmethod
    def _detail_with_timings(detail: str, timings: list[str]) -> str:
        if not timings:
            return detail
        return f"{detail}; " + " / ".join(timings)

    @staticmethod
    def _emit_progress(
        progress_callback: Callable[[int, str], None] | None,
        percent: int,
        text: str,
    ) -> None:
        if progress_callback is not None:
            progress_callback(percent, text)

    @staticmethod
    def _emit_step(progress_step: Callable[[str], None] | None, text: str) -> None:
        if progress_step is not None:
            progress_step(text)

    @staticmethod
    def _cancel_requested(cancel_event: Any | None) -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    @staticmethod
    def _stopped(item: WorkItem) -> WorkItem:
        item.status = WorkStatus.STOPPED
        item.detail = "stopped"
        return item
