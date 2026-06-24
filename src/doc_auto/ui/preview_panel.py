from __future__ import annotations

from math import ceil
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImageReader, QKeyEvent, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from doc_auto.services.manual_crop import Box, ManualCropHistory
from doc_auto.services.image_rotation import rotate_image_in_place
from doc_auto.domain.file_types import EDITABLE_IMAGE_EXTENSIONS
from doc_auto.services.temp_storage import PortableStorage


ROTATE_LEFT_ICON = "↶"
ROTATE_RIGHT_ICON = "↷"
FULLSCREEN_ICON = "⛶"
THUMBNAIL_LOAD_INTERVAL_MS = 0
THUMBNAIL_CACHE_LIMIT = 512
THUMBNAIL_CACHE_TRIM_COUNT = 128


def _configure_icon_button(button: QToolButton, text: str, *, width: int = 34) -> None:
    button.setText(text)
    button.setFixedSize(width, 34)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    font = QFont("Segoe UI Symbol")
    font.setPointSize(13)
    button.setFont(font)
    button.setStyleSheet(
        """
        QToolButton {
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 7px;
            color: #0f172a;
        }
        QToolButton:hover { background: #f1f5f9; }
        QToolButton:disabled { color: #94a3b8; background: #f8fafc; }
        """
    )


def _configure_text_tool_button(button: QToolButton, text: str, *, width: int = 68) -> None:
    button.setText(text)
    button.setFixedSize(width, 34)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    font = QFont("Malgun Gothic")
    font.setPointSize(10)
    button.setFont(font)
    button.setStyleSheet(
        """
        QToolButton {
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 7px;
            color: #0f172a;
            font-weight: 600;
        }
        QToolButton:hover { background: #f1f5f9; }
        QToolButton:checked { background: #dbeafe; border-color: #60a5fa; color: #1e3a8a; }
        QToolButton:disabled { color: #94a3b8; background: #f8fafc; }
        """
    )


def _configure_crop_action_button(button: QPushButton, text: str) -> None:
    button.setText(text)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setMinimumHeight(32)
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    font = QFont("Malgun Gothic")
    font.setPointSize(10)
    button.setFont(font)
    button.setStyleSheet(
        """
        QPushButton {
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 7px;
            color: #0f172a;
            font-weight: 600;
            padding: 6px 12px;
        }
        QPushButton:hover { background: #f1f5f9; }
        QPushButton:pressed { background: #e2e8f0; }
        """
    )
    button.adjustSize()


class _CropCanvas(QLabel):
    selection_finished = Signal(tuple, object, float)
    selection_started = Signal()
    empty_clicked = Signal()
    selection_geometry_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._press_pos: QPoint | None = None
        self._selection: QRect | None = None
        self._selection_box: Box | None = None
        self._rotating = False
        self._tilt_mode = False
        self._rotation_origin_x = 0
        self._rotation_origin_angle = 0.0
        self._rotation_angle = 0.0
        self._image_size = QSize()
        self._source_pixmap = QPixmap()
        self._preferred_size = QSize(640, 480)

    def set_image(self, image_path: Path, display_size: QSize) -> None:
        self._source_pixmap = QPixmap(str(image_path))
        self._image_size = self._source_pixmap.size()
        self._preferred_size = display_size if not display_size.isEmpty() else QSize(640, 480)
        self._selection = None
        self._selection_box = None
        self._rotation_angle = 0.0
        self._rotating = False
        self._tilt_mode = False
        if self._source_pixmap.isNull():
            self.setText(image_path.name)
            self.setPixmap(QPixmap())
            return
        self.setText("")
        self._update_scaled_pixmap(self.size() if not self.size().isEmpty() else self._preferred_size)
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self._preferred_size

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(320, 240)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._update_scaled_pixmap(event.size())

    def image_box_from_selection(self) -> Box | None:
        if self._selection_box is not None:
            return self._selection_box
        if self._selection is None or self.pixmap() is None:
            return None
        return ImagePreviewWindow.image_box_from_display_rect(
            self._selection,
            display_rect=self._pixmap_rect(),
            image_size=self._image_size,
        )

    @property
    def rotation_angle(self) -> float:
        return self._rotation_angle

    @property
    def tilt_mode(self) -> bool:
        return self._tilt_mode

    def set_tilt_mode(self, enabled: bool) -> None:
        self._tilt_mode = enabled
        self._press_pos = None
        self._selection = None
        self._selection_box = None
        self._rotating = False
        self.update()

    def clear_selection(self, *, reset_rotation: bool = False) -> None:
        self._selection = None
        self._selection_box = None
        self._rotating = False
        if reset_rotation:
            self._rotation_angle = 0.0
            self._update_scaled_pixmap(self.size() if not self.size().isEmpty() else self._preferred_size)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and self._pixmap_rect().contains(event.position().toPoint()):
            self.selection_started.emit()
            if self._tilt_mode:
                self._rotating = True
                self._rotation_origin_x = event.position().toPoint().x()
                self._rotation_origin_angle = self._rotation_angle
                self._selection = None
                self._selection_box = None
            else:
                self._press_pos = event.position().toPoint()
                self._selection = QRect(self._press_pos, self._press_pos)
                self._selection_box = None
            self.update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.empty_clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._rotating:
            dx = event.position().toPoint().x() - self._rotation_origin_x
            self._rotation_angle = max(-360.0, min(360.0, self._rotation_origin_angle + dx / 8.0))
            self._update_scaled_pixmap(self.size() if not self.size().isEmpty() else self._preferred_size)
            self.update()
            event.accept()
            return
        if self._press_pos is not None:
            self._selection = QRect(self._press_pos, event.position().toPoint()).normalized()
            self._selection_box = None
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._rotating:
            self._rotating = False
            event.accept()
            return
        if self._press_pos is not None:
            self._selection = QRect(self._press_pos, event.position().toPoint()).normalized()
            self._press_pos = None
            box = self.image_box_from_selection() if self._is_drag_selection(self._selection) else None
            if box is not None:
                self._selection_box = box
                self._restore_selection_from_box()
                self.selection_finished.emit(box, event.position().toPoint(), self._rotation_angle)
            else:
                self._selection = None
                self._selection_box = None
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)
        if self._selection is None:
            return
        painter = QPainter(self)
        painter.setPen(QPen(QColor("#2563eb"), 2, Qt.PenStyle.SolidLine))
        selection = self._selection.normalized()
        painter.drawRect(selection)

    def _pixmap_rect(self) -> QRect:
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return QRect()
        x = max(0, (self.width() - pixmap.width()) // 2)
        y = max(0, (self.height() - pixmap.height()) // 2)
        return QRect(x, y, pixmap.width(), pixmap.height())

    def _update_scaled_pixmap(self, size: QSize) -> None:
        if self._source_pixmap.isNull():
            return
        pixmap = self._source_pixmap
        if abs(self._rotation_angle) >= 0.05:
            pixmap = pixmap.transformed(
                QTransform().rotate(self._rotation_angle),
                Qt.TransformationMode.SmoothTransformation,
            )
        self._image_size = pixmap.size()
        available = QSize(max(1, size.width()), max(1, size.height()))
        self.setPixmap(
            pixmap.scaled(
                available,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._restore_selection_from_box()

    def _restore_selection_from_box(self) -> None:
        if self._selection_box is None or self.pixmap() is None:
            return
        selection = ImagePreviewWindow.display_rect_from_image_box(
            self._selection_box,
            display_rect=self._pixmap_rect(),
            image_size=self._image_size,
        )
        if selection != self._selection:
            self._selection = selection
            self.selection_geometry_changed.emit()

    @staticmethod
    def _is_drag_selection(selection: QRect) -> bool:
        return selection.normalized().width() >= 4 and selection.normalized().height() >= 4


class ImagePreviewWindow(QWidget):
    image_changed = Signal(object)
    image_created = Signal(object)
    image_selected = Signal(object)

    def __init__(
        self,
        image_path: Path,
        parent: QWidget | None = None,
        *,
        storage: PortableStorage | None = None,
        sibling_paths: list[Path] | None = None,
        sibling_index: int = 0,
    ) -> None:
        super().__init__(parent)
        self.image_path = Path(image_path)
        self.editable_image = self._is_editable_image_path(self.image_path)
        self.storage = storage or PortableStorage(Path.cwd())
        self.sibling_paths = [Path(path) for path in sibling_paths] if sibling_paths else [self.image_path]
        self.sibling_index = max(0, min(sibling_index, len(self.sibling_paths) - 1))
        self.history = ManualCropHistory(self.storage, self.image_path)
        self.history.start()
        self.setWindowTitle(self.image_path.name)
        pixmap = QPixmap(str(self.image_path))
        self.preview_size = self.default_preview_size(pixmap.size(), available_size=self._available_screen_size())
        self._pending_box: Box | None = None
        self._pending_rotation_degrees = 0.0
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.back_button = QToolButton(self)
        _configure_icon_button(self.back_button, "←")
        self.back_button.clicked.connect(self.go_back)
        self.forward_button = QToolButton(self)
        _configure_icon_button(self.forward_button, "→")
        self.forward_button.clicked.connect(self.go_forward)
        self.rotate_left_button = QToolButton(self)
        _configure_icon_button(self.rotate_left_button, ROTATE_LEFT_ICON)
        self.rotate_left_button.setToolTip("왼쪽으로 회전")
        self.rotate_left_button.clicked.connect(self.rotate_counterclockwise)
        self.rotate_right_button = QToolButton(self)
        _configure_icon_button(self.rotate_right_button, ROTATE_RIGHT_ICON)
        self.rotate_right_button.setToolTip("오른쪽으로 회전")
        self.rotate_right_button.clicked.connect(self.rotate_clockwise)
        self.tilt_button = QToolButton(self)
        _configure_text_tool_button(self.tilt_button, "기울임")
        self.tilt_button.setCheckable(True)
        self.tilt_button.setToolTip("기울임 모드 (R)")
        self.tilt_button.toggled.connect(self._set_tilt_mode)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.back_button)
        toolbar.addWidget(self.forward_button)
        toolbar.addWidget(self.rotate_left_button)
        toolbar.addWidget(self.rotate_right_button)
        toolbar.addWidget(self.tilt_button)
        toolbar.addStretch(1)

        self.canvas = _CropCanvas(self)
        self.canvas.selection_finished.connect(self._selection_finished)
        self.canvas.selection_started.connect(self._clear_pending_selection)
        self.canvas.empty_clicked.connect(self._clear_pending_selection)
        self.save_button = QPushButton(self.canvas)
        _configure_crop_action_button(self.save_button, "저장")
        self.save_button.clicked.connect(self.save_selection)
        self.save_button.hide()
        self.save_as_button = QPushButton(self.canvas)
        _configure_crop_action_button(self.save_as_button, "새 파일 저장")
        self.save_as_button.clicked.connect(self.save_selection_as)
        self.save_as_button.hide()
        self.canvas.selection_geometry_changed.connect(self._position_selection_buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(toolbar)
        layout.addWidget(self.canvas)
        self._reload_image()
        self.resize(self.default_window_size(self.preview_size))

    def apply_crop(self, box: Box, *, rotation_degrees: float = 0.0) -> Path:
        result = self.history.crop(box, rotation_degrees=rotation_degrees)
        self._reload_image()
        self.image_changed.emit(result)
        return result

    def save_selection(self) -> Path | None:
        if self._pending_box is None:
            return None
        result = self.apply_crop(self._pending_box, rotation_degrees=self.canvas.rotation_angle)
        self._pending_box = None
        self._pending_rotation_degrees = 0.0
        self._hide_selection_buttons()
        return result

    def save_selection_as(self) -> Path | None:
        if self._pending_box is None:
            return None
        result = self.history.crop_to_new_file(self._pending_box, rotation_degrees=self.canvas.rotation_angle)
        self._pending_box = None
        self._pending_rotation_degrees = 0.0
        self._hide_selection_buttons()
        self.image_created.emit(result)
        return result

    def rotate_clockwise(self) -> Path:
        if not self.editable_image:
            return self.image_path
        result = self.history.rotate(clockwise=True)
        self._reload_image()
        self.image_changed.emit(result)
        return result

    def rotate_counterclockwise(self) -> Path:
        if not self.editable_image:
            return self.image_path
        result = self.history.rotate(clockwise=False)
        self._reload_image()
        self.image_changed.emit(result)
        return result

    def go_back(self) -> None:
        if not self.history.can_go_back:
            return
        self.history.back()
        self._reload_image()
        self.image_changed.emit(self.image_path)

    def go_forward(self) -> None:
        if not self.history.can_go_forward:
            return
        self.history.forward()
        self._reload_image()
        self.image_changed.emit(self.image_path)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.BackButton:
            self.go_back()
            event.accept()
            return
        if event.button() == Qt.MouseButton.ForwardButton:
            self.go_forward()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            if self._pending_box is not None:
                self._clear_pending_selection()
                self.canvas.clear_selection()
                event.accept()
                return
            self.close()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Right:
            self.move_sibling(1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Left:
            self.move_sibling(-1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_R and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.rotate_clockwise()
            event.accept()
            return
        if event.key() == Qt.Key.Key_R and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.tilt_button.setChecked(not self.tilt_button.isChecked())
            event.accept()
            return
        super().keyPressEvent(event)

    def move_sibling(self, offset: int) -> None:
        if not self.sibling_paths:
            return
        next_index = self.sibling_index + offset
        if next_index < 0 or next_index >= len(self.sibling_paths):
            return
        self.sibling_index = next_index
        self.image_path = self.sibling_paths[self.sibling_index]
        self.editable_image = self._is_editable_image_path(self.image_path)
        self.history = ManualCropHistory(self.storage, self.image_path)
        self.history.start()
        self.setWindowTitle(self.image_path.name)
        self._pending_box = None
        self._hide_selection_buttons()
        self._reload_image()
        self.image_selected.emit(self.image_path)

    def _selection_finished(self, box: Box, _position: QPoint, rotation_degrees: float = 0.0) -> None:
        self._pending_box = box
        self._pending_rotation_degrees = rotation_degrees
        self._position_selection_buttons()

    def _position_selection_buttons(self) -> None:
        if self._pending_box is None:
            return
        if self.canvas._selection is None:
            self.canvas._selection_box = self._pending_box
            self.canvas._selection = self.display_rect_from_image_box(
                self._pending_box,
                display_rect=self.canvas._pixmap_rect(),
                image_size=self.canvas._image_size,
            )
        self.save_button.adjustSize()
        self.save_as_button.adjustSize()
        gap = 6
        button_width = max(self.save_button.width(), self.save_as_button.width())
        button_height = self.save_button.height() + gap + self.save_as_button.height()
        anchor = self.canvas._selection.normalized().bottomRight() + QPoint(gap, gap)
        x = min(max(0, anchor.x()), max(0, self.canvas.width() - button_width))
        y = min(max(0, anchor.y()), max(0, self.canvas.height() - button_height))
        self.save_button.move(x, y)
        self.save_as_button.move(x, y + self.save_button.height() + gap)
        self.save_button.show()
        self.save_as_button.show()
        self.save_button.raise_()
        self.save_as_button.raise_()

    def _hide_selection_buttons(self) -> None:
        self.save_button.hide()
        self.save_as_button.hide()

    def _set_tilt_mode(self, enabled: bool) -> None:
        if not enabled and self.canvas.tilt_mode:
            rotation_degrees = self.canvas.rotation_angle
            self.canvas.set_tilt_mode(False)
            self._clear_pending_selection()
            if self.editable_image and abs(rotation_degrees) >= 0.05:
                result = self.history.rotate_degrees(rotation_degrees)
                self._reload_image()
                self.image_changed.emit(result)
            return
        self.canvas.set_tilt_mode(enabled)
        self._clear_pending_selection()

    def _clear_pending_selection(self) -> None:
        self._pending_box = None
        self._pending_rotation_degrees = 0.0
        self._hide_selection_buttons()

    def _reload_image(self) -> None:
        self.editable_image = self._is_editable_image_path(self.image_path)
        pixmap = QPixmap(str(self.image_path))
        self.preview_size = self.default_preview_size(pixmap.size(), available_size=self._available_screen_size())
        self.canvas.set_image(self.image_path, self.preview_size)
        if self.tilt_button.isChecked():
            self.tilt_button.setChecked(False)
        self.back_button.setEnabled(self.history.can_go_back)
        self.forward_button.setEnabled(self.history.can_go_forward)
        self.rotate_left_button.setEnabled(self.editable_image)
        self.rotate_right_button.setEnabled(self.editable_image)
        self.tilt_button.setEnabled(self.editable_image)
        if not self.editable_image and self.tilt_button.isChecked():
            self.tilt_button.setChecked(False)

    @staticmethod
    def _scaled_size(size: QSize, *, max_long_side: int) -> QSize:
        if size.isEmpty():
            return QSize(640, 480)
        long_side = max(size.width(), size.height())
        if long_side <= max_long_side:
            return size
        scale = max_long_side / long_side
        return QSize(max(1, round(size.width() * scale)), max(1, round(size.height() * scale)))

    @staticmethod
    def default_preview_size(size: QSize, *, available_size: QSize | None = None) -> QSize:
        if size.isEmpty():
            return QSize(640, 480)
        available = available_size if available_size is not None and not available_size.isEmpty() else QSize(1920, 1080)
        max_width = max(320, min(1920, available.width() - 80))
        max_height = max(320, available.height() - 96)
        scale = min(max_width / size.width(), max_height / size.height(), 1.0)
        return QSize(max(1, round(size.width() * scale)), max(1, round(size.height() * scale)))

    @staticmethod
    def default_window_size(preview_size: QSize) -> QSize:
        return QSize(preview_size.width(), preview_size.height() + 48)

    def _available_screen_size(self) -> QSize:
        app = QApplication.instance()
        if app is not None and app.platformName().casefold() == "offscreen":
            return QSize(1920, 1080)
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return QSize(1920, 1080)
        return screen.availableGeometry().size()

    @staticmethod
    def image_box_from_display_rect(selection: QRect, *, display_rect: QRect, image_size: QSize) -> Box:
        rect = selection.normalized().intersected(display_rect)
        if rect.isEmpty() or display_rect.isEmpty() or image_size.isEmpty():
            return (0, 0, 1, 1)
        scale_x = image_size.width() / display_rect.width()
        scale_y = image_size.height() / display_rect.height()
        left = round((rect.left() - display_rect.left()) * scale_x)
        top = round((rect.top() - display_rect.top()) * scale_y)
        right = round((rect.right() + 1 - display_rect.left()) * scale_x)
        bottom = round((rect.bottom() + 1 - display_rect.top()) * scale_y)
        return (
            max(0, min(image_size.width() - 1, left)),
            max(0, min(image_size.height() - 1, top)),
            max(1, min(image_size.width(), right)),
            max(1, min(image_size.height(), bottom)),
        )

    @staticmethod
    def display_rect_from_image_box(box: Box, *, display_rect: QRect, image_size: QSize) -> QRect:
        if display_rect.isEmpty() or image_size.isEmpty():
            return QRect()
        left_px, top_px, right_px, bottom_px = box
        scale_x = display_rect.width() / image_size.width()
        scale_y = display_rect.height() / image_size.height()
        left = display_rect.left() + round(max(0, min(image_size.width(), left_px)) * scale_x)
        top = display_rect.top() + round(max(0, min(image_size.height(), top_px)) * scale_y)
        right = display_rect.left() + round(max(0, min(image_size.width(), right_px)) * scale_x)
        bottom = display_rect.top() + round(max(0, min(image_size.height(), bottom_px)) * scale_y)
        return QRect(left, top, max(1, right - left), max(1, bottom - top))

    @staticmethod
    def _is_editable_image_path(path: Path) -> bool:
        return Path(path).suffix.lower() in EDITABLE_IMAGE_EXTENSIONS


class _PreviewThumbnail(QWidget):
    def __init__(
        self,
        image_path: Path,
        open_callback: Callable[[Path], None],
        parent: QWidget | None = None,
        *,
        badge_text: str = "",
    ) -> None:
        super().__init__(parent)
        self.image_path = image_path
        self.open_callback = open_callback
        self.setMinimumSize(1, 1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(1, 1)
        self.name_label = QLabel(image_path.name, self)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setStyleSheet("color: #475569; font-size: 11px;")
        self.badge_label = QLabel(badge_text, self)
        self.badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_label.setStyleSheet(
            "background: #334155; color: #ffffff; border-radius: 9px; padding: 3px 8px; font-size: 12px; font-weight: 700;"
        )
        self.badge_label.setMinimumSize(34, 22)
        self.badge_label.setVisible(bool(badge_text))
        self.badge_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.image_label, 1)
        layout.addWidget(self.name_label)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if not self.badge_label.isHidden():
            self._position_badge()

    def _position_badge(self) -> None:
        layout = self.layout()
        if layout is not None:
            layout.activate()
        self.badge_label.adjustSize()
        pixmap = self.image_label.pixmap()
        image_rect = self.image_label.geometry()
        x = image_rect.x() + 6
        y = image_rect.y() + 6
        if pixmap is not None and not pixmap.isNull():
            x = image_rect.x() + max(0, (image_rect.width() - pixmap.width()) // 2) + 6
            y = image_rect.y() + max(0, (image_rect.height() - pixmap.height()) // 2) + 6
        self.badge_label.move(x, y)
        self.badge_label.raise_()

    def set_preview_size(self, size: QSize) -> None:
        self.setFixedSize(size)
        pixmap = QPixmap(str(self.image_path))
        if pixmap.isNull():
            self.image_label.setText(self.image_path.name)
            return
        self.image_label.setText("")
        image_size = QSize(size.width(), max(1, size.height() - 22))
        self.image_label.setPixmap(
            pixmap.scaled(
                image_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        if not self.badge_label.isHidden():
            self._position_badge()

    def set_preview_pixmap(self, size: QSize, pixmap: QPixmap) -> None:
        self.setFixedSize(size)
        if pixmap.isNull():
            self.image_label.setText(self.image_path.name)
            self.image_label.setPixmap(QPixmap())
            return
        self.image_label.setText("")
        image_size = QSize(size.width(), max(1, size.height() - 22))
        self.image_label.setPixmap(
            pixmap.scaled(
                image_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        if not self.badge_label.isHidden():
            self._position_badge()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_callback(self.image_path)
            return
        super().mousePressEvent(event)


class _PreviewFullscreenWindow(QWidget):
    closed = Signal()

    def __init__(
        self,
        paths: list[Path],
        parent: QWidget | None = None,
        *,
        storage: PortableStorage | None = None,
        edit_path_resolver: Callable[[Path], Path | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preview")
        self.panel = PreviewPanel(
            allow_fullscreen=False,
            parent=self,
            storage=storage,
            edit_path_resolver=edit_path_resolver,
        )
        self.panel.set_paths(paths)
        self.close_button = QToolButton(self)
        _configure_icon_button(self.close_button, "X")
        self.close_button.clicked.connect(self.close)
        header = QHBoxLayout()
        header.addStretch(1)
        header.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(header)
        layout.addWidget(self.panel)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.closed.emit()
        super().closeEvent(event)


class PreviewPanel(QFrame):
    image_created = Signal(object)
    image_selected = Signal(object)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        allow_fullscreen: bool = True,
        storage: PortableStorage | None = None,
        edit_path_resolver: Callable[[Path], Path | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("previewPanel")
        self.setMinimumWidth(280)
        self.paths: list[Path] = []
        self.navigation_paths: list[Path] = []
        self.page_badges: dict[Path, str] = {}
        self.vertical_mode = False
        self.grid_columns = 0
        self.fullscreen_window: _PreviewFullscreenWindow | None = None
        self._image_windows: list[ImagePreviewWindow] = []
        self.storage = storage or PortableStorage(Path.cwd())
        self.edit_path_resolver = edit_path_resolver
        self._thumbnail_cache: dict[tuple[str, int, int, int], QPixmap] = {}
        self._content_signature: tuple | None = None
        self._layout_signature: tuple | None = None
        self._thumbnail_queue: list[tuple[int, _PreviewThumbnail, Path, QSize]] = []
        self._thumbnail_generation = 0
        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.setSingleShot(True)
        self.thumbnail_timer.timeout.connect(self._load_next_thumbnail)

        header = QHBoxLayout()
        header.setContentsMargins(10, 8, 10, 0)
        header.addStretch(1)
        self.rotate_left_button = QToolButton(self)
        _configure_icon_button(self.rotate_left_button, ROTATE_LEFT_ICON)
        self.rotate_left_button.setToolTip("왼쪽으로 회전")
        self.rotate_left_button.clicked.connect(lambda: self.rotate_paths(clockwise=False))
        header.addWidget(self.rotate_left_button)
        self.rotate_right_button = QToolButton(self)
        _configure_icon_button(self.rotate_right_button, ROTATE_RIGHT_ICON)
        self.rotate_right_button.setToolTip("오른쪽으로 회전")
        self.rotate_right_button.clicked.connect(lambda: self.rotate_paths(clockwise=True))
        header.addWidget(self.rotate_right_button)
        self.fullscreen_button = QToolButton(self)
        _configure_icon_button(self.fullscreen_button, FULLSCREEN_ICON)
        self.fullscreen_button.setToolTip("전체화면")
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        self.fullscreen_button.setVisible(allow_fullscreen)
        header.addWidget(self.fullscreen_button)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.container = QWidget(self.scroll)
        self.grid = QGridLayout(self.container)
        self.grid.setContentsMargins(10, 10, 10, 10)
        self.grid.setSpacing(8)
        self.scroll.setWidget(self.container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self.scroll, 1)

    def set_paths(
        self,
        paths: list[Path],
        *,
        vertical: bool = False,
        page_badges: dict[Path, str] | None = None,
        navigation_paths: list[Path] | None = None,
        defer_reflow: bool = False,
    ) -> None:
        next_paths = [Path(path) for path in paths]
        next_page_badges = {Path(path): text for path, text in (page_badges or {}).items()}
        next_navigation_paths = [Path(path) for path in navigation_paths] if navigation_paths is not None else list(next_paths)
        signature = self._make_content_signature(
            next_paths,
            vertical=vertical,
            page_badges=next_page_badges,
            navigation_paths=next_navigation_paths,
        )
        if signature == self._content_signature and self.grid.count() > 0:
            self._sync_action_state()
            return

        self.paths = next_paths
        self.vertical_mode = vertical
        self.page_badges = next_page_badges
        self.navigation_paths = next_navigation_paths
        self._content_signature = signature
        self._layout_signature = None
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if vertical else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._sync_action_state()
        if defer_reflow:
            return
        self.reflow()

    def reflow(self) -> None:
        if not self.paths:
            self._clear()
            self.grid_columns = 0
            self._layout_signature = None
            return

        viewport_size = self.scroll.viewport().size()
        available_width = max(240, self.width() or viewport_size.width() or 360)
        available_height = max(240, (self.height() - 40) or viewport_size.height() or 520)
        layout_signature = (self._content_signature, available_width, available_height)
        if layout_signature == self._layout_signature and self.grid.count() > 0:
            return
        self._layout_signature = layout_signature
        self._clear()

        if self.vertical_mode:
            columns = 1
            content_width = max(1, available_width - 24)
            cell_size = QSize(content_width, max(220, round(content_width * 1.35)))
        else:
            columns, cell_size = self._layout_for_count(len(self.paths), available_width, available_height)
        self.grid_columns = columns
        self._thumbnail_generation += 1
        self._thumbnail_queue.clear()

        for index, path in enumerate(self.paths):
            label = _PreviewThumbnail(
                path,
                self.open_image_window,
                self.container,
                badge_text=self.page_badges.get(path, ""),
            )
            cached = self._cached_thumbnail_for(path, cell_size)
            if cached is None:
                label.set_preview_pixmap(cell_size, QPixmap())
                self._thumbnail_queue.append((self._thumbnail_generation, label, path, cell_size))
            else:
                label.set_preview_pixmap(cell_size, cached)
            self.grid.addWidget(label, index // columns, index % columns)
        if self._thumbnail_queue:
            self.thumbnail_timer.start(THUMBNAIL_LOAD_INTERVAL_MS)

    def toggle_fullscreen(self) -> None:
        if self.fullscreen_window is not None:
            self.exit_fullscreen()
            return
        self.fullscreen_window = _PreviewFullscreenWindow(
            self.paths,
            storage=self.storage,
            edit_path_resolver=self.edit_path_resolver,
        )
        self.fullscreen_window.panel.image_created.connect(self._add_created_image)
        self.fullscreen_window.panel.image_selected.connect(self._handle_image_window_selected)
        self.fullscreen_window.closed.connect(self._fullscreen_closed)
        self.fullscreen_window.showFullScreen()

    def rotate_paths(self, *, clockwise: bool = True) -> None:
        if len(self.paths) != 1:
            return
        path = self.paths[0]
        if not path.exists() or not self._is_editable_image_path(path):
            return
        rotate_image_in_place(path, clockwise=clockwise, temp_dir=self.storage.temp_dir / "originals")
        self._refresh_after_image_change()

    def _sync_action_state(self) -> None:
        rotate_enabled = len(self.paths) == 1 and self._is_editable_image_path(self.paths[0])
        self.rotate_left_button.setVisible(rotate_enabled)
        self.rotate_right_button.setVisible(rotate_enabled)
        self.rotate_left_button.setEnabled(rotate_enabled)
        self.rotate_right_button.setEnabled(rotate_enabled)

    def exit_fullscreen(self) -> None:
        window = self.fullscreen_window
        if window is None:
            return
        self.fullscreen_window = None
        window.close()

    def close_auxiliary_windows(self) -> None:
        self.exit_fullscreen()
        windows = list(self._image_windows)
        self._image_windows.clear()
        for window in windows:
            window.close()

    def open_image_window(self, image_path: Path) -> ImagePreviewWindow | None:
        path = Path(image_path)
        if self.edit_path_resolver is not None:
            resolved = self.edit_path_resolver(path)
            if resolved is None:
                return None
            path = Path(resolved)
        if not self._is_editable_image_path(path):
            return None
        self._image_windows = [window for window in self._image_windows if window.isVisible()]
        for window in self._image_windows:
            if window.image_path != path:
                continue
            window.show()
            window.raise_()
            window.activateWindow()
            return window
        try:
            index = self.navigation_paths.index(path)
        except ValueError:
            index = 0
        window = ImagePreviewWindow(path, storage=self.storage, sibling_paths=self.navigation_paths, sibling_index=index)
        window.image_changed.connect(lambda _path: self._refresh_after_image_change())
        window.image_created.connect(self._add_created_image)
        window.image_selected.connect(self._handle_image_window_selected)
        self._image_windows.append(window)
        self._place_image_window(window)
        window.show()
        window.setFocus(Qt.FocusReason.OtherFocusReason)
        return window

    @staticmethod
    def _is_editable_image_path(path: Path) -> bool:
        return Path(path).suffix.lower() in EDITABLE_IMAGE_EXTENSIONS

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if self.paths:
            self.reflow()

    def _fullscreen_closed(self) -> None:
        self.fullscreen_window = None

    def refresh_current_previews(self) -> None:
        self._refresh_after_image_change()

    def _refresh_after_image_change(self) -> None:
        self._thumbnail_cache.clear()
        self._layout_signature = None
        self._thumbnail_queue.clear()
        self.thumbnail_timer.stop()
        self.reflow()

    def _add_created_image(self, image_path: Path) -> None:
        path = Path(image_path)
        if path not in self.paths:
            self.paths.append(path)
            self._content_signature = None
        self._sync_action_state()
        self._refresh_after_image_change()
        self.image_created.emit(path)

    def _handle_image_window_selected(self, image_path: Path) -> None:
        self.image_selected.emit(Path(image_path))

    def _place_image_window(self, window: QWidget) -> None:
        app = QApplication.instance()
        screen = QApplication.primaryScreen() if app is not None else None
        available = screen.availableGeometry() if screen is not None else QRect(0, 0, 1920, 1080)
        size = window.size()
        if size.isEmpty():
            size = window.sizeHint()
        width = max(1, min(size.width(), available.width()))
        height = max(1, min(size.height(), available.height()))
        existing_rects = [
            QRect(other.pos(), other.size())
            for other in self._image_windows
            if other is not window and other.isVisible()
        ]
        step = 40
        candidates: list[QPoint] = []
        max_x = max(available.left(), available.right() - width)
        max_y = max(available.top(), available.bottom() - height)
        y = available.top() + 24
        while y <= max_y:
            x = available.left() + 24
            while x <= max_x:
                candidates.append(QPoint(x, y))
                x += step
            y += step
        if not candidates:
            candidates = [available.topLeft()]
        for point in candidates:
            rect = QRect(point, QSize(width, height))
            if not any(rect.intersects(existing) for existing in existing_rects):
                window.move(point)
                return
        window.move(candidates[(len(self._image_windows) - 1) % len(candidates)])

    def _clear(self) -> None:
        self._thumbnail_queue.clear()
        self.thumbnail_timer.stop()
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    @staticmethod
    def _make_content_signature(
        paths: list[Path],
        *,
        vertical: bool,
        page_badges: dict[Path, str],
        navigation_paths: list[Path],
    ) -> tuple:
        return (
            tuple(str(Path(path)) for path in paths),
            bool(vertical),
            tuple(sorted((str(Path(path)), text) for path, text in page_badges.items())),
            tuple(str(Path(path)) for path in navigation_paths),
        )

    def _thumbnail_key(self, path: Path, size: QSize) -> tuple[str, int, int, int]:
        path = Path(path)
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            mtime_ns = 0
        return (str(path), mtime_ns, size.width(), size.height())

    def _cached_thumbnail_for(self, path: Path, size: QSize) -> QPixmap | None:
        return self._thumbnail_cache.get(self._thumbnail_key(path, size))

    def _load_next_thumbnail(self) -> None:
        while self._thumbnail_queue:
            generation, label, path, size = self._thumbnail_queue.pop(0)
            if generation != self._thumbnail_generation:
                continue
            try:
                if label.parent() is None:
                    continue
                label.set_preview_pixmap(size, self._thumbnail_for(path, size))
            except RuntimeError:
                continue
            break
        if self._thumbnail_queue:
            self.thumbnail_timer.start(THUMBNAIL_LOAD_INTERVAL_MS)

    def _thumbnail_for(self, path: Path, size: QSize) -> QPixmap:
        key = self._thumbnail_key(path, size)
        cached = self._thumbnail_cache.get(key)
        if cached is not None:
            return cached

        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        source_size = reader.size()
        if not source_size.isEmpty():
            scaled = source_size.scaled(size, Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(scaled)
        image = reader.read()
        pixmap = QPixmap.fromImage(image)
        if not pixmap.isNull() and (pixmap.width() > size.width() or pixmap.height() > size.height()):
            pixmap = pixmap.scaled(
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._thumbnail_cache[key] = pixmap
        if len(self._thumbnail_cache) > THUMBNAIL_CACHE_LIMIT:
            for old_key in list(self._thumbnail_cache)[:THUMBNAIL_CACHE_TRIM_COUNT]:
                self._thumbnail_cache.pop(old_key, None)
        return pixmap

    @staticmethod
    def _layout_for_count(count: int, available_width: int, available_height: int) -> tuple[int, QSize]:
        if count <= 1:
            return 1, QSize(max(1, available_width - 24), max(1, available_height - 24))

        best_columns = 1
        best_side = 1
        for columns in range(1, count + 1):
            rows = ceil(count / columns)
            cell_width = max(1, (available_width - 20 - ((columns - 1) * 8)) // columns)
            cell_height = max(1, (available_height - 20 - ((rows - 1) * 8)) // rows)
            side = min(cell_width, cell_height)
            if side > best_side:
                best_side = side
                best_columns = columns
        rows = ceil(count / best_columns)
        return best_columns, QSize(
            max(1, (available_width - 20 - ((best_columns - 1) * 8)) // best_columns),
            max(1, (available_height - 20 - ((rows - 1) * 8)) // rows),
        )
