from __future__ import annotations

import os
import re
from pathlib import Path


def text_excerpt(text: str, limit: int = 300) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:limit]


def recycle_path(path: Path) -> None:
    if not path.exists():
        return
    path_str = str(path.resolve())
    if os.name == "nt":
        try:
            import pythoncom
            pythoncom.CoInitialize()
            try:
                from win32com.shell import shell, shellcon
                # pywin32의 SHFileOperation은 32/64비트 정렬 및 더블 널 버퍼를 완벽하고 안전하게 자동 처리합니다.
                shell.SHFileOperation((
                    0,
                    shellcon.FO_DELETE,
                    path_str + "\0",
                    None,
                    shellcon.FOF_ALLOWUNDO | shellcon.FOF_NOCONFIRMATION | shellcon.FOF_NOERRORUI | shellcon.FOF_SILENT,
                    None,
                    None
                ))
            finally:
                pythoncom.CoUninitialize()
        except Exception:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
    else:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
