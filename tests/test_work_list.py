from doc_auto.services.work_list import WorkList
import zipfile


def test_add_file_creates_pending_item(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"fake")

    work_list = WorkList()
    added = work_list.add_paths([image])

    assert len(added) == 1
    assert added[0].original_name == "a.jpg"
    assert added[0].status.value == "pending"


def test_add_folder_collects_supported_files(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"fake")
    (tmp_path / "b.txt").write_text("skip", encoding="utf-8")

    work_list = WorkList()
    added = work_list.add_paths([tmp_path])

    assert [item.original_name for item in added] == ["a.jpg"]


def test_add_paths_dedupes_existing_items(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"fake")

    work_list = WorkList()
    first = work_list.add_paths([image])
    second = work_list.add_paths([image])

    assert len(first) == 1
    assert second == []
    assert len(work_list.items) == 1


def test_replace_paths_discards_previous_items(tmp_path):
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    work_list = WorkList()
    work_list.add_paths([first])
    added = work_list.replace_paths([second])

    assert [item.source_path for item in work_list.items] == [second]
    assert [item.source_path for item in added] == [second]


def test_remove_items_updates_dedup_state(tmp_path):
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    work_list = WorkList()
    items = work_list.add_paths([first, second])
    work_list.remove_items([items[0]])
    added_again = work_list.add_paths([first])

    assert [item.source_path for item in work_list.items] == [second, first]
    assert [item.source_path for item in added_again] == [first]


def test_add_zip_lists_all_safe_internal_files_without_extracting(tmp_path):
    zip_path = tmp_path / "docs.zip"
    nested_zip = tmp_path / "nested.zip"
    with zipfile.ZipFile(nested_zip, "w") as archive:
        archive.writestr("inside.jpg", b"image")
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("receipt.jpg", b"image")
        archive.writestr("nested/detail.pdf", b"%PDF")
        archive.writestr("notes.txt", "keep")
        archive.write(nested_zip, "nested.zip")

    work_list = WorkList()
    added = work_list.add_paths([zip_path])

    assert [item.original_name for item in added] == ["receipt.jpg", "detail.pdf", "notes.txt", "nested.zip"]
    assert all(item.source_path == zip_path for item in added)
    assert [item.archive_member_name for item in added] == [
        "receipt.jpg",
        "nested/detail.pdf",
        "notes.txt",
        "nested.zip",
    ]
    assert not (tmp_path / "docs").exists()
