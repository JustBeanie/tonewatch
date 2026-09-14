# Tune detection

ToneWatch first marks a spectrum frame as tonal when its purity is at least
`purity_min` and its level is at least `level_min_dbfs`. The analyzer defaults
are `purity_min: 0.6` and `level_min_dbfs: -45`. A tonal frame's frequency is
then grouped into a segment and matched against each tone set.

## Tone-set settings

| Setting | Default | Effect |
| --- | ---: | --- |
| `tol_pct` | `1.5` | Frequency tolerance around each tone, as a percent. |
| `min_s` | required | Minimum duration for that tone to match. |
| `max_s` | unlimited | Maximum duration for that tone; longer audio is reported as excess. |
| `max_gap_s` | `0.5` | Largest gap allowed between adjacent tones in a sequence. |
| `cooldown_s` | `60` | Time after a match before the same tone set can alert again. |

`freq_hz` must be between 250 and 3000 Hz. A tone set can contain one to eight
ordered tones. `min_s` must be positive, and `max_s`, when supplied, must be at
least `min_s`.

## Symptoms and adjustments

If a page is missed, first check that the source is receiving audio and that
the tone is inside the 250–3000 Hz analysis band. Then consider lowering
`purity_min` for noisy or distorted audio, lowering `level_min_dbfs` for a
quiet feed, increasing `tol_pct` for frequency drift, or lowering `min_s` when
the beginning of a tone is consistently clipped. Increase `max_gap_s` when
the gap between tones is longer than the configured value.

If you get false positives, raise `purity_min` or `level_min_dbfs`, reduce
`tol_pct`, increase `min_s`, or reduce `max_gap_s`. Use `max_s` to reject a tone
that stays present too long. Keep `cooldown_s` long enough that repeated
matches from one page do not alert again immediately.

Make one change at a time and validate it with a saved recording using the
[analyzer workflow](troubleshooting.md).

## Squelch

Squelch controls the optional live-audio gate and recorder stop behavior; it never gates
tone detection. Set `squelch.mode` to `auto` to estimate a long-window noise floor and
spread from the running stream. Auto mode fails open while it calibrates, then uses the
10th percentile as the floor, a bounded `auto_k * spread` margin, and hysteresis for its
open and close thresholds. `auto_window_s`, `auto_min_samples_s`, `auto_k`,
`min_margin_db`, and `max_margin_db` tune the estimator.

The source diagnostics expose `calibrating`, `stuck_open`, `chatter`, and
`transitions_per_min`. A stuck carrier adds bounded 3 dB steps that decay after normal
operation. Chatter temporarily increases the hang time. Both flags are transition-logged
and visible in the REST and WebSocket status.

To measure a running source without opening another device, call
`POST /api/sources/{id}/squelch/calibrate` with `{ "seconds": 5 }` through `{ "seconds": 120 }`.
The response contains p10/p50/p90, a coarse histogram, and suggested `level` thresholds.
Calibration does not write configuration; apply the suggestion with a normal source update.

Software squelch marks a source as active when its level rises above the open
threshold and keeps it active through the configured attack and hang times.
The `level` mode uses fixed dBFS thresholds; `noise_floor` tracks the quietest
roughly ten percent of levels in a rolling window and applies `floor_margin_db`.
Hysteresis prevents chatter between the open and close thresholds.

Squelch controls activity display and future live audio gating only. It does
not affect detection: the matcher, discovery, ring buffer, and recorder always
receive the raw audio, including while squelch is closed.
