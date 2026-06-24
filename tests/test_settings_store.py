from __future__ import annotations

from pathlib import Path

from doc_auto.services.settings_store import AppSettings, SettingsStore
from doc_auto.services.temp_storage import PortableStorage


def test_settings_store_round_trips_ui_and_processing_settings(tmp_path: Path) -> None:
    store = SettingsStore(PortableStorage(tmp_path))
    settings = AppSettings(
        temp_dir=tmp_path / "custom_temp",
        rotation_enabled=False,
        resize_enabled=False,
        png_to_jpg_enabled=False,
        archive_delete_source=True,
        archive_extract_to_current_dir=True,
        pdf_tiff_extract_to_current_dir=False,
        resize_max_long_side=1600,
        png_to_jpg_threshold_bytes=2_000_000,
        jpeg_quality=90,
    )

    store.save(settings)

    loaded = store.load()
    assert loaded == settings


def test_settings_store_defaults_missing_values(tmp_path: Path) -> None:
    store = SettingsStore(PortableStorage(tmp_path))
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text('{"auto_start_on_drop": false, "unknown": "ignored"}', encoding="utf-8")

    loaded = store.load()

    assert loaded.auto_start_on_drop is True
    assert loaded.rotation_enabled is True
    assert loaded.resize_enabled is True
    assert loaded.png_to_jpg_enabled is True
    assert loaded.archive_delete_source is False
    assert loaded.archive_extract_to_current_dir is False
    assert loaded.pdf_tiff_extract_to_current_dir is True
    assert loaded.temp_dir is None


def test_settings_resize_options_include_feature_toggles() -> None:
    settings = AppSettings(resize_enabled=False, png_to_jpg_enabled=False)

    options = settings.resize_options

    assert options.resize_enabled is False
    assert options.png_to_jpg_enabled is False
