from __future__ import annotations

from pathlib import Path
import shutil

from doc_auto.domain.job import WorkItem
from doc_auto.services.shell_notify import notify_path_changed
from doc_auto.services.temp_storage import PortableStorage


class SourceCache:
    def __init__(self, storage: PortableStorage) -> None:
        self.storage = storage

    def cache_item(self, item: WorkItem) -> Path:
        source = Path(item.source_path)
        target_dir = self.storage.cache_dir / "sources" / item.item_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        if not target.exists():
            shutil.copy2(source, target)
        item.cached_source_path = target
        return target

    def restore_item(self, item: WorkItem) -> Path:
        if item.cached_source_path is None:
            raise FileNotFoundError("cached source path is not set")
        cached = Path(item.cached_source_path)
        if not cached.exists():
            raise FileNotFoundError(str(cached))
        target = Path(item.current_path or item.source_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cached, target)
        item.current_path = target
        notify_path_changed(target.parent)
        return target
