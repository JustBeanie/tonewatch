# Home Assistant recipes

The MQTT path works with a Docker or Raspberry Pi deployment. Configure an
MQTT alert target with `ha_discovery: true`; the default MQTT broker is
`localhost` and the default topic prefix is `tonewatch`. In add-on mode,
`mqtt_mode: supervisor` uses Supervisor-provided broker credentials.

## MQTT discovery

ToneWatch publishes retained Home Assistant discovery payloads under the
`homeassistant` MQTT prefix. It creates a device for the instance, an event
entity for each enabled tone set, a last-call sensor, a call-active binary
sensor, and a feed-health binary sensor for each source.

The availability topic is:

```text
tonewatch/<instance_id>/availability
```

Call payloads are published to:

```text
tonewatch/<instance_id>/call
```

The event entity reports `pre_alert` and `recording_ready`. If the alert target
includes the opt-in `tone_discovered` event, discovery events use
`tonewatch/<instance_id>/discovered`. Feed health uses
`tonewatch/<instance_id>/health/<source_id>` with `online` or `offline`.

## Recording URLs

When a call has a saved recording, its call detail API includes an authenticated
URL such as `/api/recordings/<recording_id>`. The call notification payload
uses `recording_url` when a public base URL is configured. MQTT carries the URL;
it does not carry the audio bytes. Keep the URL reachable by Home Assistant and
protect it with the normal ToneWatch authentication and network controls.

Set `TONEWATCH_PUBLIC_BASE_URL` to the URL that Home Assistant can reach when
you need a full URL in the MQTT payload. Without it, the payload marks the
relative recording URL with `recording_path_relative: true`.

## Play a recording on a media player

For the current MQTT path, an automation can pass the full URL from a
`recording_ready` message to a media player. Replace the instance name, topic,
and player entity with your values:

```yaml
alias: Play a ToneWatch recording
trigger:
  - platform: mqtt
    topic: tonewatch/my-instance/call
condition:
  - condition: template
    value_template: "{{ trigger.payload_json.phase == 'recording_ready' }}"
  - condition: template
    value_template: "{{ trigger.payload_json.recording_url is string and trigger.payload_json.recording_url != '' }}"
action:
  - service: media_player.play_media
    target:
      entity_id: media_player.your_player
    data:
      media_content_id: "{{ trigger.payload_json.recording_url }}"
      media_content_type: audio/mpeg
mode: queued
```

The default recording format is MP3, so the example uses `audio/mpeg`. Change
the media type if you configure Opus output and your player supports it.

With the future custom Home Assistant integration, recordings will be exposed
through Home Assistant's media source and a media-player automation can play
the selected recording. That integration is **coming soon**.

Until then, use the authenticated recording URL in a notification or a
Home Assistant action that can fetch a URL, for example by passing the URL from
the MQTT call payload to the action's media content field. The exact action
depends on the media player and its network access to ToneWatch. The add-on's
future `/media/tonewatch/` mapping will also make recordings available in
Home Assistant's Media browser once the add-on is published.
