from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import shutil

from PIL import Image

from doc_auto.services.shell_notify import notify_path_changed
from doc_auto.services.temp_storage import PortableStorage


Box = tuple[int, int, int, int]


@dataclass
class ManualCropHistory:
    storage: PortableStorage
    target_path: Path
    history_dir: Path = field(init=False)
    states: list[Path] = field(default_factory=list, init=False)
    index: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.target_path = Path(self.target_path)
        digest = hashlib.sha1(str(self.target_path.resolve()).encode("utf-8", errors="ignore")).hexdigest()[:16]
        self.history_dir = self.storage.temp_dir / "manual_crops" / digest

    @property
    def can_go_back(self) -> bool:
        return self.index > 0

    @property
    def can_go_forward(self) -> bool:
        return self.index < len(self.states) - 1

    def start(self) -> Path:
        self.history_dir.mkdir(parents=True, exist_ok=True)
        for child in self.history_dir.iterdir():
            if child.is_file():
                child.unlink(missing_ok=True)
        self.states = [self._state_path(0)]
        shutil.copy2(self.target_path, self.states[0])
        self.index = 0
        return self.states[0]

    def crop(self, box: Box, *, rotation_degrees: float = 0.0) -> Path:
        if not self.states:
            self.start()
        current = self.states[self.index]
        self._discard_forward_states()
        next_path = self._state_path(self.index + 1)
        self._crop_to(current, next_path, box, rotation_degrees=rotation_degrees)
        self.states.append(next_path)
        self.index += 1
        shutil.copy2(next_path, self.target_path)
        notify_path_changed(self.target_path.parent)
        return self.target_path

    def crop_to_new_file(self, box: Box, *, rotation_degrees: float = 0.0) -> Path:
        if not self.states:
            self.start()
        target = self._unique_cut_path()
        self._crop_to(self.states[self.index], target, box, rotation_degrees=rotation_degrees)
        notify_path_changed(target.parent)
        return target

    def rotate(self, *, clockwise: bool = True) -> Path:
        if not self.states:
            self.start()
        current = self.states[self.index]
        self._discard_forward_states()
        next_path = self._state_path(self.index + 1)
        self._rotate_to(current, next_path, clockwise=clockwise)
        self.states.append(next_path)
        self.index += 1
        shutil.copy2(next_path, self.target_path)
        notify_path_changed(self.target_path.parent)
        return self.target_path

    def rotate_degrees(self, degrees: float) -> Path:
        degrees = self._effective_degrees(degrees)
        if abs(degrees) < 0.05:
            return self.target_path
        if not self.states:
            self.start()
        current = self.states[self.index]
        self._discard_forward_states()
        next_path = self._state_path(self.index + 1)
        self._rotate_degrees_to(current, next_path, degrees)
        self.states.append(next_path)
        self.index += 1
        shutil.copy2(next_path, self.target_path)
        notify_path_changed(self.target_path.parent)
        return self.target_path

    def back(self) -> Path:
        if self.can_go_back:
            self.index -= 1
            shutil.copy2(self.states[self.index], self.target_path)
            notify_path_changed(self.target_path.parent)
        return self.target_path

    def forward(self) -> Path:
        if self.can_go_forward:
            self.index += 1
            shutil.copy2(self.states[self.index], self.target_path)
            notify_path_changed(self.target_path.parent)
        return self.target_path

    def _discard_forward_states(self) -> None:
        for state in self.states[self.index + 1 :]:
            state.unlink(missing_ok=True)
        del self.states[self.index + 1 :]

    def _state_path(self, index: int) -> Path:
        suffix = self.target_path.suffix or ".png"
        return self.history_dir / f"step_{index:03d}{suffix}"

    def _unique_cut_path(self) -> Path:
        suffix = self.target_path.suffix or ".png"
        base = self.target_path.with_name(f"{self.target_path.stem}_cut_00{suffix}")
        if not base.exists():
            return base
        for index in range(1, 1000):
            candidate = self.target_path.with_name(f"{self.target_path.stem}_cut_{index:02d}{suffix}")
            if not candidate.exists():
                return candidate
        raise FileExistsError(f"Unable to allocate crop output for {self.target_path}")

    @staticmethod
    def _crop_to(source: Path, target: Path, box: Box, *, rotation_degrees: float = 0.0) -> None:
        with Image.open(source) as image:
            working = image
            if abs(rotation_degrees) >= 0.05:
                if working.mode not in {"RGB", "L"}:
                    working = working.convert("RGB")
                fill = 255 if working.mode == "L" else (255, 255, 255)
                working = working.rotate(
                    -rotation_degrees,
                    expand=True,
                    fillcolor=fill,
                    resample=Image.Resampling.BICUBIC,
                )
            clamped = ManualCropHistory._clamp_box(box, working.size)
            cropped = working.crop(clamped)
            if target.suffix.lower() in {".jpg", ".jpeg"} and cropped.mode not in {"RGB", "L"}:
                cropped = cropped.convert("RGB")
            cropped.save(target)

    @staticmethod
    def _rotate_to(source: Path, target: Path, *, clockwise: bool) -> None:
        with Image.open(source) as image:
            rotated = image.rotate(-90 if clockwise else 90, expand=True, fillcolor=(255, 255, 255))
            if target.suffix.lower() in {".jpg", ".jpeg"} and rotated.mode not in {"RGB", "L"}:
                rotated = rotated.convert("RGB")
            rotated.save(target)

    @staticmethod
    def _rotate_degrees_to(source: Path, target: Path, degrees: float) -> None:
        with Image.open(source) as image:
            working = image
            if working.mode not in {"RGB", "L"}:
                working = working.convert("RGB")
            fill = 255 if working.mode == "L" else (255, 255, 255)
            rotated = working.rotate(
                -degrees,
                expand=True,
                fillcolor=fill,
                resample=Image.Resampling.BICUBIC,
            )
            if target.suffix.lower() in {".jpg", ".jpeg"} and rotated.mode not in {"RGB", "L"}:
                rotated = rotated.convert("RGB")
            rotated.save(target)

    @staticmethod
    def _effective_degrees(degrees: float) -> float:
        return ((degrees + 180.0) % 360.0) - 180.0

    @staticmethod
    def _clamp_box(box: Box, size: tuple[int, int]) -> Box:
        width, height = size
        x1, y1, x2, y2 = box
        left = max(0, min(width - 1, min(x1, x2)))
        top = max(0, min(height - 1, min(y1, y2)))
        right = max(left + 1, min(width, max(x1, x2)))
        bottom = max(top + 1, min(height, max(y1, y2)))
        return int(left), int(top), int(right), int(bottom)
