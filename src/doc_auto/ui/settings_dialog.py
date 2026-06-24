from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from doc_auto.services.settings_store import AppSettings


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        parent: QWidget | None = None,
        *,
        default_temp_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("설정")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setMinimumHeight(680)
        self._default_temp_dir = default_temp_dir

        self.rotation = QCheckBox("회전")
        self.rotation.setChecked(settings.rotation_enabled)
        self.resize_enabled = QCheckBox("리사이징")
        self.resize_enabled.setChecked(settings.resize_enabled)
        self.png_to_jpg = QCheckBox("PNG-JPG 변환")
        self.png_to_jpg.setChecked(settings.png_to_jpg_enabled)
        self.pdf_convert_delete_source = QCheckBox("PDF 변환 후 원본파일 삭제")
        self.pdf_convert_delete_source.setChecked(settings.pdf_convert_delete_source)
        self.pdf_bundle_delete_source = QCheckBox("PDF 묶음 후 원본파일 삭제")
        self.pdf_bundle_delete_source.setChecked(settings.pdf_bundle_delete_source)
        self.archive_delete_source = QCheckBox("압축파일 작업 후 원본파일 삭제")
        self.archive_delete_source.setChecked(settings.archive_delete_source)
        self.archive_extract_to_current_dir = QCheckBox("압축파일 현재 위치에 작업 풀기")
        self.archive_extract_to_current_dir.setChecked(settings.archive_extract_to_current_dir)
        self.pdf_tiff_extract_to_current_dir = QCheckBox("PDF/TIFF 현재 위치에 작업 풀기")
        self.pdf_tiff_extract_to_current_dir.setChecked(settings.pdf_tiff_extract_to_current_dir)

        self.temp_dir = self._path_row(settings.temp_dir or default_temp_dir)
        self.resize_max = self._spin(settings.resize_max_long_side, 640, 8000)
        self.jpeg_quality = self._spin(settings.jpeg_quality, 1, 100)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setVerticalSpacing(10)
        form.addRow("temp 폴더", self.temp_dir)
        form.addRow("긴 변 최대값", self.resize_max)
        form.addRow("JPG 품질", self.jpeg_quality)

        toggles = QVBoxLayout()
        for checkbox in (
            self.resize_enabled,
            self.png_to_jpg,
            self.rotation,
            self.pdf_convert_delete_source,
            self.pdf_bundle_delete_source,
            self.archive_delete_source,
            self.archive_extract_to_current_dir,
            self.pdf_tiff_extract_to_current_dir,
        ):
            toggles.addWidget(checkbox)

        shortcuts = QVBoxLayout()
        self.shortcut_labels = [
            QLabel("Delete: 선택 항목 목록에서 제거"),
            QLabel("Ctrl+A: 항목 전체 선택"),
            QLabel("Ctrl+R: 선택 파일 우회전"),
            QLabel("F: 전체화면 모드"),
            QLabel("Esc: 전체화면 미리보기/이미지 편집창 닫기"),
            QLabel("←/→: 이미지 편집창 이전/다음 이미지"),
            QLabel("마우스 뒤로/앞으로: 이미지 편집창 되돌리기/다시 실행"),
        ]
        for label in self.shortcut_labels:
            label.setStyleSheet("color: #475569; font-size: 12px;")
            shortcuts.addWidget(label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        layout.addWidget(self._section_label("경로"))
        layout.addLayout(form)
        layout.addWidget(self._section_label("기능"))
        layout.addLayout(toggles)
        layout.addWidget(self._section_label("단축키"))
        layout.addLayout(shortcuts)
        layout.addStretch(1)
        layout.addWidget(buttons)
        self.setStyleSheet(
            """
            QDialog { background: #f8fafc; color: #0f172a; }
            QLabel { color: #0f172a; }
            QLineEdit, QSpinBox {
                background: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px;
            }
            QCheckBox { color: #0f172a; spacing: 8px; min-height: 24px; }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
                background: #ffffff;
                border: 1px solid #64748b;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background: #334155;
                border: 1px solid #334155;
            }
            QPushButton {
                background: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 7px 12px;
            }
            QPushButton:hover { background: #f1f5f9; }
            """
        )

    def settings(self) -> AppSettings:
        return AppSettings(
            auto_start_on_drop=True,
            temp_dir=self._path_value(self.temp_dir),
            rotation_enabled=self.rotation.isChecked(),
            resize_enabled=self.resize_enabled.isChecked(),
            png_to_jpg_enabled=self.png_to_jpg.isChecked(),
            pdf_convert_delete_source=self.pdf_convert_delete_source.isChecked(),
            pdf_bundle_delete_source=self.pdf_bundle_delete_source.isChecked(),
            archive_delete_source=self.archive_delete_source.isChecked(),
            archive_extract_to_current_dir=self.archive_extract_to_current_dir.isChecked(),
            pdf_tiff_extract_to_current_dir=self.pdf_tiff_extract_to_current_dir.isChecked(),
            always_unbundle_for_edit=self._settings.always_unbundle_for_edit,
            resize_max_long_side=self.resize_max.value(),
            png_to_jpg_threshold_bytes=self._settings.png_to_jpg_threshold_bytes,
            jpeg_quality=self.jpeg_quality.value(),
        )

    def _path_row(self, value: Path | None) -> QWidget:
        container = QWidget(self)
        edit = QLineEdit(str(value) if value else "")
        button = QPushButton("선택")
        button.clicked.connect(lambda: self._choose_folder(edit))
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit, 1)
        layout.addWidget(button)
        container.line_edit = edit  # type: ignore[attr-defined]
        return container

    def _choose_folder(self, edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "폴더 선택", edit.text())
        if path:
            edit.setText(path)

    @staticmethod
    def _path_value(container: QWidget) -> Path | None:
        edit = container.line_edit  # type: ignore[attr-defined]
        text = edit.text().strip()
        return Path(text) if text else None

    @staticmethod
    def _spin(value: int, minimum: int, maximum: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-size: 14px; font-weight: 700; color: #0f172a;")
        return label
