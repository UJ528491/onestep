from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile

import pytest

from tests import _bootstrap  # noqa: F401


UI_TEST_FILES = {
    "test_main_window_cleanup.py",
    "test_main_window_resize.py",
    "test_main_window_pdf.py",
}

UI_TEST_NAMES = {
    "test_app_imports_create_app",
    "test_main_window_uses_branding",
    "test_run_py_imports_without_pythonpath_or_project_cwd",
}


def pytest_configure() -> None:
    temp_root = Path.cwd() / ".pytest_tmp" / str(os.getpid())
    temp_root.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(temp_root)
    os.environ["TEMP"] = str(temp_root)
    tempfile.tempdir = str(temp_root)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if importlib.util.find_spec("PySide6") is not None:
        return

    skip_ui = pytest.mark.skip(reason="PySide6 is not installed in this test environment")
    for item in items:
        path = Path(str(item.path))
        if path.name in UI_TEST_FILES or item.name in UI_TEST_NAMES:
            item.add_marker(skip_ui)
