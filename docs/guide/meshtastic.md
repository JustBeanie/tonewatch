# Meshtastic

ToneWatch can send a short page summary through a Meshtastic gateway using the
gateway's MQTT JSON downlink. It publishes to `<root>/2/json/mqtt/` with QoS 1
and no retained message.

## Gateway settings

Configure the gateway node with:

- MQTT enabled and connected through Wi-Fi, Ethernet, or Client Proxy.
- JSON enabled (use hardware with JSON support; nRF52 is not supported).
- A channel named exactly `mqtt`, with Downlink enabled. Reboot the node after
  creating the channel.
- The same MQTT broker and root topic configured in ToneWatch.

Channel 0 is the default/public channel and is readable by anyone nearby who
has the channel key. ToneWatch requires `acknowledge_public_channel: true` before
it will use channel 0. Use a private channel index when the message content
needs confidentiality. Licensed amateur-radio operation forbids encryption and
restricts content; follow the rules for your licence, region, and band.

## Example

```yaml
type: meshtastic
id: mesh-gateway
name: Fire mesh
transport: mqtt
host: 127.0.0.1
port: 1883
gateway_node_id: "!9abc1234"
channel_index: 1
destination: broadcast
root_topic: msh/US
template: "TONE {agency_short} {tonesets} {time}"
max_bytes: 200
phases: [pre_alert]
min_interval_s: 30
max_per_hour: 20
timeout_s: 30
```

Meshtastic message times use the target's `timezone` IANA name when set (for
example, `America/Denver`). If it is omitted, ToneWatch uses the `TZ`
environment variable and otherwise UTC. `coalesce_s` controls the short
per-call window used to combine stacked tone detections; it defaults to 3
seconds.

The gateway ID is the `!xxxxxxxx` node ID and is sent in the JSON envelope as
its decimal number. A direct destination may be another `!xxxxxxxx` node ID;
`broadcast` sends to `4294967295`.

Messages are capped at 200 UTF-8 bytes, sanitized, and URL-free. ToneWatch
allows `{agency_short}`, `{agency}`, `{toneset}`, `{tonesets}`, `{time}`,
`{source}`, and `{call_id_short}`. Stacked tone sets are combined into one
pre-alert message. Each target is limited by both the minimum interval and the
hourly maximum; defaults are 30 seconds and 20 messages.
