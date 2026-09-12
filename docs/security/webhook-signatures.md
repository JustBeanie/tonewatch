# Webhook signature verification

ToneWatch sends `X-ToneWatch-Timestamp` as Unix seconds and
`X-ToneWatch-Signature: sha256=<hex>`. Verify the exact request body with
HMAC-SHA256 over `timestamp + "." + body`, using the per-target secret.

Receivers should compare the supplied digest with a constant-time comparison
such as `hmac.compare_digest`, and reject timestamps outside a five-minute
window. The timestamp window prevents replay; the HMAC protects both the
timestamp and body from tampering.

Alert payloads expose recordings only through the authenticated
`/api/recordings/{id}` `recording_url`. The server filesystem `recording_path`
is never included in webhook, MQTT, or Home Assistant payload fields. It is
retained only as internal state for optional local script target argument
substitution (`{recording_path}`).
