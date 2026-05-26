"""Agent 1 V7.2 industrial signoff data models.

These models are intentionally dependency-free. They provide strict runtime
validation plus JSON-schema-shaped metadata for the Phase 1 contract lock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, ClassVar


class SignoffSchemaError(ValueError):
    """Raised when Agent 1 V7.2 signoff data fails schema validation."""


SIGNOFF_SCHEMA_VERSION = "agent1_signoff/v1"
SIGNOFF_CERTIFICATE_SCHEMA_VERSION = "agent1_final_signoff_certificate/v1"
SIGNOFF_WAIVERS_SCHEMA_VERSION = "agent1_signoff_waivers/v1"
BENCHMARK_CASE_SCHEMA_VERSION = "agent1_signoff_benchmark_case/v1"
BENCHMARK_RESULT_SCHEMA_VERSION = "agent1_signoff_benchmark_result/v1"

SIGNOFF_GATES = tuple(f"G{idx:02d}" for idx in range(13))
SIGNOFF_SEVERITIES = ("P0_FATAL", "P1_BLOCKER", "P2_MAJOR", "P3_MINOR")
SIGNOFF_PROFILES = ("balanced", "strict", "nightly")
SIGNOFF_DECISIONS = ("PASS", "PASS_WITH_WAIVERS", "FAILED", "BLOCKED")
WAIVER_RISK_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
GATE_RESULT_STATUSES = ("PASS", "WARN", "FAIL", "BLOCKED", "WAIVED", "NOT_RUN")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,96}$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+\-]{0,191}$")
_PROJECT_RE = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")
_SECRET_KEY_RE = re.compile(
    r"(^|[_\-])(api[_\-]?key|authorization|bearer|secret|password|credential|"
    r"access[_\-]?token|refresh[_\-]?token|raw[_\-]?prompt)([_\-]|$)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{10,}|Bearer\s+[A-Za-z0-9._\-]{10,}|"
    r"api[_\-]?key\s*[:=]\s*['\"]?[A-Za-z0-9._\-]{10,})",
    re.IGNORECASE,
)


def validate_sha256(value: Any, field: str) -> str:
    text = _expect_str(value, field, min_len=64, max_len=64)
    if not _SHA256_RE.fullmatch(text):
        raise SignoffSchemaError(f"{field} must be lowercase SHA256 hex")
    return text


def validate_iso8601_datetime(value: Any, field: str) -> str:
    text = _expect_str(value, field, min_len=19, max_len=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SignoffSchemaError(f"{field} must be ISO8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SignoffSchemaError(f"{field} must include timezone")
    if "T" not in text:
        raise SignoffSchemaError(f"{field} must include date and time separator")
    return text


def validate_no_secret_material(value: Any, field: str = "payload") -> None:
    _assert_no_secret_material(value, field)


def validate_signoff_finding(payload: dict[str, Any]) -> "SignoffFinding":
    return SignoffFinding.from_dict(payload)


def validate_signoff_waivers(payload: dict[str, Any]) -> "SignoffWaivers":
    return SignoffWaivers.from_dict(payload)


def validate_final_certificate(payload: dict[str, Any]) -> "Agent1FinalSignoffCertificate":
    return Agent1FinalSignoffCertificate.from_dict(payload)


def validate_benchmark_case(payload: dict[str, Any]) -> "BenchmarkCase":
    return BenchmarkCase.from_dict(payload)


def validate_benchmark_result(payload: dict[str, Any]) -> "BenchmarkResult":
    return BenchmarkResult.from_dict(payload)


@dataclass(frozen=True)
class SignoffFinding:
    finding_id: str
    gate: str
    code: str
    severity: str
    source: str
    message: str
    details: dict[str, Any]
    run_id: str
    revision_id: str
    artifact_ref: str | None
    node_id: str | None
    case_id: str | None
    waivable: bool
    waiver_id: str | None
    timestamp: str

    REQUIRED_FIELDS: ClassVar[set[str]] = {
        "finding_id",
        "gate",
        "code",
        "severity",
        "source",
        "message",
        "details",
        "run_id",
        "revision_id",
        "artifact_ref",
        "node_id",
        "case_id",
        "waivable",
        "waiver_id",
        "timestamp",
    }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignoffFinding":
        _expect_mapping(data, "signoff_finding")
        _reject_unknown_keys(data, cls.REQUIRED_FIELDS, "signoff_finding")
        _require_keys(data, cls.REQUIRED_FIELDS, "signoff_finding")
        details = _expect_dict(data["details"], "details")
        validate_no_secret_material(details, "details")
        waiver_id = _optional_ref(data["waiver_id"], "waiver_id")
        waivable = _expect_bool(data["waivable"], "waivable")
        if waiver_id is not None and not waivable:
            raise SignoffSchemaError("waiver_id requires waivable=true")
        return cls(
            finding_id=_expect_ref(data["finding_id"], "finding_id"),
            gate=_expect_enum(data["gate"], SIGNOFF_GATES, "gate"),
            code=_expect_code(data["code"], "code"),
            severity=_expect_enum(data["severity"], SIGNOFF_SEVERITIES, "severity"),
            source=_expect_ref(data["source"], "source"),
            message=_expect_str(data["message"], "message", min_len=1, max_len=2048),
            details=details,
            run_id=_expect_ref(data["run_id"], "run_id"),
            revision_id=_expect_ref(data["revision_id"], "revision_id"),
            artifact_ref=_optional_ref(data["artifact_ref"], "artifact_ref"),
            node_id=_optional_ref(data["node_id"], "node_id"),
            case_id=_optional_ref(data["case_id"], "case_id"),
            waivable=waivable,
            waiver_id=waiver_id,
            timestamp=validate_iso8601_datetime(data["timestamp"], "timestamp"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "gate": self.gate,
            "code": self.code,
            "severity": self.severity,
            "source": self.source,
            "message": self.message,
            "details": self.details,
            "run_id": self.run_id,
            "revision_id": self.revision_id,
            "artifact_ref": self.artifact_ref,
            "node_id": self.node_id,
            "case_id": self.case_id,
            "waivable": self.waivable,
            "waiver_id": self.waiver_id,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class SignoffWaiver:
    waiver_id: str
    owner: str
    reason: str
    risk_level: str
    expires_at: str
    affected_gate: str
    matching_finding_code: str
    approval_signature: str

    REQUIRED_FIELDS: ClassVar[set[str]] = {
        "waiver_id",
        "owner",
        "reason",
        "risk_level",
        "expires_at",
        "affected_gate",
        "matching_finding_code",
        "approval_signature",
    }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignoffWaiver":
        _expect_mapping(data, "signoff_waiver")
        _reject_unknown_keys(data, cls.REQUIRED_FIELDS, "signoff_waiver")
        _require_keys(data, cls.REQUIRED_FIELDS, "signoff_waiver")
        reason = _expect_str(data["reason"], "reason", min_len=12, max_len=2048)
        validate_no_secret_material(reason, "reason")
        return cls(
            waiver_id=_expect_ref(data["waiver_id"], "waiver_id"),
            owner=_expect_ref(data["owner"], "owner"),
            reason=reason,
            risk_level=_expect_enum(data["risk_level"], WAIVER_RISK_LEVELS, "risk_level"),
            expires_at=validate_iso8601_datetime(data["expires_at"], "expires_at"),
            affected_gate=_expect_enum(data["affected_gate"], SIGNOFF_GATES, "affected_gate"),
            matching_finding_code=_expect_code(data["matching_finding_code"], "matching_finding_code"),
            approval_signature=validate_sha256(data["approval_signature"], "approval_signature"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "waiver_id": self.waiver_id,
            "owner": self.owner,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "expires_at": self.expires_at,
            "affected_gate": self.affected_gate,
            "matching_finding_code": self.matching_finding_code,
            "approval_signature": self.approval_signature,
        }


@dataclass(frozen=True)
class SignoffWaivers:
    schema_version: str
    waivers: tuple[SignoffWaiver, ...]

    REQUIRED_FIELDS: ClassVar[set[str]] = {"schema_version", "waivers"}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignoffWaivers":
        _expect_mapping(data, "signoff_waivers")
        _reject_unknown_keys(data, cls.REQUIRED_FIELDS, "signoff_waivers")
        _require_keys(data, cls.REQUIRED_FIELDS, "signoff_waivers")
        schema_version = _expect_str(data["schema_version"], "schema_version")
        if schema_version != SIGNOFF_WAIVERS_SCHEMA_VERSION:
            raise SignoffSchemaError("signoff_waivers.schema_version mismatch")
        raw_waivers = _expect_list(data["waivers"], "waivers")
        waivers = tuple(SignoffWaiver.from_dict(item) for item in raw_waivers)
        seen: set[str] = set()
        for waiver in waivers:
            if waiver.waiver_id in seen:
                raise SignoffSchemaError(f"duplicate waiver_id: {waiver.waiver_id}")
            seen.add(waiver.waiver_id)
        return cls(schema_version=schema_version, waivers=waivers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "waivers": [waiver.to_dict() for waiver in self.waivers],
        }


@dataclass(frozen=True)
class Agent1FinalSignoffCertificate:
    schema_version: str
    run_id: str
    revision_id: str
    project: str
    profile: str
    decision: str
    handoff_allowed: bool
    score: float
    gate_results: dict[str, dict[str, Any]]
    finding_summary: dict[str, Any]
    waiver_summary: dict[str, Any]
    benchmark_summary: dict[str, Any]
    artifact_hashes: dict[str, str]
    topology_hash: str
    config_hash: str
    prompt_pack_hash: str
    model_ref_hash: str
    user_approval_ref: str | None
    created_at: str

    REQUIRED_FIELDS: ClassVar[set[str]] = {
        "schema_version",
        "run_id",
        "revision_id",
        "project",
        "profile",
        "decision",
        "handoff_allowed",
        "score",
        "gate_results",
        "finding_summary",
        "waiver_summary",
        "benchmark_summary",
        "artifact_hashes",
        "topology_hash",
        "config_hash",
        "prompt_pack_hash",
        "model_ref_hash",
        "user_approval_ref",
        "created_at",
    }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Agent1FinalSignoffCertificate":
        _expect_mapping(data, "agent1_final_signoff_certificate")
        _reject_unknown_keys(data, cls.REQUIRED_FIELDS, "agent1_final_signoff_certificate")
        _require_keys(data, cls.REQUIRED_FIELDS, "agent1_final_signoff_certificate")
        schema_version = _expect_str(data["schema_version"], "schema_version")
        if schema_version != SIGNOFF_CERTIFICATE_SCHEMA_VERSION:
            raise SignoffSchemaError("agent1_final_signoff_certificate.schema_version mismatch")
        decision = _expect_enum(data["decision"], SIGNOFF_DECISIONS, "decision")
        handoff_allowed = _expect_bool(data["handoff_allowed"], "handoff_allowed")
        if handoff_allowed and decision not in {"PASS", "PASS_WITH_WAIVERS"}:
            raise SignoffSchemaError("handoff_allowed requires PASS or PASS_WITH_WAIVERS")
        user_approval_ref = _optional_ref(data["user_approval_ref"], "user_approval_ref")
        if handoff_allowed and user_approval_ref is None:
            raise SignoffSchemaError("handoff_allowed requires user_approval_ref")
        gate_results = _validate_gate_results(data["gate_results"])
        finding_summary = _expect_dict(data["finding_summary"], "finding_summary")
        waiver_summary = _expect_dict(data["waiver_summary"], "waiver_summary")
        benchmark_summary = _validate_benchmark_summary(data["benchmark_summary"])
        artifact_hashes = _validate_hash_map(data["artifact_hashes"], "artifact_hashes", require_nonempty=True)
        for path, value in (
            ("finding_summary", finding_summary),
            ("waiver_summary", waiver_summary),
            ("benchmark_summary", benchmark_summary),
            ("artifact_hashes", artifact_hashes),
        ):
            validate_no_secret_material(value, path)
        if handoff_allowed:
            if benchmark_summary["false_pass_count"] != 0 or benchmark_summary["must_not_pass_violation_count"] != 0:
                raise SignoffSchemaError("handoff_allowed requires benchmark safety-zero summary")
        return cls(
            schema_version=schema_version,
            run_id=_expect_ref(data["run_id"], "run_id"),
            revision_id=_expect_ref(data["revision_id"], "revision_id"),
            project=_expect_project(data["project"], "project"),
            profile=_expect_enum(data["profile"], SIGNOFF_PROFILES, "profile"),
            decision=decision,
            handoff_allowed=handoff_allowed,
            score=_expect_score(data["score"], "score"),
            gate_results=gate_results,
            finding_summary=finding_summary,
            waiver_summary=waiver_summary,
            benchmark_summary=benchmark_summary,
            artifact_hashes=artifact_hashes,
            topology_hash=validate_sha256(data["topology_hash"], "topology_hash"),
            config_hash=validate_sha256(data["config_hash"], "config_hash"),
            prompt_pack_hash=validate_sha256(data["prompt_pack_hash"], "prompt_pack_hash"),
            model_ref_hash=validate_sha256(data["model_ref_hash"], "model_ref_hash"),
            user_approval_ref=user_approval_ref,
            created_at=validate_iso8601_datetime(data["created_at"], "created_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "revision_id": self.revision_id,
            "project": self.project,
            "profile": self.profile,
            "decision": self.decision,
            "handoff_allowed": self.handoff_allowed,
            "score": self.score,
            "gate_results": self.gate_results,
            "finding_summary": self.finding_summary,
            "waiver_summary": self.waiver_summary,
            "benchmark_summary": self.benchmark_summary,
            "artifact_hashes": self.artifact_hashes,
            "topology_hash": self.topology_hash,
            "config_hash": self.config_hash,
            "prompt_pack_hash": self.prompt_pack_hash,
            "model_ref_hash": self.model_ref_hash,
            "user_approval_ref": self.user_approval_ref,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class BenchmarkCase:
    schema_version: str
    case_id: str
    category: str
    profile: str
    requirement: str
    attachments: tuple[dict[str, Any], ...]
    mutations: tuple[dict[str, Any], ...]
    waivers: tuple[SignoffWaiver, ...]
    expected_decision: str
    expected_handoff_allowed: bool
    expected_finding_codes: tuple[str, ...]
    must_not_pass: bool
    oracle_notes: str
    expected_debug_issue_codes: tuple[str, ...]

    REQUIRED_FIELDS: ClassVar[set[str]] = {
        "schema_version",
        "case_id",
        "category",
        "profile",
        "requirement",
        "attachments",
        "mutations",
        "waivers",
        "expected_decision",
        "expected_handoff_allowed",
        "expected_finding_codes",
        "must_not_pass",
        "oracle_notes",
        "expected_debug_issue_codes",
    }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkCase":
        _expect_mapping(data, "benchmark_case")
        _reject_unknown_keys(data, cls.REQUIRED_FIELDS, "benchmark_case")
        _require_keys(data, cls.REQUIRED_FIELDS, "benchmark_case")
        schema_version = _expect_str(data["schema_version"], "schema_version")
        if schema_version != BENCHMARK_CASE_SCHEMA_VERSION:
            raise SignoffSchemaError("benchmark_case.schema_version mismatch")
        expected_decision = _expect_enum(data["expected_decision"], SIGNOFF_DECISIONS, "expected_decision")
        expected_handoff_allowed = _expect_bool(data["expected_handoff_allowed"], "expected_handoff_allowed")
        must_not_pass = _expect_bool(data["must_not_pass"], "must_not_pass")
        if expected_handoff_allowed and expected_decision not in {"PASS", "PASS_WITH_WAIVERS"}:
            raise SignoffSchemaError("expected_handoff_allowed requires PASS or PASS_WITH_WAIVERS")
        if must_not_pass and (expected_handoff_allowed or expected_decision in {"PASS", "PASS_WITH_WAIVERS"}):
            raise SignoffSchemaError("must_not_pass case must expect blocked handoff")
        attachments = tuple(_expect_dict(item, "attachments[]") for item in _expect_list(data["attachments"], "attachments"))
        mutations = tuple(_expect_dict(item, "mutations[]") for item in _expect_list(data["mutations"], "mutations"))
        waivers = tuple(SignoffWaiver.from_dict(item) for item in _expect_list(data["waivers"], "waivers"))
        for path, value in (("attachments", attachments), ("mutations", mutations)):
            validate_no_secret_material(value, path)
        return cls(
            schema_version=schema_version,
            case_id=_expect_ref(data["case_id"], "case_id"),
            category=_expect_ref(data["category"], "category"),
            profile=_expect_enum(data["profile"], SIGNOFF_PROFILES, "profile"),
            requirement=_expect_str(data["requirement"], "requirement", min_len=1, max_len=10000),
            attachments=attachments,
            mutations=mutations,
            waivers=waivers,
            expected_decision=expected_decision,
            expected_handoff_allowed=expected_handoff_allowed,
            expected_finding_codes=_expect_code_tuple(data["expected_finding_codes"], "expected_finding_codes"),
            must_not_pass=must_not_pass,
            oracle_notes=_expect_str(data["oracle_notes"], "oracle_notes", min_len=8, max_len=4096),
            expected_debug_issue_codes=_expect_code_tuple(data["expected_debug_issue_codes"], "expected_debug_issue_codes"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "category": self.category,
            "profile": self.profile,
            "requirement": self.requirement,
            "attachments": list(self.attachments),
            "mutations": list(self.mutations),
            "waivers": [waiver.to_dict() for waiver in self.waivers],
            "expected_decision": self.expected_decision,
            "expected_handoff_allowed": self.expected_handoff_allowed,
            "expected_finding_codes": list(self.expected_finding_codes),
            "must_not_pass": self.must_not_pass,
            "oracle_notes": self.oracle_notes,
            "expected_debug_issue_codes": list(self.expected_debug_issue_codes),
        }


@dataclass(frozen=True)
class BenchmarkResult:
    schema_version: str
    case_id: str
    profile: str
    actual_decision: str
    actual_handoff_allowed: bool
    actual_finding_codes: tuple[str, ...]
    expected_match: bool
    false_pass: bool
    false_block: bool
    must_not_pass_violation: bool
    oracle_disagreement: bool
    latency_s: float
    token_cost_estimate: float
    artifact_refs: tuple[str, ...]
    debug_issue_refs: tuple[str, ...]

    REQUIRED_FIELDS: ClassVar[set[str]] = {
        "schema_version",
        "case_id",
        "profile",
        "actual_decision",
        "actual_handoff_allowed",
        "actual_finding_codes",
        "expected_match",
        "false_pass",
        "false_block",
        "must_not_pass_violation",
        "oracle_disagreement",
        "latency_s",
        "token_cost_estimate",
        "artifact_refs",
        "debug_issue_refs",
    }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkResult":
        _expect_mapping(data, "benchmark_result")
        _reject_unknown_keys(data, cls.REQUIRED_FIELDS, "benchmark_result")
        _require_keys(data, cls.REQUIRED_FIELDS, "benchmark_result")
        schema_version = _expect_str(data["schema_version"], "schema_version")
        if schema_version != BENCHMARK_RESULT_SCHEMA_VERSION:
            raise SignoffSchemaError("benchmark_result.schema_version mismatch")
        actual_decision = _expect_enum(data["actual_decision"], SIGNOFF_DECISIONS, "actual_decision")
        actual_handoff_allowed = _expect_bool(data["actual_handoff_allowed"], "actual_handoff_allowed")
        if actual_handoff_allowed and actual_decision not in {"PASS", "PASS_WITH_WAIVERS"}:
            raise SignoffSchemaError("actual_handoff_allowed requires PASS or PASS_WITH_WAIVERS")
        expected_match = _expect_bool(data["expected_match"], "expected_match")
        false_pass = _expect_bool(data["false_pass"], "false_pass")
        false_block = _expect_bool(data["false_block"], "false_block")
        must_not_pass_violation = _expect_bool(data["must_not_pass_violation"], "must_not_pass_violation")
        if expected_match and (false_pass or false_block or must_not_pass_violation):
            raise SignoffSchemaError("expected_match cannot coexist with false_pass/false_block/must_not_pass_violation")
        if false_pass and not actual_handoff_allowed:
            raise SignoffSchemaError("false_pass requires actual_handoff_allowed=true")
        if must_not_pass_violation and not false_pass:
            raise SignoffSchemaError("must_not_pass_violation requires false_pass=true")
        return cls(
            schema_version=schema_version,
            case_id=_expect_ref(data["case_id"], "case_id"),
            profile=_expect_enum(data["profile"], SIGNOFF_PROFILES, "profile"),
            actual_decision=actual_decision,
            actual_handoff_allowed=actual_handoff_allowed,
            actual_finding_codes=_expect_code_tuple(data["actual_finding_codes"], "actual_finding_codes"),
            expected_match=expected_match,
            false_pass=false_pass,
            false_block=false_block,
            must_not_pass_violation=must_not_pass_violation,
            oracle_disagreement=_expect_bool(data["oracle_disagreement"], "oracle_disagreement"),
            latency_s=_expect_nonnegative_float(data["latency_s"], "latency_s"),
            token_cost_estimate=_expect_nonnegative_float(data["token_cost_estimate"], "token_cost_estimate"),
            artifact_refs=_expect_ref_tuple(data["artifact_refs"], "artifact_refs"),
            debug_issue_refs=_expect_ref_tuple(data["debug_issue_refs"], "debug_issue_refs"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "profile": self.profile,
            "actual_decision": self.actual_decision,
            "actual_handoff_allowed": self.actual_handoff_allowed,
            "actual_finding_codes": list(self.actual_finding_codes),
            "expected_match": self.expected_match,
            "false_pass": self.false_pass,
            "false_block": self.false_block,
            "must_not_pass_violation": self.must_not_pass_violation,
            "oracle_disagreement": self.oracle_disagreement,
            "latency_s": self.latency_s,
            "token_cost_estimate": self.token_cost_estimate,
            "artifact_refs": list(self.artifact_refs),
            "debug_issue_refs": list(self.debug_issue_refs),
        }


def _expect_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SignoffSchemaError(f"{field} must be object")
    return value


def _expect_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SignoffSchemaError(f"{field} must be object")
    return dict(value)


def _expect_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise SignoffSchemaError(f"{field} must be array")
    return value


def _expect_str(value: Any, field: str, *, min_len: int = 1, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise SignoffSchemaError(f"{field} must be string")
    if not min_len <= len(value) <= max_len:
        raise SignoffSchemaError(f"{field} length must be {min_len}..{max_len}")
    if _SECRET_VALUE_RE.search(value):
        raise SignoffSchemaError(f"{field} contains secret-like material")
    return value


def _expect_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise SignoffSchemaError(f"{field} must be boolean")
    return value


def _expect_score(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SignoffSchemaError(f"{field} must be number")
    score = float(value)
    if not 0.0 <= score <= 100.0:
        raise SignoffSchemaError(f"{field} must be between 0 and 100")
    return score


def _expect_nonnegative_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SignoffSchemaError(f"{field} must be number")
    number = float(value)
    if number < 0:
        raise SignoffSchemaError(f"{field} must be non-negative")
    return number


def _expect_enum(value: Any, allowed: tuple[str, ...], field: str) -> str:
    text = _expect_str(value, field, min_len=1, max_len=128)
    if text not in allowed:
        raise SignoffSchemaError(f"{field} must be one of {', '.join(allowed)}")
    return text


def _expect_code(value: Any, field: str) -> str:
    text = _expect_str(value, field, min_len=3, max_len=96)
    if not _CODE_RE.fullmatch(text):
        raise SignoffSchemaError(f"{field} must match ^[A-Z][A-Z0-9_]{{2,96}}$")
    return text


def _expect_ref(value: Any, field: str) -> str:
    text = _expect_str(value, field, min_len=1, max_len=192)
    if not _REF_RE.fullmatch(text):
        raise SignoffSchemaError(f"{field} must be a safe reference string")
    return text


def _optional_ref(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _expect_ref(value, field)


def _expect_project(value: Any, field: str) -> str:
    text = _expect_str(value, field, min_len=1, max_len=64)
    if not _PROJECT_RE.fullmatch(text):
        raise SignoffSchemaError(f"{field} must be RTL-safe ^[a-z_][a-z0-9_]*$")
    return text


def _expect_code_tuple(value: Any, field: str) -> tuple[str, ...]:
    return tuple(_expect_code(item, f"{field}[]") for item in _expect_list(value, field))


def _expect_ref_tuple(value: Any, field: str) -> tuple[str, ...]:
    return tuple(_expect_ref(item, f"{field}[]") for item in _expect_list(value, field))


def _reject_unknown_keys(data: dict[str, Any], allowed: set[str], model_name: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise SignoffSchemaError(f"{model_name} unknown keys: {sorted(unknown)}")


def _require_keys(data: dict[str, Any], required: set[str], model_name: str) -> None:
    missing = required - set(data)
    if missing:
        raise SignoffSchemaError(f"{model_name} missing keys: {sorted(missing)}")


def _validate_hash_map(value: Any, field: str, *, require_nonempty: bool) -> dict[str, str]:
    mapping = _expect_dict(value, field)
    if require_nonempty and not mapping:
        raise SignoffSchemaError(f"{field} must be non-empty")
    output: dict[str, str] = {}
    for key, digest in mapping.items():
        safe_key = _expect_ref(key, f"{field}.key")
        output[safe_key] = validate_sha256(digest, f"{field}.{safe_key}")
    return output


def _validate_gate_results(value: Any) -> dict[str, dict[str, Any]]:
    gate_results = _expect_dict(value, "gate_results")
    missing = set(SIGNOFF_GATES) - set(gate_results)
    if missing:
        raise SignoffSchemaError(f"gate_results missing gates: {sorted(missing)}")
    unknown = set(gate_results) - set(SIGNOFF_GATES)
    if unknown:
        raise SignoffSchemaError(f"gate_results unknown gates: {sorted(unknown)}")
    output: dict[str, dict[str, Any]] = {}
    for gate, result in gate_results.items():
        entry = _expect_dict(result, f"gate_results.{gate}")
        status = _expect_enum(entry.get("status"), GATE_RESULT_STATUSES, f"gate_results.{gate}.status")
        finding_codes = _expect_code_tuple(entry.get("finding_codes", []), f"gate_results.{gate}.finding_codes")
        validate_no_secret_material(entry, f"gate_results.{gate}")
        output[gate] = {**entry, "status": status, "finding_codes": list(finding_codes)}
    return output


def _validate_benchmark_summary(value: Any) -> dict[str, Any]:
    summary = _expect_dict(value, "benchmark_summary")
    for key in ("false_pass_count", "must_not_pass_violation_count"):
        raw = summary.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise SignoffSchemaError(f"benchmark_summary.{key} must be non-negative integer")
    return summary


def _assert_no_secret_material(value: Any, field: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if _SECRET_KEY_RE.search(key_text):
                raise SignoffSchemaError(f"{field}.{key_text} contains forbidden secret-like key")
            _assert_no_secret_material(item, f"{field}.{key_text}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_secret_material(item, f"{field}[{index}]")
    elif isinstance(value, str) and _SECRET_VALUE_RE.search(value):
        raise SignoffSchemaError(f"{field} contains secret-like material")


_STRING_SCHEMA = {"type": "string", "minLength": 1}
_SHA256_SCHEMA = {"type": "string", "pattern": r"^[0-9a-f]{64}$"}
_DATETIME_SCHEMA = {"type": "string", "format": "date-time"}

SIGNOFF_FINDING_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(SignoffFinding.REQUIRED_FIELDS),
    "properties": {
        "finding_id": _STRING_SCHEMA,
        "gate": {"type": "string", "enum": list(SIGNOFF_GATES)},
        "code": {"type": "string", "pattern": _CODE_RE.pattern},
        "severity": {"type": "string", "enum": list(SIGNOFF_SEVERITIES)},
        "source": _STRING_SCHEMA,
        "message": _STRING_SCHEMA,
        "details": {"type": "object"},
        "run_id": _STRING_SCHEMA,
        "revision_id": _STRING_SCHEMA,
        "artifact_ref": {"type": ["string", "null"]},
        "node_id": {"type": ["string", "null"]},
        "case_id": {"type": ["string", "null"]},
        "waivable": {"type": "boolean"},
        "waiver_id": {"type": ["string", "null"]},
        "timestamp": _DATETIME_SCHEMA,
    },
}

SIGNOFF_WAIVERS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(SignoffWaivers.REQUIRED_FIELDS),
    "properties": {
        "schema_version": {"type": "string", "const": SIGNOFF_WAIVERS_SCHEMA_VERSION},
        "waivers": {"type": "array", "items": {"type": "object"}},
    },
}

FINAL_CERTIFICATE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(Agent1FinalSignoffCertificate.REQUIRED_FIELDS),
    "properties": {
        "schema_version": {"type": "string", "const": SIGNOFF_CERTIFICATE_SCHEMA_VERSION},
        "run_id": _STRING_SCHEMA,
        "revision_id": _STRING_SCHEMA,
        "project": {"type": "string", "pattern": _PROJECT_RE.pattern},
        "profile": {"type": "string", "enum": list(SIGNOFF_PROFILES)},
        "decision": {"type": "string", "enum": list(SIGNOFF_DECISIONS)},
        "handoff_allowed": {"type": "boolean"},
        "score": {"type": "number", "minimum": 0, "maximum": 100},
        "gate_results": {"type": "object"},
        "finding_summary": {"type": "object"},
        "waiver_summary": {"type": "object"},
        "benchmark_summary": {"type": "object"},
        "artifact_hashes": {"type": "object", "additionalProperties": _SHA256_SCHEMA},
        "topology_hash": _SHA256_SCHEMA,
        "config_hash": _SHA256_SCHEMA,
        "prompt_pack_hash": _SHA256_SCHEMA,
        "model_ref_hash": _SHA256_SCHEMA,
        "user_approval_ref": {"type": ["string", "null"]},
        "created_at": _DATETIME_SCHEMA,
    },
}

BENCHMARK_CASE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(BenchmarkCase.REQUIRED_FIELDS),
    "properties": {
        "schema_version": {"type": "string", "const": BENCHMARK_CASE_SCHEMA_VERSION},
        "case_id": _STRING_SCHEMA,
        "category": _STRING_SCHEMA,
        "profile": {"type": "string", "enum": list(SIGNOFF_PROFILES)},
        "requirement": _STRING_SCHEMA,
        "attachments": {"type": "array"},
        "mutations": {"type": "array"},
        "waivers": {"type": "array"},
        "expected_decision": {"type": "string", "enum": list(SIGNOFF_DECISIONS)},
        "expected_handoff_allowed": {"type": "boolean"},
        "expected_finding_codes": {"type": "array", "items": {"type": "string", "pattern": _CODE_RE.pattern}},
        "must_not_pass": {"type": "boolean"},
        "oracle_notes": _STRING_SCHEMA,
        "expected_debug_issue_codes": {"type": "array", "items": {"type": "string", "pattern": _CODE_RE.pattern}},
    },
}

BENCHMARK_RESULT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(BenchmarkResult.REQUIRED_FIELDS),
    "properties": {
        "schema_version": {"type": "string", "const": BENCHMARK_RESULT_SCHEMA_VERSION},
        "case_id": _STRING_SCHEMA,
        "profile": {"type": "string", "enum": list(SIGNOFF_PROFILES)},
        "actual_decision": {"type": "string", "enum": list(SIGNOFF_DECISIONS)},
        "actual_handoff_allowed": {"type": "boolean"},
        "actual_finding_codes": {"type": "array", "items": {"type": "string", "pattern": _CODE_RE.pattern}},
        "expected_match": {"type": "boolean"},
        "false_pass": {"type": "boolean"},
        "false_block": {"type": "boolean"},
        "must_not_pass_violation": {"type": "boolean"},
        "oracle_disagreement": {"type": "boolean"},
        "latency_s": {"type": "number", "minimum": 0},
        "token_cost_estimate": {"type": "number", "minimum": 0},
        "artifact_refs": {"type": "array", "items": _STRING_SCHEMA},
        "debug_issue_refs": {"type": "array", "items": _STRING_SCHEMA},
    },
}

SIGNOFF_JSON_SCHEMAS: dict[str, dict[str, Any]] = {
    "signoff_finding": SIGNOFF_FINDING_JSON_SCHEMA,
    "agent1_final_signoff_certificate": FINAL_CERTIFICATE_JSON_SCHEMA,
    "signoff_waivers": SIGNOFF_WAIVERS_JSON_SCHEMA,
    "benchmark_case": BENCHMARK_CASE_JSON_SCHEMA,
    "benchmark_result": BENCHMARK_RESULT_JSON_SCHEMA,
}
