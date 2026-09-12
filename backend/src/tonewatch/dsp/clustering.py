"""Deterministic clustering primitives for discovered tone candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from tonewatch.dsp.discovery import ToneCandidate


@dataclass(frozen=True, slots=True)
class ClusterObservation:
    """One candidate observed on one source."""

    candidate: ToneCandidate
    source_id: str
    seen_at: datetime


@dataclass(slots=True)
class DiscoveredCluster:
    """A running cluster summary."""

    frequencies: tuple[float, ...]
    durations: tuple[float, ...]
    count: int
    first_seen: datetime
    last_seen: datetime
    source_ids: set[str] = field(default_factory=set)
    frequency_spread_pct: float = 0.0
    status: str = "new"
    best_mean_purity: float = 0.0
    _frequency_samples: list[tuple[float, ...]] = field(default_factory=list, repr=False)
    _duration_samples: list[tuple[float, ...]] = field(default_factory=list, repr=False)


class DiscoveryClusterer:
    """Cluster observations with canonical ordering and deterministic tie breaks."""

    def __init__(self, *, tol_pct: float = 1.5) -> None:
        if tol_pct <= 0:
            raise ValueError("tol_pct must be positive")
        self.tol_pct = tol_pct
        self._observations: list[ClusterObservation] = []

    @property
    def observations(self) -> tuple[ClusterObservation, ...]:
        """Return observations accepted by this clusterer."""
        return tuple(self._observations)

    def add(self, observation: ClusterObservation) -> tuple[DiscoveredCluster, int]:
        """Add an observation and return its deterministic cluster and index."""
        self._observations.append(observation)
        clusters = self._rebuild()
        target = observation.candidate.frequencies
        index = min(
            (
                (self._distance(cluster.frequencies, target), cluster.frequencies, number)
                for number, cluster in enumerate(clusters)
                if len(cluster.frequencies) == len(target)
            ),
            default=(0.0, target, 0),
        )[2]
        return clusters[index], index

    def _rebuild(self) -> list[DiscoveredCluster]:
        clusters: list[DiscoveredCluster] = []
        observations = sorted(
            self._observations,
            key=lambda item: (
                item.candidate.frequencies,
                item.candidate.durations,
                item.seen_at,
                item.source_id,
            ),
        )
        for observation in observations:
            candidate = observation.candidate
            eligible = [
                (self._distance(cluster.frequencies, candidate.frequencies), index, cluster)
                for index, cluster in enumerate(clusters)
                if self._agrees(cluster.frequencies, candidate.frequencies)
            ]
            if eligible:
                _, _, cluster = min(
                    eligible, key=lambda item: (item[0], item[2].frequencies, item[1])
                )
                self._merge(cluster, observation)
            else:
                clusters.append(
                    DiscoveredCluster(
                        frequencies=candidate.frequencies,
                        durations=candidate.durations,
                        count=1,
                        first_seen=observation.seen_at,
                        last_seen=observation.seen_at,
                        source_ids={observation.source_id},
                        best_mean_purity=candidate.mean_purity,
                        _frequency_samples=[candidate.frequencies],
                        _duration_samples=[candidate.durations],
                    )
                )
        for cluster in clusters:
            cluster.source_ids = set(cluster.source_ids)
        return clusters

    def _merge(self, cluster: DiscoveredCluster, observation: ClusterObservation) -> None:
        candidate = observation.candidate
        cluster.count += 1
        cluster._frequency_samples.append(candidate.frequencies)
        cluster._duration_samples.append(candidate.durations)
        cluster.frequencies = tuple(
            (old * (cluster.count - 1) + new) / cluster.count
            for old, new in zip(cluster.frequencies, candidate.frequencies, strict=True)
        )
        cluster.durations = tuple(
            median(values) for values in zip(*cluster._duration_samples, strict=True)
        )
        cluster.first_seen = min(cluster.first_seen, observation.seen_at)
        cluster.last_seen = max(cluster.last_seen, observation.seen_at)
        cluster.source_ids.add(observation.source_id)
        spread = max(
            max(
                abs(sample[index] - cluster.frequencies[index]) / cluster.frequencies[index] * 100
                for sample in cluster._frequency_samples
            )
            for index in range(len(cluster.frequencies))
        )
        cluster.frequency_spread_pct = max(cluster.frequency_spread_pct, spread)
        cluster.best_mean_purity = max(cluster.best_mean_purity, candidate.mean_purity)

    def _agrees(self, mean: tuple[float, ...], values: tuple[float, ...]) -> bool:
        return len(mean) == len(values) and all(
            abs(actual - expected) <= expected * self.tol_pct / 100
            for actual, expected in zip(values, mean, strict=True)
        )

    @staticmethod
    def _distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        if len(left) != len(right):
            return float("inf")
        return sum(abs(a - b) / max(b, 1.0) for a, b in zip(left, right, strict=True))
