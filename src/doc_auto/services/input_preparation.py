from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from collections.abc import Iterable
from pathlib import Path
import shutil
from typing import Protocol
import zipfile

from doc_auto.domain.file_types import (
    ARCHIVE_EXTENSIONS,
    HWP_EXTENSIONS,
    PDF_EXTENSIONS,
    RASTER_IMAGE_EXTENSIONS,
    SUPPORTED_INPUT_EXTENSIONS,
    TIFF_EXTENSIONS,
)
from doc_auto.domain.job import WorkItem
from doc_auto.services.pdf_page_renderer import render_pdf_pages
from doc_auto.services.shell_notify import notify_path_changed
from doc_auto.services.temp_storage import PortableStorage


@dataclass(frozen=True)
class PreparedInput:
    path: Path
    source_path: Path
    kind: str = "image"
    output_path: Path | None = None
    restore_path: Path | None = None
    delete_source_path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        object.__setattr__(self, "source_path", Path(self.source_path))
        if self.output_path is not None:
            object.__setattr__(self, "output_path", Path(self.output_path))
        if self.restore_path is None:
            object.__setattr__(self, "restore_path", Path(self.path))
        else:
            object.__setattr__(self, "restore_path", Path(self.restore_path))
        if self.delete_source_path is not None:
            object.__setattr__(self, "delete_source_path", Path(self.delete_source_path))


class ArchiveExtractor:
    def extract(self, zip_path: Path, destination_dir: Path) -> list[PreparedInput]:
        destination_dir = Path(destination_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination_root = destination_dir.resolve()
        extracted: list[PreparedInput] = []

        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                member_path = self._safe_member_path(self._decode_member_name(member))
                if member_path is None:
                    continue
                target = (destination_dir / member_path.name).resolve()
                try:
                    target.relative_to(destination_root)
                except ValueError:
                    continue
                target = self._unique_path(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as target_file:
                    shutil.copyfileobj(source, target_file)
                extracted.append(
                    PreparedInput(
                        path=target,
                        source_path=Path(zip_path),
                        kind=self._kind_for(target),
                        restore_path=target,
                    )
                )
        return extracted

    def extract_member(self, zip_path: Path, member_name: str, destination_dir: Path) -> PreparedInput | None:
        destination_dir = Path(destination_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                member_path = self._safe_member_path(self._decode_member_name(member))
                if member_path is None or member_path.as_posix() != member_name:
                    continue
                target = self._unique_path(destination_dir / member_path.name)
                with archive.open(member) as source, target.open("wb") as target_file:
                    shutil.copyfileobj(source, target_file)
                return PreparedInput(
                    path=target,
                    source_path=Path(zip_path),
                    kind=self._kind_for(target),
                    restore_path=target,
                )
        return None

    @staticmethod
    def _safe_member_path(name: str) -> Path | None:
        normalized = name.replace("\\", "/").strip("/")
        parts = [part for part in normalized.split("/") if part and part != "."]
        if not parts:
            return None
        if any(part == ".." or ":" in part for part in parts):
            return None
        return Path(*parts)

    @staticmethod
    def _decode_member_name(member: zipfile.ZipInfo) -> str:
        if member.flag_bits & 0x800:
            return member.filename
        try:
            return member.filename.encode("cp437").decode("cp949")
        except UnicodeError:
            return member.filename

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        for index in range(1, 1000):
            candidate = path.with_name(f"{path.stem}_{index:02d}{path.suffix}")
            if not candidate.exists():
                return candidate
        raise FileExistsError(f"Unable to allocate unique path for {path}")

    @staticmethod
    def _kind_for(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in ARCHIVE_EXTENSIONS:
            return "archive"
        if suffix in PDF_EXTENSIONS:
            return "pdf"
        if suffix in TIFF_EXTENSIONS:
            return "tiff"
        if suffix in HWP_EXTENSIONS:
            return "hwp"
        return "image"


class TiffFrameExtractor:
    def split(self, tiff_path: Path, destination_dir: Path) -> list[PreparedInput]:
        from PIL import Image, ImageSequence

        destination_dir = Path(destination_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)
        frames: list[PreparedInput] = []
        with Image.open(tiff_path) as image:
            for index, frame in enumerate(ImageSequence.Iterator(image), start=1):
                target = destination_dir / f"{Path(tiff_path).stem}_{index:03d}.png"
                target = ArchiveExtractor._unique_path(target)
                output = frame.copy()
                if output.mode not in {"RGB", "L"}:
                    output = output.convert("RGB")
                output.save(target, "PNG")
                frames.append(PreparedInput(path=target, source_path=Path(tiff_path), kind="image", restore_path=target))
        return frames


class PdfRenderer(Protocol):
    def page_count(self, pdf_path: Path) -> int:
        ...

    def render(self, pdf_path: Path, destination_dir: Path) -> list[PreparedInput]:
        ...


class ExistingPdfRenderer:
    def page_count(self, pdf_path: Path) -> int:
        import asyncio

        async def count_async() -> int:
            from winrt.windows.data.pdf import PdfDocument
            from winrt.windows.storage import StorageFile

            file = await StorageFile.get_file_from_path_async(str(Path(pdf_path).resolve()))
            doc = await PdfDocument.load_from_file_async(file)
            return int(doc.page_count)

        return asyncio.run(count_async())

    def render(self, pdf_path: Path, destination_dir: Path) -> list[PreparedInput]:
        destination_dir = Path(destination_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)
        source_pdf = Path(pdf_path)
        try:
            already_in_destination = source_pdf.parent.resolve() == destination_dir.resolve()
        except OSError:
            already_in_destination = source_pdf.parent.absolute() == destination_dir.absolute()
        if already_in_destination:
            working_pdf = source_pdf
        else:
            working_pdf = ArchiveExtractor._unique_path(destination_dir / source_pdf.name)
            shutil.copy2(source_pdf, working_pdf)

        pages = render_pdf_pages(working_pdf)
        prepared: list[PreparedInput] = []
        for page in pages:
            page_path = Path(page)
            if page_path.exists():
                if page_path.parent != destination_dir:
                    flat_path = ArchiveExtractor._unique_path(destination_dir / page_path.name)
                    shutil.move(str(page_path), flat_path)
                    page_path = flat_path
                prepared.append(PreparedInput(path=page_path, source_path=Path(pdf_path), kind="image", restore_path=page_path))
        try:
            if not already_in_destination:
                working_pdf.unlink(missing_ok=True)
            for child in destination_dir.iterdir():
                if child.is_dir() and not any(child.iterdir()):
                    child.rmdir()
        except OSError:
            pass
        return prepared


class InputPreparationPipeline:
    def __init__(
        self,
        storage: PortableStorage,
        *,
        archive_extractor: ArchiveExtractor | None = None,
        tiff_extractor: TiffFrameExtractor | None = None,
        pdf_renderer: PdfRenderer | None = None,
        archive_extract_to_current_dir: bool = False,
        pdf_tiff_extract_to_current_dir: bool = True,
    ) -> None:
        self.storage = storage
        self.archive_extractor = archive_extractor or ArchiveExtractor()
        self.tiff_extractor = tiff_extractor or TiffFrameExtractor()
        self.pdf_renderer = pdf_renderer or ExistingPdfRenderer()
        self.archive_extract_to_current_dir = archive_extract_to_current_dir
        self.pdf_tiff_extract_to_current_dir = pdf_tiff_extract_to_current_dir

    def prepare(self, paths: Iterable[Path]) -> list[PreparedInput]:
        return self.prepare_items(WorkItem(source_path=Path(path)) for path in paths)

    def prepare_items(self, items: Iterable[WorkItem]) -> list[PreparedInput]:
        queue = deque((item, None, False) for item in items)
        prepared: list[PreparedInput] = []
        allocated_outputs: set[str] = set()
        while queue:
            item, output_dir, flatten_output = queue.popleft()
            original_path = Path(item.source_path)
            path = original_path
            if item.archive_member_name:
                current_path = Path(item.current_path) if item.current_path is not None else None
                if current_path is not None and current_path.exists():
                    member_output_dir = self._archive_output_dir(original_path, output_dir, unique=False)
                    member_output_dir.mkdir(parents=True, exist_ok=True)
                    notify_path_changed(member_output_dir.parent)
                    queue.append(
                        (
                            WorkItem(
                                source_path=current_path,
                                cached_source_path=item.cached_source_path,
                                delete_source_path=original_path,
                            ),
                            member_output_dir,
                            True,
                        )
                    )
                    continue
                if not original_path.exists():
                    continue
                extracted = self.archive_extractor.extract_member(
                    original_path,
                    item.archive_member_name,
                    self._originals_dir(),
                )
                if extracted is not None:
                    member_output_dir = self._archive_output_dir(original_path, output_dir, unique=False)
                    member_output_dir.mkdir(parents=True, exist_ok=True)
                    notify_path_changed(member_output_dir.parent)
                    queue.append(
                        (
                            WorkItem(
                                source_path=extracted.path,
                                cached_source_path=extracted.restore_path,
                                delete_source_path=original_path,
                            ),
                            member_output_dir,
                            True,
                        )
                    )
                continue
            if item.current_path is not None and Path(item.current_path).exists():
                path = Path(item.current_path)
            if not path.exists():
                continue
            if path.is_dir():
                for file_path in self._supported_files_in(path):
                    queue.append((WorkItem(source_path=file_path), None, False))
                continue
            suffix = path.suffix.lower()
            if suffix in RASTER_IMAGE_EXTENSIONS:
                temp_path = path if item.cached_source_path is not None else self._copy_original(path)
                prepared.append(
                    PreparedInput(
                        path=temp_path,
                        source_path=path,
                        kind="image",
                        output_path=self._output_path_for_image(
                            path,
                            output_dir=output_dir,
                            flatten=flatten_output,
                            allocated_outputs=allocated_outputs,
                        ),
                            restore_path=temp_path,
                            delete_source_path=item.delete_source_path,
                        )
                )
                continue
            if suffix in ARCHIVE_EXTENSIONS:
                archive_output_dir = self._archive_output_dir(path, output_dir)
                archive_output_dir.mkdir(parents=True, exist_ok=True)
                notify_path_changed(archive_output_dir.parent)
                for extracted in self.archive_extractor.extract(path, self._originals_dir()):
                    queue.append(
                        (
                            WorkItem(
                                source_path=extracted.path,
                                cached_source_path=extracted.restore_path,
                                delete_source_path=path,
                            ),
                            archive_output_dir,
                            True,
                        )
                    )
                continue
            if suffix in TIFF_EXTENSIONS:
                tiff_output_dir = self._pdf_tiff_output_dir(path, output_dir)
                frames = self.tiff_extractor.split(path, self._originals_dir())
                self._discard_temp_container(path)
                for frame in frames:
                    prepared.append(
                        PreparedInput(
                            path=frame.path,
                            source_path=path,
                            kind="image",
                            output_path=self._output_path_for_image(
                                frame.path,
                                output_dir=tiff_output_dir,
                                flatten=flatten_output,
                                allocated_outputs=allocated_outputs,
                            ),
                            restore_path=frame.path,
                            delete_source_path=item.delete_source_path,
                        )
                    )
                continue
            if suffix in PDF_EXTENSIONS:
                pdf_output_dir = self._pdf_tiff_output_dir(path, output_dir)
                pages = self.pdf_renderer.render(path, self._originals_dir())
                self._discard_temp_container(path)
                for page in pages:
                    prepared.append(
                        PreparedInput(
                            path=page.path,
                            source_path=path,
                            kind="image",
                            output_path=self._output_path_for_image(
                                page.path,
                                output_dir=pdf_output_dir,
                                flatten=True,
                                allocated_outputs=allocated_outputs,
                            ),
                            restore_path=page.path,
                            delete_source_path=item.delete_source_path,
                        )
                    )
                continue
            if suffix in HWP_EXTENSIONS:
                temp_path = path if item.cached_source_path is not None else self._copy_original(path)
                prepared.append(
                    PreparedInput(
                        path=temp_path,
                        source_path=path,
                        kind="hwp",
                        output_path=self._output_path_for_copy(
                            path,
                            output_dir=output_dir,
                            flatten=flatten_output,
                            allocated_outputs=allocated_outputs,
                        ),
                        restore_path=temp_path,
                        delete_source_path=item.delete_source_path,
                    )
                )
                continue
            temp_path = path if item.cached_source_path is not None else self._copy_original(path)
            prepared.append(
                PreparedInput(
                    path=temp_path,
                    source_path=path,
                    kind="copy",
                    output_path=self._output_path_for_copy(
                        path,
                        output_dir=output_dir,
                        flatten=flatten_output,
                        allocated_outputs=allocated_outputs,
                    ),
                    restore_path=temp_path,
                    delete_source_path=item.delete_source_path,
                )
            )
        return prepared

    @staticmethod
    def _supported_files_in(folder: Path) -> list[Path]:
        return [
            path
            for path in sorted(folder.rglob("*"))
            if path.is_file() and path.suffix.lower() in SUPPORTED_INPUT_EXTENSIONS
        ]

    def _archive_output_dir(self, archive_path: Path, output_dir: Path | None, *, unique: bool = True) -> Path:
        if output_dir is not None:
            return output_dir
        if self.archive_extract_to_current_dir:
            return archive_path.parent
        target = archive_path.parent / archive_path.stem
        return self._unique_output_dir(target) if unique else target

    def _pdf_tiff_output_dir(self, container_path: Path, output_dir: Path | None) -> Path:
        if output_dir is not None:
            return output_dir
        if self.pdf_tiff_extract_to_current_dir:
            return container_path.parent
        target = self._unique_output_dir(container_path.parent / container_path.stem)
        target.mkdir(parents=True, exist_ok=True)
        notify_path_changed(target.parent)
        return target

    def _copy_original(self, path: Path) -> Path:
        destination = ArchiveExtractor._unique_path(self._originals_dir() / path.name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        return destination

    def _originals_dir(self) -> Path:
        path = self.storage.temp_dir / "originals"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _discard_temp_container(self, path: Path) -> None:
        try:
            Path(path).resolve().relative_to(self._originals_dir().resolve())
        except (OSError, ValueError):
            return
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            return

    @classmethod
    def _output_path_for_image(
        cls,
        path: Path,
        *,
        output_dir: Path | None,
        flatten: bool,
        allocated_outputs: set[str],
    ) -> Path:
        if output_dir is None:
            return path

        target = Path(output_dir) / path.name
        if not flatten and target.exists():
            target = target.with_name(f"{target.stem}_work{target.suffix}")
        return cls._reserve_output_path(target, allocated_outputs)

    @classmethod
    def _output_path_for_copy(
        cls,
        path: Path,
        *,
        output_dir: Path | None,
        flatten: bool,
        allocated_outputs: set[str],
    ) -> Path:
        if output_dir is None:
            return path
        target = Path(output_dir) / path.name
        if not flatten and target.exists():
            target = target.with_name(f"{target.stem}_work{target.suffix}")
        return cls._reserve_output_path(target, allocated_outputs)

    @classmethod
    def _reserve_output_path(cls, path: Path, allocated_outputs: set[str]) -> Path:
        candidate = Path(path)
        if not candidate.exists() and cls._path_key(candidate) not in allocated_outputs:
            allocated_outputs.add(cls._path_key(candidate))
            return candidate
        for index in range(1, 1000):
            candidate = path.with_name(f"{path.stem}_{index:02d}{path.suffix}")
            key = cls._path_key(candidate)
            if not candidate.exists() and key not in allocated_outputs:
                allocated_outputs.add(key)
                return candidate
        raise FileExistsError(f"Unable to allocate output path for {path}")

    @staticmethod
    def _path_key(path: Path) -> str:
        try:
            return str(path.resolve()).casefold()
        except OSError:
            return str(path.absolute()).casefold()

    @staticmethod
    def _unique_output_dir(path: Path) -> Path:
        if not path.exists():
            return path
        for index in range(1, 1000):
            candidate = path.with_name(f"{path.name}_{index:02d}")
            if not candidate.exists():
                return candidate
        raise FileExistsError(f"Unable to allocate output directory for {path}")
