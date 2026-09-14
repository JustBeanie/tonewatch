"""Pure software squelch state machine.

In ``noise_floor`` mode the estimator keeps a timestamped, bounded window of
levels and uses its 10th percentile as the floor.  Old samples are evicted as
stream time advances, so memory is bounded by the configured window and input
rate. Levels are quantised into a 0.5 dBFS histogram, so updates and percentile
lookup are O(1) over the fixed [-120, 0] dBFS range.
"""

from __future__ import annotations

from collections import deque
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SquelchConfig(BaseModel):
    """Validated software squelch settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["off", "level", "noise_floor", "auto"] = "off"
    open_dbfs: float = Field(default=-40, ge=-120, le=0)
    close_dbfs: float = Field(default=-45, ge=-120, le=0)
    attack_ms: float = Field(default=50, ge=0, le=2000)
    hang_ms: float = Field(default=1500, ge=0, le=30000)
    floor_margin_db: float = Field(default=10, ge=1, le=40)
    auto_window_s: float = Field(default=300, ge=30, le=1800)
    auto_min_samples_s: float = Field(default=30, ge=5, le=300)
    auto_k: float = Field(default=1.5, ge=0.25, le=4)
    min_margin_db: float = Field(default=6, ge=1, le=40)
    max_margin_db: float = Field(default=25, ge=1, le=60)
    stuck_open_s: float = Field(default=600, ge=30, le=7200)
    max_transitions_per_min: int = Field(default=20, ge=2, le=600)

    @model_validator(mode="after")
    def ordered_thresholds(self) -> SquelchConfig:
        """Ensure the close threshold does not exceed the open threshold."""
        if self.close_dbfs > self.open_dbfs:
            raise ValueError("close_dbfs must be less than or equal to open_dbfs")
        if self.auto_min_samples_s > self.auto_window_s:
            raise ValueError("auto_min_samples_s must be less than or equal to auto_window_s")
        if self.max_margin_db < self.min_margin_db:
            raise ValueError("max_margin_db must be greater than or equal to min_margin_db")
        return self


class Squelch:
    """Frame-fed hysteretic squelch with attack and hang timers."""

    def __init__(self, config: SquelchConfig, *, window_s: float = 30.0) -> None:
        self.config = config
        self.window_s = config.auto_window_s if config.mode == "auto" else window_s
        self.open = config.mode == "auto"
        self.noise_floor: float | None = None
        self._attack_since: float | None = None
        self._quiet_since: float | None = None
        self._levels: deque[tuple[float, int]] = deque()
        self._histogram = [0] * 241
        self._first_time: float | None = None
        self._opened_at: float | None = None
        self._margin_steps = 0
        self._transitions: deque[float] = deque()
        self.stuck_open = False
        self.chatter = False
        self._health_changed = False
        self._last_transition: float | None = None
        self._closed_at: float | None = None

    @property
    def open_threshold_dbfs(self) -> float:
        """Return the current level required to open the squelch."""
        if self.config.mode == "noise_floor" and self.noise_floor is not None:
            return self.noise_floor + self.config.floor_margin_db
        p10, p50, _ = self.percentiles()
        if self.config.mode == "auto" and p10 is not None and p50 is not None:
            base_margin = min(
                self.config.max_margin_db,
                max(self.config.min_margin_db, self.config.auto_k * (p50 - p10)),
            )
            margin = base_margin + min(12, self._margin_steps * 3)
            return p10 + margin
        return self.config.open_dbfs

    @property
    def close_threshold_dbfs(self) -> float:
        """Return the current effective close threshold."""
        p10, p50, _ = self.percentiles()
        if self.config.mode == "auto" and p10 is not None and p50 is not None:
            return self.open_threshold_dbfs - max(3.0, (p50 - p10) / 2)
        if self.config.mode == "noise_floor" and self.noise_floor is not None:
            return self.open_threshold_dbfs - (self.config.open_dbfs - self.config.close_dbfs)
        return self.config.close_dbfs

    @property
    def p10(self) -> float | None:
        """Return the tenth percentile of the retained levels."""
        return self.percentiles()[0]

    @property
    def p50(self) -> float | None:
        """Return the median of the retained levels."""
        return self.percentiles()[1]

    @property
    def p90(self) -> float | None:
        """Return the ninetieth percentile of the retained levels."""
        return self.percentiles()[2]

    @property
    def spread(self) -> float | None:
        """Return the median-minus-floor spread."""
        return None if self.p10 is None or self.p50 is None else self.p50 - self.p10

    @property
    def calibrating(self) -> bool:
        """Whether auto mode has observed its minimum stream-time sample span."""
        return self.config.mode == "auto" and (
            self._first_time is None
            or not self._levels
            or self._levels[-1][0] - self._first_time < self.config.auto_min_samples_s
        )

    @property
    def effective_hang_ms(self) -> float:
        """Return the hang after chatter health adjustment."""
        if not self.chatter:
            return self.config.hang_ms
        return min(30_000.0, self.config.hang_ms * 2)

    @property
    def health_changed(self) -> bool:
        """Consume and return whether a health flag changed."""
        changed, self._health_changed = self._health_changed, False
        return changed

    def health(self) -> tuple[bool, bool]:
        """Return stuck-open and chatter flags."""
        return self.stuck_open, self.chatter

    @property
    def transitions_per_min(self) -> float:
        """Return transitions currently retained in the trailing minute."""
        return float(len(self._transitions))

    def percentiles(self) -> tuple[float, float, float] | tuple[None, None, None]:
        """Return p10, p50 and p90 using the bounded histogram."""
        if not self._levels:
            return None, None, None
        total = len(self._levels)
        values: list[float] = []
        for quantile in (0.1, 0.5, 0.9):
            target = max(1, int(total * quantile))
            cumulative = 0
            for candidate_bin, count in enumerate(self._histogram):
                cumulative += count
                if cumulative >= target:
                    values.append(candidate_bin / 2 - 120)
                    break
        return values[0], values[1], values[2]

    def feed(self, level_dbfs: float, stream_time_s: float) -> tuple[bool, bool]:  # noqa: PLR0915 -- state-machine branches are intentionally explicit
        """Consume one level and return ``(open, changed)``."""
        if self.config.mode == "off":
            return False, False
        if self._first_time is None:
            self._first_time = stream_time_s
        level_bin = max(0, min(240, round((level_dbfs + 120) * 2)))
        self._levels.append((stream_time_s, level_bin))
        self._histogram[level_bin] += 1
        cutoff = stream_time_s - self.window_s
        while self._levels and self._levels[0][0] < cutoff:
            _, old_bin = self._levels.popleft()
            self._histogram[old_bin] -= 1
        if self.config.mode == "noise_floor":
            self.noise_floor = self.percentiles()[0]
            open_threshold = self.open_threshold_dbfs
            close_threshold = self.close_threshold_dbfs
        elif self.config.mode == "auto":
            open_threshold, close_threshold = self.open_threshold_dbfs, self.close_threshold_dbfs
            self.noise_floor = self.p10
        else:
            open_threshold, close_threshold = self.config.open_dbfs, self.config.close_dbfs
        if self.config.mode == "auto" and self.calibrating:
            self.open = True
            return True, False
        if self.config.mode == "auto" and self.open and self._opened_at is None:
            self._opened_at = stream_time_s - self.config.auto_min_samples_s
        self._update_health(stream_time_s)
        changed = False
        if self.open:
            if level_dbfs <= close_threshold:
                self._attack_since = None
                if self._quiet_since is None:
                    self._quiet_since = stream_time_s
                if stream_time_s - self._quiet_since + 1e-9 >= self.effective_hang_ms / 1000:
                    self.open = False
                    changed = True
                    self._quiet_since = None
            else:
                self._quiet_since = None
        elif level_dbfs >= open_threshold:
            self._quiet_since = None
            if self._attack_since is None:
                self._attack_since = stream_time_s
            if stream_time_s - self._attack_since + 1e-9 >= self.config.attack_ms / 1000:
                self.open = True
                changed = True
                self._attack_since = None
        else:
            self._attack_since = None
        if changed:
            self._transitions.append(stream_time_s)
            self._last_transition = stream_time_s
            while self._transitions and self._transitions[0] < stream_time_s - 60:
                self._transitions.popleft()
            if len(self._transitions) > self.config.max_transitions_per_min and not self.chatter:
                self.chatter = True
                self._health_changed = True
            if self.open:
                self._opened_at = stream_time_s
            else:
                self._closed_at = stream_time_s
        if (
            not self.open
            and self.stuck_open
            and self._closed_at is not None
            and stream_time_s - self._closed_at >= self.effective_hang_ms / 1000 + 5
        ):
            self.stuck_open = False
            self._margin_steps = 0
            self._health_changed = True
        return self.open, changed

    def _update_health(self, now: float) -> None:
        if self.open and self._opened_at is None:
            self._opened_at = now
        if self.open and self._opened_at is not None:
            elapsed = now - self._opened_at
            steps = min(4, int(elapsed // self.config.stuck_open_s))
            if steps != self._margin_steps:
                self._margin_steps = steps
            if steps and not self.stuck_open:
                self.stuck_open = True
                self._health_changed = True
        if self.chatter and self._last_transition is not None and now - self._last_transition >= 60:
            self.chatter = False
            self._health_changed = True
