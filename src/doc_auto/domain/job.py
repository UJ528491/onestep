from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import uuid

from doc_auto.domain.options import ProcessingMode
from doc_auto.domain.strategy import ProcessingStrategy


class WorkStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class WorkItem:
    source_path: Path
    item_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    archive_member_name: str | None = None
    cached_source_path: Path | None = None
    delete_source_path: Path | None = None
    current_path: Path | None = None
    bundle_group_id: str | None = None
    page_index: int | None = None
    page_count: int = 1
    file_size_bytes: int | None = None
    status: WorkStatus = WorkStatus.PENDING
    last_mode: ProcessingMode | None = None
    last_strategy: ProcessingStrategy = ProcessingStrategy.AUTO
    detail: str = ""

    def __post_init__(self) -> None:
        self.source_path = Path(self.source_path)
        if self.cached_source_path is not None:
            self.cached_source_path = Path(self.cached_source_path)
        if self.delete_source_path is not None:
            self.delete_source_path = Path(self.delete_source_path)
        if self.current_path is not None:
            self.current_path = Path(self.current_path)

    @property
    def original_name(self) -> str:
        if self.archive_member_name:
            return Path(self.archive_member_name).name
        return self.source_path.name

    @property
    def current_name(self) -> str:
        if self.current_path is None and self.archive_member_name:
            return Path(self.archive_member_name).name
        return (self.current_path or self.source_path).name
