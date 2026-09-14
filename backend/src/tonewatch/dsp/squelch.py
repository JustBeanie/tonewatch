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
    mode: Literal["off", "level", "noise_floor"] = "off"
    open_dbfs: float = Field(default=-40, ge=-120, le=0)
    close_dbfs: float = Field(default=-45, ge=-120, le=0)
    attack_ms: float = Field(default=50, ge=0, le=2000)
    hang_ms: float = Field(default=1500, ge=0, le=30000)
    floor_margin_db: float = Field(default=10, ge=1, le=40)

    @model_validator(mode="after")
    def ordered_thresholds(self) -> SquelchConfig:
        """Ensure the close threshold does not exceed the open threshold."""
        if self.close_dbfs > self.open_dbfs:
            raise ValueError("close_dbfs must be less than or equal to open_dbfs")
        return self


class Squelch:
    """Frame-fed hysteretic squelch with attack and hang timers."""

    def __init__(self, config: SquelchConfig, *, window_s: float = 30.0) -> None:
        self.config = config
        self.window_s = window_s
        self.open = False
        self.noise_floor: float | None = None
        self._attack_since: float | None = None
        self._quiet_since: float | None = None
        self._levels: deque[tuple[float, int]] = deque()
        self._histogram = [0] * 241

    @property
    def open_threshold_dbfs(self) -> float:
        """Return the current level required to open the squelch."""
        if self.config.mode == "noise_floor" and self.noise_floor is not None:
            return self.noise_floor + self.config.floor_margin_db
        return self.config.open_dbfs

    def feed(self, level_dbfs: float, stream_time_s: float) -> tuple[bool, bool]:
        """Consume one level and return ``(open, changed)``."""
        if self.config.mode == "off":
            return False, False
        level_bin = max(0, min(240, round((level_dbfs + 120) * 2)))
        self._levels.append((stream_time_s, level_bin))
        self._histogram[level_bin] += 1
        cutoff = stream_time_s - self.window_s
        while self._levels and self._levels[0][0] < cutoff:
            _, old_bin = self._levels.popleft()
            self._histogram[old_bin] -= 1
        if self.config.mode == "noise_floor":
            target = max(1, int(len(self._levels) * 0.1))
            cumulative = 0
            floor_bin = 0
            for candidate_bin, count in enumerate(self._histogram):
                cumulative += count
                if cumulative >= target:
                    floor_bin = candidate_bin
                    break
            self.noise_floor = floor_bin / 2 - 120
            open_threshold = self.open_threshold_dbfs
            close_threshold = open_threshold - (self.config.open_dbfs - self.config.close_dbfs)
        else:
            open_threshold, close_threshold = self.config.open_dbfs, self.config.close_dbfs
        changed = False
        if self.open:
            if level_dbfs <= close_threshold:
                self._attack_since = None
                if self._quiet_since is None:
                    self._quiet_since = stream_time_s
                if stream_time_s - self._quiet_since + 1e-9 >= self.config.hang_ms / 1000:
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
        return self.open, changed
