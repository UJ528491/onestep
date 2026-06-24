from __future__ import annotations

from pathlib import Path
import re


def assert_pdf_page_count(path: Path, expected: int) -> None:
    data = Path(path).read_bytes()
    assert data.startswith(b"%PDF")
    pages = re.findall(rb"/Type\s*/Page\b", data)
    assert len(pages) == expected
