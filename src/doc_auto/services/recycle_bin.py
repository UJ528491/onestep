from __future__ import annotations

from pathlib import Path
import os
import shutil

from doc_auto.services.shell_notify import notify_path_changed


def move_to_recycle_bin(path: Path) -> None:
    path = Path(path)
    if not path.exists():
        return
    parent = path.parent
    if os.name == "nt":
        _move_to_windows_recycle_bin(path)
        if path.exists():
            _delete_permanently(path)
        notify_path_changed(parent)
        return
    _delete_permanently(path)
    notify_path_changed(parent)


def _delete_permanently(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _move_to_windows_recycle_bin(path: Path) -> None:
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.UINT),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    operation = SHFILEOPSTRUCTW()
    operation.hwnd = None
    operation.wFunc = 0x0003
    operation.pFrom = str(path.resolve()) + "\0\0"
    operation.pTo = None
    operation.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0 or operation.fAnyOperationsAborted:
        raise OSError(f"Recycle bin move failed: {result}")
