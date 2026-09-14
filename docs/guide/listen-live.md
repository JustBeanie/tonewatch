# Listen live

Live restreaming is disabled by default. Enable `live_stream.enabled` in the
ToneWatch configuration, keep the source's `live_stream_enabled` switch on,
and reload the configuration. The server encodes normalized source audio as a
short-lived MP3 stream. Listener and bitrate caps are intentionally bounded.

Create a URL with an authenticated `POST /api/sources/{id}/live-url` request.
The response contains `url` and `expires_at`; use the URL as-is in a browser or
audio player. Add `external=true` when the URL must be built from the configured
`public_base_url` for a player outside the web ingress. The URL contains a
signed token, so treat it like a temporary credential and do not paste it into
shared tickets, dashboards, or permanent history.

For Home Assistant, obtain a fresh URL from the API and pass it to the target
player:

```yaml
action: media_player.play_media
target:
  entity_id: media_player.kitchen
data:
  media_content_id: "https://tonewatch.example/api/sources/scanner/live.mp3?t=..."
  media_content_type: audio/mpeg
```

URLs expire, are scoped to one source, and are invalidated when the live-stream
secret is rotated. Generate a new URL for each playback session. HTTP Range
requests are not supported and responses are marked `no-store`.

Radio rebroadcasting may be regulated by local, state, or national law and by
the terms of the source service. You are responsible for obtaining permission
and complying with applicable privacy, copyright, emergency-communications,
and rebroadcast rules.
