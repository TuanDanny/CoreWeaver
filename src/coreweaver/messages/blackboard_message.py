from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from coreweaver.framework_types import StrictCoreModel, stable_hash, utc_now, validate_id_text, validate_iso8601_text, validate_optional_id, validate_sha256_text

from .blocks import EvidenceRef, MessageBlock
from .core_message import CoreMessage, MessageKind, MessageRole

BlackboardRevision = int


class BlackboardConflict(StrictCoreModel):
    conflict_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    run_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    key: str
    current_revision: int
    attempted_read_revision: int
    current_entry_id: str
    attempted_entry_id: str
    timestamp: str = Field(default_factory=utc_now)

    @field_validator("conflict_id", "run_id", "current_entry_id", "attempted_entry_id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        return validate_id_text(value, "id")

    @field_validator("timestamp")
    @classmethod
    def _valid_ts(cls, value: str) -> str:
        return validate_iso8601_text(value)


class BlackboardEntry(StrictCoreModel):
    entry_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    run_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    message: CoreMessage
    author_role: MessageRole
    read_revision: int
    write_revision: int
    conflict_key: str | None = None
    group_id: str | None = None
    parent_message_id: str | None = None
    input_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    output_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    evidence_refs: tuple[EvidenceRef, ...] = ()
    timestamp: str = Field(default_factory=utc_now)

    @field_validator("entry_id", "run_id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        return validate_id_text(value, "id")

    @field_validator("group_id", "parent_message_id")
    @classmethod
    def _valid_optional_id(cls, value: str | None) -> str | None:
        return validate_optional_id(value, "optional_id")

    @field_validator("input_hash", "output_hash")
    @classmethod
    def _valid_hash(cls, value: str) -> str:
        return validate_sha256_text(value)

    @field_validator("timestamp")
    @classmethod
    def _valid_ts(cls, value: str) -> str:
        return validate_iso8601_text(value)

    @model_validator(mode="after")
    def _revisions_valid(self) -> "BlackboardEntry":
        if self.read_revision < 0 or self.write_revision <= self.read_revision:
            raise ValueError("blackboard revisions must be monotonic")
        return self


class BlackboardSnapshot(StrictCoreModel):
    snapshot_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    run_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    revision: int
    entries: tuple[BlackboardEntry, ...]
    conflicts: tuple[BlackboardConflict, ...] = ()


class BlackboardAppendResult(StrictCoreModel):
    entry: BlackboardEntry
    conflict: BlackboardConflict | None = None
    conflict_message: CoreMessage | None = None


class Blackboard:
    """Append-only blackboard. Public API intentionally has no update/delete."""

    def __init__(self, run_id: str) -> None:
        validate_id_text(run_id, "run_id")
        self.run_id = run_id
        self._revision = 0
        self._entries: list[BlackboardEntry] = []
        self._conflicts: list[BlackboardConflict] = []
        self._latest_by_key: dict[str, BlackboardEntry] = {}

    @property
    def revision(self) -> int:
        return self._revision

    def snapshot(self) -> BlackboardSnapshot:
        return BlackboardSnapshot(
            snapshot_id=f"{self.run_id}:snapshot:{self._revision}",
            run_id=self.run_id,
            revision=self._revision,
            entries=tuple(self._entries),
            conflicts=tuple(self._conflicts),
        )

    def append(self, message: CoreMessage, *, conflict_key: str | None = None) -> BlackboardAppendResult:
        read_revision = message.read_revision if message.read_revision is not None else self._revision
        self._revision += 1
        entry = BlackboardEntry(
            entry_id=f"{self.run_id}:bb:{self._revision}",
            run_id=self.run_id,
            message=message,
            author_role=message.role,
            read_revision=read_revision,
            write_revision=self._revision,
            conflict_key=conflict_key,
            group_id=message.group_id,
            parent_message_id=message.parent_message_id,
            input_hash=message.input_hash,
            output_hash=message.output_hash,
            evidence_refs=message.evidence_refs,
        )
        self._entries.append(entry)
        conflict = self._detect_conflict(entry)
        conflict_message = None
        if conflict:
            self._conflicts.append(conflict)
            payload = {"conflict_id": conflict.conflict_id, "key": conflict.key}
            payload_hash = stable_hash(payload)
            conflict_message = CoreMessage(
                message_id=f"{conflict.conflict_id}:message",
                run_id=self.run_id,
                revision_id=f"rev:{self._revision}",
                role=MessageRole.SYSTEM,
                kind=MessageKind.BLACKBOARD_CONFLICT,
                blocks=(MessageBlock(block_id=f"{conflict.conflict_id}:block", kind="json", content=payload),),
                input_hash=payload_hash,
                output_hash=payload_hash,
            )
        if conflict_key:
            self._latest_by_key[conflict_key] = entry
        return BlackboardAppendResult(entry=entry, conflict=conflict, conflict_message=conflict_message)

    def _detect_conflict(self, entry: BlackboardEntry) -> BlackboardConflict | None:
        if not entry.conflict_key:
            return None
        current = self._latest_by_key.get(entry.conflict_key)
        if current is None:
            return None
        if entry.read_revision < current.write_revision and entry.output_hash != current.output_hash:
            return BlackboardConflict(
                conflict_id=f"{self.run_id}:conflict:{len(self._conflicts) + 1}",
                run_id=self.run_id,
                key=entry.conflict_key,
                current_revision=current.write_revision,
                attempted_read_revision=entry.read_revision,
                current_entry_id=current.entry_id,
                attempted_entry_id=entry.entry_id,
            )
        return None
