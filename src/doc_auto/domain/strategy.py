from __future__ import annotations

from enum import Enum


class ProcessingStrategy(str, Enum):
    AUTO = "auto"
    DARK_BACKGROUND = "dark_background"
    WHITE_BACKGROUND = "white_background"
    FULL_FRAME = "full_frame"
    CONSERVATIVE = "conservative"
