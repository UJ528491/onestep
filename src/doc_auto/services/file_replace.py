from __future__ import annotations

import os
from pathlib import Path
import stat
import time

from doc_auto.services.shell_notify import notify_path_changed


DEFAULT_REPLACE_DELAYS = (0.0, 0.05, 0.10, 0.20, 0.40)


def replace_file_with_retry(
    source: Path,
    target: Path,
    delays: tuple[float, ...] = DEFAULT_REPLACE_DELAYS,
) -> None:
    last_error: PermissionError | None = None
    for delay in delays:
        if delay:
            time.sleep(delay)
        try:
            os.replace(source, target)
            notify_path_changed(Path(target).parent)
            return
        except PermissionError as error:
            last_error = error
            _make_writable(target)
    if last_error is not None:
        raise last_error


def _make_writable(path: Path) -> None:
    try:
        if path.exists():
            path.chmod(stat.S_IREAD | stat.S_IWRITE)
    except OSError:
        return
