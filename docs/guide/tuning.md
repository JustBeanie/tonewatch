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

Software squelch marks a source as active when its level rises above the open
threshold and keeps it active through the configured attack and hang times.
The `level` mode uses fixed dBFS thresholds; `noise_floor` tracks the quietest
roughly ten percent of levels in a rolling window and applies `floor_margin_db`.
Hysteresis prevents chatter between the open and close thresholds.

Squelch controls activity display and future live audio gating only. It does
not affect detection: the matcher, discovery, ring buffer, and recorder always
receive the raw audio, including while squelch is closed.
