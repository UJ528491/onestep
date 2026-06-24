from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Protocol


class OcrBatchRunner(Protocol):
    def run_batch(self, images) -> list[str]:
        ...


@dataclass(frozen=True)
class OcrOrientationDecision:
    detected: bool
    angle_degrees: int
    method: str
    scores: dict[int, float]
    region_count: int


class WindowsOcrBatchRunner:
    def run_batch(self, images) -> list[str]:
        from doc_auto.services.ocr import OcrEngine

        return OcrEngine().run_image_batch(list(images))


class OcrOrientationProbe:
    def __init__(
        self,
        runner: OcrBatchRunner | None = None,
        *,
        angles: tuple[int, ...] = (0, 90, 180, 270),
        min_score: float = 8.0,
        min_margin_ratio: float = 0.18,
        region_trust_score: float = 300.0,
        region_trust_margin: float = 180.0,
        region_max_side: int = 1200,
        full_page_max_side: int = 1200,
    ) -> None:
        self.runner = runner or WindowsOcrBatchRunner()
        self.angles = angles
        self.min_score = min_score
        self.min_margin_ratio = min_margin_ratio
        self.region_trust_score = region_trust_score
        self.region_trust_margin = region_trust_margin
        self.region_max_side = region_max_side
        self.full_page_max_side = full_page_max_side

    def detect(self, image_path: Path) -> OcrOrientationDecision:
        from PIL import Image

        total_regions = 0
        last_scores = {angle: 0.0 for angle in self.angles}
        with Image.open(image_path) as image:
            rgb = image.convert("RGB")
            for phase_index, phase in enumerate(self._phases()):
                images = self._crop_phase_regions(rgb, phase["cells_by_angle"])
                total_regions += len(images)
                try:
                    texts = self.runner.run_batch(images)
                finally:
                    for phase_image in images:
                        phase_image.close()

                scores = {
                    angle: round(self._score_text(text), 4)
                    for angle, text in zip(self.angles, texts)
                }
                for angle in self.angles:
                    scores.setdefault(angle, 0.0)
                last_scores = scores

                decision = self._decide_from_scores(
                    scores=scores,
                    min_score=float(phase["min_score"]),
                    min_margin=float(phase["min_margin"]),
                    region_count=total_regions,
                )
                if decision.method != "ocr_probe_rejected":
                    if self._can_trust_region_decision(decision, phase_index=phase_index):
                        return decision
                    if self._needs_full_page_validation(decision):
                        full_decision = self._detect_full_page(rgb, total_regions)
                        if full_decision.method != "ocr_probe_full_page_rejected":
                            return full_decision
                    return decision

        full_decision = self._detect_full_page(rgb, total_regions)
        if full_decision.method != "ocr_probe_full_page_rejected":
            return full_decision

        return OcrOrientationDecision(
            detected=False,
            angle_degrees=0,
            method="ocr_probe_rejected",
            scores=last_scores,
            region_count=total_regions,
        )

    def _crop_phase_regions(self, image, cells_by_angle: dict[int, list[tuple[int, int]]]) -> list:
        from PIL import Image

        width, height = image.size
        images = []
        for angle in self.angles:
            cropped = image.crop(self._grid_bbox(width, height, cells_by_angle[angle]))
            if angle != 0:
                cropped = cropped.rotate(angle, expand=True, fillcolor=(255, 255, 255))
            cropped.thumbnail(
                (self.region_max_side, self.region_max_side),
                resample=Image.Resampling.LANCZOS,
            )
            images.append(cropped)
        return images

    def _decide_from_scores(
        self,
        *,
        scores: dict[int, float],
        min_score: float,
        min_margin: float,
        region_count: int,
        method: str = "ocr_probe",
        zero_guard: bool = True,
    ) -> OcrOrientationDecision:
        best_angle = max(scores, key=lambda angle: scores[angle])
        best_score = scores[best_angle]
        second_score = max(score for angle, score in scores.items() if angle != best_angle)
        margin = best_score - second_score
        required_score = max(self.min_score, min_score)
        required_margin = max(min_margin, best_score * self.min_margin_ratio)

        if zero_guard and best_angle != 0 and self._zero_degree_guard(scores, best_angle):
            return OcrOrientationDecision(
                detected=False,
                angle_degrees=0,
                method=f"{method}_zero_guard",
                scores=scores,
                region_count=region_count,
            )

        if best_score < required_score or margin < required_margin:
            return OcrOrientationDecision(
                detected=False,
                angle_degrees=0,
                method=f"{method}_rejected",
                scores=scores,
                region_count=region_count,
            )

        if best_angle == 0:
            return OcrOrientationDecision(
                detected=False,
                angle_degrees=0,
                method=f"{method}_upright",
                scores=scores,
                region_count=region_count,
            )

        return OcrOrientationDecision(
            detected=True,
            angle_degrees=int(best_angle),
            method=method,
            scores=scores,
            region_count=region_count,
        )

    def _needs_full_page_validation(self, decision: OcrOrientationDecision) -> bool:
        if decision.method in {"ocr_probe_rejected", "ocr_probe_zero_guard"}:
            return True
        return decision.method in {"ocr_probe", "ocr_probe_upright"}

    def _can_trust_region_decision(self, decision: OcrOrientationDecision, *, phase_index: int) -> bool:
        if phase_index != 0 or decision.method != "ocr_probe_upright":
            return False
        best_score = max(decision.scores.values(), default=0.0)
        second_score = max(
            (score for angle, score in decision.scores.items() if angle != decision.angle_degrees),
            default=0.0,
        )
        margin = best_score - second_score
        return best_score >= self.region_trust_score and margin >= self.region_trust_margin

    def _detect_full_page(self, image, previous_region_count: int) -> OcrOrientationDecision:
        from PIL import Image

        images = []
        for angle in self.angles:
            candidate = image.copy()
            if angle != 0:
                candidate = candidate.rotate(
                    angle,
                    expand=True,
                    fillcolor=(255, 255, 255),
                    resample=Image.Resampling.BICUBIC,
                )
            candidate.thumbnail(
                (self.full_page_max_side, self.full_page_max_side),
                Image.Resampling.LANCZOS,
            )
            images.append(candidate)

        try:
            texts = self.runner.run_batch(images)
        finally:
            for candidate in images:
                candidate.close()

        scores = {
            angle: round(self._score_text(text), 4)
            for angle, text in zip(self.angles, texts)
        }
        for angle in self.angles:
            scores.setdefault(angle, 0.0)

        return self._decide_from_scores(
            scores=scores,
            min_score=160.0,
            min_margin=120.0,
            region_count=previous_region_count + len(images),
            method="ocr_probe_full_page",
            zero_guard=False,
        )

    def _zero_degree_guard(self, scores: dict[int, float], best_angle: int) -> bool:
        zero_score = scores.get(0, 0.0)
        best_score = scores.get(best_angle, 0.0)
        return zero_score >= 40.0 and best_score < zero_score * 2.5

    def _grid_bbox(
        self,
        width: int,
        height: int,
        cells: list[tuple[int, int]],
    ) -> tuple[int, int, int, int]:
        cell_width = width / 5
        cell_height = height / 9
        xs = [cell[0] for cell in cells]
        ys = [cell[1] for cell in cells]
        left = int(min(xs) * cell_width)
        top = int(min(ys) * cell_height)
        right = int((max(xs) + 1) * cell_width)
        bottom = int((max(ys) + 1) * cell_height)
        return (
            max(0, min(left, width - 1)),
            max(0, min(top, height - 1)),
            max(1, min(right, width)),
            max(1, min(bottom, height)),
        )

    def _phases(self):
        return (
            {
                "min_score": 120.0,
                "min_margin": 80.0,
                "cells_by_angle": {
                    0: [(1, 0), (2, 0), (3, 0)],
                    90: [(4, 3), (4, 4), (4, 5)],
                    180: [(1, 8), (2, 8), (3, 8)],
                    270: [(0, 3), (0, 4), (0, 5)],
                },
            },
            {
                "min_score": 250.0,
                "min_margin": 100.0,
                "cells_by_angle": {
                    0: [(x, y) for x in range(1, 5) for y in (0, 1)],
                    90: [(x, y) for x in (3, 4) for y in range(2, 6)],
                    180: [(x, y) for x in range(0, 4) for y in (7, 8)],
                    270: [(x, y) for x in (0, 1) for y in range(3, 7)],
                },
            },
            {
                "min_score": 250.0,
                "min_margin": 100.0,
                "cells_by_angle": {
                    angle: [(x, y) for x in range(1, 4) for y in range(2, 6)]
                    for angle in self.angles
                },
            },
        )

    def _score_text(self, text: str) -> float:
        value = str(text or "")
        if not value.strip():
            return 0.0

        hangul = len(re.findall(r"[가-힣]", value))
        digits = len(re.findall(r"\d", value))
        latin = len(re.findall(r"[A-Za-z]", value))
        tokens = re.findall(r"[가-힣A-Za-z0-9]{2,}", value)
        short_tokens = re.findall(r"\b[가-힣A-Za-z0-9]\b", value)
        lines = [line for line in value.splitlines() if line.strip()]

        score = 0.0
        score += hangul * 1.8
        score += digits * 0.6
        score += latin * 0.2
        score += len(tokens) * 2.5
        score += min(8.0, len(lines) * 1.0)
        score -= min(8.0, len(short_tokens) * 0.8)
        return max(0.0, score)
