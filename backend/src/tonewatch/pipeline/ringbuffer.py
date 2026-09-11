"""Fixed-size audio storage for recorder pre-roll."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Iterator

    from numpy.typing import NDArray

TIME_EPSILON_S = 1e-6


class RingBuffer:
    """A float32 ring with stream-time bounds for future recording slices."""

    def __init__(self, capacity_s: float = 10, sample_rate: int = 16_000) -> None:
        """Create an empty ring with a fixed sample capacity."""
        if capacity_s <= 0 or sample_rate <= 0:
            raise ValueError("capacity_s and sample_rate must be positive")
        self.sample_rate = sample_rate
        self.capacity_samples = max(1, round(capacity_s * sample_rate))
        self._data = np.zeros(self.capacity_samples, dtype=np.float32)
        self._written = 0
        self._cursor = 0
        self._oldest_stream_time_s: float | None = None
        self._end_stream_time_s: float | None = None

    @property
    def size(self) -> int:
        """Number of samples currently retained."""
        return self._written

    @property
    def start_stream_time_s(self) -> float | None:
        """Stream timestamp of the oldest retained sample."""
        return self._oldest_stream_time_s

    @property
    def end_stream_time_s(self) -> float | None:
        """Exclusive stream timestamp at the end of the retained samples."""
        return self._end_stream_time_s

    def extend(self, samples: NDArray[np.float32], *, stream_time_s: float | None = None) -> None:
        """Append samples, retaining only the newest fixed-capacity suffix."""
        values = np.asarray(samples, dtype=np.float32).reshape(-1)
        if not values.size:
            return
        input_size = values.size
        inferred_start = self._end_stream_time_s
        start = (
            inferred_start
            if stream_time_s is None and inferred_start is not None
            else stream_time_s
        )
        if start is None:
            start = 0.0
        if (
            self._end_stream_time_s is not None
            and abs(start - self._end_stream_time_s) > TIME_EPSILON_S
        ):
            self._oldest_stream_time_s = start
            self._written = 0
            self._cursor = 0
        if values.size >= self.capacity_samples:
            values = values[-self.capacity_samples :]
            self._cursor = 0
            self._data[:] = values
            self._written = self.capacity_samples
            self._oldest_stream_time_s = (
                start + (input_size - self.capacity_samples) / self.sample_rate
            )
        else:
            for chunk in self._chunks(values):
                end = min(self.capacity_samples - self._cursor, chunk.size)
                self._data[self._cursor : self._cursor + end] = chunk[:end]
                self._cursor = (self._cursor + end) % self.capacity_samples
                self._written = min(self.capacity_samples, self._written + end)
                if end < chunk.size:
                    self._data[: chunk.size - end] = chunk[end:]
                    self._cursor = chunk.size - end
                    self._written = self.capacity_samples
        new_end = start + input_size / self.sample_rate
        self._end_stream_time_s = new_end
        self._oldest_stream_time_s = new_end - self._written / self.sample_rate

    def _chunks(self, values: NDArray[np.float32]) -> Iterator[NDArray[np.float32]]:
        """Yield one value; keeping writes simple avoids aliasing caller arrays."""
        yield values

    def snapshot(self, seconds: float | None = None) -> NDArray[np.float32]:
        """Return the newest ``seconds`` of retained samples in chronological order."""
        if seconds is not None and seconds < 0:
            raise ValueError("seconds must not be negative")
        count = self._written
        if seconds is not None:
            count = min(count, round(seconds * self.sample_rate))
        if count == 0:
            return np.zeros(0, dtype=np.float32)
        start = (self._cursor - self._written) % self.capacity_samples
        start = (start + self._written - count) % self.capacity_samples
        indexes = (start + np.arange(count)) % self.capacity_samples
        return self._data[indexes].astype(np.float32, copy=True)

    def snapshot_with_time(
        self, seconds: float | None = None
    ) -> tuple[NDArray[np.float32], float | None]:
        """Return samples and the stream timestamp of their first sample."""
        samples = self.snapshot(seconds)
        if self._end_stream_time_s is None:
            return samples, None
        return samples, self._end_stream_time_s - samples.size / self.sample_rate
