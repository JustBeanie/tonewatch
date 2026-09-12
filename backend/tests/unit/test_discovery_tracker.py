from tonewatch.dsp.discovery import DiscoveryTracker
from tonewatch.dsp.matcher import Detection
from tonewatch.dsp.segmenter import SegmenterUpdate, ToneSegment


def segment(
    freq: float, start: float, duration: float, purity: float = 0.9, level: float = -30.0
) -> ToneSegment:
    return ToneSegment(freq, start, start + duration, purity, True, mean_level_dbfs=level)


def update(*segments: ToneSegment) -> SegmenterUpdate:
    return SegmenterUpdate(closed=segments)


def test_unknown_two_tone_finalizes_after_gap() -> None:
    tracker = DiscoveryTracker()
    assert tracker.feed(update(segment(1000, 0, 1), segment(1500, 1.1, 2)), now_s=3.0) == []
    candidates = tracker.feed(SegmenterUpdate(), now_s=3.7)
    assert len(candidates) == 1
    assert candidates[0].frequencies == (1000, 1500)


def test_long_tone_is_discovered_and_short_blip_is_rejected() -> None:
    tracker = DiscoveryTracker()
    candidates = tracker.feed(update(segment(1200, 0, 4), segment(1800, 5, 0.15)), now_s=5.2)
    candidates.extend(tracker.feed(SegmenterUpdate(), now_s=6))
    assert len(candidates) == 1
    assert candidates[0].frequencies == (1200,)


def test_known_span_is_removed_but_stacked_unknown_span_remains() -> None:
    tracker = DiscoveryTracker()
    known = segment(1000, 0, 1)
    unknown = segment(1800, 1.1, 2)
    detection = Detection("known", 0.8, (known,), True)
    tracker.feed(update(known, unknown), (detection,), now_s=3)
    candidates = tracker.feed(SegmenterUpdate(), now_s=3.7)
    assert len(candidates) == 1
    assert candidates[0].frequencies == (1800,)


def test_frequency_bounds_and_memory_cap() -> None:
    tracker = DiscoveryTracker(max_buffered_segments=2)
    tracker.feed(update(segment(100, 0, 1), segment(1000, 2, 1), segment(1500, 3.1, 1)), now_s=3.2)
    assert tracker.buffered_segment_count <= 2


def test_level_gate_fails_closed_for_quiet_tones() -> None:
    missing = DiscoveryTracker().feed(update(ToneSegment(1200, 0, 4, 0.9, True)), now_s=5)
    quiet = DiscoveryTracker().feed(update(segment(1200, 0, 4, level=-60)), now_s=5)
    audible = DiscoveryTracker().feed(update(segment(1200, 0, 4, level=-30)), now_s=5)
    assert missing == []
    assert quiet == []
    assert len(audible) == 1
