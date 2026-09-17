"""Validated, immutable ToneWatch configuration models."""

import json
import math
from string import Formatter
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from tonewatch.dsp.squelch import SquelchConfig

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1)]
BoundedString = Annotated[str, StringConstraints(min_length=1, max_length=500)]
Positive = Annotated[float, Field(gt=0)]
AlertEvent = Literal["pre_alert", "recording_ready", "closed", "tone_discovered", "call_enriched"]
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
    stop_on_squelch: bool = False
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
    name: str = Field(min_length=1, max_length=200)
    agency_id: Slug | None = None
    sequence: list[ToneSpec] = Field(min_length=1, max_length=8)
    max_gap_s: Positive = 0.5
    cooldown_s: float = Field(default=60, ge=0)
    enabled: bool = True
    alert_targets: list[Slug] = []
    record: RecordingPolicy = Field(default_factory=RecordingPolicy)


class AgencyLocation(FrozenModel):
    """A WGS84 point, represented as latitude/longitude for API users."""

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def finite_coordinates(self) -> "AgencyLocation":
        if not math.isfinite(self.lat) or not math.isfinite(self.lon):
            raise ValueError("location coordinates must be finite")
        return self


class AgencyAddress(FrozenModel):
    street: str = Field(default="", max_length=300)
    city: str = Field(default="", max_length=120)
    region: str = Field(default="", max_length=120)
    postal_code: str = Field(default="", max_length=40)
    country: str = Field(default="", max_length=80)


class AgencyStation(FrozenModel):
    name: str = Field(min_length=1, max_length=200)
    address: AgencyAddress = Field(default_factory=AgencyAddress)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def finite_coordinates(self) -> "AgencyStation":
        if not math.isfinite(self.lat) or not math.isfinite(self.lon):
            raise ValueError("station coordinates must be finite")
        return self


_RING_MIN_POSITIONS = 4
_POSITION_SIZE = 2
_LON_MIN, _LON_MAX, _LAT_MIN, _LAT_MAX = -180, 180, -90, 90
_MAX_COVERAGE_VERTICES = 10_000
_MAX_CAD_NAME_LENGTH = 120


def _validate_coverage(value: object) -> object:  # noqa: PLR0912 -- bounded GeoJSON validator.
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("coverage must be a GeoJSON Polygon or MultiPolygon")
    try:
        serialized = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("coverage must be JSON serializable") from exc
    if len(serialized.encode("utf-8")) > 256 * 1024:
        raise ValueError("coverage exceeds the 256 KiB serialized limit")
    coordinates = value.get("coordinates")
    rings: list[object] = []
    if value["type"] == "Polygon":
        if not isinstance(coordinates, list):
            raise ValueError("Polygon coordinates must be an array of linear rings")
        rings = coordinates
    elif isinstance(coordinates, list):
        rings = [ring for polygon in coordinates if isinstance(polygon, list) for ring in polygon]
    else:
        raise ValueError("MultiPolygon coordinates must be an array of polygons")
    vertices = 0
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < _RING_MIN_POSITIONS or ring[0] != ring[-1]:
            raise ValueError("coverage linear rings need at least 4 closed positions")
        vertices += len(ring)
        for position in ring:
            if (
                not isinstance(position, list)
                or len(position) != _POSITION_SIZE
                or not all(
                    isinstance(item, (int, float)) and not isinstance(item, bool)
                    for item in position
                )
                or not math.isfinite(float(position[0]))
                or not math.isfinite(float(position[1]))
                or not _LON_MIN <= float(position[0]) <= _LON_MAX
                or not _LAT_MIN <= float(position[1]) <= _LAT_MAX
            ):
                raise ValueError("coverage positions must be finite [lon, lat] pairs in range")
    if vertices > _MAX_COVERAGE_VERTICES:
        raise ValueError("coverage exceeds the 10,000 vertex limit")
    return value


class Agency(FrozenModel):
    """A configured agency and its optional map coverage."""

    id: Slug
    name: str = Field(min_length=1, max_length=200)
    short_name: str = Field(min_length=1, max_length=80)
    kind: Literal["fire", "ems", "police", "rescue", "dispatch", "other"]
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    description: str = Field(default="", max_length=1000)
    address: AgencyAddress = Field(default_factory=AgencyAddress)
    location: AgencyLocation
    stations: list[AgencyStation] = Field(default_factory=list, max_length=100)
    coverage: dict[str, object] | None = None
    phone: str = Field(default="", max_length=40)
    website: str = Field(default="", max_length=2048)
    radio: str = Field(default="", max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    notes: str = Field(default="", max_length=4000)
    cad_names: list[str] = Field(default_factory=list, max_length=20)

    _coverage = field_validator("coverage")(_validate_coverage)

    @field_validator("website")
    @classmethod
    def https_website(cls, value: str) -> str:
        if value and urlsplit(value).scheme not in {"http", "https"}:
            raise ValueError("website must use http or https")
        return value

    @field_validator("cad_names")
    @classmethod
    def normalize_cad_names(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for name in value:
            trimmed = name.strip()
            if not 1 <= len(trimmed) <= _MAX_CAD_NAME_LENGTH:
                raise ValueError("each cad name must contain 1-120 characters")
            key = trimmed.casefold()
            if key not in seen:
                result.append(trimmed)
                seen.add(key)
        return result


class MapConfig(FrozenModel):
    """Optional external map tile provider configuration."""

    tile_url: str = Field(default="", max_length=2048)
    attribution: str = Field(default="", max_length=1000)

    @field_validator("tile_url")
    @classmethod
    def safe_tile_template(cls, value: str) -> str:
        if not value:
            return value
        if any(char in value for char in "; \"'*"):
            raise ValueError("tile_url contains forbidden characters")
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise ValueError("tile_url must be an https template without credentials or query data")
        if parts.port not in (None, 443):
            raise ValueError("tile_url must use the default HTTPS port")
        if "{" in parts.netloc or "}" in parts.netloc:
            raise ValueError("tile_url subdomain templates are not supported")
        if not all(token in value for token in ("{z}", "{x}", "{y}")):
            raise ValueError("tile_url must contain {z}, {x}, and {y}")
        return value


OSM_MAP_PRESET = MapConfig(
    tile_url="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution="© OpenStreetMap contributors",
)


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
    squelch: SquelchConfig = Field(default_factory=SquelchConfig)


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
    rtl_fm_squelch: int = 0

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_squelch(cls, value: object) -> object:
        if isinstance(value, dict) and "squelch" in value and "rtl_fm_squelch" not in value:
            value = dict(value)
            legacy = value.pop("squelch")
            if isinstance(legacy, int) and not isinstance(legacy, bool):
                value["rtl_fm_squelch"] = legacy
            else:
                value["squelch"] = legacy
        return value


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


class CadFeed(FrozenModel):
    """An icad2mqtt v2 CAD feed."""

    id: Slug
    name: str = Field(min_length=1, max_length=200)
    type: Literal["icad2mqtt"] = "icad2mqtt"
    mqtt_target_id: Slug | None = None
    host: str | None = None
    port: int = Field(default=1883, ge=1, le=65535)
    tls: bool = False
    username: str | None = None
    password: str | None = None
    base_topic: str = Field(default="911/cad", min_length=1, max_length=300)
    enabled: bool = True
    window_before_s: float = Field(default=180, ge=0, le=3600)
    window_after_s: float = Field(default=300, ge=0, le=3600)

    @model_validator(mode="after")
    def exactly_one_broker(self) -> "CadFeed":
        if (self.host is None) == (self.mqtt_target_id is None):
            raise ValueError("exactly one of host or mqtt_target_id is required")
        return self


_NODE_ID = r"^![0-9a-fA-F]{8}$"
_MESHTASTIC_FIELDS = {
    "agency_short",
    "agency",
    "toneset",
    "tonesets",
    "time",
    "source",
    "call_id_short",
    "cad_type",
    "cad_address",
}


class MeshtasticTarget(FrozenModel):
    """MQTT JSON downlink target for a Meshtastic gateway node."""

    type: Literal["meshtastic"] = "meshtastic"
    id: Slug
    name: str = Field(min_length=1)
    transport: Literal["mqtt"] = "mqtt"
    host: str | None = None
    port: int = Field(default=1883, ge=1, le=65535)
    tls: bool = False
    username: str | None = None
    password: str | None = None
    mqtt_target_id: Slug | None = None
    root_topic: str = Field(default="msh/US", min_length=1)
    gateway_node_id: str = Field(pattern=_NODE_ID)
    channel_index: int = Field(default=0, ge=0, le=7)
    destination: str = Field(default="broadcast", pattern=r"^(broadcast|![0-9a-fA-F]{8})$")
    template: str = "TONE {agency_short} {toneset} {time}"
    max_bytes: int = Field(default=200, ge=1, le=200)
    phases: list[Literal["pre_alert", "recording_ready", "closed", "call_enriched"]] = ["pre_alert"]
    min_interval_s: float = Field(default=30, ge=0)
    max_per_hour: int = Field(default=20, ge=1)
    timeout_s: Positive = 30
    coalesce_s: float = Field(default=3.0, ge=0, le=15)
    timezone: str | None = None
    acknowledge_public_channel: bool = False
    enabled: bool = True

    @model_validator(mode="after")
    def validate_target(self) -> "MeshtasticTarget":
        if (self.host is None) == (self.mqtt_target_id is None):
            raise ValueError("exactly one of inline MQTT broker host or mqtt_target_id is required")
        if self.channel_index == 0 and not self.acknowledge_public_channel:
            raise ValueError(
                "channel 0 is the default public channel readable by anyone nearby; "
                "set acknowledge_public_channel=true to use it"
            )
        if "http" in self.template.lower():
            raise ValueError("Meshtastic templates may not contain http URLs")
        try:
            fields = Formatter().parse(self.template)
            for _literal, field_name, _format_spec, _conversion in fields:
                if field_name is not None and field_name not in _MESHTASTIC_FIELDS:
                    raise ValueError(f"unsupported Meshtastic placeholder: {{{field_name}}}")
        except ValueError as exc:
            raise ValueError(f"invalid Meshtastic template: {exc}") from exc
        if self.timezone is not None:
            try:
                ZoneInfo(self.timezone)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("timezone must be a valid IANA zone name") from exc
        return self

    @property
    def gateway_number(self) -> int:
        return int(self.gateway_node_id[1:], 16)

    @property
    def destination_number(self) -> int:
        return 0xFFFFFFFF if self.destination == "broadcast" else int(self.destination[1:], 16)


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


AlertTarget = Annotated[
    MqttTarget | MeshtasticTarget | WebhookTarget | ScriptTarget, Field(discriminator="type")
]


class AdminAlertsConfig(FrozenModel):
    """Thresholds and rate limits for operational (non-page) alerts."""

    enabled: bool = False
    targets: list[str] = Field(default_factory=list)
    feed_unhealthy_min: float = Field(default=5, ge=1, le=1440)
    disk_used_pct: float = Field(default=90, ge=50, le=99)
    disk_forecast_days: float = Field(default=7, ge=1, le=365)
    target_failures: int = Field(default=5, ge=2, le=100)
    squelch_stuck_open: bool = True
    realtime_factor_min: float = Field(default=1.5, ge=1.0, le=10)
    realtime_factor_min_s: float = Field(default=300, ge=30, le=3600)
    min_interval_s: float = Field(default=300, ge=60, le=86400)
    max_per_hour: int = Field(default=6, ge=1, le=100)


def _validate_meshtastic_references(targets: list[AlertTarget]) -> None:
    mqtt_ids = {item.id for item in targets if isinstance(item, MqttTarget)}
    for target in targets:
        if (
            isinstance(target, MeshtasticTarget)
            and target.mqtt_target_id is not None
            and target.mqtt_target_id not in mqtt_ids
        ):
            raise ValueError(
                f"Meshtastic target {target.id} references missing MQTT target {target.mqtt_target_id}"
            )


def _validate_cad_references(config: "AppConfig") -> None:
    mqtt_ids = {item.id for item in config.alert_targets if isinstance(item, MqttTarget)}
    for feed in config.cad_feeds:
        if feed.mqtt_target_id is not None and feed.mqtt_target_id not in mqtt_ids:
            raise ValueError(
                f"CAD feed {feed.id} references missing MQTT target {feed.mqtt_target_id}"
            )


def _validate_admin_alert_references(config: "AppConfig") -> None:
    """Ensure operational alerts only name configured output targets."""
    target_ids = {item.id for item in config.alert_targets}
    for target_id in config.admin_alerts.targets:
        if target_id not in target_ids:
            raise ValueError(f"admin alerts references missing alert target {target_id}")


class AppConfig(FrozenModel):
    """Complete configuration with reference integrity checks."""

    tone_sets: list[ToneSet] = Field(default_factory=list, max_length=500)
    sources: list[Source] = Field(default_factory=list, max_length=16)
    alert_targets: list[AlertTarget] = Field(default_factory=list, max_length=128)
    agencies: list[Agency] = Field(default_factory=list, max_length=500)
    cad_feeds: list[CadFeed] = Field(default_factory=list, max_length=64)
    map: MapConfig = Field(default_factory=MapConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    live_stream: LiveStreamConfig = Field(default_factory=LiveStreamConfig)
    admin_alerts: AdminAlertsConfig = Field(default_factory=AdminAlertsConfig)

    @model_validator(mode="after")
    def references_and_unique_ids(self) -> "AppConfig":
        for label, items in (
            ("tone set", self.tone_sets),
            ("source", self.sources),
            ("alert target", self.alert_targets),
            ("agency", self.agencies),
            ("CAD feed", self.cad_feeds),
        ):
            seen: set[str] = set()
            for item in items:
                if item.id in seen:
                    raise ValueError(f"duplicate {label} id: {item.id}")
                seen.add(item.id)
        tone_ids = {item.id for item in self.tone_sets}
        target_ids = {item.id for item in self.alert_targets}
        _validate_meshtastic_references(self.alert_targets)
        _validate_cad_references(self)
        agency_ids = {item.id for item in self.agencies}
        _validate_admin_alert_references(self)
        for toneset in self.tone_sets:
            if toneset.agency_id is not None and toneset.agency_id not in agency_ids:
                raise ValueError(
                    f"tone set {toneset.id} references missing agency {toneset.agency_id}"
                )
            for ref_id in toneset.alert_targets:
                if ref_id not in target_ids:
                    raise ValueError(
                        f"tone set {toneset.id} references missing alert target {ref_id}"
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
