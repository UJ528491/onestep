from __future__ import annotations

from collections.abc import Iterable
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Callable

from doc_auto.domain.job import WorkItem, WorkStatus
from doc_auto.domain.options import ProcessingMode
from doc_auto.services.interfaces import HwpPdfService, InputPreparer, PdfBuildService
from doc_auto.services.pdf_converter import PdfConversionResult
from doc_auto.services.recycle_bin import move_to_recycle_bin
from doc_auto.services.runtime_paths import worker_command
from doc_auto.services.shell_notify import notify_path_changed


class HwpPdfConverter:
    def convert_to_pdf(
        self,
        hwp_path: Path,
        output_path: Path,
        *,
        permission_hwp_path: Path | None = None,
    ) -> PdfConversionResult:
        hwp_path = Path(hwp_path)
        output_path = Path(output_path)
        permission_hwp_path = Path(permission_hwp_path) if permission_hwp_path is not None else hwp_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            creationflags = 0x08000000

        last_error = ""
        with tempfile.TemporaryDirectory(prefix="hwp_pdf_") as work_dir_name:
            work_dir = Path(work_dir_name)
            worker_hwp = work_dir / "source.hwp"
            worker_pdf = work_dir / "output.pdf"
            target_json = work_dir / "result.json"
            shutil.copy2(hwp_path, worker_hwp)
            for attempt in range(1, 3):
                target_json.unlink(missing_ok=True)
                worker_pdf.unlink(missing_ok=True)
                try:
                    completed = subprocess.run(
                        worker_command(
                            "--hwp-pdf-worker",
                            str(worker_hwp.resolve()),
                            str(worker_pdf.resolve()),
                            str(target_json.resolve()),
                            str(permission_hwp_path.resolve()),
                        ),
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=600,
                        startupinfo=startupinfo,
                        creationflags=creationflags,
                    )
                    if completed.returncode != 0:
                        last_error = completed.stderr.strip() or completed.stdout.strip() or f"worker returncode {completed.returncode}"
                    pdf = self._worker_pdf_result(worker_pdf, target_json)
                    if pdf is not None:
                        self._copy_pdf_result(pdf, output_path)
                        return PdfConversionResult(output_path=output_path, source_paths=[hwp_path], page_count=1)
                    if not last_error:
                        last_error = "HWP PDF worker produced no PDF file"
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
            raise RuntimeError(f"HWP PDF conversion failed: {last_error}")

    @staticmethod
    def _worker_pdf_result(worker_pdf: Path, target_json: Path) -> Path | None:
        candidates = [worker_pdf]
        if target_json.exists():
            data = json.loads(target_json.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                candidates.insert(0, Path(data.get("pdf", worker_pdf)))
        for candidate in candidates:
            candidate = Path(candidate)
            if candidate.exists() and candidate.stat().st_size > 0:
                return candidate
        return None

    @staticmethod
    def _copy_pdf_result(source: Path, target: Path) -> None:
        source = Path(source)
        target = Path(target)
        try:
            if source.resolve() == target.resolve():
                return
        except OSError:
            if source.absolute() == target.absolute():
                return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        notify_path_changed(target.parent)


class PdfConversionWorkflow:
    def __init__(
        self,
        *,
        input_pipeline: InputPreparer,
        converter: PdfBuildService,
        hwp_converter: HwpPdfService | None = None,
        source_deleter: Callable[[Path], None] | None = None,
    ) -> None:
        self.input_pipeline = input_pipeline
        self.converter = converter
        self.hwp_converter = hwp_converter or HwpPdfConverter()
        self.source_deleter = source_deleter or move_to_recycle_bin

    def convert_individual(
        self,
        items: Iterable[WorkItem],
        *,
        cancel_event: Any | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
        delete_source_on_success: bool = False,
    ) -> list[WorkItem]:
        results: list[WorkItem] = []
        item_list = list(items)
        total = max(1, len(item_list) * 2)
        done = 0

        def step(text: str) -> None:
            nonlocal done
            done += 1
            if progress_callback is not None:
                progress_callback(min(99, int(done / total * 100)), text)

        for item in item_list:
            item.last_mode = ProcessingMode.PDF_CONVERT
            delete_target = self._delete_target_for_item(item)
            if self._cancel_requested(cancel_event):
                results.append(self._stopped(item))
                continue
            try:
                prepared = self.input_pipeline.prepare_items([item])
                step(f"원본 준비 {item.original_name}")
                if self._cancel_requested(cancel_event):
                    results.append(self._stopped(item))
                    continue
                conversions: list[PdfConversionResult] = []
                for prepared_item in prepared:
                    suffix = Path(prepared_item.path).suffix.lower()
                    if prepared_item.kind == "hwp" or suffix == ".hwp":
                        conversions.append(
                            self.hwp_converter.convert_to_pdf(
                                prepared_item.path,
                                self._individual_output_path(item, prepared_item).with_suffix(".pdf"),
                                permission_hwp_path=prepared_item.source_path,
                            )
                        )
                    elif prepared_item.kind == "image":
                        conversions.append(
                            self.converter.convert_single_to(
                                prepared_item.path,
                                self._individual_output_path(item, prepared_item),
                            )
                        )
                step(f"PDF 변환 {item.original_name}")
                if not conversions:
                    item.status = WorkStatus.FAILED
                    item.detail = "no image input"
                    results.append(item)
                    continue
                for index, conversion in enumerate(conversions):
                    target_item = item if index == 0 else WorkItem(source_path=conversion.source_paths[0])
                    target_item.current_path = conversion.output_path
                    notify_path_changed(Path(conversion.output_path).parent)
                    target_item.status = WorkStatus.COMPLETED
                    target_item.last_mode = ProcessingMode.PDF_CONVERT
                    target_item.page_count = conversion.page_count
                    target_item.detail = f"pdf_pages={conversion.page_count}"
                    results.append(target_item)
                if delete_source_on_success:
                    self._delete_source_path(delete_target)
            except Exception as exc:
                item.status = WorkStatus.FAILED
                item.detail = f"{type(exc).__name__}: {exc}"
                results.append(item)
        return results

    def convert_bundle(
        self,
        items: Iterable[WorkItem],
        output_path: Path,
        *,
        cancel_event: Any | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
        delete_source_on_success: bool = False,
    ) -> PdfConversionResult:
        images: list[Path] = []
        item_list = self._ordered_bundle_items(list(items))
        total = max(1, len(item_list) + 1)
        done = 0

        def step(text: str) -> None:
            nonlocal done
            done += 1
            if progress_callback is not None:
                progress_callback(min(99, int(done / total * 100)), text)

        for item in item_list:
            item.last_mode = ProcessingMode.PDF_BUNDLE
            if self._cancel_requested(cancel_event):
                raise InterruptedError("stopped")
            prepared = self.input_pipeline.prepare_items([item])
            step(f"원본 준비 {item.original_name}")
            if self._cancel_requested(cancel_event):
                raise InterruptedError("stopped")
            images.extend(prepared_item.path for prepared_item in prepared if prepared_item.kind == "image")
        result = self.converter.convert_bundle(images, output_path)
        step("PDF 묶음 저장")
        if delete_source_on_success:
            for item in item_list:
                self._delete_item_source(item, output_path=result.output_path)
        notify_path_changed(Path(result.output_path).parent)
        return result

    @staticmethod
    def _individual_output_path(item: WorkItem, prepared_item) -> Path:
        if Path(prepared_item.source_path) == Path(item.source_path):
            return Path(item.source_path).with_suffix(".pdf")
        if prepared_item.output_path is not None:
            return Path(prepared_item.output_path).with_suffix(".pdf")
        return Path(prepared_item.path).with_suffix(".pdf")

    @staticmethod
    def _cancel_requested(cancel_event: Any | None) -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    @staticmethod
    def _ordered_bundle_items(items: list[WorkItem]) -> list[WorkItem]:
        if not items:
            return []
        group_ids = {item.bundle_group_id for item in items}
        if len(group_ids) == 1 and None not in group_ids and all(item.page_index is not None for item in items):
            return sorted(items, key=lambda item: int(item.page_index or 0))
        return items

    def _delete_item_source(self, item: WorkItem, *, output_path: Path | None = None) -> None:
        target = self._delete_target_for_item(item)
        self._delete_source_path(target, output_path=output_path)

    def _delete_source_path(self, target: Path | None, *, output_path: Path | None = None) -> None:
        if target is None or not target.exists():
            return
        if output_path is not None and self._same_path(target, output_path):
            return
        self.source_deleter(target)
        notify_path_changed(target.parent)

    @staticmethod
    def _delete_target_for_item(item: WorkItem) -> Path | None:
        if item.current_path is not None and Path(item.current_path).exists():
            return Path(item.current_path)
        if item.archive_member_name:
            return None
        if item.source_path.exists():
            return Path(item.source_path)
        return None

    @staticmethod
    def _same_path(left: Path, right: Path) -> bool:
        try:
            return left.resolve() == right.resolve()
        except OSError:
            return left.absolute() == right.absolute()

    @staticmethod
    def _stopped(item: WorkItem) -> WorkItem:
        item.status = WorkStatus.STOPPED
        item.detail = "stopped"
        return item
