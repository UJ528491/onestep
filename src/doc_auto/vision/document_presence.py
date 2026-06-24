from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class DocumentPresence:
    document_like: bool
    scene_kind: str
    confidence: float
    signals: dict[str, float]


class DocumentPresenceAnalyzer:
    def analyze(self, image_path: Path) -> DocumentPresence:
        from PIL import Image

        with Image.open(image_path) as image:
            rgb = image.convert("RGB")
            rgb.thumbnail((900, 900))
            arr = np.asarray(rgb, dtype=np.float32)

        brightness = arr.mean(axis=2)
        saturation_proxy = arr.max(axis=2) - arr.min(axis=2)
        red_blue_gap = arr[:, :, 0] - arr[:, :, 2]
        neutral = saturation_proxy <= 42
        bright_paper = (brightness >= 175) & neutral
        shadowed_paper = (brightness >= 115) & (saturation_proxy <= 30)
        paper = bright_paper | shadowed_paper
        paper_ratio = float(np.mean(paper))

        height, width = brightness.shape
        border = max(4, int(min(width, height) * 0.08))
        border_mask = np.zeros_like(brightness, dtype=bool)
        border_mask[:border, :] = True
        border_mask[-border:, :] = True
        border_mask[:, :border] = True
        border_mask[:, -border:] = True
        border_brightness = float(np.mean(brightness[border_mask]))
        border_paper_ratio = float(np.mean(paper[border_mask]))
        border_dark_ratio = float(np.mean(brightness[border_mask] <= 80))
        center_mask = ~border_mask
        center_paper_ratio = float(np.mean(paper[center_mask])) if np.any(center_mask) else paper_ratio
        color_content = (saturation_proxy >= 50) & (brightness >= 35) & (brightness <= 245)
        border_color_ratio = float(np.mean(color_content[border_mask]))
        center_color_ratio = (
            float(np.mean(color_content[center_mask])) if np.any(center_mask) else float(np.mean(color_content))
        )
        center_dark_ratio = float(np.mean(brightness[center_mask] <= 110)) if np.any(center_mask) else 0.0
        warm_background = (
            (brightness >= 120)
            & (saturation_proxy >= 12)
            & (saturation_proxy <= 58)
            & (red_blue_gap >= 18)
        )
        border_warm_ratio = float(np.mean(warm_background[border_mask]))
        center_warm_ratio = (
            float(np.mean(warm_background[center_mask])) if np.any(center_mask) else float(np.mean(warm_background))
        )

        if (
            paper_ratio >= 0.82
            and border_paper_ratio >= 0.65
            and border_warm_ratio >= 0.45
            and center_warm_ratio <= border_warm_ratio * 0.45
        ):
            scene_kind = "warm_background_document"
            confidence = min(
                0.90,
                0.52
                + min(0.16, center_paper_ratio * 0.16)
                + min(0.12, border_warm_ratio * 0.12)
                + min(0.10, (border_warm_ratio - center_warm_ratio) * 0.18),
            )
        elif paper_ratio >= 0.82 and border_paper_ratio >= 0.65:
            scene_kind = "full_frame"
            confidence = min(0.96, 0.62 + paper_ratio * 0.34)
        elif paper_ratio >= 0.62 and border_paper_ratio >= 0.65 and center_paper_ratio >= 0.55:
            scene_kind = "text_graphic_document"
            confidence = min(0.90, 0.48 + paper_ratio * 0.34 + center_paper_ratio * 0.20)
        elif (
            paper_ratio >= 0.50
            and border_paper_ratio >= 0.78
            and center_paper_ratio >= 0.38
            and center_color_ratio >= 0.02
            and center_dark_ratio >= 0.18
            and border_color_ratio <= 0.08
        ):
            scene_kind = "color_document_canvas"
            confidence = min(
                0.88,
                0.46
                + paper_ratio * 0.18
                + center_paper_ratio * 0.16
                + min(0.10, center_color_ratio * 1.50)
                + min(0.08, center_dark_ratio * 0.12),
            )
        elif center_paper_ratio >= 0.28 and border_dark_ratio >= 0.30:
            scene_kind = "dark_background"
            contrast_bonus = min(0.20, max(0.0, (150 - border_brightness) / 350))
            confidence = min(0.95, 0.55 + center_paper_ratio * 0.55 + contrast_bonus)
        elif paper_ratio >= 0.35 and border_paper_ratio < 0.75:
            scene_kind = "background_document"
            confidence = min(0.86, 0.45 + paper_ratio * 0.55)
        else:
            scene_kind = "non_document"
            confidence = min(0.40, paper_ratio * 0.45)

        document_like = scene_kind != "non_document" and confidence >= 0.55
        return DocumentPresence(
            document_like=document_like,
            scene_kind=scene_kind,
            confidence=round(float(confidence), 4),
            signals={
                "paper_ratio": round(paper_ratio, 4),
                "border_paper_ratio": round(border_paper_ratio, 4),
                "center_paper_ratio": round(center_paper_ratio, 4),
                "border_dark_ratio": round(border_dark_ratio, 4),
                "border_brightness": round(border_brightness, 4),
                "border_color_ratio": round(border_color_ratio, 4),
                "center_color_ratio": round(center_color_ratio, 4),
                "center_dark_ratio": round(center_dark_ratio, 4),
                "border_warm_ratio": round(border_warm_ratio, 4),
                "center_warm_ratio": round(center_warm_ratio, 4),
            },
        )
