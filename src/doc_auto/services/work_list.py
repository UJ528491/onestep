from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import zipfile

from doc_auto.domain.file_types import ARCHIVE_EXTENSIONS, SUPPORTED_INPUT_EXTENSIONS
from doc_auto.domain.job import WorkItem


class WorkList:
    def __init__(self) -> None:
        self.items: list[WorkItem] = []
        self._seen_paths: set[str] = set()

    def add_paths(self, paths: Iterable[Path]) -> list[WorkItem]:
        added: list[WorkItem] = []
        for path in paths:
            for item in self._expand_path(Path(path)):
                key = self._item_key(item)
                if key in self._seen_paths:
                    continue
                self.items.append(item)
                self._seen_paths.add(key)
                added.append(item)
        return added

    def replace_paths(self, paths: Iterable[Path]) -> list[WorkItem]:
        self.clear()
        return self.add_paths(paths)

    def remove_items(self, items: Iterable[WorkItem]) -> None:
        remove_ids = {item.item_id for item in items}
        self.items = [item for item in self.items if item.item_id not in remove_ids]
        self.rebuild_seen_paths()

    def rebuild_seen_paths(self) -> None:
        self._seen_paths = {self._item_key(item) for item in self.items}

    def clear(self) -> None:
        self.items.clear()
        self._seen_paths.clear()

    def _expand_path(self, path: Path) -> list[WorkItem]:
        if not path.exists():
            return []
        if path.is_dir():
            return [
                WorkItem(source_path=file_path)
                for file_path in sorted(path.rglob("*"))
                if file_path.is_file() and self._is_supported(file_path)
            ]
        if path.is_file() and path.suffix.lower() in ARCHIVE_EXTENSIONS:
            return self._archive_items(path)
        if path.is_file() and self._is_supported(path):
            return [WorkItem(source_path=path)]
        return []

    def _archive_items(self, path: Path) -> list[WorkItem]:
        items: list[WorkItem] = []
        try:
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    name = self._decode_member_name(member)
                    safe_path = self._safe_member_path(name)
                    if safe_path is None:
                        continue
                    items.append(
                        WorkItem(
                            source_path=path,
                            archive_member_name=safe_path.as_posix(),
                            file_size_bytes=int(member.file_size),
                        )
                    )
        except zipfile.BadZipFile:
            return [WorkItem(source_path=path)]
        return items or [WorkItem(source_path=path)]

    @staticmethod
    def _is_supported(path: Path) -> bool:
        return path.suffix.lower() in SUPPORTED_INPUT_EXTENSIONS

    @staticmethod
    def _path_key(path: Path) -> str:
        try:
            return str(path.resolve()).casefold()
        except Exception:
            return str(path.absolute()).casefold()

    @classmethod
    def _item_key(cls, item: WorkItem) -> str:
        key = cls._path_key(item.source_path)
        if item.archive_member_name:
            key = f"{key}!{item.archive_member_name.casefold()}"
        return key

    @staticmethod
    def _decode_member_name(member: zipfile.ZipInfo) -> str:
        if member.flag_bits & 0x800:
            return member.filename
        try:
            return member.filename.encode("cp437").decode("cp949")
        except UnicodeError:
            return member.filename

    @staticmethod
    def _safe_member_path(name: str) -> Path | None:
        normalized = name.replace("\\", "/").strip("/")
        parts = [part for part in normalized.split("/") if part and part != "."]
        if not parts:
            return None
        if any(part == ".." or ":" in part for part in parts):
            return None
        return Path(*parts)
