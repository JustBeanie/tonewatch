"""Importer for legacy ``tones.cfg`` two-tone configuration files."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from tonewatch.config.models import AppConfig, RecordingPolicy, ToneSet, ToneSpec
from tonewatch.config.store import replace_config

TONES_CFG_MAX_BYTES = 256 * 1024
TONES_CFG_MAX_SECTIONS = 500
_MIN_TOL_PCT = 0.1
_MAX_TOL_PCT = 10.0
_EMAIL_KEYS = {"text_emails", "mp3_emails", "amr_emails"}
_COMMAND_KEYS = {"post_email_command", "alert_command"}
_IMPORTED_KEYS = {
    "atone",
    "atonelength",
    "btone",
    "btonelength",
    "longtone",
    "longtonelength",
    "tone_tolerance",
    "description",
    "record_seconds",
    "ignore_after",
    "gaplength",
}


class TonesCfgImportError(ValueError):
    """Base error for invalid tones.cfg input or application."""


class TonesCfgImportLimitError(TonesCfgImportError):
    """Raised when an input exceeds the importer resource limits."""

    def __init__(self, limit: Literal["bytes", "sections"]) -> None:
        """Build a safe error naming only the exceeded importer limit."""
        message = (
            "tones.cfg input exceeds the 256 KiB limit"
            if limit == "bytes"
            else "tones.cfg input exceeds the 500 section limit"
        )
        super().__init__(message)


class TonesCfgApplyError(TonesCfgImportError):
    """Raised when imported tone sets cannot form a valid application config."""

    @classmethod
    def invalid_mode(cls) -> TonesCfgApplyError:
        """Build the invalid mode error."""
        return cls("mode must be merge or replace")

    @classmethod
    def invalid_config(cls, message: str) -> TonesCfgApplyError:
        """Build an error from safe model validation text."""
        return cls(f"imported tone sets cannot be applied: {message}")


@dataclass(frozen=True)
class TonesCfgSectionResult:
    """Preview result for one source section."""

    name: str
    tone_set: ToneSet | None
    notes: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def imported(self) -> bool:
        """Whether this section produced a usable tone set."""
        return self.tone_set is not None and not self.errors


@dataclass(frozen=True)
class TonesCfgImportResult:
    """All proposed tone sets and safe, per-section preview messages."""

    sections: tuple[TonesCfgSectionResult, ...]

    @property
    def tone_sets(self) -> tuple[ToneSet, ...]:
        """Return only valid proposed tone sets in source order."""
        return tuple(
            section.tone_set
            for section in self.sections
            if section.imported and section.tone_set is not None
        )

    @property
    def imported_count(self) -> int:
        """Number of sections that produced tone sets."""
        return len(self.tone_sets)

    @property
    def skipped_count(self) -> int:
        """Number of sections rejected from import."""
        return len(self.sections) - self.imported_count

    @property
    def notes(self) -> tuple[str, ...]:
        """Flatten notes for callers that need a compact report."""
        return tuple(note for section in self.sections for note in section.notes)

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe preview without source values."""
        return {
            "imported": self.imported_count,
            "skipped": self.skipped_count,
            "sections": [
                {
                    "name": section.name,
                    "status": "imported" if section.imported else "skipped",
                    "tone_set": section.tone_set.model_dump(mode="json")
                    if section.tone_set is not None
                    else None,
                    "notes": list(section.notes),
                    "errors": list(section.errors),
                }
                for section in self.sections
            ],
        }

    def to_json(self) -> str:
        """Serialize the safe preview used by the CLI and tests."""
        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


def _parse_number(raw: str, key: str, errors: list[str]) -> float | None:
    if not raw:
        errors.append(f"{key} is required")
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        errors.append(f"{key} must be a number")
        return None
    if not math.isfinite(value):
        errors.append(f"{key} must be finite")
        return None
    return value


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    result = re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")
    return result or "tone-set"


def _safe_key(key: str) -> str:
    """Keep key-only diagnostics from becoming a value or address echo."""
    return key.replace("@", "[at]")


def _safe_text(value: str) -> str:
    """Prevent an address-shaped label from being echoed in an output."""
    return value.replace("@", "[at]")


def _unique_slug(base: str, used: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _parse_definition(lower: dict[str, str], errors: list[str]) -> list[tuple[float, float]]:
    has_two = any(key in lower for key in ("atone", "atonelength", "btone", "btonelength"))
    has_long = any(key in lower for key in ("longtone", "longtonelength"))
    if has_two and has_long:
        errors.append("section mixes two-tone and long-tone definitions")
        return []
    if has_two:
        values: list[tuple[float, float]] = []
        for frequency_key, length_key in (("atone", "atonelength"), ("btone", "btonelength")):
            frequency = _parse_number(lower.get(frequency_key, ""), frequency_key, errors)
            length = _parse_number(lower.get(length_key, ""), length_key, errors)
            if frequency is not None and length is not None:
                values.append((frequency, length))
        return values
    if has_long:
        frequency = _parse_number(lower.get("longtone", ""), "longtone", errors)
        length = _parse_number(lower.get("longtonelength", ""), "longtonelength", errors)
        return [(frequency, length)] if frequency is not None and length is not None else []
    errors.append("missing long-tone or complete two-tone definition")
    return []


def _policy_number(
    lower: dict[str, str], key: str, default: float, errors: list[str], notes: list[str]
) -> float:
    raw = lower.get(key, "")
    if not raw:
        notes.append(f"{key} missing: model default used")
        return default
    parsed = _parse_number(raw, key, errors)
    return parsed if parsed is not None else default


def _parse_tolerance(lower: dict[str, str], errors: list[str], notes: list[str]) -> float:
    tolerance = 1.5
    raw_tolerance = lower.get("tone_tolerance", "")
    if raw_tolerance:
        fraction = _parse_number(raw_tolerance, "tone_tolerance", errors)
        if fraction is not None:
            tolerance = fraction * 100
            if not _MIN_TOL_PCT <= tolerance <= _MAX_TOL_PCT:
                errors.append("tone_tolerance must be between 0.1 and 10 percent")
    else:
        notes.append("tone_tolerance missing: model default used")
    return tolerance


def _parse_policy(
    lower: dict[str, str], errors: list[str], notes: list[str]
) -> tuple[float, float, float, float]:
    tolerance = _parse_tolerance(lower, errors, notes)

    gap = _policy_number(lower, "gaplength", 0.5, errors, notes)
    if lower.get("gaplength") and gap <= 0:
        gap = 0.5
        notes.append("gaplength not imported: value is not positive")
    post_s = _policy_number(lower, "record_seconds", 60.0, errors, notes)
    cooldown = _policy_number(lower, "ignore_after", 60.0, errors, notes)
    return tolerance, gap, post_s, cooldown


def _dropped_notes(lower: dict[str, str]) -> list[str]:
    notes: list[str] = []
    for key in sorted(_EMAIL_KEYS):
        count = sum(1 for item in lower.get(key, "").split(",") if item.strip())
        if count:
            notes.append(
                f"{key}: {count} email recipient field(s) not imported "
                "(use a webhook or MQTT target)"
            )
    notes.extend(
        f"{key}: not imported: configure a script alert target manually"
        for key in sorted(_COMMAND_KEYS)
        if lower.get(key, "")
    )
    notes.extend(
        f"{_safe_key(key)}: not imported"
        for key in sorted(lower)
        if key != "__name__" and key not in _IMPORTED_KEYS
    )
    return notes


def _section_result(
    name: str, values: dict[str, str], used_ids: set[str], parse_errors: list[str]
) -> TonesCfgSectionResult:
    errors = list(parse_errors)
    notes: list[str] = []
    lower = {key.casefold(): value.strip() for key, value in values.items()}
    sequence_values = _parse_definition(lower, errors)
    tolerance, gap, post_s, cooldown = _parse_policy(lower, errors, notes)
    notes.extend(_dropped_notes(lower))
    name_value = _safe_text(lower.get("description", "") or name)
    tone_id = _unique_slug(_slug(name_value), used_ids)
    if errors:
        return TonesCfgSectionResult(name, None, tuple(notes), tuple(errors))
    try:
        sequence = [
            ToneSpec(freq_hz=frequency, tol_pct=tolerance, min_s=length)
            for frequency, length in sequence_values
        ]
        tone_set = ToneSet(
            id=tone_id,
            name=name_value,
            sequence=sequence,
            max_gap_s=gap,
            cooldown_s=cooldown,
            record=RecordingPolicy(post_s=post_s),
        )
    except ValidationError as exc:
        message = f"invalid tone set: {exc.errors()[0]['msg']}"
        return TonesCfgSectionResult(name, None, tuple(notes), (message,))
    return TonesCfgSectionResult(name, tone_set, tuple(notes))


def parse_tones_cfg(text: str) -> TonesCfgImportResult:
    """Parse tones.cfg text without reading files or executing imported commands."""
    if len(text.encode("utf-8", errors="replace")) > TONES_CFG_MAX_BYTES:
        raise TonesCfgImportLimitError("bytes")
    normalized = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    sections: list[tuple[str, dict[str, str], list[str]]] = []
    current_name: str | None = None
    current_values: dict[str, str] = {}
    current_errors: list[str] = []

    def finish() -> None:
        if current_name is not None:
            sections.append((current_name, current_values.copy(), current_errors.copy()))

    for line_number, line in enumerate(normalized.split("\n"), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            finish()
            current_name = _safe_text(stripped[1:-1].strip() or f"section-{len(sections) + 1}")
            current_values = {}
            current_errors = []
            continue
        if stripped.startswith("["):
            finish()
            current_name = f"section-{len(sections) + 1}"
            current_values = {}
            current_errors = [f"line {line_number}: malformed section header"]
            continue
        if current_name is None:
            continue
        if "=" not in line:
            current_errors.append(f"line {line_number}: expected key = value")
            continue
        key, value = line.split("=", 1)
        key = key.strip().casefold()
        if not key:
            current_errors.append(f"line {line_number}: key is empty")
            continue
        current_values[key] = value.strip()
    finish()
    if len(sections) > TONES_CFG_MAX_SECTIONS:
        raise TonesCfgImportLimitError("sections")
    used_ids: set[str] = set()
    results = tuple(
        _section_result(name, values, used_ids, errors) for name, values, errors in sections
    )
    return TonesCfgImportResult(results)


def apply_tones_cfg(
    config: AppConfig, result: TonesCfgImportResult, mode: Literal["merge", "replace"]
) -> AppConfig:
    """Return a validated config with only tone sets changed."""
    if mode not in {"merge", "replace"}:
        raise TonesCfgApplyError.invalid_mode()
    if mode == "replace":
        tone_sets = list(result.tone_sets)
    else:
        used_ids = {item.id for item in config.tone_sets}
        tone_sets = list(config.tone_sets)
        for item in result.tone_sets:
            unique_id = _unique_slug(item.id, used_ids)
            tone_sets.append(item.model_copy(update={"id": unique_id}))
    try:
        return replace_config(config, tone_sets=tone_sets)
    except ValidationError as exc:
        raise TonesCfgApplyError.invalid_config(exc.errors()[0]["msg"]) from exc
