from pathlib import Path
import threading
import zipfile

from PIL import Image

from doc_auto.domain.job import WorkItem, WorkStatus
from doc_auto.domain.options import ProcessingMode
from doc_auto.services.input_preparation import InputPreparationPipeline
from doc_auto.services.pdf_converter import PdfConversionResult, PdfConverter
from doc_auto.services.pdf_workflow import PdfConversionWorkflow
from doc_auto.services.temp_storage import PortableStorage
from tests.pdf_assertions import assert_pdf_page_count


class FakeHwpPdfConverter:
    def __init__(self) -> None:
        self.calls = []

    def convert_to_pdf(
        self,
        hwp_path: Path,
        output_path: Path,
        *,
        permission_hwp_path: Path | None = None,
    ) -> PdfConversionResult:
        self.calls.append((hwp_path, output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"%PDF-hwp")
        return PdfConversionResult(output_path=output_path, source_paths=[hwp_path], page_count=1)


class FakeFailingHwpPdfConverter:
    def convert_to_pdf(
        self,
        hwp_path: Path,
        output_path: Path,
        *,
        permission_hwp_path: Path | None = None,
    ) -> PdfConversionResult:
        raise RuntimeError("hwp failed")


def test_pdf_workflow_converts_items_individually(tmp_path):
    image_path = tmp_path / "scan.jpg"
    Image.new("RGB", (1200, 800), "white").save(image_path)
    storage = PortableStorage(tmp_path / "app")
    item = WorkItem(source_path=image_path)

    workflow = PdfConversionWorkflow(input_pipeline=InputPreparationPipeline(storage), converter=PdfConverter())
    results = workflow.convert_individual([item])

    assert len(results) == 1
    assert results[0].status == WorkStatus.COMPLETED
    assert results[0].last_mode == ProcessingMode.PDF_CONVERT
    assert results[0].current_path == tmp_path / "scan.pdf"
    with Image.open(image_path) as original:
        assert original.size == (1200, 800)


def test_pdf_workflow_notifies_output_folder_after_individual_convert(tmp_path, monkeypatch):
    from doc_auto.services import pdf_workflow as pdf_workflow_module

    image_path = tmp_path / "scan.jpg"
    Image.new("RGB", (1200, 800), "white").save(image_path)
    notified: list[Path] = []
    monkeypatch.setattr(pdf_workflow_module, "notify_path_changed", lambda path: notified.append(Path(path)))
    workflow = PdfConversionWorkflow(
        input_pipeline=InputPreparationPipeline(PortableStorage(tmp_path / "app")),
        converter=PdfConverter(),
    )

    workflow.convert_individual([WorkItem(source_path=image_path)])

    assert tmp_path in notified


def test_pdf_workflow_deletes_individual_source_when_enabled(tmp_path):
    image_path = tmp_path / "scan.jpg"
    Image.new("RGB", (120, 80), "white").save(image_path)
    deleted: list[Path] = []
    workflow = PdfConversionWorkflow(
        input_pipeline=InputPreparationPipeline(PortableStorage(tmp_path / "app")),
        converter=PdfConverter(),
        source_deleter=lambda path: deleted.append(Path(path)),
    )

    results = workflow.convert_individual([WorkItem(source_path=image_path)], delete_source_on_success=True)

    assert results[0].status == WorkStatus.COMPLETED
    assert deleted == [image_path]


def test_pdf_workflow_deletes_current_file_when_enabled_for_processed_item(tmp_path):
    original = tmp_path / "original.jpg"
    current = tmp_path / "work" / "processed.jpg"
    current.parent.mkdir()
    Image.new("RGB", (120, 80), "white").save(original)
    Image.new("RGB", (120, 80), "black").save(current)
    deleted: list[Path] = []
    workflow = PdfConversionWorkflow(
        input_pipeline=InputPreparationPipeline(PortableStorage(tmp_path / "app")),
        converter=PdfConverter(),
        source_deleter=lambda path: deleted.append(Path(path)),
    )

    results = workflow.convert_individual(
        [WorkItem(source_path=original, current_path=current)],
        delete_source_on_success=True,
    )

    assert results[0].status == WorkStatus.COMPLETED
    assert deleted == [current]


def test_pdf_workflow_deletes_extracted_archive_pdf_when_enabled(tmp_path):
    from doc_auto.services.input_preparation import PreparedInput

    class FakePdfRenderer:
        def page_count(self, _pdf_path: Path) -> int:
            return 1

        def render(self, pdf_path: Path, destination_dir: Path):
            destination_dir.mkdir(parents=True, exist_ok=True)
            page = destination_dir / "claim_001.png"
            Image.new("RGB", (100, 100), "white").save(page)
            return [PreparedInput(path=page, source_path=pdf_path, kind="image", restore_path=page)]

    archive = tmp_path / "docs.zip"
    extracted_pdf = tmp_path / "docs" / "claim.pdf"
    extracted_pdf.parent.mkdir()
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("claim.pdf", b"%PDF")
    extracted_pdf.write_bytes(b"%PDF")
    deleted: list[Path] = []
    workflow = PdfConversionWorkflow(
        input_pipeline=InputPreparationPipeline(PortableStorage(tmp_path / "app"), pdf_renderer=FakePdfRenderer()),
        converter=PdfConverter(),
        source_deleter=lambda path: deleted.append(Path(path)),
    )

    results = workflow.convert_individual(
        [WorkItem(source_path=archive, archive_member_name="claim.pdf", current_path=extracted_pdf)],
        delete_source_on_success=True,
    )

    assert results
    assert results[0].status == WorkStatus.COMPLETED
    assert deleted == [extracted_pdf]


def test_pdf_workflow_converts_bundle(tmp_path):
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    Image.new("RGB", (100, 100), "white").save(first)
    Image.new("RGB", (100, 100), "black").save(second)
    storage = PortableStorage(tmp_path / "app")
    items = [WorkItem(source_path=first), WorkItem(source_path=second)]

    workflow = PdfConversionWorkflow(input_pipeline=InputPreparationPipeline(storage), converter=PdfConverter())
    result = workflow.convert_bundle(items, tmp_path / "bundle.pdf")

    assert result.output_path == tmp_path / "bundle.pdf"
    assert result.page_count == 2
    assert_pdf_page_count(result.output_path, 2)


def test_pdf_workflow_notifies_output_folder_after_bundle(tmp_path, monkeypatch):
    from doc_auto.services import pdf_workflow as pdf_workflow_module

    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    Image.new("RGB", (100, 100), "white").save(first)
    Image.new("RGB", (100, 100), "black").save(second)
    notified: list[Path] = []
    monkeypatch.setattr(pdf_workflow_module, "notify_path_changed", lambda path: notified.append(Path(path)))

    workflow = PdfConversionWorkflow(input_pipeline=InputPreparationPipeline(PortableStorage(tmp_path / "app")), converter=PdfConverter())
    workflow.convert_bundle([WorkItem(source_path=first), WorkItem(source_path=second)], tmp_path / "bundle.pdf")

    assert notified == [tmp_path]


def test_pdf_workflow_deletes_bundle_sources_when_enabled(tmp_path):
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    Image.new("RGB", (100, 100), "white").save(first)
    Image.new("RGB", (100, 100), "black").save(second)
    deleted: list[Path] = []
    workflow = PdfConversionWorkflow(
        input_pipeline=InputPreparationPipeline(PortableStorage(tmp_path / "app")),
        converter=PdfConverter(),
        source_deleter=lambda path: deleted.append(Path(path)),
    )

    workflow.convert_bundle(
        [WorkItem(source_path=first), WorkItem(source_path=second)],
        tmp_path / "bundle.pdf",
        delete_source_on_success=True,
    )

    assert deleted == [first, second]


def test_pdf_workflow_deletes_bundle_current_files_when_enabled(tmp_path):
    originals = [tmp_path / "original_a.jpg", tmp_path / "original_b.jpg"]
    current_dir = tmp_path / "work"
    current_dir.mkdir()
    currents = [current_dir / "a.jpg", current_dir / "b.jpg"]
    for path in originals + currents:
        Image.new("RGB", (100, 100), "white").save(path)
    deleted: list[Path] = []
    workflow = PdfConversionWorkflow(
        input_pipeline=InputPreparationPipeline(PortableStorage(tmp_path / "app")),
        converter=PdfConverter(),
        source_deleter=lambda path: deleted.append(Path(path)),
    )

    workflow.convert_bundle(
        [
            WorkItem(source_path=originals[0], current_path=currents[0]),
            WorkItem(source_path=originals[1], current_path=currents[1]),
        ],
        current_dir / "bundle.pdf",
        delete_source_on_success=True,
    )

    assert deleted == currents


def test_pdf_workflow_bundle_uses_current_paths_for_processed_items(tmp_path):
    missing_first = tmp_path / "missing_first.jpg"
    missing_second = tmp_path / "missing_second.jpg"
    first = tmp_path / "first_current.jpg"
    second = tmp_path / "second_current.jpg"
    Image.new("RGB", (100, 100), "white").save(first)
    Image.new("RGB", (100, 100), "black").save(second)
    storage = PortableStorage(tmp_path / "app")
    items = [
        WorkItem(source_path=missing_first, current_path=first),
        WorkItem(source_path=missing_second, current_path=second),
    ]

    workflow = PdfConversionWorkflow(input_pipeline=InputPreparationPipeline(storage), converter=PdfConverter())
    result = workflow.convert_bundle(items, tmp_path / "bundle.pdf")

    assert result.page_count == 2
    assert_pdf_page_count(result.output_path, 2)


def test_pdf_workflow_bundle_preserves_page_metadata_order(tmp_path, monkeypatch):
    from doc_auto.services import pdf_workflow as pdf_workflow_module

    first = tmp_path / "doc_001.png"
    second = tmp_path / "doc_002.png"
    third = tmp_path / "doc_003.png"
    for path in (first, second, third):
        Image.new("RGB", (100, 100), "white").save(path)
    captured: list[Path] = []

    class CapturingConverter(PdfConverter):
        def convert_bundle(self, images, output_path):
            captured.extend(Path(path) for path in images)
            return super().convert_bundle(images, output_path)

    workflow = PdfConversionWorkflow(
        input_pipeline=InputPreparationPipeline(PortableStorage(tmp_path / "app")),
        converter=CapturingConverter(),
    )
    items = [
        WorkItem(source_path=third, current_path=third, bundle_group_id="doc.pdf", page_index=3),
        WorkItem(source_path=first, current_path=first, bundle_group_id="doc.pdf", page_index=1),
        WorkItem(source_path=second, current_path=second, bundle_group_id="doc.pdf", page_index=2),
    ]

    workflow.convert_bundle(items, tmp_path / "bundle.pdf")

    assert [path.name for path in captured] == [first.name, second.name, third.name]


def test_pdf_converter_preserves_source_image_size_before_pdf(tmp_path):
    image_path = tmp_path / "large.jpg"
    Image.new("RGB", (3000, 2000), "white").save(image_path)

    prepared = PdfConverter()._prepare_pdf_image(image_path)

    assert prepared.size == (3000, 2000)
    prepared.close()


def test_pdf_converter_embeds_jpeg_without_reencoding_for_bundle(tmp_path):
    image_path = tmp_path / "photo.jpg"
    Image.new("RGB", (160, 120), "white").save(image_path, quality=87)
    original_bytes = image_path.read_bytes()
    output_path = tmp_path / "bundle.pdf"

    result = PdfConverter().convert_bundle([image_path], output_path)

    assert result.output_path == output_path
    assert original_bytes in output_path.read_bytes()


def test_pdf_workflow_converts_hwp_to_pdf(tmp_path):
    hwp_path = tmp_path / "doc.hwp"
    hwp_path.write_bytes(b"hwp")
    storage = PortableStorage(tmp_path / "app")
    hwp_converter = FakeHwpPdfConverter()
    workflow = PdfConversionWorkflow(
        input_pipeline=InputPreparationPipeline(storage),
        converter=PdfConverter(),
        hwp_converter=hwp_converter,
    )

    results = workflow.convert_individual([WorkItem(source_path=hwp_path)])

    assert len(results) == 1
    assert results[0].status == WorkStatus.COMPLETED
    assert results[0].current_path == tmp_path / "doc.pdf"
    assert results[0].current_path.read_bytes() == b"%PDF-hwp"
    assert hwp_converter.calls[0][0] == storage.temp_dir / "originals" / "doc.hwp"


def test_pdf_workflow_converts_hwp_inside_zip_to_pdf(tmp_path):
    zip_path = tmp_path / "docs.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("claim.hwp", b"hwp")
    storage = PortableStorage(tmp_path / "app")
    hwp_converter = FakeHwpPdfConverter()
    workflow = PdfConversionWorkflow(
        input_pipeline=InputPreparationPipeline(storage),
        converter=PdfConverter(),
        hwp_converter=hwp_converter,
    )

    results = workflow.convert_individual([WorkItem(source_path=zip_path)])

    assert len(results) == 1
    assert results[0].status == WorkStatus.COMPLETED
    assert results[0].current_path == tmp_path / "docs" / "claim.pdf"
    assert results[0].current_path.read_bytes() == b"%PDF-hwp"
    assert hwp_converter.calls[0][0] == storage.temp_dir / "originals" / "claim.hwp"


def test_hwp_pdf_converter_does_not_require_png_pages(tmp_path, monkeypatch):
    import json

    from doc_auto.services import pdf_workflow as pdf_workflow_module

    hwp_path = tmp_path / "doc.hwp"
    pdf_path = tmp_path / "doc.pdf"
    hwp_path.write_bytes(b"hwp")
    calls: list[list[str]] = []

    def fake_worker_command(*args: str) -> list[str]:
        return ["python", *args]

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        pdf_path.write_bytes(b"%PDF-only")
        target_json = Path(cmd[4])
        target_json.write_text(json.dumps({"pdf": str(pdf_path)}), encoding="utf-8")

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr(pdf_workflow_module, "worker_command", fake_worker_command)
    monkeypatch.setattr(pdf_workflow_module.subprocess, "run", fake_run)

    result = pdf_workflow_module.HwpPdfConverter().convert_to_pdf(hwp_path, pdf_path)

    assert result.output_path == pdf_path
    assert result.page_count == 1
    assert pdf_path.read_bytes() == b"%PDF-only"
    assert calls[0][1] == "--hwp-pdf-worker"
    assert not list(tmp_path.glob("doc_page*"))


def test_hwp_pdf_converter_uses_ascii_worker_paths_for_hwp_com(tmp_path, monkeypatch):
    import json

    from doc_auto.services import pdf_workflow as pdf_workflow_module

    hwp_path = tmp_path / "간이영수증.hwp"
    pdf_path = tmp_path / "간이영수증.pdf"
    hwp_path.write_bytes(b"hwp")
    worker_paths: list[tuple[Path, Path]] = []

    def fake_worker_command(*args: str) -> list[str]:
        return ["python", *args]

    def fake_run(cmd, **kwargs):
        worker_hwp = Path(cmd[2])
        worker_pdf = Path(cmd[3])
        permission_hwp = Path(cmd[5])
        worker_paths.append((worker_hwp, worker_pdf))
        assert worker_hwp.name == "source.hwp"
        assert worker_pdf.name == "output.pdf"
        assert permission_hwp == hwp_path.resolve()
        assert worker_hwp.read_bytes() == b"hwp"
        worker_pdf.write_bytes(b"%PDF-ascii")
        Path(cmd[4]).write_text(json.dumps({"pdf": str(worker_pdf)}), encoding="utf-8")

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr(pdf_workflow_module, "worker_command", fake_worker_command)
    monkeypatch.setattr(pdf_workflow_module.subprocess, "run", fake_run)

    result = pdf_workflow_module.HwpPdfConverter().convert_to_pdf(hwp_path, pdf_path)

    assert worker_paths
    assert result.output_path == pdf_path
    assert pdf_path.read_bytes() == b"%PDF-ascii"


def test_run_py_hwp_pdf_worker_dispatches_to_canonical_hwp_module(monkeypatch):
    import importlib
    import sys
    import types

    run_module = importlib.import_module("run")
    called: list[str] = []

    hwp_module = types.ModuleType("doc_auto.services.hwp_pdf")
    hwp_module.run_hwp_pdf_worker = lambda: called.append("canonical")
    legacy_module = types.ModuleType("doc_auto.services.simple_pipeline")
    legacy_module.run_hwp_pdf_worker = lambda: (_ for _ in ()).throw(AssertionError("legacy HWP worker must not run"))
    monkeypatch.setitem(sys.modules, "doc_auto.services.hwp_pdf", hwp_module)
    monkeypatch.setitem(sys.modules, "doc_auto.services.simple_pipeline", legacy_module)

    assert run_module._run_worker_if_requested(["run.py", "--hwp-pdf-worker"]) is True
    assert called == ["canonical"]


def test_hwp_pdf_converter_reports_pdf_worker_failure(tmp_path, monkeypatch):
    from doc_auto.services import pdf_workflow as pdf_workflow_module

    hwp_path = tmp_path / "doc.hwp"
    pdf_path = tmp_path / "doc.pdf"
    hwp_path.write_bytes(b"hwp")
    calls: list[list[str]] = []

    def fake_worker_command(*args: str) -> list[str]:
        return ["python", *args]

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        class Failed:
            returncode = 1
            stdout = ""
            stderr = "pdf worker failed"

        return Failed()

    monkeypatch.setattr(pdf_workflow_module, "worker_command", fake_worker_command)
    monkeypatch.setattr(pdf_workflow_module.subprocess, "run", fake_run)

    try:
        pdf_workflow_module.HwpPdfConverter().convert_to_pdf(hwp_path, pdf_path)
    except RuntimeError as exc:
        assert "pdf worker failed" in str(exc)
    else:
        raise AssertionError("expected HWP PDF conversion failure")

    assert [call[1] for call in calls] == ["--hwp-pdf-worker", "--hwp-pdf-worker"]


def test_hwp_pdf_converter_ignores_stale_output_when_worker_fails(tmp_path, monkeypatch):
    from doc_auto.services import pdf_workflow as pdf_workflow_module

    hwp_path = tmp_path / "doc.hwp"
    pdf_path = tmp_path / "doc.pdf"
    hwp_path.write_bytes(b"hwp")
    pdf_path.write_bytes(b"%PDF-stale")

    def fake_worker_command(*args: str) -> list[str]:
        return ["python", *args]

    def fake_run(cmd, **kwargs):
        class Failed:
            returncode = 1
            stdout = ""
            stderr = "hwp worker failed"

        return Failed()

    monkeypatch.setattr(pdf_workflow_module, "worker_command", fake_worker_command)
    monkeypatch.setattr(pdf_workflow_module.subprocess, "run", fake_run)

    try:
        pdf_workflow_module.HwpPdfConverter().convert_to_pdf(hwp_path, pdf_path)
    except RuntimeError as exc:
        assert "hwp worker failed" in str(exc)
    else:
        raise AssertionError("expected stale output to be ignored")

    assert pdf_path.read_bytes() == b"%PDF-stale"


def test_hwp_pdf_worker_saves_pdf_only_without_png_export(tmp_path, monkeypatch):
    import sys
    import types

    from doc_auto.services import hwp_pdf as hwp_module

    hwp_path = tmp_path / "doc.hwp"
    pdf_path = tmp_path / "doc.pdf"
    hwp_path.write_bytes(b"hwp")
    save_calls: list[tuple[str, str, str]] = []
    launched: list[Path] = []
    visibility: list[bool] = []

    class FakeWindow:
        def __init__(self) -> None:
            self._visible = False

        @property
        def Visible(self):
            return self._visible

        @Visible.setter
        def Visible(self, value):
            visibility.append(bool(value))
            self._visible = bool(value)

    class FakeWindows:
        Active_XHwpWindow = FakeWindow()

        def Item(self, _index):
            return FakeWindow()

    class FakeHwp:
        XHwpWindows = FakeWindows()

        def RegisterModule(self, *_args):
            return True

        def Clear(self, *_args):
            return True

        def Open(self, *_args):
            return True

        def SaveAs(self, path, file_format, options):
            save_calls.append((Path(path).name, file_format, options))
            if file_format == "PDF":
                Path(path).write_bytes(b"%PDF-only")
            elif file_format == "PNG":
                Path(path).write_bytes(b"PNG")
            return True

        def Quit(self):
            return True

    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: None
    pythoncom.CoUninitialize = lambda: None
    win32com = types.ModuleType("win32com")
    client = types.ModuleType("win32com.client")
    client.Dispatch = lambda _name: FakeHwp()
    win32com.client = client
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setattr(hwp_module, "open_hwp_for_permission", lambda path: launched.append(Path(path)))

    hwp_module.convert_hwp_to_pdf_only(hwp_path, pdf_path)

    assert pdf_path.read_bytes() == b"%PDF-only"
    assert save_calls == [("doc.pdf", "PDF", "")]
    assert launched == []
    assert visibility == [False]
    assert not list(tmp_path.glob("doc_page*"))


def test_hwp_pdf_worker_falls_back_to_visible_permission_flow_after_hidden_failure(tmp_path, monkeypatch):
    import sys
    import types

    from doc_auto.services import hwp_pdf as hwp_module

    hwp_path = tmp_path / "doc.hwp"
    permission_path = tmp_path / "permission.hwp"
    pdf_path = tmp_path / "doc.pdf"
    hwp_path.write_bytes(b"hwp")
    permission_path.write_bytes(b"hwp")
    calls: list[tuple[str, Path | None]] = []
    visibility: list[bool] = []

    class FakeWindow:
        def __init__(self) -> None:
            self._visible = False

        @property
        def Visible(self):
            return self._visible

        @Visible.setter
        def Visible(self, value):
            visibility.append(bool(value))
            self._visible = bool(value)

    class FakeWindows:
        def __init__(self) -> None:
            self.Active_XHwpWindow = FakeWindow()

        def Item(self, _index):
            return FakeWindow()

    class FakeHiddenFailureHwp:
        def __init__(self) -> None:
            self.XHwpWindows = FakeWindows()

        def RegisterModule(self, *_args):
            return True

        def Clear(self, *_args):
            return True

        def Open(self, *_args):
            calls.append(("hidden_open", None))
            return False

        def Quit(self):
            return True

    class FakeVisibleHwp:
        def __init__(self) -> None:
            self.XHwpWindows = FakeWindows()

        def RegisterModule(self, *_args):
            return True

        def Clear(self, *_args):
            return True

        def Open(self, *_args):
            calls.append(("visible_open", None))
            return True

        def SaveAs(self, path, file_format, _options):
            Path(path).write_bytes(b"%PDF")
            return True

        def Quit(self):
            return True

    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: None
    pythoncom.CoUninitialize = lambda: None
    win32com = types.ModuleType("win32com")
    client = types.ModuleType("win32com.client")
    dispatches = iter([FakeHiddenFailureHwp(), FakeVisibleHwp()])
    client.Dispatch = lambda _name: next(dispatches)
    win32com.client = client
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setattr(
        hwp_module,
        "open_hwp_for_permission",
        lambda path: calls.append(("launch", Path(path))),
        raising=False,
    )
    monkeypatch.setattr(
        hwp_module,
        "close_hwp_permission_window",
        lambda handle: calls.append(("close", handle)),
        raising=False,
    )

    hwp_module.convert_hwp_to_pdf_only(hwp_path, pdf_path, permission_hwp_path=permission_path)

    assert calls == [
        ("hidden_open", None),
        ("launch", permission_path),
        ("visible_open", None),
        ("close", None),
    ]
    assert visibility == [False, True]


def test_hwp_permission_launch_tracks_only_new_hwp_processes(tmp_path, monkeypatch):
    from doc_auto.services import hwp_pdf as hwp_module

    hwp_path = tmp_path / "doc.hwp"
    hwp_path.write_bytes(b"hwp")
    snapshots = iter([{100}, {100, 200, 201}])
    launched: list[Path] = []
    monkeypatch.setattr(hwp_module, "_hwp_process_ids", lambda: next(snapshots))
    monkeypatch.setattr(hwp_module.os, "startfile", lambda path: launched.append(Path(path)), raising=False)
    monkeypatch.setattr(hwp_module.time, "sleep", lambda _seconds: None)

    handle = hwp_module.open_hwp_for_permission(hwp_path)

    assert launched == [hwp_path.resolve()]
    assert handle.pids == {200, 201}


def test_packaged_spec_uses_onestep_name_and_includes_pywin32_hidden_imports():
    project_root = Path(__file__).resolve().parents[1]
    spec_path = project_root / "OneStep-Windows.spec"

    assert spec_path.exists()
    assert not (project_root / "Doc-Auto-Windows-OCR.spec").exists()

    spec = spec_path.read_text(encoding="utf-8")

    assert "'pythoncom'" in spec
    assert "'win32com'" in spec
    assert "'win32com.client'" in spec
    assert "'pywintypes'" in spec


def test_pdf_workflow_reports_hwp_converter_failure(tmp_path):
    hwp_path = tmp_path / "doc.hwp"
    hwp_path.write_bytes(b"hwp")
    storage = PortableStorage(tmp_path / "app")
    workflow = PdfConversionWorkflow(
        input_pipeline=InputPreparationPipeline(storage),
        converter=PdfConverter(),
        hwp_converter=FakeFailingHwpPdfConverter(),
    )

    results = workflow.convert_individual([WorkItem(source_path=hwp_path)])

    assert results[0].status == WorkStatus.FAILED
    assert "hwp failed" in results[0].detail


def test_pdf_workflow_stops_individual_conversion_before_preparing_when_cancelled(tmp_path):
    class CountingInputPipeline(InputPreparationPipeline):
        def __init__(self, storage: PortableStorage) -> None:
            super().__init__(storage)
            self.calls = 0

        def prepare(self, paths):
            self.calls += 1
            return super().prepare(paths)

    image_path = tmp_path / "scan.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path)
    storage = PortableStorage(tmp_path / "app")
    input_pipeline = CountingInputPipeline(storage)
    cancel_event = threading.Event()
    cancel_event.set()
    item = WorkItem(source_path=image_path)

    workflow = PdfConversionWorkflow(input_pipeline=input_pipeline, converter=PdfConverter())
    results = workflow.convert_individual([item], cancel_event=cancel_event)

    assert input_pipeline.calls == 0
    assert results[0].status == WorkStatus.STOPPED
    assert results[0].detail == "stopped"


def test_pdf_workflow_stops_bundle_before_preparing_when_cancelled(tmp_path):
    class CountingInputPipeline(InputPreparationPipeline):
        def __init__(self, storage: PortableStorage) -> None:
            super().__init__(storage)
            self.calls = 0

        def prepare(self, paths):
            self.calls += 1
            return super().prepare(paths)

    image_path = tmp_path / "scan.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path)
    storage = PortableStorage(tmp_path / "app")
    input_pipeline = CountingInputPipeline(storage)
    cancel_event = threading.Event()
    cancel_event.set()
    workflow = PdfConversionWorkflow(input_pipeline=input_pipeline, converter=PdfConverter())

    try:
        workflow.convert_bundle(
            [WorkItem(source_path=image_path)],
            tmp_path / "bundle.pdf",
            cancel_event=cancel_event,
        )
    except InterruptedError as exc:
        assert str(exc) == "stopped"
    else:
        raise AssertionError("expected InterruptedError")

    assert input_pipeline.calls == 0
