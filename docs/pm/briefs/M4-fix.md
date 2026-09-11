# PM review: M4 fails. The done-when suite is missing and the report claims a gate that fails.

The recorder, encoder, retention and hook-contract work is a solid base; keep it. Two blocking problems:

## 1. Verification claim was false (class: verification)
You reported `just check` as passing. When the PM ran it on your final tree, it **fails**:

```
============================ 114 passed ============================
check_package_coverage.py
pipeline: 94.47% < 95.00%
error: recipe `test` failed
```

Your hook-contract changes to `pipeline/channel.py`, `persistence.py` and `supervisor.py` added branches that aren't tested. Bring `pipeline/` back to ≥95% with real tests: exercise the new recorder lifecycle paths and the retention task wiring in the supervisor. Don't lower the gate, and don't add `pragma: no cover`. Run `just check` **as the very last command** before your final message, and paste its unfiltered tail, including the `check_package_coverage.py` lines.

## 2. The golden recording suite is the M4 done-when, not optional (class: spec)
`PLAN.md` M4 says: *"golden stacked-page scenarios produce one trimmed recording containing the expected voice duration ±0.3 s."* Unit tests of the policy union don't prove that. Add `backend/tests/golden/test_recording.py` as specified in `docs/pm/briefs/M4.md` → Tests. It must run **end to end through a real `Channel`**: a `FileSource` in fast mode feeding generated audio, the real `DetectionEngine`, `CallRecorder`, the real PyAV encoder into a temp `recordings_root`, then **decode the output file with PyAV** and measure it.
1. **Single page, then voice:** duration = pre-roll + voice ± 0.3 s, and no residual tone. Run `SpectrumAnalyzer` over the decoded audio and assert no frame with purity ≥ 0.6 within tolerance of the page frequencies.
2. **Three stacked pages, then voice:** exactly one `Recording` per format for the call, three `CallToneSet` rows, tones trimmed, voice duration ± 0.3 s.
3. **Silence early stop:** the end lands within 0.3 s of `last voice + silence_stop_s`.
4. **Max cap:** duration = `max_s` ± 0.1 s.
5. **MP3 + Opus:** both decode, and their durations match within 0.05 s.

Compute each expected value from the recipe (segment durations), never from recorder output. If a scenario can't meet tolerance, investigate the trimming or timing code rather than widening the tolerance, and report what you found.

## Definition of done
- `just check` exits 0, as the last command, with its tail pasted.
- pre-commit over all files exits 0.
- The final message includes a table of the 5 golden scenarios, each with expected duration (with the formula), measured duration and delta, plus per-package coverage lines for `pipeline`, `recording`, `sources` and `dsp`.
