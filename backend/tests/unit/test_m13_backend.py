import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import numpy as np
from fastapi import HTTPException
from sqlalchemy import select

if TYPE_CHECKING:
    from fastapi import Request

from tonewatch.api.routes.config import create_toneset
from tonewatch.api.routes.discovered_tones import (
    _dump,
    _slug,
    delete_discovered_tone,
    discovered_clip,
    discovered_tone,
    discovered_tones,
    dismiss,
    promote,
)
from tonewatch.config.models import AppConfig
from tonewatch.config.store import ConfigStore
from tonewatch.dsp.clustering import ClusterObservation, DiscoveryClusterer
from tonewatch.dsp.discovery import DiscoveryTracker, ToneCandidate
from tonewatch.dsp.segmenter import SegmenterUpdate, ToneSegment
from tonewatch.events import EventBus, ToneCandidateObserved, ToneDiscovered
from tonewatch.pipeline.persistence import PersistenceSubscriber
from tonewatch.recording.discovery import (
    discovery_clip_path,
    encode_discovery_clip,
    replace_discovery_clip,
)
from tonewatch.settings import Settings
from tonewatch.storage.db import create_database
from tonewatch.storage.models import Base, DiscoveredTone


def _candidate(*freqs: float, start: float = 0) -> ToneCandidate:
    return ToneCandidate(
        tuple(
            ToneSegment(freq, start + index, start + index + 1, 0.9, True)
            for index, freq in enumerate(freqs)
        )
    )


def test_clusterer_is_stable_and_clip_replacement_is_safe(tmp_path: Path) -> None:
    first = datetime(2026, 1, 1, tzinfo=UTC)
    observations = [
        ClusterObservation(_candidate(1000, 1500), "a", first),
        ClusterObservation(_candidate(1004, 1502), "b", first),
        ClusterObservation(_candidate(1900, 2200), "c", first),
    ]
    clusterer = DiscoveryClusterer()
    for observation in reversed(observations):
        clusterer.add(observation)
    clusters = clusterer._rebuild()
    assert [cluster.count for cluster in clusters] == [2, 1]
    path = discovery_clip_path(tmp_path, 1)
    assert replace_discovery_clip(tmp_path, 1, b"old") == path
    replace_discovery_clip(tmp_path, 1, b"new")
    assert path.read_bytes() == b"new"
    encoded = encode_discovery_clip(
        tmp_path,
        2,
        np.zeros(16_000, dtype=np.float32),
        call_start=first,
        source_id="a",
    )
    assert encoded.stat().st_size > 0


def test_clusterer_keeps_true_duration_median() -> None:
    def candidate(duration: float) -> ToneCandidate:
        return ToneCandidate((ToneSegment(1000, 0, duration, 0.9, True),))

    clusterer = DiscoveryClusterer()
    for duration in (1.0, 10.0, 2.0):
        clusterer.add(
            ClusterObservation(candidate(duration), "radio", datetime(2026, 1, 1, tzinfo=UTC))
        )
    assert clusterer._rebuild()[0].durations == (2.0,)


def test_tracker_rejects_invalid_configuration_and_overflow() -> None:
    try:
        DiscoveryTracker(max_gap_s=-1)
    except ValueError:
        pass
    else:
        raise AssertionError
    tracker = DiscoveryTracker(max_buffered_segments=1)
    tracker.feed(
        SegmenterUpdate(
            closed=(
                ToneSegment(1000, 0, 1, 0.9, True),
                ToneSegment(1500, 1.1, 2.1, 0.9, True),
            )
        ),
        now_s=2,
    )
    assert tracker.buffered_segment_count <= 1
    quiet = DiscoveryTracker(level_min_dbfs=-30)
    assert (
        quiet.feed(
            SegmenterUpdate(closed=(ToneSegment(1000, 0, 4, 0.9, True, 0, -40),)),
            now_s=5,
        )
        == []
    )


def test_persistence_emits_only_new_cluster(tmp_path: Path) -> None:
    async def run() -> None:
        engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'm13.sqlite'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        bus = EventBus()
        subscriber = PersistenceSubscriber(bus, sessions)
        event = ToneCandidateObserved(_candidate(1000, 1500), "radio", datetime.now(UTC))
        subscription = bus.subscribe()
        await subscriber._persist(event)
        await subscriber._persist(event)
        async with sessions() as session:
            rows = list((await session.scalars(select(DiscoveredTone))).all())
        assert len(rows) == 1
        assert isinstance((await subscription.__anext__()), ToneDiscovered)
        await engine.dispose()

    asyncio.run(run())


def test_discovered_api_endpoints_and_range_clip(  # noqa: PLR0915 -- endpoint contract coverage is intentionally end to end.
    tmp_path: Path,
) -> None:
    async def run() -> None:  # noqa: PLR0915 -- endpoint contract coverage is intentionally end to end.
        engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'api.sqlite'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        settings = Settings(data_dir=tmp_path, recordings_root=tmp_path / "recordings")
        clip = settings.recording_path / "discovered" / "7.mp3"
        clip.parent.mkdir(parents=True)
        clip.write_bytes(b"abcdef")
        async with sessions() as session:
            session.add(
                DiscoveredTone(
                    id=7,
                    mean_frequencies=[1000, 1500],
                    median_durations=[1, 2],
                    count=3,
                    first_seen=datetime(2026, 1, 1, tzinfo=UTC),
                    last_seen=datetime(2026, 1, 2, tzinfo=UTC),
                    source_ids=["radio"],
                    observed_frequency_spread_pct=1,
                    status="new",
                    best_clip_recording_path=str(clip),
                    best_mean_purity=0.9,
                )
            )
            await session.commit()
        app = SimpleNamespace(
            state=SimpleNamespace(
                session_factory=sessions,
                settings=settings,
                config=AppConfig(),
                store=ConfigStore(tmp_path),
                supervisor=SimpleNamespace(reload=lambda _config: asyncio.sleep(0)),
            )
        )
        request = SimpleNamespace(
            app=app,
            state=SimpleNamespace(auth="test"),
            headers={},
        )
        typed_request = cast("Request", request)
        assert (
            len(
                (
                    await discovered_tones(
                        typed_request, source=None, since=None, status=None, limit=100, offset=0
                    )
                )["items"]
            )
            == 1
        )
        filtered = await discovered_tones(
            typed_request,
            source="radio",
            since="2026-01-01T00:00:00+00:00",
            status="new",
            limit=1,
            offset=0,
        )
        assert filtered["limit"] == 1 and filtered["offset"] == 0
        offset_since = await discovered_tones(
            typed_request,
            source=None,
            since="2026-01-01T17:00:00-07:00",
            status=None,
            limit=100,
            offset=0,
        )
        naive_since = await discovered_tones(
            typed_request,
            source=None,
            since="2026-01-02T00:00:00",
            status=None,
            limit=100,
            offset=0,
        )
        assert len(offset_since["items"]) == len(naive_since["items"]) == 1
        assert (await discovered_tones(typed_request, None, None, "new", 100, 1))["items"] == []
        try:
            await discovered_tones(typed_request, None, "invalid", None, 100, 0)
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError
        assert (await discovered_tone(typed_request, 7))["id"] == 7
        async with sessions() as session:
            stored = await session.get(DiscoveredTone, 7)
        assert stored is not None
        assert _dump(stored)["id"] == 7
        assert _slug(stored, set()).startswith("discovered-")
        assert _slug(stored, {"discovered-1000-1500", "discovered-1000-1500-2"}) == (
            "discovered-1000-1500-3"
        )
        request.headers = {"range": "bytes=1-3"}
        response = await discovered_clip(typed_request, 7)
        assert response.status_code == 206 and response.body == b"bcd"
        request.headers = {"range": "bytes=99-100"}
        assert (await discovered_clip(typed_request, 7)).status_code == 416
        request.headers = {"range": "items=0-1"}
        assert (await discovered_clip(typed_request, 7)).status_code == 416
        request.headers = {"range": "bytes=-2"}
        assert (await discovered_clip(typed_request, 7)).body == b"ef"
        request.headers = {}
        draft = await promote(typed_request, 7)
        assert draft["sequence"][0]["freq_hz"] == 1000
        created = await create_toneset(
            typed_request,
            {
                "id": "new-set",
                "name": "New set",
                "sequence": [{"freq_hz": 1000, "tol_pct": 1.5, "min_s": 0.8}],
            },
        )
        assert created["id"] == "new-set"
        promoted = await create_toneset(
            typed_request,
            {
                "id": "discovered-set",
                "name": "Discovered set",
                "sequence": [{"freq_hz": 1000, "tol_pct": 1.5, "min_s": 0.8}],
                "discovered_tone_id": 7,
            },
        )
        assert promoted["id"] == "discovered-set"
        await dismiss(typed_request, 7)
        request.headers = {}
        await delete_discovered_tone(typed_request, 7)
        assert not clip.exists()
        for handler in (discovered_tone, promote, dismiss, delete_discovered_tone):
            try:
                await handler(typed_request, 7)
            except HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError
        try:
            await discovered_clip(typed_request, 7)
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError
        await engine.dispose()

    asyncio.run(run())


def test_delete_missing_or_foreign_clip_removes_only_the_selected_row(tmp_path: Path) -> None:
    async def run() -> None:
        engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'delete.sqlite'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        settings = Settings(data_dir=tmp_path, recordings_root=tmp_path / "recordings")
        foreign = settings.recording_path / "other.mp3"
        foreign.parent.mkdir(parents=True, exist_ok=True)
        foreign.write_bytes(b"keep")
        missing = settings.recording_path / "discovered" / "8.mp3"
        async with sessions() as session:
            session.add_all(
                [
                    DiscoveredTone(
                        id=8,
                        mean_frequencies=[1000],
                        median_durations=[2],
                        count=1,
                        first_seen=datetime(2026, 1, 1, tzinfo=UTC),
                        last_seen=datetime(2026, 1, 1, tzinfo=UTC),
                        source_ids=["radio"],
                        status="new",
                        best_clip_recording_path=str(missing),
                    ),
                    DiscoveredTone(
                        id=9,
                        mean_frequencies=[1500],
                        median_durations=[2],
                        count=1,
                        first_seen=datetime(2026, 1, 1, tzinfo=UTC),
                        last_seen=datetime(2026, 1, 1, tzinfo=UTC),
                        source_ids=["radio"],
                        status="new",
                        best_clip_recording_path=str(foreign),
                    ),
                ]
            )
            await session.commit()
        app = SimpleNamespace(state=SimpleNamespace(session_factory=sessions, settings=settings))
        request = cast("Request", SimpleNamespace(app=app, state=SimpleNamespace(auth="test")))
        assert await delete_discovered_tone(request, 8) == {"ok": True}
        assert await delete_discovered_tone(request, 9) == {"ok": True}
        assert foreign.read_bytes() == b"keep"
        async with sessions() as session:
            assert await session.get(DiscoveredTone, 8) is None
            assert await session.get(DiscoveredTone, 9) is None
        await engine.dispose()

    asyncio.run(run())
