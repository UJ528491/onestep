from pathlib import Path

from doc_auto.domain.job import WorkItem
from doc_auto.services.source_cache import SourceCache
from doc_auto.services.temp_storage import PortableStorage


def test_source_cache_copies_file_under_item_id(tmp_path):
    source = tmp_path / "scan.jpg"
    source.write_bytes(b"original")
    storage = PortableStorage(tmp_path / "app")
    item = WorkItem(source_path=source, item_id="item123")

    cached = SourceCache(storage).cache_item(item)

    assert cached == storage.temp_dir / "cache" / "sources" / "item123" / "scan.jpg"
    assert cached.read_bytes() == b"original"
    assert item.cached_source_path == cached


def test_source_cache_reuses_existing_cached_file(tmp_path):
    source = tmp_path / "scan.jpg"
    source.write_bytes(b"original")
    storage = PortableStorage(tmp_path / "app")
    item = WorkItem(source_path=source, item_id="item123")
    cache = SourceCache(storage)

    first = cache.cache_item(item)
    source.write_bytes(b"changed")
    second = cache.cache_item(item)

    assert first == second
    assert second.read_bytes() == b"original"


def test_source_cache_restores_cached_file(tmp_path):
    source = tmp_path / "scan.jpg"
    source.write_bytes(b"original")
    storage = PortableStorage(tmp_path / "app")
    item = WorkItem(source_path=source, item_id="item123")
    cache = SourceCache(storage)
    cache.cache_item(item)
    source.write_bytes(b"changed")

    restored = cache.restore_item(item)

    assert restored == source
    assert source.read_bytes() == b"original"


def test_source_cache_restore_notifies_target_folder(tmp_path, monkeypatch):
    from doc_auto.services import source_cache as source_cache_module

    source = tmp_path / "scan.jpg"
    source.write_bytes(b"original")
    storage = PortableStorage(tmp_path / "app")
    item = WorkItem(source_path=source, item_id="item123")
    cache = SourceCache(storage)
    cache.cache_item(item)
    source.write_bytes(b"changed")
    notified: list[Path] = []
    monkeypatch.setattr(source_cache_module, "notify_path_changed", lambda path: notified.append(Path(path)))

    cache.restore_item(item)

    assert notified == [tmp_path]
