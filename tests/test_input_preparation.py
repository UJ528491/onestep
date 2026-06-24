from pathlib import Path
import binascii
import struct
import zipfile

from PIL import Image

from doc_auto.domain.job import WorkItem
from doc_auto.services.input_preparation import ArchiveExtractor, ExistingPdfRenderer, InputPreparationPipeline, TiffFrameExtractor
from doc_auto.services.temp_storage import PortableStorage
from doc_auto.services.work_list import WorkList


def write_cp949_zip(zip_path: Path, member_name: str, payload: bytes = b"image") -> None:
    raw_name = member_name.encode("cp949")
    crc = binascii.crc32(payload) & 0xFFFFFFFF
    local_header = (
        struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,
            20,
            0,
            0,
            0,
            0,
            crc,
            len(payload),
            len(payload),
            len(raw_name),
            0,
        )
        + raw_name
        + payload
    )
    central_offset = len(local_header)
    central_header = (
        struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,
            20,
            20,
            0,
            0,
            0,
            0,
            crc,
            len(payload),
            len(payload),
            len(raw_name),
            0,
            0,
            0,
            0,
            0,
            0,
        )
        + raw_name
    )
    end_record = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(central_header), central_offset, 0)
    zip_path.write_bytes(local_header + central_header + end_record)


def test_archive_extractor_extracts_all_safe_files_to_destination(tmp_path):
    zip_path = tmp_path / "docs.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("receipt.jpg", b"image")
        archive.writestr("notes.txt", "ignore")

    destination = tmp_path / "data" / "temp" / "archive"
    extracted = ArchiveExtractor().extract(zip_path, destination)

    assert [item.path.name for item in extracted] == ["receipt.jpg", "notes.txt"]
    assert extracted[0].path == destination / "receipt.jpg"
    assert extracted[0].source_path == zip_path
    assert (destination / "notes.txt").exists()


def test_input_preparation_uses_single_originals_temp_folder_for_images(tmp_path):
    image = tmp_path / "scan.jpg"
    image.write_bytes(b"image")
    storage = PortableStorage(tmp_path / "app")

    prepared = InputPreparationPipeline(storage).prepare([image])

    assert len(prepared) == 1
    assert prepared[0].path.parent == storage.temp_dir / "originals"
    assert prepared[0].restore_path == prepared[0].path
    assert not (storage.temp_dir / "inputs").exists()


def test_archive_extractor_recovers_cp949_member_names(tmp_path):
    korean_name = "영수증.jpg"
    cp949_bytes = korean_name.encode("cp949")
    cp437_mojibake = cp949_bytes.decode("cp437")

    info = zipfile.ZipInfo(cp437_mojibake)
    info.flag_bits = 0

    assert ArchiveExtractor._decode_member_name(info) == korean_name


def test_archive_extractor_extracts_cp949_member_names(tmp_path):
    zip_path = tmp_path / "docs.zip"
    korean_name = "영수증.jpg"
    write_cp949_zip(zip_path, korean_name)

    extracted = ArchiveExtractor().extract(zip_path, tmp_path / "out")

    assert [item.path.name for item in extracted] == [korean_name]
    assert extracted[0].path.read_bytes() == b"image"


def test_archive_extractor_marks_hwp_members_as_hwp(tmp_path):
    zip_path = tmp_path / "docs.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("claim.hwp", b"hwp")

    extracted = ArchiveExtractor().extract(zip_path, tmp_path / "out")

    assert len(extracted) == 1
    assert extracted[0].path.name == "claim.hwp"
    assert extracted[0].kind == "hwp"


def test_archive_extractor_skips_unsafe_paths(tmp_path):
    zip_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("../escape.jpg", b"bad")
        archive.writestr("safe.jpg", b"good")

    destination = tmp_path / "data" / "temp" / "archive"
    extracted = ArchiveExtractor().extract(zip_path, destination)

    assert [item.path.name for item in extracted] == ["safe.jpg"]
    assert not (tmp_path / "escape.jpg").exists()


def test_tiff_frame_extractor_splits_frames_to_png(tmp_path):
    tiff_path = tmp_path / "scan.tiff"
    first = Image.new("RGB", (10, 10), "white")
    second = Image.new("RGB", (10, 10), "black")
    first.save(tiff_path, save_all=True, append_images=[second])

    destination = tmp_path / "data" / "temp" / "tiff"
    frames = TiffFrameExtractor().split(tiff_path, destination)

    assert [frame.path.name for frame in frames] == ["scan_001.png", "scan_002.png"]
    assert all(frame.path.exists() for frame in frames)
    assert all(frame.source_path == tiff_path for frame in frames)


class FakePdfRenderer:
    def __init__(self, page_count: int = 1) -> None:
        self._page_count = page_count
        self.render_calls = 0

    def page_count(self, pdf_path: Path) -> int:
        return self._page_count

    def render(self, pdf_path: Path, destination_dir: Path):
        self.render_calls += 1
        destination_dir.mkdir(parents=True, exist_ok=True)
        pages = []
        from doc_auto.services.input_preparation import PreparedInput

        for index in range(1, self._page_count + 1):
            page = destination_dir / f"doc_{index:03d}.png"
            page.write_bytes(b"page")
            pages.append(PreparedInput(path=page, source_path=pdf_path, kind="image", restore_path=page))
        return pages


def test_input_preparation_pipeline_prepares_direct_images(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"image")
    storage = PortableStorage(tmp_path)

    prepared = InputPreparationPipeline(storage).prepare([image])

    assert len(prepared) == 1
    assert prepared[0].path != image
    assert prepared[0].path == storage.temp_dir / "originals" / "a.jpg"
    assert prepared[0].path.read_bytes() == b"image"
    assert prepared[0].source_path == image
    assert prepared[0].restore_path == prepared[0].path
    assert prepared[0].output_path == image
    assert image.exists()


def test_input_preparation_pipeline_expands_zip_and_tiff_and_multipage_pdf(tmp_path):
    image_in_zip = "receipt.jpg"
    zip_path = tmp_path / "docs.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(image_in_zip, b"image")

    tiff_path = tmp_path / "scan.tif"
    first = Image.new("RGB", (8, 8), "white")
    second = Image.new("RGB", (8, 8), "black")
    first.save(tiff_path, save_all=True, append_images=[second])

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-pretend")
    storage = PortableStorage(tmp_path)

    prepared = InputPreparationPipeline(storage, pdf_renderer=FakePdfRenderer(page_count=2)).prepare(
        [zip_path, tiff_path, pdf_path]
    )

    names = sorted(item.path.name for item in prepared)
    assert names == ["doc_001.png", "doc_002.png", "receipt.jpg", "scan_001.png", "scan_002.png"]
    assert all(item.path.parent == storage.temp_dir / "originals" for item in prepared)
    assert not (storage.temp_dir / "archives" / "docs" / "docs.zip").exists()
    assert not (storage.temp_dir / "archives").exists()
    assert not (storage.temp_dir / "pdf").exists()
    assert not (storage.temp_dir / "tiff").exists()
    assert {item.output_path.name for item in prepared} == {"doc_001.png", "doc_002.png", "receipt.jpg", "scan_001.png", "scan_002.png"}
    assert zip_path.exists()


def test_input_preparation_pipeline_renders_single_page_pdf_to_image(tmp_path):
    pdf_path = tmp_path / "single.pdf"
    pdf_path.write_bytes(b"%PDF-single")
    storage = PortableStorage(tmp_path / "app")
    renderer = FakePdfRenderer(page_count=1)

    prepared = InputPreparationPipeline(storage, pdf_renderer=renderer).prepare([pdf_path])

    assert len(prepared) == 1
    assert prepared[0].kind == "image"
    assert prepared[0].path == storage.temp_dir / "originals" / "doc_001.png"
    assert prepared[0].output_path == tmp_path / "doc_001.png"
    assert prepared[0].path.read_bytes() == b"page"
    assert renderer.render_calls == 1


def test_input_preparation_pipeline_can_render_pdf_to_file_named_folder(tmp_path):
    pdf_path = tmp_path / "single.pdf"
    pdf_path.write_bytes(b"%PDF-single")
    storage = PortableStorage(tmp_path / "app")
    renderer = FakePdfRenderer(page_count=1)

    prepared = InputPreparationPipeline(
        storage,
        pdf_renderer=renderer,
        pdf_tiff_extract_to_current_dir=False,
    ).prepare([pdf_path])

    assert len(prepared) == 1
    assert prepared[0].output_path == tmp_path / "single" / "doc_001.png"


def test_input_preparation_pipeline_can_split_tiff_to_file_named_folder(tmp_path):
    tiff_path = tmp_path / "scan.tif"
    first = Image.new("RGB", (8, 8), "white")
    second = Image.new("RGB", (8, 8), "black")
    first.save(tiff_path, save_all=True, append_images=[second])
    storage = PortableStorage(tmp_path / "app")

    prepared = InputPreparationPipeline(
        storage,
        pdf_tiff_extract_to_current_dir=False,
    ).prepare([tiff_path])

    assert [item.output_path for item in prepared] == [
        tmp_path / "scan" / "scan_001.png",
        tmp_path / "scan" / "scan_002.png",
    ]


def test_input_preparation_pipeline_flattens_zip_pdf_pages_to_zip_result_folder(tmp_path):
    zip_path = tmp_path / "A.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("sample.pdf", b"%PDF-pretend")
        archive.writestr("image1.png", b"png1")
        archive.writestr("nested/image2.png", b"png2")
        archive.writestr("image3.png", b"png3")
    storage = PortableStorage(tmp_path)

    prepared = InputPreparationPipeline(storage, pdf_renderer=FakePdfRenderer(page_count=2)).prepare([zip_path])

    assert sorted(item.output_path for item in prepared) == [
        tmp_path / "A" / "doc_001.png",
        tmp_path / "A" / "doc_002.png",
        tmp_path / "A" / "image1.png",
        tmp_path / "A" / "image2.png",
        tmp_path / "A" / "image3.png",
    ]
    assert all(item.path.exists() for item in prepared)
    assert all(item.path.parent == storage.temp_dir / "originals" for item in prepared)
    assert not any(item.output_path.parent.name == "sample" for item in prepared)
    assert not (storage.temp_dir / "originals" / "sample.pdf").exists()


def test_input_preparation_pipeline_can_flatten_zip_outputs_to_current_folder(tmp_path):
    zip_path = tmp_path / "A.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("receipt.jpg", b"image")
    storage = PortableStorage(tmp_path)

    prepared = InputPreparationPipeline(storage, archive_extract_to_current_dir=True).prepare([zip_path])

    assert len(prepared) == 1
    assert prepared[0].output_path == tmp_path / "receipt.jpg"


def test_input_preparation_pipeline_keeps_zip_pdf_page_number_single(tmp_path):
    class StemPreservingPdfRenderer:
        def render(self, pdf_path: Path, destination_dir: Path):
            destination_dir.mkdir(parents=True, exist_ok=True)
            from doc_auto.services.input_preparation import PreparedInput

            pages = []
            for index in range(1, 3):
                page = destination_dir / f"{Path(pdf_path).stem}_{index:02d}.png"
                page.write_bytes(b"page")
                pages.append(PreparedInput(path=page, source_path=pdf_path, kind="image", restore_path=page))
            return pages

    zip_path = tmp_path / "A.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("sample.pdf", b"%PDF-pretend")
    storage = PortableStorage(tmp_path)

    prepared = InputPreparationPipeline(storage, pdf_renderer=StemPreservingPdfRenderer()).prepare([zip_path])

    assert [item.output_path.name for item in prepared] == ["sample_01.png", "sample_02.png"]


def test_existing_pdf_renderer_does_not_add_copy_suffix_when_pdf_is_already_in_destination(tmp_path, monkeypatch):
    from doc_auto.services import input_preparation as input_preparation_module

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF")

    def fake_render_pdf_pages(working_pdf: Path):
        page = working_pdf.parent / f"{working_pdf.stem}_01.png"
        page.write_bytes(b"page")
        return [page]

    monkeypatch.setattr(input_preparation_module, "render_pdf_pages", fake_render_pdf_pages)

    rendered = ExistingPdfRenderer().render(pdf_path, tmp_path)

    assert [item.path.name for item in rendered] == ["sample_01.png"]
    assert not (tmp_path / "sample_01_01.png").exists()
    assert pdf_path.exists()


def test_input_preparation_pipeline_creates_archive_output_folder_before_processing(tmp_path, monkeypatch):
    from doc_auto.services import input_preparation as input_preparation_module

    zip_path = tmp_path / "A.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("image.png", b"png")
    storage = PortableStorage(tmp_path)
    notified: list[Path] = []
    monkeypatch.setattr(input_preparation_module, "notify_path_changed", lambda path: notified.append(Path(path)))

    InputPreparationPipeline(storage).prepare([zip_path])

    assert (tmp_path / "A").is_dir()
    assert tmp_path in notified


def test_input_preparation_pipeline_removes_extracted_tiff_after_splitting_archive_member(tmp_path):
    tiff_path = tmp_path / "scan.tif"
    first = Image.new("RGB", (8, 8), "white")
    second = Image.new("RGB", (8, 8), "black")
    first.save(tiff_path, save_all=True, append_images=[second])
    zip_path = tmp_path / "A.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(tiff_path, "scan.tif")
    storage = PortableStorage(tmp_path / "app")

    prepared = InputPreparationPipeline(storage).prepare([zip_path])

    assert [item.path.name for item in prepared] == ["scan_001.png", "scan_002.png"]
    assert not (storage.temp_dir / "originals" / "scan.tif").exists()


def test_input_preparation_pipeline_preserves_folder_structure_with_work_outputs(tmp_path):
    folder = tmp_path / "docs"
    nested = folder / "nested"
    nested.mkdir(parents=True)
    image = nested / "scan.jpg"
    image.write_bytes(b"image")
    storage = PortableStorage(tmp_path / "app")

    prepared = InputPreparationPipeline(storage).prepare([folder])

    assert len(prepared) == 1
    assert prepared[0].path == storage.temp_dir / "originals" / "scan.jpg"
    assert prepared[0].output_path == nested / "scan.jpg"
    assert image.exists()


def test_input_preparation_pipeline_allocates_unique_flattened_zip_output_names(tmp_path):
    zip_path = tmp_path / "A.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("same.png", b"first")
        archive.writestr("nested/same.png", b"second")
    storage = PortableStorage(tmp_path / "app")

    prepared = InputPreparationPipeline(storage).prepare([zip_path])

    assert sorted(item.output_path for item in prepared) == [
        tmp_path / "A" / "same.png",
        tmp_path / "A" / "same_01.png",
    ]


def test_input_preparation_pipeline_copies_unsupported_archive_members_to_result_folder(tmp_path):
    zip_path = tmp_path / "A.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("memo.txt", b"memo")
        archive.writestr("nested/data.csv", b"a,b")
    storage = PortableStorage(tmp_path / "app")

    prepared = InputPreparationPipeline(storage).prepare_items(WorkList().add_paths([zip_path]))

    assert [(item.kind, item.path.name, item.output_path) for item in prepared] == [
        ("copy", "memo.txt", tmp_path / "A" / "memo.txt"),
        ("copy", "data.csv", tmp_path / "A" / "data.csv"),
    ]
    assert all(item.path.parent == storage.temp_dir / "originals" for item in prepared)


def test_input_preparation_pipeline_uses_edited_archive_member_current_path(tmp_path):
    zip_path = tmp_path / "A.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("scan.png", b"original")
    edited = tmp_path / "edited.png"
    edited.write_bytes(b"edited")
    storage = PortableStorage(tmp_path / "app")
    item = WorkItem(source_path=zip_path, archive_member_name="scan.png", current_path=edited)

    prepared = InputPreparationPipeline(storage).prepare_items([item])

    assert len(prepared) == 1
    assert prepared[0].path.read_bytes() == b"edited"
    assert prepared[0].output_path == tmp_path / "A" / "edited.png"


def test_input_preparation_pipeline_uses_current_path_for_regular_items(tmp_path):
    original = tmp_path / "scan.png"
    current = tmp_path / "scan_cut.png"
    original.write_bytes(b"original")
    current.write_bytes(b"current")
    storage = PortableStorage(tmp_path / "app")
    item = WorkItem(source_path=original, current_path=current)

    prepared = InputPreparationPipeline(storage).prepare_items([item])

    assert len(prepared) == 1
    assert prepared[0].source_path == current
    assert prepared[0].path.read_bytes() == b"current"
    assert prepared[0].output_path == current


def test_input_preparation_pipeline_expands_nested_zip_into_outer_result_folder(tmp_path):
    nested_zip = tmp_path / "B.zip"
    with zipfile.ZipFile(nested_zip, "w") as archive:
        archive.writestr("inner.jpg", b"image")
        archive.writestr("inner.txt", b"text")
    zip_path = tmp_path / "A.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(nested_zip, "B.zip")
    storage = PortableStorage(tmp_path / "app")

    prepared = InputPreparationPipeline(storage).prepare_items(WorkList().add_paths([zip_path]))

    assert sorted(item.output_path for item in prepared) == [
        tmp_path / "A" / "inner.jpg",
        tmp_path / "A" / "inner.txt",
    ]
    assert {item.kind for item in prepared} == {"copy", "image"}
