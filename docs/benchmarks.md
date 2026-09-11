# DSP benchmark

Measured locally on 2026-09-11 with Python 3.13.13 on an Intel(R) Core(TM)
i9-9900K CPU @ 3.60GHz.

The `just bench` recipe runs pytest-benchmark over 600 seconds of generated
audio: 20 blocks of 30 s, each a real two-tone page (1000 Hz 1.0 s, 0.1 s gap,
1500 Hz 3.0 s) followed by seeded `voice_like` audio and pink noise. It uses 200
two-tone sets (199 decoys spread across the band plus the one that fires), and
builds a fresh engine per round. The test asserts exactly 20 detections, all for
the page set, so the segmenter and matcher are exercised rather than idling on
non-tonal frames.

| Measurement | Result |
| --- | ---: |
| Mean engine time | 478.72 ms |
| Minimum engine time | 473.43 ms |
| Audio duration | 600 s |
| Throughput | ~1,250x realtime |
| Detections | 20 / 20 expected |
| Benchmark rounds | 5 |

The target is 20x realtime. The first M2 run measured a non-tonal stream only
(469 ms, 1,278x); PM review replaced it with this realistic mix, which costs
about 2% more. Raspberry Pi 4/5 numbers are still to be recorded by hand.

## `analyze --json` schema

`tonewatch analyze FILE.wav --config config.yaml --json` emits one stable JSON
object with `schema_version: 1`, `segments`, and `detections`. `--frames`
adds the `frames` array. Segment objects contain `freq_hz`, `start_s`, `end_s`,
`mean_purity`, `closed`, and `excess_s`. Detection objects contain
`toneset_id`, `detected_at_s`, `early`, and their matched `segments`. Numeric
values are seconds, hertz, or unitless purity as named; no wall-clock fields
are included.
