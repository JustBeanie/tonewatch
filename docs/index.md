# ToneWatch

ToneWatch listens to radio audio, detects configured tone sequences, records the
dispatch that follows, and sends notifications through MQTT, webhooks, or an
optional local script. It can use a sound card, a network stream, an RTL-SDR
source, or a WAV file.

ToneWatch is a supplemental notification tool, not a certified primary alerting
system. Recording or rebroadcasting radio traffic may be regulated where you
live; you are responsible for complying with the rules that apply to you.

## Choose a path

- [Install with Docker](install/docker.md), or use the [Raspberry Pi guide](install/raspberry-pi.md).
- [Install the native Windows build](windows.md).
- [Find tone frequencies](guide/finding-frequencies.md) and create a tone set.
- [Tune detection](guide/tuning.md) when pages are missed or false positives occur.
- [Troubleshoot a recording](guide/troubleshooting.md) with the analyzer.
- [Import a `tones.cfg` file](guide/importing-tones-cfg.md).
- [Connect Home Assistant](guide/home-assistant.md). The add-on is [coming soon](install/home-assistant-addon.md).
