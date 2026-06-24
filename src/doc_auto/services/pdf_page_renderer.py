from __future__ import annotations

import asyncio
from pathlib import Path


def render_pdf_pages(pdf_path: Path, *, target_long_side: int = 1920) -> list[Path]:
    return asyncio.run(_render_pdf_pages_async(Path(pdf_path), target_long_side=target_long_side))


async def _render_pdf_pages_async(pdf_path: Path, *, target_long_side: int) -> list[Path]:
    from winrt.windows.data.pdf import PdfDocument
    from winrt.windows.storage import StorageFile
    from winrt.windows.storage.streams import DataReader, InMemoryRandomAccessStream

    extracted_pages: list[Path] = []
    try:
        file = await StorageFile.get_file_from_path_async(str(pdf_path.resolve()))
        doc = await PdfDocument.load_from_file_async(file)
        page_count = int(doc.page_count)

        destination_dir = pdf_path.parent / pdf_path.stem if page_count > 1 else pdf_path.parent
        destination_dir.mkdir(parents=True, exist_ok=True)

        for page_index in range(page_count):
            page = doc.get_page(page_index)
            stream = InMemoryRandomAccessStream()
            render_options, render_size = _pdf_render_options(page, target_long_side=target_long_side)
            if render_options is None:
                await page.render_to_stream_async(stream)
            else:
                await page.render_with_options_to_stream_async(stream, render_options)

            reader = DataReader(stream)
            await reader.load_async(stream.size)
            data = bytearray(stream.size)
            reader.read_bytes(data)

            if page_count == 1:
                target = _unique_path(destination_dir / f"{pdf_path.stem}.png")
            else:
                target = _unique_path(destination_dir / f"{pdf_path.stem}_{page_index + 1:02d}.png")
            with target.open("wb") as handle:
                handle.write(data)
            extracted_pages.append(target)
    except Exception:
        return []
    return extracted_pages


def _pdf_render_options(page, *, target_long_side: int):
    try:
        from winrt.windows.data.pdf import PdfPageRenderOptions

        width = float(page.size.width)
        height = float(page.size.height)
        if width <= 0 or height <= 0:
            return None, (0, 0)
        scale = target_long_side / max(width, height)
        render_width = max(1, int(round(width * scale)))
        render_height = max(1, int(round(height * scale)))
        options = PdfPageRenderOptions()
        options.destination_width = render_width
        options.destination_height = render_height
        return options, (render_width, render_height)
    except Exception:
        return None, (0, 0)


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{index:02d}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Unable to allocate unique path for {path}")
