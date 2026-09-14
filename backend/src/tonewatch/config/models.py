"""Validated, immutable ToneWatch configuration models."""

from string import Formatter
from typing import Annotated, Literal

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1)]
Positive = Annotated[float, Field(gt=0)]
AlertEvent = Literal["pre_alert", "recording_ready", "closed", "tone_discovered"]
DEFAULT_ALERT_EVENTS: tuple[AlertEvent, ...] = ("pre_alert", "recording_ready", "closed")


def _deduplicate_events(value: list[AlertEvent]) -> list[AlertEvent]:
    return list(dict.fromkeys(value))


class FrozenModel(BaseModel):
    """Base for strict immutable configuration objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ToneSpec(FrozenModel):
    """One frequency and duration constraint."""

    freq_hz: float = Field(ge=250, le=3000)
    tol_pct: float = Field(default=1.5, ge=0.1, le=10)
    min_s: Positive
    max_s: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def duration_order(self) -> "ToneSpec":
        if self.max_s is not None and self.max_s < self.min_s:
            raise ValueError("max_s must be greater than or equal to min_s")
        return self


class RecordingPolicy(FrozenModel):
    """Recording retention and output policy."""

    pre_roll_s: float = Field(default=2, ge=0, le=10)
    post_s: Positive = 60
    silence_stop_s: Positive = 8
    max_s: Positive = 300
    formats: list[Literal["mp3", "opus"]] = ["mp3"]

    @field_validator("formats")
    @classmethod
    def formats_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("formats must contain at least one format")
        return value


class ToneSet(FrozenModel):
    """An ordered tone sequence and its alert policy."""

    id: Slug
    name: str = Field(min_length=1)
    sequence: list[ToneSpec] = Field(min_length=1, max_length=8)
    max_gap_s: Positive = 0.5
    cooldown_s: float = Field(default=60, ge=0)
    enabled: bool = True
    alert_targets: list[Slug] = []
    record: RecordingPolicy = Field(default_factory=RecordingPolicy)


class DiscoveryConfig(FrozenModel):
    """Global tone auto-discovery settings."""

    enabled: bool = True
    clip: bool = True
    min_segment_s: Positive = Field(default=0.3, le=3)
    max_segment_s: Positive = Field(default=3.0, le=10)
    max_gap_s: float = Field(default=0.5, ge=0, le=10)
    tol_pct: float = Field(default=1.5, ge=0.5, le=5)

    @model_validator(mode="after")
    def segment_order(self) -> "DiscoveryConfig":
        if self.max_segment_s < self.min_segment_s:
            raise ValueError("max_segment_s must be greater than or equal to min_segment_s")
        return self


class LiveStreamConfig(FrozenModel):
    """Global live MP3 restream policy."""

    enabled: bool = False
    bitrate_kbps: int = Field(default=48, ge=32, le=128)
    max_listeners_per_source: int = Field(default=4, ge=1, le=64)
    max_listeners_total: int = Field(default=12, ge=1, le=256)
    token_ttl_s: int = Field(default=3600, ge=60, le=86400)
    max_lag_s: float = Field(default=10, gt=0, le=120)


class SourceBase(FrozenModel):
    """Common source settings."""

    id: Slug
    name: str = Field(min_length=1)
    enabled: bool = True
    tonesets: list[Slug] | Literal["all"] = "all"
    discovery_enabled: bool = True
    live_stream_enabled: bool = True


class SoundcardSource(SourceBase):
    type: Literal["soundcard"] = "soundcard"
    device: str | int
    channel: Literal["left", "right", "mix"] = "mix"


class StreamSource(SourceBase):
    type: Literal["stream"] = "stream"
    url: AnyUrl

    @field_validator("url")
    @classmethod
    def validate_stream_scheme(cls, value: AnyUrl) -> AnyUrl:
        if value.scheme not in {"http", "https", "rtsp", "rtsps"}:
            raise ValueError("stream URL scheme must be http, https, rtsp, or rtsps")
        return value


class RtlSdrSource(SourceBase):
    type: Literal["rtlsdr"] = "rtlsdr"
    freq_hz: float
    gain: float | None = None
    ppm: int = 0
    squelch: int = 0


class FileSource(SourceBase):
    type: Literal["file"] = "file"
    path: str = Field(min_length=1)
    realtime: bool = True
    loop: bool = False


Source = Annotated[
    SoundcardSource | StreamSource | RtlSdrSource | FileSource, Field(discriminator="type")
]


class MqttTarget(FrozenModel):
    type: Literal["mqtt"] = "mqtt"
    id: Slug
    name: str = Field(min_length=1)
    broker: str = "localhost"
    host: str | None = None
    port: int = Field(default=1883, ge=1, le=65535)
    tls: bool = False
    username: str | None = None
    password: str | None = None
    source: Literal["manual", "supervisor"] = "manual"
    ha_discovery: bool = True
    topic: str = "tonewatch"
    enabled: bool = True
    events: list[AlertEvent] = Field(default_factory=lambda: list(DEFAULT_ALERT_EVENTS))

    @field_validator("events")
    @classmethod
    def deduplicate_events(cls, value: list[AlertEvent]) -> list[AlertEvent]:
        return _deduplicate_events(value)

    @property
    def hostname(self) -> str:
        """Return the explicit host, or the legacy broker value."""
        return self.host or self.broker


class WebhookTarget(FrozenModel):
    type: Literal["webhook"] = "webhook"
    id: Slug
    name: str = Field(min_length=1)
    url: AnyUrl
    secret: str = ""
    include_audio: bool = False
    allow_insecure_http: bool = False
    enabled: bool = True
    events: list[AlertEvent] = Field(default_factory=lambda: list(DEFAULT_ALERT_EVENTS))

    @field_validator("events")
    @classmethod
    def deduplicate_events(cls, value: list[AlertEvent]) -> list[AlertEvent]:
        return _deduplicate_events(value)


class ScriptTarget(FrozenModel):
    type: Literal["script"] = "script"
    id: Slug
    name: str = Field(min_length=1)
    executable: str = Field(min_length=1)
    args: list[str] = []
    timeout_s: Positive = 30
    enabled: bool = False
    events: list[AlertEvent] = Field(default_factory=lambda: list(DEFAULT_ALERT_EVENTS))

    @field_validator("events")
    @classmethod
    def deduplicate_events(cls, value: list[AlertEvent]) -> list[AlertEvent]:
        return _deduplicate_events(value)

    @field_validator("args")
    @classmethod
    def validate_args(cls, value: list[str]) -> list[str]:
        """Reject format fields that could silently become configuration bugs."""
        allowed = {"call_id", "toneset", "recording_path", "source_id", "phase"}
        for template in value:
            try:
                fields = Formatter().parse(template)
                for _literal, field_name, _format_spec, _conversion in fields:
                    if field_name is not None and field_name not in allowed | {"recording_url"}:
                        raise ValueError(f"unsupported script placeholder: {{{field_name}}}")
            except ValueError as exc:
                raise ValueError(f"invalid script args template: {template!r}: {exc}") from exc
        return value


AlertTarget = Annotated[MqttTarget | WebhookTarget | ScriptTarget, Field(discriminator="type")]


class AppConfig(FrozenModel):
    """Complete configuration with reference integrity checks."""

    tone_sets: list[ToneSet] = Field(default_factory=list, max_length=500)
    sources: list[Source] = Field(default_factory=list, max_length=16)
    alert_targets: list[AlertTarget] = Field(default_factory=list, max_length=128)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    live_stream: LiveStreamConfig = Field(default_factory=LiveStreamConfig)

    @model_validator(mode="after")
    def references_and_unique_ids(self) -> "AppConfig":
        for label, items in (
            ("tone set", self.tone_sets),
            ("source", self.sources),
            ("alert target", self.alert_targets),
        ):
            seen: set[str] = set()
            for item in items:
                if item.id in seen:
                    raise ValueError(f"duplicate {label} id: {item.id}")
                seen.add(item.id)
        tone_ids = {item.id for item in self.tone_sets}
        target_ids = {item.id for item in self.alert_targets}
        for toneset in self.tone_sets:
            for target in toneset.alert_targets:
                if target not in target_ids:
                    raise ValueError(
                        f"tone set {toneset.id} references missing alert target {target}"
                    )
        for source in self.sources:
            if source.tonesets != "all":
                for tone_id in source.tonesets:
                    if tone_id not in tone_ids:
                        raise ValueError(
                            f"source {source.id} references missing tone set {tone_id}"
                        )
        return self

    def lint(self, *, addon_mode: bool = False) -> list[str]:
        """Return non-fatal configuration warnings."""
        warnings: list[str] = []
        for toneset in self.tone_sets:
            for previous, current in zip(toneset.sequence, toneset.sequence[1:], strict=False):
                tolerance = (
                    max(previous.freq_hz * previous.tol_pct, current.freq_hz * current.tol_pct)
                    / 100
                )
                if abs(previous.freq_hz - current.freq_hz) <= tolerance:
                    warnings.append(
                        f"tone set {toneset.id}: adjacent tones {previous.freq_hz:g} and {current.freq_hz:g} overlap"
                    )
        if not addon_mode:
            warnings.extend(
                f"alert target {target.id}: supervisor source requires add-on mode"
                for target in self.alert_targets
                if isinstance(target, MqttTarget) and target.source == "supervisor"
            )
        return warnings
