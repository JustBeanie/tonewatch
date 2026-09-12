# ADR 0008: Native Windows service

## Status

Accepted for M9.

## Decision

Use the PSF-licensed `pywin32` service APIs to register `ToneWatch` as a
delayed automatic Windows service. The service command line records the frozen
executable and its data directory, configures restart-on-failure recovery, and
starts `tonewatch serve` through the service wrapper. `SvcStop` sets the same
uvicorn exit flag used by the server runner, so FastAPI lifespan shutdown runs
the supervisor finalizer and flushes recordings.

NSSM was not selected because it would require a separately downloaded third-party
binary with its own update and licensing burden.

## TLS behavior

The Windows PyAV wheel uses FFmpeg's schannel TLS backend. Schannel ignores the
product `ca_file` option and verifies public certificates against the Windows
certificate store. The Windows smoke therefore supplies the same `tls_verify=1`
and `ca_file` options as other platforms, then asserts that a verified HTTPS
handshake reaches FFmpeg's expected `InvalidDataError` for the HTML payload.
