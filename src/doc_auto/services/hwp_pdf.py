from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import time


@dataclass(frozen=True)
class HwpLaunchHandle:
    pids: set[int]


def _hwp_process_ids() -> set[int]:
    if os.name != "nt":
        return set()
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process Hwp -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
            creationflags=0x08000000,
        )
    except Exception:
        return set()
    pids: set[int] = set()
    for line in completed.stdout.splitlines():
        try:
            pids.add(int(line.strip()))
        except ValueError:
            continue
    return pids


def open_hwp_for_permission(hwp_path: Path) -> HwpLaunchHandle | None:
    if os.name != "nt":
        return None
    before = _hwp_process_ids()
    try:
        os.startfile(str(Path(hwp_path).resolve()))  # type: ignore[attr-defined]
        time.sleep(1.0)
        return HwpLaunchHandle(pids=_hwp_process_ids() - before)
    except OSError:
        return None


def close_hwp_permission_window(handle: HwpLaunchHandle | None) -> None:
    if os.name != "nt" or handle is None or not handle.pids:
        return
    ids = ",".join(str(pid) for pid in sorted(handle.pids))
    script = f"""
$ids = @({ids})
foreach ($id in $ids) {{
  $process = Get-Process -Id $id -ErrorAction SilentlyContinue
  if ($process) {{ [void]$process.CloseMainWindow() }}
}}
Start-Sleep -Milliseconds 800
foreach ($id in $ids) {{
  $process = Get-Process -Id $id -ErrorAction SilentlyContinue
  if ($process) {{ Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }}
}}
"""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            creationflags=0x08000000,
        )
    except Exception:
        return


def _set_hwp_visible(hwp, visible: bool) -> None:
    try:
        hwp.XHwpWindows.Active_XHwpWindow.Visible = visible
        return
    except Exception:
        pass
    try:
        hwp.XHwpWindows.Item(0).Visible = visible
    except Exception:
        pass


def _remove_failed_pdf(pdf_path: Path) -> None:
    try:
        pdf_path.unlink(missing_ok=True)
    except OSError:
        pass


def _convert_hwp_to_pdf_once(hwp_path: Path, pdf_path: Path, *, visible: bool) -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    hwp = None
    try:
        hwp = win32com.client.Dispatch("HWPFrame.HwpObject")
        _set_hwp_visible(hwp, visible)
        try:
            hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        except Exception:
            pass
        try:
            hwp.Clear(1)
        except Exception:
            pass
        opened = hwp.Open(str(hwp_path.resolve()), "HWP", "")
        if not opened:
            raise RuntimeError("HWP Open returned false")
        saved_pdf = hwp.SaveAs(str(pdf_path.resolve()), "PDF", "")
        if not saved_pdf and (not pdf_path.exists() or pdf_path.stat().st_size <= 0):
            raise RuntimeError("HWP SaveAs(PDF) returned false")
    finally:
        if hwp is not None:
            try:
                hwp.Clear(1)
            except Exception:
                pass
            try:
                hwp.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()
    if not pdf_path.exists() or pdf_path.stat().st_size <= 0:
        raise RuntimeError("HWP PDF conversion produced no PDF file")


def convert_hwp_to_pdf_only(hwp_path: Path, pdf_path: Path, *, permission_hwp_path: Path | None = None) -> None:
    hwp_path = Path(hwp_path)
    pdf_path = Path(pdf_path)
    permission_hwp_path = Path(permission_hwp_path) if permission_hwp_path is not None else hwp_path
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        _convert_hwp_to_pdf_once(hwp_path, pdf_path, visible=False)
        return
    except Exception as hidden_error:
        _remove_failed_pdf(pdf_path)

    launch_handle = open_hwp_for_permission(permission_hwp_path)
    try:
        _convert_hwp_to_pdf_once(hwp_path, pdf_path, visible=True)
    except Exception as visible_error:
        raise RuntimeError(
            f"HWP PDF conversion failed after hidden attempt: {hidden_error}; "
            f"visible attempt: {visible_error}"
        ) from visible_error
    finally:
        close_hwp_permission_window(launch_handle)


def run_hwp_pdf_worker() -> None:
    if len(sys.argv) < 5:
        sys.exit(1)

    hwp_path = Path(sys.argv[2])
    pdf_path = Path(sys.argv[3])
    target_json = Path(sys.argv[4])
    permission_hwp_path = Path(sys.argv[5]) if len(sys.argv) >= 6 else hwp_path

    try:
        convert_hwp_to_pdf_only(hwp_path, pdf_path, permission_hwp_path=permission_hwp_path)
        with target_json.open("w", encoding="utf-8") as handle:
            json.dump({"pdf": str(pdf_path.resolve())}, handle, ensure_ascii=False)
        sys.exit(0)
    except Exception as exc:
        import traceback

        traceback.print_exc()
        sys.exit(1)
