# PM review: M3a fails on spec. The required integration tests are missing.

The source implementations, `tonewatch devices` and the M1 carry-over thread test are good, and `just check` is green (PM re-verified). But you acknowledged that the stream and RTL-SDR tests are mocked. Those integration tests were explicit requirements, because reconnect and restart are exactly where these sources fail in the field.

## Findings, all required
1. **Stream integration test (M3.4).**
   - Generate a short Ogg/Opus or MP3 file with PyAV.
   - Serve it from a local `http.server.ThreadingHTTPServer` thread on `127.0.0.1` with port 0.
   - Decode through `StreamSource` with the **real** PyAV path (not mocked), and assert that the decoded samples are mono float32 at 16 kHz with the expected duration within 5%.
   - **Reconnect:** have the server drop the connection mid-file, then serve it again, with the injected sleep so the test doesn't actually wait. Assert that the source reconnects, that `stream_time_s` keeps increasing monotonically, and that the first frame after reconnect has `discontinuity=True`.
   - Put this in `backend/tests/integration/test_stream_source.py`.
2. **RTL-SDR integration test (M3.5).**
   - Add a fake `rtl_fm`: `backend/tests/integration/fake_rtl_fm.py`, run as `[sys.executable, fake_rtl_fm.py, ...]` through a configurable executable plus prefix args.
   - The fake writes a known 1 kHz s16le tone for N samples, records its argv to a file, then exits.
   - Assert the recorded argv, with **no shell** involved.
   - Assert the decoded tone frequency, via `SpectrumAnalyzer` or a zero-crossing count.
   - Assert that the process exiting causes a **restart** (the fake runs a second time).
   - Assert that after `close()` no child process remains; check `returncode` is set, or use `psutil` only if it's already a dependency.
3. **Resampler property test (M3.1).** Use Hypothesis to check that, for input rates {8k, 22.05k, 44.1k, 48k} and 1–2 channels, the output length matches duration within 1 sample and a 1 kHz tone still measures within 5 Hz of 1 kHz at 16 kHz.
4. **Realtime file mode (M3.2).** Test pacing with the injectable clock and sleep: chunks are released at chunk_duration intervals of injected time, and nothing actually sleeps.
5. **Coverage.** `sources/` must reach **≥90% per module**. Today: file 73%, rtlsdr 75%, stream 85%, soundcard 87%. Add `tonewatch.sources` to the package coverage gate in `backend/scripts/check_package_coverage.py` at 90%.

## Constraints
- Integration tests must pass on Windows and on Linux CI; avoid POSIX-only signals. Mark any test slower than 5 s as `slow`.
- Don't modify `scripts/license_check.py`, `backend/tests/unit/test_license_check.py` or `.github/workflows/security.yml`. They are PM work in progress.

## Definition of done
`just check` exits 0, pre-commit over all files exits 0, and the final message includes the per-module coverage for `sources/` and unfiltered verification tails.
