from pathlib import Path

from PIL import Image

from doc_auto.services.image_pipeline import DocumentImagePipeline
from doc_auto.vision.document_presence import DocumentPresence
from doc_auto.vision.ocr_orientation import OcrOrientationDecision


class FakePresenceAnalyzer:
    def __init__(self, presence: DocumentPresence) -> None:
        self.presence = presence

    def analyze(self, _image_path: Path) -> DocumentPresence:
        return self.presence


class FailingOcrProbe:
    def detect(self, _image_path: Path):
        raise AssertionError("OCR orientation should not run")


class FixedOcrProbe:
    def __init__(self, angle: int) -> None:
        self.angle = angle

    def detect(self, _image_path: Path) -> OcrOrientationDecision:
        return OcrOrientationDecision(
            detected=self.angle != 0,
            angle_degrees=self.angle,
            method="test_probe",
            scores={0: 1.0, 90: 10.0, 180: 1.0, 270: 1.0},
            region_count=1,
        )


def _presence(document_like: bool) -> DocumentPresence:
    return DocumentPresence(
        document_like=document_like,
        scene_kind="document" if document_like else "non_document",
        confidence=1.0 if document_like else 0.0,
        signals={},
    )


def test_image_pipeline_skips_ocr_orientation_for_non_document(tmp_path):
    image_path = tmp_path / "photo.jpg"
    Image.new("RGB", (80, 120), "blue").save(image_path)
    from doc_auto.services.temp_storage import PortableStorage

    pipeline = DocumentImagePipeline(
        PortableStorage(tmp_path / "app"),
        presence_analyzer=FakePresenceAnalyzer(_presence(False)),
        ocr_orientation_probe=FailingOcrProbe(),
    )

    result = pipeline.normalize(image_path)

    assert result.changed is False
    assert result.detail == "non_document"
    assert [stage.name for stage in result.stages] == [
        "exif_orientation",
        "document_presence",
        "ocr_orientation",
    ]


def test_image_pipeline_applies_ocr_orientation_without_auto_crop(tmp_path):
    image_path = tmp_path / "scan.jpg"
    Image.new("RGB", (80, 120), "white").save(image_path)
    from doc_auto.services.temp_storage import PortableStorage

    pipeline = DocumentImagePipeline(
        PortableStorage(tmp_path / "app"),
        presence_analyzer=FakePresenceAnalyzer(_presence(True)),
        ocr_orientation_probe=FixedOcrProbe(90),
    )

    result = pipeline.normalize(image_path)

    assert result.changed is True
    assert result.detail == "ocr_oriented:90"
    assert [stage.name for stage in result.stages] == [
        "exif_orientation",
        "document_presence",
        "ocr_orientation",
    ]
    with Image.open(image_path) as image:
        assert image.size == (120, 80)
