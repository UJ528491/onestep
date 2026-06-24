from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Callable

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from doc_auto.branding import APP_NAME, WINDOW_TITLE
from doc_auto.domain.file_types import (
    ARCHIVE_EXTENSIONS,
    EDITABLE_IMAGE_EXTENSIONS,
    EXPANDED_CONTAINER_EXTENSIONS,
    HWP_EXTENSIONS,
    PDF_EXTENSIONS,
    TIFF_EXTENSIONS,
)
from doc_auto.domain.job import WorkItem, WorkStatus
from doc_auto.domain.options import ProcessingMode
from doc_auto.services.document_cleanup_workflow import DocumentCleanupWorkflow
from doc_auto.services.image_rotation import rotate_image_in_place
from doc_auto.services.image_pipeline import DocumentImagePipeline, ImageNormalizationOptions
from doc_auto.services.image_resizer import ImageResizer
from doc_auto.services.input_preparation import (
    ArchiveExtractor,
    ExistingPdfRenderer,
    InputPreparationPipeline,
)
from doc_auto.services.pdf_converter import PdfConverter
from doc_auto.services.pdf_workflow import PdfConversionWorkflow
from doc_auto.services.recycle_bin import move_to_recycle_bin
from doc_auto.services.resize_workflow import ResizeOnlyWorkflow
from doc_auto.services.settings_store import AppSettings, SettingsStore
from doc_auto.services.shell_notify import notify_path_changed
from doc_auto.services.source_cache import SourceCache
from doc_auto.services.temp_storage import PortableStorage
from doc_auto.services.work_list import WorkList
from doc_auto.ui.file_table import FileTableWidget
from doc_auto.ui.preview_panel import PreviewPanel
from doc_auto.ui.settings_dialog import SettingsDialog


PREVIEW_SYNC_DEBOUNCE_MS = 120
REMOVED_FILE_PICKER_BUTTON_TEXT = "파일/폴더 열기"


class _ElidedLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt override
        self._full_text = text
        self.setToolTip(text)
        self._refresh_elided_text()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._refresh_elided_text()

    def _refresh_elided_text(self) -> None:
        width = max(0, self.width() - 4)
        if width <= 0:
            QLabel.setText(self, self._full_text)
            return
        QLabel.setText(
            self,
            self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideMiddle, width),
        )


class MainWindow(QMainWindow):
    def __init__(self, app_root: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(980, 700)

        self.app_root = Path(app_root or Path.cwd())
        self._load_window_icon()
        self.storage = PortableStorage(self.app_root)
        self.settings_store = SettingsStore(self.storage)
        self.settings = self.settings_store.load()
        self._apply_storage_settings(self.settings)
        self.work_list = WorkList()
        self.started_at: float | None = None
        self.cancel_event = threading.Event()
        self.preview_panel: PreviewPanel | None = None
        self.preview_placeholder: QWidget | None = None
        self.preview_sidebar_width = 520
        self._preview_sidebar_minimum_width = 520
        self._resting_window_width = 0
        self._preview_sidebar_expanded = False
        self._active_future: Future | None = None
        self._active_executor: ThreadPoolExecutor | None = None
        self._active_finish: Callable[[Any], None] | None = None
        self._known_items_by_path: dict[str, WorkItem] = {}
        self._pdf_preview_cache: dict[str, list[Path]] = {}
        self._progress_lock = threading.Lock()
        self._progress_events: list[tuple[int, str]] = []
        self.tray_icon: QSystemTrayIcon | None = None
        self._preview_selection_drag_active = False
        self._preview_sync_queued = False
        self._removed_file_picker_button_width: int | None = None

        central = QWidget(self)
        self.setCentralWidget(central)
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.shell_layout = shell
        self.shell_splitter = QSplitter(Qt.Orientation.Horizontal, central)
        self.shell_splitter.setHandleWidth(7)
        self.shell_splitter.splitterMoved.connect(self._sync_shell_splitter_widths)
        shell.addWidget(self.shell_splitter)
        shell.setAlignment(self.shell_splitter, Qt.AlignmentFlag.AlignLeft)
        self.left_panel = QWidget(central)
        root = QVBoxLayout(self.left_panel)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        self.shell_splitter.addWidget(self.left_panel)
        self.shell_splitter.setStretchFactor(0, 1)
        self.shell_splitter.setCollapsible(0, False)

        self.toolbar_layout = QHBoxLayout()
        self.toolbar_layout.setSpacing(8)
        root.addLayout(self.toolbar_layout)

        self.pdf_button = self._button("PDF 변환", self._run_pdf_convert)
        self.pdf_bundle_button = self._button("PDF 묶음", self._run_pdf_bundle)
        self.settings_button = self._button("⚙", self._open_settings)
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.setToolTip("설정")
        self.settings_button.setFont(QFont("Segoe UI Symbol", 18))

        self.toolbar_buttons = (
            self.pdf_button,
            self.pdf_bundle_button,
            self.settings_button,
        )

        for button in self.toolbar_buttons[:-1]:
            self.toolbar_layout.addWidget(button)
        self.toolbar_layout.addStretch(1)
        self.toolbar_layout.addWidget(self.settings_button)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.file_table = FileTableWidget(self)
        self.file_table.paths_dropped.connect(self._drop_paths)
        self.file_table.delete_requested.connect(self._remove_items)
        self.file_table.open_requested.connect(self._open_item)
        self.file_table.fullscreen_requested.connect(self._toggle_preview_fullscreen)
        self.file_table.rotate_clockwise_requested.connect(lambda: self._rotate_selected(clockwise=True))
        self.file_table.selection_drag_started.connect(self._begin_preview_selection_drag)
        self.file_table.selection_drag_finished.connect(self._finish_preview_selection_drag)
        self.file_table.selection_changed.connect(lambda _items: self._schedule_preview_sync())
        self.splitter.addWidget(self.file_table)
        root.addWidget(self.splitter, 1)

        self.footer_layout = QVBoxLayout()
        self.footer_layout.setSpacing(6)
        root.addLayout(self.footer_layout)
        self.stage_label = _ElidedLabel("대기")
        self.stage_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.stage_label.setMinimumHeight(22)
        self.footer_controls_layout = QHBoxLayout()
        self.footer_controls_layout.setSpacing(10)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setMinimumHeight(22)
        self.progress.setMaximumHeight(22)
        self.progress.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.progress_percent_label = QLabel("0%")
        self.progress_percent_label.setFixedWidth(48)
        self.progress_percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.stage_time_label = QLabel("")
        self.stage_time_label.setFixedWidth(280)
        self.stage_time_label.hide()
        self.elapsed_label = QLabel("0.0초")
        self.elapsed_label.setFixedWidth(64)
        self.elapsed_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.elapsed_label.hide()
        self.start_stop_button = self._button("시작", self._start_or_stop)
        self.start_stop_button.setFixedWidth(112)
        self.footer_layout.addWidget(self.stage_label)
        self.footer_controls_layout.addWidget(self.progress, 1)
        self.footer_controls_layout.addWidget(self.progress_percent_label)
        self.footer_controls_layout.addWidget(self.start_stop_button)
        self.footer_layout.addLayout(self.footer_controls_layout)

        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._tick_elapsed)
        self.task_timer = QTimer(self)
        self.task_timer.setInterval(100)
        self.task_timer.timeout.connect(self._poll_active_task)
        self.preview_sync_timer = QTimer(self)
        self.preview_sync_timer.setSingleShot(True)
        self.preview_sync_timer.setInterval(PREVIEW_SYNC_DEBOUNCE_MS)
        self.preview_sync_timer.timeout.connect(self._flush_preview_sync)

        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f8fafc; color: #0f172a; }
            QLabel { color: #0f172a; }
            QPushButton {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 7px;
                padding: 8px 13px;
                color: #0f172a;
                min-width: 76px;
            }
            QPushButton:hover { background: #f1f5f9; }
            QPushButton:disabled { color: #94a3b8; background: #f8fafc; }
            QPushButton#settingsButton { min-width: 42px; max-width: 42px; padding: 0; }
            QTableWidget {
                background: #ffffff;
                alternate-background-color: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                gridline-color: #e2e8f0;
                selection-background-color: #dbeafe;
                selection-color: #0f172a;
            }
            QTableWidget::item { color: #0f172a; padding: 0 3px; }
            QHeaderView::section {
                background: #eef2f7;
                color: #111827;
                border: 0;
                padding: 8px 3px;
                font-weight: 600;
            }
            QProgressBar {
                border: 1px solid #cbd5e1;
                border-radius: 7px;
                background: #ffffff;
                min-height: 22px;
                max-height: 22px;
            }
            QProgressBar::chunk { background: #334155; border-radius: 6px; }
            #previewPanel {
                background: #f1f5f9;
                border: 1px solid #dbe3ee;
                border-radius: 8px;
            }
            """
        )
        self._sync_toolbar_button_metrics()
        self.start_stop_button.setFixedWidth(112)
        self.left_panel.setFixedWidth(self._list_area_width())
        self._resting_window_width = self._list_area_width()
        self.setMinimumWidth(self._list_area_width())
        self.resize(self.minimumWidth(), 700)

    def _button(self, text: str, callback) -> QPushButton:
        button = QPushButton(text)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(callback)
        return button

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if not hasattr(self, "left_panel"):
            return
        self.left_panel.setFixedWidth(self._list_area_width())
        if self._preview_sidebar_expanded:
            self._apply_shell_splitter_sizes()
            return
        self._resting_window_width = max(self._list_area_width(), self.width())

    def _load_window_icon(self) -> None:
        candidates: list[Path] = []
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.extend(
                [
                    exe_dir / "assets" / "onestep.ico",
                    Path(getattr(sys, "_MEIPASS", exe_dir)) / "assets" / "onestep.ico",
                ]
            )
        candidates.extend(
            [
                self.app_root / "assets" / "onestep.ico",
                Path(__file__).resolve().parents[3] / "assets" / "onestep.ico",
            ]
        )
        for icon_path in candidates:
            if not icon_path.exists():
                continue
            icon = QIcon(str(icon_path))
            if icon.isNull():
                continue
            self.setWindowIcon(icon)
            return

    def _sync_toolbar_button_metrics(self) -> None:
        button_height = self.pdf_button.sizeHint().height()
        self.settings_button.setFixedSize(42, button_height)

    def _set_resting_shell_alignment(self) -> None:
        self.shell_layout.setAlignment(self.shell_splitter, Qt.AlignmentFlag.AlignLeft)

    def _set_expanded_shell_alignment(self) -> None:
        self.shell_layout.setAlignment(self.shell_splitter, Qt.Alignment())

    def _toolbar_required_width(self) -> int:
        spacing = max(0, self.toolbar_layout.spacing())
        button_width = sum(button.sizeHint().width() for button in self.toolbar_buttons)
        margins = 32
        slack = 24
        return button_width + spacing * max(0, len(self.toolbar_buttons) - 1) + margins + slack

    def _list_area_width(self) -> int:
        return max(
            round(self._toolbar_required_width() * 1.2),
            round(self._previous_picker_toolbar_required_width() * 1.2),
        )

    def _previous_picker_toolbar_required_width(self) -> int:
        return self._toolbar_required_width() + self._removed_file_picker_width() + max(0, self.toolbar_layout.spacing())

    def _removed_file_picker_width(self) -> int:
        if self._removed_file_picker_button_width is None:
            self._removed_file_picker_button_width = QPushButton(REMOVED_FILE_PICKER_BUTTON_TEXT).sizeHint().width()
        return self._removed_file_picker_button_width

    def _list_area_minimum_width(self) -> int:
        return self._list_area_width()

    def _preview_sidebar_min_width(self) -> int:
        return self._preview_sidebar_minimum_width

    def _expanded_window_minimum_width(self, sidebar_width: int) -> int:
        return self._list_area_width() + self.shell_splitter.handleWidth() + max(self._preview_sidebar_min_width(), sidebar_width)

    def _default_window_width(self) -> int:
        return self.minimumWidth()

    def _drop_paths(self, paths: list[Path], *, auto_start: bool = True) -> None:
        if not paths:
            return
        if self._active_future is not None and not self._active_future.done():
            self.stage_label.setText("작업 진행 중")
            return
        try:
            self.storage.clear_temp()
        except (OSError, ValueError) as exc:
            self.stage_label.setText(f"temp clear failed: {type(exc).__name__}")
            return
        self._add_paths(paths, auto_start=auto_start)

    def _add_paths(self, paths: list[Path], *, auto_start: bool = False) -> None:
        if self._active_future is not None and not self._active_future.done():
            self.stage_label.setText("작업 진행 중")
            return
        added = self.work_list.replace_paths(paths)
        for item in added:
            self._hydrate_known_item(item)
        self.file_table.set_items(self.work_list.items)
        self.stage_label.setText(f"목록 추가: {len(added)}개")
        if added and auto_start:
            self._run_document_processing()

    def _remove_items(self, items: list[WorkItem]) -> None:
        self.work_list.remove_items(items)
        self.file_table.set_items(self.work_list.items)
        self._sync_preview_from_selection()
        self.stage_label.setText(f"목록 제거: {len(items)}개")

    def _open_item(self, item: WorkItem) -> None:
        self._open_path(item.current_path or item.source_path)

    @staticmethod
    def _open_path(path: Path) -> None:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
            return
        subprocess.Popen(["xdg-open", str(path)])

    def _rotate_selected(self, *, clockwise: bool = True) -> None:
        if not self._can_rotate_selected():
            self.stage_label.setText("회전할 파일 선택 없음")
            return
        selected = self.file_table.selected_items()
        rotated = 0
        for item in selected:
            path = self._preview_path_for_item(item)
            if path.suffix.lower() not in EDITABLE_IMAGE_EXTENSIONS or not path.exists():
                item.detail = "rotate_unavailable"
                continue
            rotate_image_in_place(path, clockwise=clockwise, temp_dir=self.storage.temp_dir / "originals")
            item.current_path = path
            rotated += 1
        self.file_table.refresh_items(self.work_list.items)
        self._sync_preview_from_selection()
        if rotated and self.preview_panel is not None:
            self.preview_panel.refresh_current_previews()
        self.stage_label.setText(f"회전 완료: {rotated}개")

    def _can_rotate_selected(self) -> bool:
        selected = self.file_table.selected_items()
        if len(selected) != 1:
            return False
        path = self._preview_path_for_item(selected[0])
        return path.exists() and path.suffix.lower() in EDITABLE_IMAGE_EXTENSIONS

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_R and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self._can_rotate_selected():
                self._rotate_selected(clockwise=True)
            event.accept()
            return
        if event.key() == Qt.Key.Key_F and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self._toggle_preview_fullscreen()
            event.accept()
            return
        super().keyPressEvent(event)

    def _toggle_preview_fullscreen(self) -> None:
        if not self.file_table.selected_items():
            return
        self._sync_preview_from_selection()
        if self.preview_panel is not None and self.preview_panel.isVisible():
            self.preview_panel.toggle_fullscreen()

    def _start_or_stop(self) -> None:
        if self._active_future is not None and not self._active_future.done():
            self._stop()
            return
        self._run_document_processing()

    def _run_document_processing(self) -> None:
        if not self.work_list.items:
            self.stage_label.setText("작업할 파일 없음")
            return
        workflow = self._create_cleanup_workflow()
        items = list(self.work_list.items)
        self._start_background_task(
            "처리 중",
            lambda: workflow.run(items, cancel_event=self.cancel_event, progress_callback=self._queue_progress),
            lambda results: self._finish_item_results(results, "완료", output_basis=True),
        )

    def _run_resize_only(self) -> None:
        if not self.work_list.items:
            self.stage_label.setText("리사이징할 파일 없음")
            return
        workflow = ResizeOnlyWorkflow(
            input_pipeline=self._input_pipeline(),
            resizer=ImageResizer(self.storage, self.settings.resize_options),
        )
        items = self._utility_items()
        self._start_background_task(
            "리사이징 중",
            lambda: workflow.run(items, cancel_event=self.cancel_event, progress_callback=self._queue_progress),
            lambda results: self._finish_item_results(results, "리사이징 완료", merge_scope=items),
        )

    def _run_pdf_convert(self) -> None:
        if not self.work_list.items:
            self.stage_label.setText("PDF 변환할 파일 없음")
            return
        items = [item for item in self._utility_items() if not self._is_pdf_convert_excluded(item)]
        if not items:
            self.stage_label.setText("PDF 변환할 이미지 없음")
            return
        workflow = PdfConversionWorkflow(
            input_pipeline=self._input_pipeline(),
            converter=PdfConverter(temp_dir=self.storage.temp_dir / "originals"),
        )
        self._start_background_task(
            "PDF 변환 중",
            lambda: workflow.convert_individual(
                items,
                cancel_event=self.cancel_event,
                progress_callback=self._queue_progress,
                delete_source_on_success=self.settings.pdf_convert_delete_source,
            ),
            lambda results: self._finish_item_results(
                results,
                "PDF 변환 완료",
                merge_scope=items,
                output_basis=True,
            ),
        )

    def _is_pdf_convert_excluded(self, item: WorkItem) -> bool:
        if item.archive_member_name and Path(item.archive_member_name).suffix.lower() in PDF_EXTENSIONS:
            return True
        return self._bundle_source_path_for_item(item).suffix.lower() in PDF_EXTENSIONS

    def _run_pdf_bundle(self) -> None:
        if not self.work_list.items:
            self.stage_label.setText("PDF 묶음할 파일 없음")
            return
        items = self._utility_items()
        output_path = self._default_bundle_pdf_path(items)
        workflow = PdfConversionWorkflow(
            input_pipeline=self._input_pipeline(),
            converter=PdfConverter(temp_dir=self.storage.temp_dir / "originals"),
        )
        self._start_background_task(
            "PDF 묶음 중",
            lambda: workflow.convert_bundle(
                items,
                output_path,
                cancel_event=self.cancel_event,
                progress_callback=self._queue_progress,
                delete_source_on_success=self.settings.pdf_bundle_delete_source,
            ),
            lambda result: self._finish_pdf_bundle(
                result,
                source_items=items,
                delete_source_on_success=self.settings.pdf_bundle_delete_source,
            ),
        )

    def _legacy_restore_selected(self) -> None:
        selected = self.file_table.selected_items()
        if not selected:
            self.stage_label.setText("복원할 파일 선택 없음")
            return
        cache = SourceCache(self.storage)
        restored = 0
        restored_ids: set[str] = set()
        bundle_items: list[WorkItem] = []
        for item in selected:
            if self._is_pdf_bundle_item(item):
                restored_paths = self._restore_pdf_bundle_item(item)
                restored += len(restored_paths)
                bundle_items.append(item)
                restored_ids.update(self._item_ids_for_paths(restored_paths))
                continue
            try:
                cache.restore_item(item)
                restored += 1
            except OSError:
                item.detail = "restore_failed"
        if bundle_items:
            self.work_list.remove_items(bundle_items)
            self.file_table.set_items(self.work_list.items)
            if restored_ids:
                self.file_table.select_item_ids(restored_ids)
        else:
            self.file_table.refresh_items(self.work_list.items)
        self._sync_preview_from_selection()
        self.stage_label.setText(f"원본 복원 완료: {restored}개")

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            self.settings,
            self,
            default_temp_dir=self.storage.temp_dir,
        )
        if dialog.exec():
            self.settings = dialog.settings()
            self.settings_store.save(self.settings)
            self._apply_storage_settings(self.settings)
            self.stage_label.setText("설정 저장 완료")

    def _create_cleanup_workflow(self) -> DocumentCleanupWorkflow:
        normalization = ImageNormalizationOptions(
            exif_orientation_enabled=self.settings.rotation_enabled,
            ocr_orientation_enabled=self.settings.rotation_enabled,
        )
        return DocumentCleanupWorkflow(
            input_pipeline=self._input_pipeline(),
            image_pipeline=DocumentImagePipeline(self.storage, options=normalization),
            resizer=ImageResizer(self.storage, self.settings.resize_options),
            delete_source_extensions=self._cleanup_delete_source_extensions(),
            source_deleter=move_to_recycle_bin,
        )

    def _input_pipeline(self) -> InputPreparationPipeline:
        return InputPreparationPipeline(
            self.storage,
            archive_extract_to_current_dir=self.settings.archive_extract_to_current_dir,
            pdf_tiff_extract_to_current_dir=self.settings.pdf_tiff_extract_to_current_dir,
        )

    def _cleanup_delete_source_extensions(self) -> set[str]:
        extensions = set(EXPANDED_CONTAINER_EXTENSIONS | HWP_EXTENSIONS) if self.settings.pdf_convert_delete_source else set()
        if self.settings.archive_delete_source:
            extensions.update(ARCHIVE_EXTENSIONS)
        return extensions

    def _default_bundle_pdf_path(self, items: list[WorkItem] | None = None) -> Path:
        target_items = items if items is not None else list(self.work_list.items)
        first = self._bundle_source_path_for_item(target_items[0])
        return first.with_suffix(".pdf")

    def _utility_items(self) -> list[WorkItem]:
        selected = self.file_table.selected_items()
        return selected if selected else list(self.work_list.items)

    def _start_background_task(
        self,
        running_text: str,
        work: Callable[[], Any],
        finish: Callable[[Any], None],
    ) -> None:
        if self._active_future is not None:
            if not self._active_future.done():
                self.stage_label.setText("작업 진행 중")
                return
            self._poll_active_task()
            if self._active_future is not None:
                return

        self.cancel_event.clear()
        with self._progress_lock:
            self._progress_events.clear()
        self.started_at = time.perf_counter()
        self.timer.start()
        self._set_progress_value(0)
        self.stage_label.setText(running_text)
        self.stage_time_label.setText("")
        self.start_stop_button.setText("정지")
        self._set_work_controls_enabled(False)
        self._active_finish = finish
        self._active_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="onestep-ui")
        self._active_future = self._active_executor.submit(work)
        self.task_timer.start()

    def _stop(self) -> None:
        self.cancel_event.set()
        self.start_stop_button.setEnabled(False)
        self.stage_label.setText("정지 요청")

    def _poll_active_task(self) -> None:
        self._drain_progress_events()
        future = self._active_future
        if future is None or not future.done():
            return

        self.task_timer.stop()
        finish = self._active_finish
        executor = self._active_executor
        try:
            result = future.result()
        except InterruptedError:
            self._set_progress_value(100)
            self.stage_label.setText("정지 완료")
        except Exception as exc:
            self._set_progress_value(0)
            self.stage_label.setText(f"오류: {type(exc).__name__}")
        else:
            if finish is not None:
                finish(result)
        finally:
            self._active_future = None
            self._active_finish = None
            self._active_executor = None
            self.cancel_event.clear()
            self.timer.stop()
            self.start_stop_button.setText("시작")
            self.start_stop_button.setEnabled(True)
            self._set_work_controls_enabled(True)
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)

    def _finish_item_results(
        self,
        results: list[WorkItem],
        done_text: str,
        *,
        merge_scope: list[WorkItem] | None = None,
        output_basis: bool = False,
    ) -> None:
        if output_basis:
            self._normalize_completed_results_to_outputs(results)
        self._remember_items(results)
        if merge_scope is None:
            self.work_list.items = results
        else:
            self.work_list.items = self._merge_results(self.work_list.items, results, merge_scope)
        self.work_list.rebuild_seen_paths()
        self.file_table.refresh_items(self.work_list.items)
        completed = sum(1 for item in results if item.status.value == "completed")
        failed = sum(1 for item in results if item.status.value == "failed")
        stopped = sum(1 for item in results if item.status.value == "stopped")
        self._set_progress_value(100)
        if stopped and completed == 0 and failed == 0:
            self.stage_label.setText("정지 완료")
            self._notify_completed(APP_NAME, "정지 완료")
            return
        message = done_text
        if failed and completed == 0 and stopped == 0:
            message = done_text.replace("완료", "실패")
            message = f"{message}: {failed}개"
        elif failed:
            message = f"{done_text}: 실패 {failed}개"
        self.stage_label.setText(message)
        self.stage_time_label.setText("")
        self._sync_preview_from_selection()
        self._notify_completed(APP_NAME, message)

    @staticmethod
    def _merge_results(current: list[WorkItem], results: list[WorkItem], scope: list[WorkItem]) -> list[WorkItem]:
        if not scope:
            return current
        scope_ids = {item.item_id for item in scope}
        first_index = next((index for index, item in enumerate(current) if item.item_id in scope_ids), len(current))
        merged = [item for item in current if item.item_id not in scope_ids]
        for offset, result in enumerate(results):
            merged.insert(first_index + offset, result)
        return merged

    def _remember_items(self, items: list[WorkItem]) -> None:
        for item in items:
            cached = item.cached_source_path
            if cached is None or not Path(cached).exists():
                continue
            remembered_path = item.current_path or item.source_path
            self._known_items_by_path[self.work_list._path_key(Path(remembered_path))] = item

    def _hydrate_known_item(self, item: WorkItem) -> None:
        added_path = item.source_path
        known = self._known_items_by_path.get(self.work_list._path_key(item.source_path))
        if known is None:
            return
        cached = known.cached_source_path
        if cached is None or not Path(cached).exists():
            return
        item.item_id = known.item_id
        item.source_path = known.source_path
        item.cached_source_path = Path(cached)
        item.current_path = added_path
        item.status = known.status
        item.last_mode = known.last_mode
        item.last_strategy = known.last_strategy
        item.page_count = known.page_count
        item.detail = known.detail

    def _finish_pdf_bundle(
        self,
        result,
        *,
        source_items: list[WorkItem] | None = None,
        delete_source_on_success: bool | None = None,
        bundle_cache_dir: Path | None = None,
    ) -> None:
        if source_items is not None:
            if delete_source_on_success is None:
                delete_source_on_success = self.settings.pdf_bundle_delete_source
            if delete_source_on_success:
                self.work_list.remove_items(source_items)
            bundle_item = self._upsert_pdf_bundle_item(Path(result.output_path), bundle_cache_dir, page_count=result.page_count)
            self.work_list.rebuild_seen_paths()
            self.file_table.set_items(self.work_list.items)
            self.file_table.select_item_ids({bundle_item.item_id})
            self._sync_preview_from_selection()
        self._set_progress_value(100)
        message = f"PDF 묶음 완료: {result.page_count}페이지"
        self.stage_label.setText(message)
        self.stage_time_label.setText("")
        self._notify_completed(APP_NAME, message)

    def _notify_completed(self, title: str, message: str) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = self.windowIcon()
        if icon.isNull():
            return
        if self.tray_icon is None:
            self.tray_icon = QSystemTrayIcon(icon, self)
        if not self.tray_icon.isVisible():
            self.tray_icon.show()
        self.tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 5000)

    def _queue_progress(self, percent: int, text: str) -> None:
        with self._progress_lock:
            self._progress_events.append((percent, text))

    def _drain_progress_events(self) -> None:
        with self._progress_lock:
            events = list(self._progress_events)
            self._progress_events.clear()
        if not events:
            return
        percent, text = events[-1]
        self._set_progress_value(max(0, min(99, int(percent))))
        self.stage_label.setText(text)

    def _set_progress_value(self, value: int) -> None:
        clamped = max(0, min(100, int(value)))
        self.progress.setValue(clamped)
        self.progress_percent_label.setText(f"{clamped}%")

    @staticmethod
    def _timing_summary(results: list[WorkItem]) -> str:
        for item in results:
            if "; " in item.detail:
                return item.detail.split("; ", 1)[1]
        return ""

    def _begin_preview_selection_drag(self) -> None:
        self._preview_selection_drag_active = True
        self.preview_sync_timer.stop()

    def _finish_preview_selection_drag(self) -> None:
        self._preview_selection_drag_active = False
        if not self._preview_sync_queued:
            return
        self.preview_sync_timer.stop()
        self._flush_preview_sync()

    def _schedule_preview_sync(self) -> None:
        self._preview_sync_queued = True
        if self._preview_selection_drag_active:
            return
        selected = self.file_table.selected_items()
        if (selected and not self._preview_sidebar_expanded) or (not selected and self._preview_sidebar_expanded):
            self.preview_sync_timer.stop()
            self._flush_preview_sync()
            return
        self.preview_sync_timer.start()

    def _flush_preview_sync(self) -> None:
        if self._preview_selection_drag_active or not self._preview_sync_queued:
            return
        self._preview_sync_queued = False
        self._sync_preview_from_selection()

    def _sync_preview_from_selection(self) -> None:
        selected = self.file_table.selected_items()
        if not selected:
            if self.preview_panel is not None:
                self.preview_panel.hide()
                self.preview_panel.setParent(None)
            if self.preview_placeholder is not None:
                self.preview_placeholder.hide()
                self.preview_placeholder.setParent(None)
            if self._preview_sidebar_expanded:
                self._preview_sidebar_expanded = False
                self._set_resting_shell_alignment()
                self.setMinimumWidth(self._list_area_width())
                self.resize(max(self._list_area_width(), self._resting_window_width), self.height())
            return
        self._set_expanded_shell_alignment()
        should_expand_window = not self._preview_sidebar_expanded
        if self.preview_placeholder is not None:
            self.preview_placeholder.hide()
            self.preview_placeholder.setParent(None)
        if self.preview_panel is None:
            self.preview_panel = PreviewPanel(
                self,
                storage=self.storage,
                edit_path_resolver=self._ensure_editable_preview_path,
            )
            self.preview_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.preview_panel.image_created.connect(self._add_created_preview_image)
            self.preview_panel.image_selected.connect(self._select_preview_path_in_list)
        paths, page_badges, vertical = self._preview_paths_for_selection(selected)
        navigation_paths = self._preview_navigation_paths()
        sidebar_transition = self.isVisible() and (
            should_expand_window or self.shell_splitter.indexOf(self.preview_panel) < 0
        )
        if sidebar_transition:
            self.setUpdatesEnabled(False)
            self.preview_panel.setUpdatesEnabled(False)
        if self.shell_splitter.indexOf(self.preview_panel) < 0:
            self.shell_splitter.addWidget(self.preview_panel)
            self.shell_splitter.setStretchFactor(0, 1)
            self.shell_splitter.setStretchFactor(1, 0)
            self.shell_splitter.setCollapsible(1, False)
        if should_expand_window:
            self._resting_window_width = max(self._list_area_width(), self.width())
            self._preview_sidebar_expanded = True
        sidebar_width = self._sidebar_width_for_current_window()
        expanded_width = self._expanded_window_minimum_width(sidebar_width)
        self.setMinimumWidth(self._expanded_window_minimum_width(self._preview_sidebar_min_width()))
        if self.width() < expanded_width:
            self.resize(expanded_width, self.height())
        self.shell_layout.activate()
        self._apply_shell_splitter_sizes()
        self.preview_panel.set_paths(
            paths,
            vertical=vertical,
            page_badges=page_badges,
            navigation_paths=navigation_paths,
            defer_reflow=sidebar_transition,
        )
        self.preview_panel.show()
        self._apply_shell_splitter_sizes()
        if sidebar_transition:
            QTimer.singleShot(0, self._finish_preview_sidebar_transition)

    def _finish_preview_sidebar_transition(self, attempt: int = 0) -> None:
        if self.preview_panel is None:
            self.setUpdatesEnabled(True)
            return
        self._apply_shell_splitter_sizes()
        if self.preview_panel.width() < self._preview_sidebar_min_width() and attempt < 8:
            QTimer.singleShot(0, lambda: self._finish_preview_sidebar_transition(attempt + 1))
            return
        self.preview_panel.reflow()
        self.preview_panel.setUpdatesEnabled(True)
        self.setUpdatesEnabled(True)
        self.preview_panel.update()
        self.update()

    def _ensure_preview_placeholder(self) -> QWidget:
        if self.preview_placeholder is None:
            self.preview_placeholder = QWidget(self)
            self.preview_placeholder.setObjectName("previewPlaceholder")
            self.preview_placeholder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        if self.shell_splitter.indexOf(self.preview_placeholder) < 0:
            self.shell_splitter.addWidget(self.preview_placeholder)
            self.shell_splitter.setStretchFactor(0, 1)
            self.shell_splitter.setStretchFactor(1, 0)
            self.shell_splitter.setCollapsible(1, False)
        return self.preview_placeholder

    def _default_preview_sidebar_width(self) -> int:
        return self._preview_sidebar_min_width()

    def _sidebar_width_for_current_window(self) -> int:
        available = self.width() - self._list_area_width() - self.shell_splitter.handleWidth()
        return max(self._preview_sidebar_min_width(), available)

    def _apply_shell_splitter_sizes(self) -> None:
        if not self._preview_sidebar_expanded:
            return
        sidebar_width = self._sidebar_width_for_current_window()
        self.preview_sidebar_width = sidebar_width
        self.shell_splitter.setSizes([self._list_area_width(), sidebar_width])

    def _sync_shell_splitter_widths(self) -> None:
        sizes = self.shell_splitter.sizes()
        if len(sizes) < 2 or not self._preview_sidebar_expanded:
            return
        sidebar_width = max(self._preview_sidebar_min_width(), sizes[1])
        self.preview_sidebar_width = sidebar_width
        if self.preview_panel is not None and self.preview_panel.isVisible():
            self.setMinimumWidth(self._expanded_window_minimum_width(sidebar_width))

    def _add_created_preview_image(self, image_path: Path) -> None:
        selected_ids = {item.item_id for item in self.file_table.selected_items()}
        added = self.work_list.add_paths([Path(image_path)])
        for item in added:
            self._hydrate_known_item(item)
            selected_ids.add(item.item_id)
        self.file_table.set_items(self.work_list.items)
        self.file_table.select_item_ids(selected_ids)
        self._sync_preview_from_selection()

    def _preview_path_for_item(self, item: WorkItem) -> Path:
        if item.current_path is not None and Path(item.current_path).exists():
            return Path(item.current_path)
        if item.archive_member_name:
            preview_path = self._extract_archive_member_preview(item)
            if preview_path is not None:
                item.current_path = preview_path
                return preview_path
        return item.source_path

    def _ensure_editable_preview_path(self, preview_path: Path) -> Path | None:
        path = Path(preview_path)
        item = self._item_for_preview_path(path)
        if item is None:
            return path if path.exists() and path.suffix.lower() in EDITABLE_IMAGE_EXTENSIONS else None
        if not self._item_needs_materialization_for_edit(item):
            return path if path.exists() and path.suffix.lower() in EDITABLE_IMAGE_EXTENSIONS else None
        return None

        preview_index = self._preview_page_index_for_item(path, item)
        if not self._confirm_materialize_bundle_for_edit(item):
            return None
        materialized = self._materialize_bundle_item_for_edit(item)
        if not materialized:
            self.stage_label.setText("페이지 풀기 실패")
            return None

        self._replace_item_with_materialized(item, materialized)
        selected_item = materialized[min(preview_index, len(materialized) - 1)]
        self.file_table.set_items(self.work_list.items)
        self.file_table.select_item_ids({selected_item.item_id})
        self._sync_preview_from_selection()
        self.stage_label.setText(f"페이지로 풀기: {len(materialized)}개")
        return selected_item.current_path or selected_item.source_path

    def _item_for_preview_path(self, preview_path: Path) -> WorkItem | None:
        path = Path(preview_path)
        for item in self.work_list.items:
            candidates = [item.source_path]
            if item.current_path is not None:
                candidates.append(Path(item.current_path))
            if any(self._same_path(candidate, path) for candidate in candidates):
                return item
            if self._is_pdf_item(item) and any(self._same_path(page, path) for page in self._cached_pdf_preview_pages(item)):
                return item
        return None

    def _preview_page_index_for_item(self, preview_path: Path, item: WorkItem) -> int:
        if self._is_pdf_item(item):
            for index, page in enumerate(self._cached_pdf_preview_pages(item)):
                if self._same_path(page, preview_path):
                    return index
        return 0

    def _item_needs_materialization_for_edit(self, item: WorkItem) -> bool:
        suffix = Path(item.current_path or item.source_path).suffix.lower()
        if item.archive_member_name:
            return True
        return suffix in PDF_EXTENSIONS or suffix in TIFF_EXTENSIONS

    def _materialize_prompt_copy(self, _item: WorkItem) -> tuple[str, str, str]:
        return "페이지로 풀기", "편집하려면 페이지 이미지로 풀어야 합니다.", "앞으로 묻지 않기"

    def _confirm_materialize_bundle_for_edit(self, item: WorkItem) -> bool:
        if self.settings.always_unbundle_for_edit:
            return True
        title, body, checkbox_text = self._materialize_prompt_copy(item)
        message = QMessageBox(self)
        message.setWindowTitle(title)
        message.setText(body)
        confirm_button = message.addButton("페이지로 풀기", QMessageBox.ButtonRole.AcceptRole)
        message.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        checkbox = QCheckBox(checkbox_text, message)
        message.setCheckBox(checkbox)
        message.exec()
        accepted = message.clickedButton() is confirm_button
        if accepted and checkbox.isChecked():
            self.settings = replace(self.settings, always_unbundle_for_edit=True)
            self.settings_store.save(self.settings)
        return accepted

    def _materialize_bundle_item_for_edit(self, item: WorkItem) -> list[WorkItem]:
        prepared = InputPreparationPipeline(self.storage).prepare_items([item])
        images = [entry for entry in prepared if entry.kind == "image"]
        group_id = self._bundle_group_id_for_item(item)
        materialized: list[WorkItem] = []
        for index, prepared_item in enumerate(images, start=1):
            target = Path(prepared_item.output_path or prepared_item.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not self._same_path(prepared_item.path, target):
                shutil.copy2(prepared_item.path, target)
            materialized.append(
                WorkItem(
                    source_path=target,
                    current_path=target,
                    cached_source_path=prepared_item.restore_path,
                    bundle_group_id=group_id,
                    page_index=index,
                )
            )
        return materialized

    def _replace_item_with_materialized(self, item: WorkItem, materialized: list[WorkItem]) -> None:
        replaced: list[WorkItem] = []
        for existing in self.work_list.items:
            if existing.item_id == item.item_id:
                replaced.extend(materialized)
            else:
                replaced.append(existing)
        self.work_list.items = replaced
        self.work_list.rebuild_seen_paths()
        self._pdf_preview_cache = {
            key: pages for key, pages in self._pdf_preview_cache.items() if not key.startswith(f"{item.item_id}:")
        }

    @staticmethod
    def _bundle_group_id_for_item(item: WorkItem) -> str:
        if item.archive_member_name:
            return f"{item.source_path.resolve()}!{item.archive_member_name}"
        return str(item.source_path.resolve())

    @staticmethod
    def _same_path(left: Path, right: Path) -> bool:
        try:
            return Path(left).resolve() == Path(right).resolve()
        except OSError:
            return Path(left).absolute() == Path(right).absolute()

    def _preview_paths_for_selection(self, selected: list[WorkItem]) -> tuple[list[Path], dict[Path, str], bool]:
        if len(selected) == 1 and self._is_pdf_item(selected[0]):
            pages = self._pdf_preview_pages(selected[0])
            if pages:
                return pages, {}, True
        paths: list[Path] = []
        page_badges: dict[Path, str] = {}
        for item in selected:
            if self._is_pdf_item(item):
                pages = self._pdf_preview_pages(item)
                if pages:
                    paths.append(pages[0])
                    if len(pages) > 1:
                        page_badges[pages[0]] = f"PDF | {len(pages)}P"
                    continue
            paths.append(self._preview_path_for_item(item))
        return paths, page_badges, False

    def _preview_navigation_paths(self) -> list[Path]:
        paths: list[Path] = []
        for item in self.work_list.items:
            if self._is_pdf_item(item):
                pages = self._cached_pdf_preview_pages(item)
                if pages:
                    paths.append(pages[0])
                    continue
                continue
            paths.append(self._preview_path_for_item(item))
        return paths

    def _select_preview_path_in_list(self, image_path: Path) -> None:
        path = Path(image_path)
        for item in self.work_list.items:
            if self._preview_path_matches_item(path, item):
                self.file_table.select_item_ids({item.item_id})
                self._sync_preview_from_selection()
                return

    def _preview_path_matches_item(self, path: Path, item: WorkItem) -> bool:
        candidates = {self._preview_path_for_item(item)}
        if item.current_path is not None:
            candidates.add(Path(item.current_path))
        candidates.add(item.source_path)
        if path in candidates:
            return True
        if self._is_pdf_item(item):
            return path in self._cached_pdf_preview_pages(item)
        return False

    def _is_pdf_item(self, item: WorkItem) -> bool:
        if item.current_path is not None and Path(item.current_path).suffix.lower() in PDF_EXTENSIONS:
            return True
        if item.archive_member_name and Path(item.archive_member_name).suffix.lower() in PDF_EXTENSIONS:
            return True
        return item.source_path.suffix.lower() in PDF_EXTENSIONS

    def _pdf_preview_pages(self, item: WorkItem) -> list[Path]:
        pdf_path = self._pdf_source_for_preview(item)
        if pdf_path is None or not pdf_path.exists():
            return []
        try:
            mtime_ns = pdf_path.stat().st_mtime_ns
        except OSError:
            mtime_ns = 0
        key = f"{item.item_id}:{pdf_path}:{mtime_ns}"
        cached = self._pdf_preview_cache.get(key)
        if cached is not None:
            return [path for path in cached if path.exists()]
        destination = self.storage.temp_dir / "previews" / item.item_id / "pdf_pages"
        try:
            rendered = ExistingPdfRenderer().render(pdf_path, destination)
        except Exception:
            self._pdf_preview_cache[key] = []
            return []
        pages = [prepared.path for prepared in rendered if prepared.path.exists()]
        self._pdf_preview_cache[key] = pages
        return pages

    def _cached_pdf_preview_pages(self, item: WorkItem) -> list[Path]:
        prefix = f"{item.item_id}:"
        for key, pages in self._pdf_preview_cache.items():
            if key.startswith(prefix):
                return [path for path in pages if path.exists()]
        return []

    def _pdf_source_for_preview(self, item: WorkItem) -> Path | None:
        if item.current_path is not None and Path(item.current_path).suffix.lower() in PDF_EXTENSIONS:
            return Path(item.current_path)
        if item.archive_member_name and Path(item.archive_member_name).suffix.lower() in PDF_EXTENSIONS:
            preview_dir = self.storage.temp_dir / "previews" / item.item_id / "source"
            extracted = ArchiveExtractor().extract_member(item.source_path, item.archive_member_name, preview_dir)
            return extracted.path if extracted is not None else None
        if item.source_path.suffix.lower() in PDF_EXTENSIONS:
            return item.source_path
        return None

    def _normalize_completed_results_to_outputs(self, results: list[WorkItem]) -> None:
        for item in results:
            if item.status.value != "completed" or item.current_path is None:
                continue
            current = Path(item.current_path)
            if not current.exists():
                continue
            item.source_path = current
            item.current_path = current
            item.archive_member_name = None

    def _bundle_source_path_for_item(self, item: WorkItem) -> Path:
        if item.current_path is not None and Path(item.current_path).exists():
            return Path(item.current_path)
        return Path(item.source_path)

    def _cache_bundle_sources(self, items: list[WorkItem], output_path: Path) -> Path:
        cache_dir = self.storage.cache_dir / "pdf_bundles" / f"{Path(output_path).stem}_{uuid.uuid4().hex}"
        cache_dir.mkdir(parents=True, exist_ok=True)
        for item in items:
            source = self._bundle_source_path_for_item(item)
            if not source.exists() or source.suffix.lower() not in EDITABLE_IMAGE_EXTENSIONS:
                continue
            target = ArchiveExtractor._unique_path(cache_dir / source.name)
            shutil.copy2(source, target)
        return cache_dir

    def _upsert_pdf_bundle_item(self, output_path: Path, bundle_cache_dir: Path | None, *, page_count: int = 1) -> WorkItem:
        output_path = Path(output_path)
        key = self.work_list._path_key(output_path)
        for item in self.work_list.items:
            if self.work_list._path_key(item.source_path) == key:
                item.source_path = output_path
                item.current_path = output_path
                item.cached_source_path = bundle_cache_dir
                item.page_count = page_count
                item.status = WorkStatus.COMPLETED
                item.last_mode = ProcessingMode.PDF_BUNDLE
                item.detail = "pdf_bundle"
                return item
        item = WorkItem(
            source_path=output_path,
            current_path=output_path,
            cached_source_path=bundle_cache_dir,
            page_count=page_count,
            status=WorkStatus.COMPLETED,
            last_mode=ProcessingMode.PDF_BUNDLE,
            detail="pdf_bundle",
        )
        self.work_list.items.append(item)
        return item

    @staticmethod
    def _is_pdf_bundle_item(item: WorkItem) -> bool:
        return item.detail == "pdf_bundle" and item.cached_source_path is not None

    def _restore_pdf_bundle_item(self, item: WorkItem) -> list[Path]:
        cache_dir = Path(item.cached_source_path) if item.cached_source_path is not None else None
        output_path = Path(item.current_path or item.source_path)
        if cache_dir is None or not cache_dir.exists() or not cache_dir.is_dir():
            item.detail = "restore_failed"
            return []
        restored: list[Path] = []
        for cached in sorted(path for path in cache_dir.iterdir() if path.is_file()):
            target = output_path.parent / cached.name
            shutil.copy2(cached, target)
            restored.append(target)
        if output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                move_to_recycle_bin(output_path)
        notify_path_changed(output_path.parent)
        self.work_list.add_paths(restored)
        return restored

    def _item_ids_for_paths(self, paths: list[Path]) -> set[str]:
        keys = {self.work_list._path_key(path) for path in paths}
        return {item.item_id for item in self.work_list.items if self.work_list._path_key(item.source_path) in keys}

    def _extract_archive_member_preview(self, item: WorkItem) -> Path | None:
        if Path(item.archive_member_name or "").suffix.lower() not in EDITABLE_IMAGE_EXTENSIONS:
            return None
        preview_dir = self.storage.temp_dir / "previews" / item.item_id
        extracted = ArchiveExtractor().extract_member(item.source_path, item.archive_member_name or "", preview_dir)
        if extracted is None:
            return None
        return extracted.path

    def _tick_elapsed(self) -> None:
        if self.started_at is None:
            self.elapsed_label.setText("0.0초")
            return
        self.elapsed_label.setText(f"{time.perf_counter() - self.started_at:.1f}초")

    def _set_work_controls_enabled(self, enabled: bool) -> None:
        for button in (
            self.pdf_button,
            self.pdf_bundle_button,
        ):
            button.setEnabled(enabled)
        self.settings_button.setEnabled(enabled)

    def _apply_storage_settings(self, settings: AppSettings) -> None:
        if settings.temp_dir is not None:
            self.storage.temp_dir = Path(settings.temp_dir)
        self.storage.ensure_dirs()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        answer = QMessageBox.question(
            self,
            "OneStep",
            "프로그램을 종료할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            event.ignore()
            return
        self.cancel_event.set()
        if self._active_future is not None:
            self._active_future.cancel()
        if self._active_executor is not None:
            self._active_executor.shutdown(wait=False, cancel_futures=True)
        if self.preview_panel is not None:
            self.preview_panel.close_auxiliary_windows()
        try:
            self.storage.clear_temp()
        except (OSError, ValueError):
            pass
        super().closeEvent(event)
