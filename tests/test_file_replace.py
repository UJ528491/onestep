from pathlib import Path


def test_replace_file_with_retry_notifies_target_folder(tmp_path, monkeypatch):
    from doc_auto.services import file_replace

    source = tmp_path / "work.tmp"
    target = tmp_path / "scan.jpg"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    notified: list[Path] = []
    monkeypatch.setattr(file_replace, "notify_path_changed", lambda path: notified.append(Path(path)))

    file_replace.replace_file_with_retry(source, target)

    assert target.read_bytes() == b"new"
    assert notified == [tmp_path]
