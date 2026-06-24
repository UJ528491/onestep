from __future__ import annotations

from pathlib import Path
import re

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QLabel,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc_auto.branding import EMPTY_DROP_TEXT
from doc_auto.domain.job import WorkItem, WorkStatus


HEADERS = ["상태", "파일명", "확장자", "페이지", "파일크기"]
DEFAULT_SORT_COLUMN = 1
CENTER_COLUMNS = {0, 2, 3}
RIGHT_COLUMNS = {4}
FILENAME_COLUMN = 1
FILE_SIZE_COLUMN = 4
BALANCED_COLUMNS = (0, 2, 3, 4)
MIN_COLUMN_WIDTHS = {
    0: 64,
    2: 64,
    3: 64,
    FILE_SIZE_COLUMN: 74,
}


def _natural_key(text: str) -> tuple:
    parts = re.split(r"(\d+)", text.casefold())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def _display_path(item: WorkItem) -> Path:
    if item.current_path is not None:
        return Path(item.current_path)
    if item.archive_member_name:
        return Path(item.archive_member_name)
    return item.source_path


def _status_text(item: WorkItem) -> str:
    return "완료" if item.status == WorkStatus.COMPLETED else "대기"


def _page_text(item: WorkItem) -> str:
    return str(max(1, int(item.page_count or 1)))


def _extension_text(item: WorkItem) -> str:
    return _display_path(item).suffix.removeprefix(".").upper()


def _file_size_bytes(item: WorkItem) -> int | None:
    display_path = _display_path(item)
    try:
        if display_path.exists() and display_path.is_file():
            return display_path.stat().st_size
    except OSError:
        pass
    return item.file_size_bytes


def _file_size_text(item: WorkItem) -> str:
    size = _file_size_bytes(item)
    if size is None:
        return ""
    if size < 1024 * 1024:
        kb = 0 if size == 0 else max(1, (size + 1023) // 1024)
        return f"{kb} KB"
    mb = size / (1024 * 1024)
    if mb >= 10 or mb.is_integer():
        return f"{round(mb):.0f} MB"
    return f"{mb:.1f} MB"


class _DropTable(QTableWidget):
    paths_dropped = Signal(list)
    delete_requested = Signal()
    fullscreen_requested = Signal()
    rotate_clockwise_requested = Signal()
    selection_drag_started = Signal()
    selection_drag_finished = Signal()
    resized = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setDragDropOverwriteMode(False)
        self._blank_drag_origin: QPoint | None = None
        self._selection_press_pos: QPoint | None = None
        self._selection_drag_active = False

    @staticmethod
    def paths_from_mime(mime_data) -> list[Path]:
        if not mime_data.hasUrls():
            return []
        return [Path(url.toLocalFile()) for url in mime_data.urls() if url.isLocalFile()]

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        paths = self.paths_from_mime(event.mimeData())
        if not paths:
            super().dropEvent(event)
            return
        self.paths_dropped.emit(paths)
        event.acceptProposedAction()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self.resized.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Delete:
            self.delete_requested.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_F and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.fullscreen_requested.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_R and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.rotate_clockwise_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        position = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton:
            self._selection_press_pos = position
            self._selection_drag_active = False
            if not self.indexAt(position).isValid():
                self._blank_drag_origin = position
                self.clearSelection()
                event.accept()
                return
        self._blank_drag_origin = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._selection_press_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            distance = (event.position().toPoint() - self._selection_press_pos).manhattanLength()
            if distance >= QApplication.startDragDistance():
                self._begin_selection_drag()
        if self._blank_drag_origin is not None:
            rect = QRect(self._blank_drag_origin, event.position().toPoint()).normalized()
            self.select_rows_in_viewport_rect(rect)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._blank_drag_origin is not None:
            self._blank_drag_origin = None
            self._finish_selection_drag()
            event.accept()
            return
        was_dragging = self._selection_drag_active
        super().mouseReleaseEvent(event)
        if was_dragging:
            self._finish_selection_drag()
        self._selection_press_pos = None

    def _begin_selection_drag(self) -> None:
        if self._selection_drag_active:
            return
        self._selection_drag_active = True
        self.selection_drag_started.emit()

    def _finish_selection_drag(self) -> None:
        if self._selection_drag_active:
            self.selection_drag_finished.emit()
        self._selection_drag_active = False
        self._selection_press_pos = None

    def select_rows_in_viewport_rect(self, rect: QRect) -> None:
        normalized = rect.normalized()
        selection_model = self.selectionModel()
        selection_model.clearSelection()
        for row in range(self.rowCount()):
            index = self.model().index(row, 0)
            if not normalized.intersects(self.visualRect(index)):
                continue
            selection_model.select(
                index,
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )


class FileTableWidget(QWidget):
    paths_dropped = Signal(list)
    selection_changed = Signal(list)
    delete_requested = Signal(list)
    open_requested = Signal(object)
    fullscreen_requested = Signal()
    rotate_clockwise_requested = Signal()
    selection_drag_started = Signal()
    selection_drag_finished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.items: list[WorkItem] = []
        self._sort_column = DEFAULT_SORT_COLUMN
        self._sort_descending = False

        self.table = _DropTable(self)
        self.table.paths_dropped.connect(self.paths_dropped)
        self.table.setColumnCount(len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.setStyleSheet(
            """
            QTableWidget::item:focus {
                border: 0;
                outline: none;
            }
            """
        )
        for column in range(len(HEADERS)):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().sectionClicked.connect(self._sort_by_column)
        self.table.resized.connect(self._apply_column_widths)
        self.table.itemClicked.connect(self._handle_item_clicked)
        self.table.itemDoubleClicked.connect(self._handle_item_double_clicked)
        self.table.itemSelectionChanged.connect(self._emit_selection_changed)
        self.table.delete_requested.connect(self._emit_delete_requested)
        self.table.fullscreen_requested.connect(self.fullscreen_requested.emit)
        self.table.rotate_clockwise_requested.connect(self.rotate_clockwise_requested.emit)
        self.table.selection_drag_started.connect(self.selection_drag_started.emit)
        self.table.selection_drag_finished.connect(self.selection_drag_finished.emit)

        self.empty_label = QLabel(EMPTY_DROP_TEXT, self)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.empty_label.setStyleSheet("color: #94a3b8; font-size: 22px; font-weight: 600;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        self._update_empty_state()
        self._apply_column_widths()

    def set_items(self, items: list[WorkItem]) -> None:
        self.items = self._sorted_items(list(items))
        self.table.setRowCount(0)
        for item in self.items:
            self._append_row(item)
        self._update_empty_state()
        self._apply_column_widths()

    def add_item(self, item: WorkItem) -> None:
        self.items.append(item)
        self.items = self._sorted_items(self.items)
        self.table.setRowCount(0)
        for item in self.items:
            self._append_row(item)
        self._update_empty_state()
        self._apply_column_widths()

    def _sort_by_column(self, column: int) -> None:
        if column == self._sort_column:
            self._sort_descending = not self._sort_descending
        else:
            self._sort_column = column
            self._sort_descending = False
        self.refresh_items(self.items)

    def _sorted_items(self, items: list[WorkItem]) -> list[WorkItem]:
        return sorted(items, key=self._sort_key, reverse=self._sort_descending)

    def _sort_key(self, item: WorkItem):
        if self._sort_column == 0:
            return (0 if item.status == WorkStatus.COMPLETED else 1, _natural_key(item.current_name))
        if self._sort_column == 1:
            return _natural_key(item.current_name)
        if self._sort_column == 2:
            return (_extension_text(item).casefold(), _natural_key(item.current_name))
        if self._sort_column == 3:
            return (int(item.page_count or 1), _natural_key(item.current_name))
        if self._sort_column == 4:
            return (_file_size_bytes(item) or -1, _natural_key(item.current_name))
        return _natural_key(item.current_name)

    def refresh_items(self, items: list[WorkItem]) -> None:
        selected_ids = {item.item_id for item in self.selected_items()}
        current_id = self._current_item_id()
        current_column = max(0, self.table.currentColumn())
        had_focus = self.table.hasFocus() or self.table.viewport().hasFocus()
        self.items = self._sorted_items(list(items))
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for item in self.items:
            self._append_row(item)
        selection_model = self.table.selectionModel()
        selection_model.clearSelection()
        restored_current_row: int | None = None
        first_selected_row: int | None = None
        for row, item in enumerate(self.items):
            index = self.table.model().index(row, 0)
            if item.item_id == current_id:
                restored_current_row = row
            if item.item_id in selected_ids:
                if first_selected_row is None:
                    first_selected_row = row
                selection_model.select(
                    index,
                    QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
                )
        current_row = restored_current_row if restored_current_row is not None else first_selected_row
        if current_row is not None:
            current_index = self.table.model().index(
                current_row,
                min(current_column, max(0, self.table.columnCount() - 1)),
            )
            selection_model.setCurrentIndex(current_index, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.table.blockSignals(False)
        if had_focus:
            self.table.setFocus(Qt.FocusReason.OtherFocusReason)
        self._update_empty_state()
        self._emit_selection_changed()

    def selected_items(self) -> list[WorkItem]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return [self.items[row] for row in rows if 0 <= row < len(self.items)]

    def _current_item_id(self) -> str | None:
        row = self.table.currentRow()
        if 0 <= row < len(self.items):
            return self.items[row].item_id
        return None

    def select_item_ids(self, item_ids: set[str]) -> None:
        selection_model = self.table.selectionModel()
        selection_model.clearSelection()
        for row, item in enumerate(self.items):
            if item.item_id not in item_ids:
                continue
            index = self.table.model().index(row, 0)
            selection_model.select(
                index,
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self.empty_label.setGeometry(self.table.geometry())
        self._apply_column_widths()

    def _apply_column_widths(self) -> None:
        if self.table.columnCount() != len(HEADERS):
            return
        total_width = self.table.viewport().width()
        if total_width <= 0:
            total_width = self.table.width()
        if total_width <= 0:
            return
        balanced_min_width = sum(MIN_COLUMN_WIDTHS[column] for column in BALANCED_COLUMNS)
        filename_width = total_width // 2
        if total_width - filename_width < balanced_min_width:
            filename_width = max(120, total_width - balanced_min_width)
        remaining_width = max(0, total_width - filename_width)
        widths = {FILENAME_COLUMN: filename_width}
        extra_width = max(0, remaining_width - balanced_min_width)
        base_extra = extra_width // len(BALANCED_COLUMNS)
        remainder = extra_width % len(BALANCED_COLUMNS)
        for index, column in enumerate(BALANCED_COLUMNS):
            widths[column] = MIN_COLUMN_WIDTHS[column] + base_extra + (1 if index < remainder else 0)
        for column in range(len(HEADERS)):
            width = widths.get(column, 0)
            if self.table.columnWidth(column) != width:
                self.table.setColumnWidth(column, width)

    def _append_row(self, item: WorkItem) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [
            _status_text(item),
            item.current_name,
            _extension_text(item),
            _page_text(item),
            _file_size_text(item),
        ]
        for column, value in enumerate(values):
            table_item = QTableWidgetItem(value)
            if column in CENTER_COLUMNS:
                table_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if column in RIGHT_COLUMNS:
                table_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, column, table_item)

    def _handle_item_clicked(self, item: QTableWidgetItem) -> None:
        return

    def _handle_item_double_clicked(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if 0 <= row < len(self.items):
            self.open_requested.emit(self.items[row])

    def _emit_delete_requested(self) -> None:
        selected = self.selected_items()
        if selected:
            self.delete_requested.emit(selected)

    def _emit_selection_changed(self) -> None:
        self.selection_changed.emit(self.selected_items())

    def _update_empty_state(self) -> None:
        self.empty_label.setVisible(self.table.rowCount() == 0)
        self.empty_label.raise_()
