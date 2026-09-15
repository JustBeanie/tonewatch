# ADR 0012: Meshtastic notification transport

## Status

Accepted for M18a: MQTT JSON downlink only.

## Verified protocol

The official Meshtastic MQTT integration documentation (accessed 2026-09-12)
defines the default root as `msh/REGION`, with the region substituted by the
node's LoRa region. The JSON downlink command is published to:

`<root>/2/json/mqtt/`

For example, the US default is `msh/US/2/json/mqtt/`. A gateway may also accept
the gateway node ID as a further topic suffix; ToneWatch uses the documented
base topic so broker ACLs and gateway subscriptions remain compatible.

The gateway must have MQTT enabled, JSON enabled, and a channel literally named
`mqtt` with Downlink enabled. The documentation says to reboot after creating
that channel. The MQTT module also needs network connectivity, either directly
through Wi-Fi/Ethernet or through Client Proxy. Channel 0 is the primary/default
channel; ToneWatch requires an explicit acknowledgement before using it because
the default public channel is readable by nearby listeners.

The JSON envelope for `sendtext` is:

```json
{"from": 2651457304, "to": 4294967295, "channel": 1,
 "type": "sendtext", "payload": "TONE FIRE 12:34"}
```

`from`, `to`, and `channel` are decimal integers; `type` is the string
`sendtext`; and `payload` is the text string. The official page calls `from`
and `payload` required, makes `to` optional for direct messages, and makes
`channel` optional (0–7). ToneWatch sends all five fields, representing a
broadcast destination as `0xFFFFFFFF` (4294967295). The official user message
limits page specifies 200 bytes for text messages; this is ToneWatch's hard
limit and is enforced after UTF-8-safe truncation.

Sources:

- [Meshtastic MQTT integration](https://meshtastic.org/docs/software/integrations/mqtt/),
  current documentation, including topic shape, JSON envelope, channel setup,
  unsigned IDs from firmware 2.2.0 onward, and the pre-2.2.20 `sender` change.
- [Meshtastic message limits](https://meshtastic.org/docs/software/android/user/messages-and-channels.md),
  current documentation, 200-byte maximum.
- [Meshtastic firmware MQTT source](https://github.com/meshtastic/firmware/blob/develop/src/mqtt/MQTT.cpp),
  `develop` source inspected 2026-09-12, showing per-channel downlink
  subscriptions at QoS 1 and current MQTT root/topic construction. JSON is
  unsupported on nRF52 hardware, so gateway hardware must support JSON.

Compatibility history recorded by the official documentation: firmware before
2.2.0 represented JSON node IDs as signed values; 2.2.0 and newer use unsigned
values. Firmware before 2.2.20 required a `sender` field; it is no longer
required. Firmware before 2.3.0 used `/c/` for the raw protobuf topic instead
of `/e/`; this does not change the JSON downlink path. The current documentation
still documents JSON downlink, while current firmware source continues to
subscribe to per-channel downlink topics. nRF52 remains unsupported.

## Alternatives

The TCP API on port 4403 and serial API can send a message through a connected
radio, but both require a physical or network-connected radio interface and a
Meshtastic protocol client. They do not provide the broker-only topology this
target needs. The Python Meshtastic client and generated protobufs are GPL-3.0,
while ToneWatch is Apache-2.0. We therefore do not link, vendor, or ship those
components. Shipping them in the image would create a copyleft licensing review
and distribution obligation; MQTT JSON with the existing aiomqtt dependency
keeps ToneWatch's implementation independent. A future TCP or serial target
would need a separate licensing and protocol review.
