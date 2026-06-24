from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
from typing import Any


class PortableStorage:
    def __init__(self, app_root: Path) -> None:
        self.app_root = Path(app_root)
        self.data_dir = self.app_root / "data"
        self.temp_dir = self.data_dir / "temp"
        self.cache_dir = self.temp_dir / "cache"
        self.ensure_dirs()

    def ensure_dirs(self) -> None:
        self.cache_dir = self.temp_dir / "cache"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def clear_temp(self) -> None:
        self._assert_safe_temp_dir()
        if self.temp_dir.exists():
            for child in self.temp_dir.iterdir():
                self._remove_path(child)
        self.ensure_dirs()

    def _assert_safe_temp_dir(self) -> None:
        temp = self.temp_dir.resolve()
        data = self.data_dir.resolve()
        try:
            temp.relative_to(data)
            return
        except ValueError:
            pass

        unsafe_roots = {Path(temp.anchor).resolve(), self.app_root.resolve(), data, Path.home().resolve()}
        if temp in unsafe_roots or not self._looks_like_temp_dir(temp):
            raise ValueError(f"Refusing to clear unsafe temp directory: {temp}")

    @staticmethod
    def _looks_like_temp_dir(path: Path) -> bool:
        name = path.name.lower()
        return (
            name in {"temp", "tmp"}
            or name.startswith(("temp", "tmp"))
            or name.endswith(("temp", "tmp", "_temp", "_tmp", "-temp", "-tmp", ".temp", ".tmp"))
        )

    def _remove_path(self, path: Path) -> None:
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, onerror=self._make_writable_and_retry)
            else:
                self._unlink_file(path)
        except FileNotFoundError:
            return

    def _unlink_file(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except PermissionError:
            path.chmod(stat.S_IREAD | stat.S_IWRITE)
            path.unlink(missing_ok=True)

    @staticmethod
    def _make_writable_and_retry(function: Any, path: str, exc_info: Any) -> None:
        error = exc_info[1]
        if not isinstance(error, PermissionError):
            raise error
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        function(path)
