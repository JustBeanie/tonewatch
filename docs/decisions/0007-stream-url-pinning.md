# ADR-0007: Stream URL pinning strategy

- Status: accepted
- Date: 2026-09-11

## Decision

ToneWatch uses option (a): it does not rewrite a stream hostname to a resolved
IP address. `StreamAudioSource.open()` resolves and validates the configured
URL immediately before each FFmpeg open, and the Python redirect probe repeats
that validation for every `Location` hop. FFmpeg receives the original
hostname, preserving HTTP `Host`, HTTPS SNI, and certificate hostname checks;
its `max_redirects=0` option prevents an unvalidated follow-up request.

Reconnects clear the validated URL, so the next open performs a fresh DNS
resolution. The remaining DNS-rebinding time-of-check/time-of-use window is
tracked as AR-003 and is bounded by the immediate validation and FFmpeg open.

## TLS probe

On a normal Windows user account, PyAV 18.1.0 / libavformat 62.12 decoded a
local self-signed HTTPS stream with `tls_verify=0`. With `tls_verify=1`, the
same stream was refused, including when `ca_file` named the test certificate.
That is expected for the Windows Schannel backend: it uses the Windows
certificate store and ignores `ca_file`. Public-CA HTTPS feeds completed their
TLS handshakes with `tls_verify=0`, `tls_verify=1`, and `tls_verify=1` plus
certifi; their subsequent `InvalidDataError` was media parsing, not TLS.

ToneWatch therefore always requests `tls_verify=1` and the certifi bundle.
The regression test first probes whether the runtime can make a local TLS
connection; sandbox accounts without Schannel credentials skip that environment
limitation rather than treating it as product behavior. It then proves that
product options refuse the self-signed certificate. On non-Windows TLS
backends, a test-local `ca_file` must be honored; on Windows the expected
refusal documents the use of the OS certificate store. AR-004 tracks only that
platform difference.
