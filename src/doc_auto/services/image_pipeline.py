from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
import uuid
from typing import Any
from typing import TYPE_CHECKING
from typing import Protocol

from doc_auto.services.file_replace import replace_file_with_retry
from doc_auto.services.temp_storage import PortableStorage
from doc_auto.vision.document_presence import (
    DocumentPresence,
    DocumentPresenceAnalyzer,
)
from doc_auto.vision.ocr_orientation import OcrOrientationProbe

if TYPE_CHECKING:
    from doc_auto.services.ocr_runner import OcrData


@dataclass(frozen=True)
class ImagePipelineStage:
    name: str
    status: str
    elapsed_seconds: float
    detail: str = ""
    signals: dict[str, Any] | None = None


@dataclass(frozen=True)
class ImagePipelineResult:
    path: Path
    changed: bool
    detail: str = ""
    cached_ocr: OcrData | None = None
    stages: tuple[ImagePipelineStage, ...] = ()


@dataclass(frozen=True)
class ImageNormalizationOptions:
    exif_orientation_enabled: bool = True
    ocr_orientation_enabled: bool = True


class ImagePipeline(Protocol):
    def normalize(self, image_path: Path) -> ImagePipelineResult:
        ...


class IdentityImagePipeline:
    def normalize(self, image_path: Path) -> ImagePipelineResult:
        return ImagePipelineResult(path=Path(image_path), changed=False, detail="identity")


class DocumentImagePipeline:
    def __init__(
        self,
        storage: PortableStorage,
        *,
        ocr_orientation_probe: OcrOrientationProbe | None = None,
        presence_analyzer: DocumentPresenceAnalyzer | None = None,
        options: ImageNormalizationOptions | None = None,
    ) -> None:
        self.storage = storage
        self.ocr_orientation_probe = ocr_orientation_probe or OcrOrientationProbe()
        self.presence_analyzer = presence_analyzer or DocumentPresenceAnalyzer()
        self.options = options or ImageNormalizationOptions()

    def normalize(self, image_path: Path) -> ImagePipelineResult:
        image_path = Path(image_path)
        details: list[str] = []
        stages: list[ImagePipelineStage] = []
        changed = False
        exif_applied = False

        start = time.perf_counter()
        if not self.options.exif_orientation_enabled:
            stages.append(self._stage("exif_orientation", "disabled", start))
        else:
            exif_applied = self._apply_exif_orientation(image_path)
            if exif_applied:
                details.append("exif_oriented")
                changed = True
                stages.append(self._stage("exif_orientation", "applied", start, "exif_oriented"))
            else:
                stages.append(self._stage("exif_orientation", "skipped", start, "not_required"))

        start = time.perf_counter()
        presence = self.presence_analyzer.analyze(image_path)
        stages.append(
            self._stage(
                "document_presence",
                "document" if presence.document_like else "non_document",
                start,
                presence.scene_kind,
                self._presence_signals(presence),
            )
        )
        if not presence.document_like:
            details.append(presence.scene_kind)
            stages.append(self._stage("ocr_orientation", "skipped", time.perf_counter(), presence.scene_kind))
            return ImagePipelineResult(
                path=image_path,
                changed=changed,
                detail=";".join(details),
                stages=tuple(stages),
            )

        start = time.perf_counter()
        if not self.options.ocr_orientation_enabled:
            stages.append(self._stage("ocr_orientation", "disabled", start))
            ocr_orientation_angle = None
        else:
            ocr_orientation_angle, ocr_stage = self._apply_ocr_orientation(
                image_path,
                start,
                exif_applied=exif_applied,
                presence=presence,
            )
            stages.append(ocr_stage)
        if ocr_orientation_angle is not None:
            details.append(f"ocr_oriented:{ocr_orientation_angle}")
            changed = True

        return ImagePipelineResult(
            path=image_path,
            changed=changed,
            detail=";".join(details),
            stages=tuple(stages),
        )

    def _apply_exif_orientation(self, image_path: Path) -> bool:
        from PIL import Image, ImageOps

        with Image.open(image_path) as image:
            exif = image.getexif()
            orientation = exif.get(274)
            if orientation in (None, 1):
                return False
            if not self._has_camera_exif(exif):
                return False

            transposed = ImageOps.exif_transpose(image)
            if image_path.suffix.lower() in {".jpg", ".jpeg"} and transposed.mode not in {"RGB", "L"}:
                transposed = transposed.convert("RGB")
            transposed.load()
            output = transposed.copy()

        temp_path = self._temp_output_path(image_path.suffix)
        self._save_image(output, temp_path, image_path.suffix)
        self._replace_file(temp_path, image_path)
        return True

    def _apply_ocr_orientation(
        self,
        image_path: Path,
        started_at: float,
        *,
        exif_applied: bool = False,
        presence: DocumentPresence | None = None,
    ) -> tuple[int | None, ImagePipelineStage]:
        if not self._should_probe_ocr_orientation(
            image_path,
            exif_applied=exif_applied,
            presence=presence,
        ):
            return None, self._stage("ocr_orientation", "skipped", started_at, "gate_false")

        decision = self.ocr_orientation_probe.detect(image_path)
        signals = {
            "method": decision.method,
            "scores": decision.scores,
            "region_count": decision.region_count,
            "angle_degrees": decision.angle_degrees,
        }
        if not decision.detected or decision.angle_degrees == 0:
            status = "rejected" if decision.method == "ocr_probe_rejected" else "skipped"
            return None, self._stage(
                "ocr_orientation",
                status,
                started_at,
                decision.method,
                signals,
            )

        self._rotate_in_place(image_path, decision.angle_degrees)
        return int(decision.angle_degrees), self._stage(
            "ocr_orientation",
            "applied",
            started_at,
            decision.method,
            signals,
        )

    def _should_probe_ocr_orientation(
        self,
        image_path: Path,
        *,
        exif_applied: bool = False,
        presence: DocumentPresence | None = None,
    ) -> bool:
        if presence is not None and not presence.document_like:
            return False
        return True

    def _rotate_in_place(self, image_path: Path, angle_degrees: float) -> None:
        from PIL import Image

        with Image.open(image_path) as image:
            rotated = image.rotate(
                angle_degrees,
                expand=True,
                fillcolor=(255, 255, 255),
                resample=Image.Resampling.BICUBIC,
            )
            if image_path.suffix.lower() in {".jpg", ".jpeg"} and rotated.mode not in {"RGB", "L"}:
                rotated = rotated.convert("RGB")
            rotated.load()
            output = rotated.copy()

        temp_path = self._temp_output_path(image_path.suffix)
        self._save_image(output, temp_path, image_path.suffix)
        self._replace_file(temp_path, image_path)

    def _temp_output_path(self, suffix: str) -> Path:
        temp_dir = self.storage.temp_dir / "originals"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir / f".tmp_{uuid.uuid4().hex}{suffix}"

    def _save_image(self, image, path: Path, suffix: str) -> None:
        try:
            if suffix.lower() in {".jpg", ".jpeg"}:
                image.save(path, "JPEG", quality=95, optimize=True)
            else:
                image.save(path)
        finally:
            image.close()

    def _replace_file(self, source: Path, target: Path) -> None:
        replace_file_with_retry(source, target)

    def _has_camera_exif(self, exif) -> bool:
        camera_tags = (271, 272, 306, 36867, 36868)
        return any(exif.get(tag) for tag in camera_tags)

    def _stage(
        self,
        name: str,
        status: str,
        started_at: float,
        detail: str = "",
        signals: dict[str, Any] | None = None,
    ) -> ImagePipelineStage:
        return ImagePipelineStage(
            name=name,
            status=status,
            elapsed_seconds=round(time.perf_counter() - started_at, 4),
            detail=detail,
            signals=signals or {},
        )

    def _presence_signals(self, presence: DocumentPresence) -> dict[str, Any]:
        return {
            "document_like": presence.document_like,
            "scene_kind": presence.scene_kind,
            "confidence": presence.confidence,
            **dict(presence.signals),
        }
