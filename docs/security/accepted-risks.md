# Accepted security risks

Any suppression must reference an entry below and expire no more than 90 days
after it is recorded.

## AR-001 — Windows token-file ACL verification

- Recorded: 2026-09-11
- Expires: 2026-11-30
- Owner: ToneWatch maintainers
- Risk: Windows does not expose POSIX mode bits, and the application does not
  yet call a native owner-only ACL API for the token file.
- Scope: Windows native packaging only; POSIX startup enforces `0600`.
- Mitigation: Keep the Windows data directory owner-private until native ACL
  enforcement is added.

## AR-002 — Zeroconf metadata disclosure

- Recorded: 2026-09-11
- Expires: 2026-11-30
- Owner: ToneWatch maintainers
- Risk: The optional Zeroconf responder exposes limited service metadata to the
  local network; this is not an authentication or bearer-token disclosure.
- Scope: Zeroconf-enabled deployments on the local network.
- Mitigation: The TXT record omits the API token, and the responder remains
  optional and disabled in addon mode.

## AR-003 - DNS rebinding TOCTOU window

- Recorded: 2026-09-11
- Expires: 2026-11-30
- Owner: ToneWatch maintainers
- Risk: A DNS answer can change between Python validation and FFmpeg's socket
  connect; option (a) preserves the hostname so HTTP Host, HTTPS SNI, and
  certificate checks remain correct, but cannot eliminate that small TOCTOU
  window without breaking name-based feeds.
- Scope: HTTP, HTTPS, and RTSP stream reconnects.
- Mitigation: Resolve immediately before every open and every HTTP redirect;
  reject unsafe answers and set FFmpeg max_redirects=0.

## AR-004 - Windows TLS custom-CA behavior

- Recorded: 2026-09-11
- Expires: 2026-11-30
- Owner: ToneWatch maintainers
- Risk: The Windows PyAV 18.1.0 / libavformat 62.12 Schannel backend ignores
  FFmpeg's `ca_file` option and validates certificates only through the Windows
  certificate store.
- Scope: Windows HTTPS stream feeds using a private CA; public-CA feeds and
  certificate verification itself remain supported.
- Mitigation: The decoder explicitly requests `tls_verify=1`; deployments with
  a private CA install it in the Windows certificate store. The portable TLS
  regression test checks refusal of a self-signed certificate and records the
  platform-specific custom-CA result.

## AR-005 - Deployment TLS and HSTS

- Recorded: 2026-09-11
- Expires: 2026-11-30
- Owner: ToneWatch maintainers
- Risk: ToneWatch is a plain-HTTP local service and does not emit
  `Strict-Transport-Security`; TLS termination and HSTS are deployment concerns
  for a reverse proxy or Home Assistant ingress.
- Scope: Browser-facing deployments outside a trusted local network.
- Mitigation: M12 deployment documentation must specify HTTPS termination and
  HSTS at the reverse proxy before exposing ToneWatch to untrusted networks.
