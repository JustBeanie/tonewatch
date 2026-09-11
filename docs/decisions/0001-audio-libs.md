# ADR 0001: Audio library compatibility

## Status

Accepted for M0.6, pending CI matrix results.

## Decision

Use PyAV for MP3 and Opus encoding/decoding and sounddevice for native audio
input. The M0.6 spike is also run by CI on Ubuntu amd64, Windows, and Ubuntu
arm64.

## Verification

The Windows spike was run successfully with:

```text
uv run --project backend pytest backend/tests/spike/test_audio_libs.py -v
```

Linux amd64 and arm64 are `PENDING-CI` until the GitHub runner matrix exists.
No lameenc fallback is selected unless the spike proves PyAV MP3 unavailable.

Windows result: PASS. PyAV `18.1.0` successfully encoded and decoded both MP3
and Opus, and `sounddevice` imported successfully. PyAV reported FFmpeg
libraries `libavutil 60.26.102`, `libavcodec 62.28.102`, `libavformat
62.12.102`, `libavdevice 62.3.102`, `libavfilter 11.14.102`, `libswscale
9.5.102`, and `libswresample 6.3.102`. The spike remains a CI job for Linux
amd64/arm64 verification.
