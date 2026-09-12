# Troubleshoot missed pages

Use a saved WAV and the same YAML configuration to see what ToneWatch heard:

```sh
tonewatch analyze file.wav --config config.yaml
```

The command normalizes the input to mono 16 kHz before analysis. It prints a
`Segments` table followed by `Detections`.

## Read the segment output

Each segment row contains:

- `freq_hz`: the estimated center frequency of the tonal segment.
- `start_s` and `end_s`: the segment's position in the recording.
- `purity`: the share of spectral energy around the detected peak.
- `closed`: whether the segment ended before analysis finished.

Compare the frequency and duration with the tone-set `freq_hz`, `tol_pct`,
`min_s`, and `max_s`. Compare the time between consecutive rows with
`max_gap_s`. A row missing entirely usually points to source level, noise, or
the purity and level thresholds. Rows that are present but produce no detection
usually point to frequency, duration, sequence order, or gap settings.

The command's JSON form is useful for scripts and stores the same data under
`segments` and `detections`:

```sh
tonewatch analyze file.wav --config config.yaml --json
```

The web **Analyze WAV** page accepts RIFF/WAVE files up to 20 MB and 600
seconds. It shows a segment timeline and any matched tone sets. The CLI is the
complete diagnostic view because it also exposes `freq_hz`, `purity`, and
`closed` for every segment.
