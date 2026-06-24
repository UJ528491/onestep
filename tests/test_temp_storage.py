from doc_auto.services.temp_storage import PortableStorage
import stat


def test_portable_storage_creates_data_dirs(tmp_path):
    storage = PortableStorage(tmp_path)

    assert storage.data_dir == tmp_path / "data"
    assert storage.temp_dir.exists()
    assert storage.cache_dir.exists()
    assert storage.cache_dir == storage.temp_dir / "cache"


def test_clear_temp_removes_temp_contents_only(tmp_path):
    storage = PortableStorage(tmp_path)
    temp_file = storage.temp_dir / "working.tmp"
    cache_file = storage.cache_dir / "remove.json"
    temp_file.write_text("remove", encoding="utf-8")
    cache_file.write_text("keep", encoding="utf-8")

    storage.clear_temp()

    assert storage.temp_dir.exists()
    assert not temp_file.exists()
    assert not cache_file.exists()
    assert storage.cache_dir.exists()


def test_clear_temp_removes_read_only_temp_contents(tmp_path):
    storage = PortableStorage(tmp_path)
    temp_dir = storage.temp_dir / "nested"
    temp_dir.mkdir()
    temp_file = temp_dir / "locked_by_attribute.tmp"
    temp_file.write_text("remove", encoding="utf-8")
    temp_file.chmod(stat.S_IREAD)

    try:
        storage.clear_temp()
    finally:
        if temp_file.exists():
            temp_file.chmod(stat.S_IREAD | stat.S_IWRITE)

    assert storage.temp_dir.exists()
    assert not temp_file.exists()
    assert not temp_dir.exists()


def test_clear_temp_allows_configured_external_temp_folder(tmp_path):
    storage = PortableStorage(tmp_path / "app")
    storage.temp_dir = tmp_path / "custom_temp"
    storage.ensure_dirs()
    temp_file = storage.temp_dir / "working.tmp"
    cache_file = storage.cache_dir / "remove.json"
    temp_file.write_text("remove", encoding="utf-8")
    cache_file.write_text("keep", encoding="utf-8")

    storage.clear_temp()

    assert storage.temp_dir.exists()
    assert not temp_file.exists()
    assert not cache_file.exists()
    assert storage.cache_dir == storage.temp_dir / "cache"
    assert storage.cache_dir.exists()
