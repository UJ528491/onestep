from __future__ import annotations

import os
from pathlib import Path


def notify_path_changed(path: Path) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        SHCNE_UPDATEDIR = 0x00001000
        SHCNF_PATHW = 0x0005
        ctypes.windll.shell32.SHChangeNotify(  # type: ignore[attr-defined]
            SHCNE_UPDATEDIR,
            SHCNF_PATHW,
            str(Path(path)),
            None,
        )
    except Exception:
        return
