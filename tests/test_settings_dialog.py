from pathlib import Path

import pytest

from doc_auto.services.settings_store import AppSettings


def test_settings_dialog_round_trips_controls(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.settings_dialog import SettingsDialog

    create_app([])
    settings = AppSettings(
        temp_dir=tmp_path / "temp",
        rotation_enabled=False,
        resize_enabled=False,
        png_to_jpg_enabled=False,
        pdf_convert_delete_source=False,
        pdf_bundle_delete_source=False,
        archive_delete_source=True,
        archive_extract_to_current_dir=True,
        pdf_tiff_extract_to_current_dir=False,
        resize_max_long_side=1600,
        png_to_jpg_threshold_bytes=2_000_000,
        jpeg_quality=88,
    )

    dialog = SettingsDialog(settings)
    loaded = dialog.settings()

    assert loaded == settings


def test_settings_dialog_updates_values_from_widgets(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.settings_dialog import SettingsDialog

    create_app([])
    dialog = SettingsDialog(AppSettings())

    dialog.rotation.setChecked(False)
    dialog.resize_enabled.setChecked(False)
    dialog.png_to_jpg.setChecked(False)
    dialog.pdf_convert_delete_source.setChecked(False)
    dialog.pdf_bundle_delete_source.setChecked(False)
    dialog.archive_delete_source.setChecked(True)
    dialog.archive_extract_to_current_dir.setChecked(True)
    dialog.pdf_tiff_extract_to_current_dir.setChecked(False)
    dialog.temp_dir.line_edit.setText(str(tmp_path / "custom_temp"))  # type: ignore[attr-defined]
    dialog.resize_max.setValue(1400)
    dialog.jpeg_quality.setValue(91)

    settings = dialog.settings()

    assert settings.auto_start_on_drop is True
    assert settings.rotation_enabled is False
    assert settings.resize_enabled is False
    assert settings.png_to_jpg_enabled is False
    assert settings.pdf_convert_delete_source is False
    assert settings.pdf_bundle_delete_source is False
    assert settings.archive_delete_source is True
    assert settings.archive_extract_to_current_dir is True
    assert settings.pdf_tiff_extract_to_current_dir is False
    assert settings.temp_dir == tmp_path / "custom_temp"
    assert settings.resize_max_long_side == 1400
    assert settings.png_to_jpg_threshold_bytes == AppSettings().png_to_jpg_threshold_bytes
    assert settings.jpeg_quality == 91


def test_settings_dialog_displays_default_paths_and_no_png_threshold(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.settings_dialog import SettingsDialog

    create_app([])
    default_temp = tmp_path / "data" / "temp"

    dialog = SettingsDialog(AppSettings(), default_temp_dir=default_temp)

    assert dialog.temp_dir.line_edit.text() == str(default_temp)  # type: ignore[attr-defined]
    assert not hasattr(dialog, "log_dir")
    assert dialog.png_to_jpg.text() == "PNG-JPG 변환"
    assert dialog.resize_enabled.text() == "리사이징"
    assert not hasattr(dialog, "png_threshold_kb")


def test_settings_dialog_shows_shortcuts_and_pdf_delete_options(monkeypatch) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.settings_dialog import SettingsDialog

    create_app([])
    dialog = SettingsDialog(AppSettings())

    assert dialog.pdf_convert_delete_source.isChecked()
    assert dialog.pdf_bundle_delete_source.isChecked()
    assert hasattr(dialog, "archive_delete_source")
    assert hasattr(dialog, "archive_extract_to_current_dir")
    assert hasattr(dialog, "pdf_tiff_extract_to_current_dir")
    assert dialog.pdf_tiff_extract_to_current_dir.isChecked()
    assert not hasattr(dialog, "auto_start")
    shortcut_text = "\n".join(label.text() for label in dialog.shortcut_labels)
    assert "Delete" in shortcut_text
    assert "Ctrl+R" in shortcut_text
    assert "Ctrl+A" in shortcut_text
    assert "F" in shortcut_text
    assert "Esc" in shortcut_text
    assert "이미지 편집창 닫기" in shortcut_text


def test_settings_dialog_makes_checkbox_indicators_visible(monkeypatch) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.settings_dialog import SettingsDialog

    create_app([])
    dialog = SettingsDialog(AppSettings())

    style = dialog.styleSheet()

    assert "QCheckBox::indicator" in style
    assert "border: 1px solid #64748b" in style
    assert "QCheckBox::indicator:checked" in style


def test_settings_dialog_hides_removed_uncertain_features(monkeypatch) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from doc_auto.app import create_app
    from doc_auto.ui.settings_dialog import SettingsDialog

    create_app([])
    dialog = SettingsDialog(AppSettings())

    assert not hasattr(dialog, "rename")
    assert not hasattr(dialog, "deskew")
    assert not hasattr(dialog, "canvas_trim")
    assert not hasattr(dialog, "crop")
    assert not hasattr(dialog, "classification")
