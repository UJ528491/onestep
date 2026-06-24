from __future__ import annotations

from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parent
SRC = SOURCE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

def _run_worker_if_requested(argv: list[str]) -> bool:
    if "--ocr-worker" in argv:
        from doc_auto.services.ocr import run_ocr_worker

        run_ocr_worker()
        return True

    if "--ocr-batch-worker" in argv:
        from doc_auto.services.ocr import run_ocr_batch_worker

        run_ocr_batch_worker()
        return True

    if "--hwp-pdf-worker" in argv:
        from doc_auto.services.hwp_pdf import run_hwp_pdf_worker

        run_hwp_pdf_worker()
        return True

    return False


def resolve_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return SOURCE_ROOT


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    if _run_worker_if_requested(args):
        return 0

    from doc_auto.app import run

    return run(app_root=resolve_app_root())


if __name__ == "__main__":
    raise SystemExit(main())
