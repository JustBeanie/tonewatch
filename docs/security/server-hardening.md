# HTTP server hardening

`tonewatch serve` applies the following Uvicorn limits: five seconds of HTTP
keep-alive, a 64 KiB maximum incomplete h11 event, and 100 concurrent
connections. These are application defaults intended to reduce slow-loris and
resource-exhaustion exposure; deployments may add a reverse proxy with stricter
timeouts and TLS.

Stream redirects are disabled at the FFmpeg boundary. Stream URLs are limited
to HTTP(S) and RTSP(S), resolved before opening, and checked against loopback,
link-local, metadata, and encoded numeric addresses. RFC1918 LAN addresses are
allowed by default; set `TONEWATCH_STREAM_BLOCK_PRIVATE=true` to block them.
