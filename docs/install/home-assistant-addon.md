# Home Assistant add-on

**Coming soon:** the ToneWatch Home Assistant add-on is planned but is not
published yet. Do not expect an add-on repository or an installable add-on at
this stage.

When the add-on is available, it will use the same application image and
Supervisor options. In add-on mode, recordings are written to
`/media/tonewatch/`, MQTT credentials can come from Supervisor, and zeroconf is
disabled. The add-on path will be documented here after it is published and
verified on a real Home Assistant installation.

For a current Home Assistant setup, run the Docker image and follow the
[Home Assistant recipes](../guide/home-assistant.md). The custom Home Assistant
integration is also **coming soon**; the MQTT discovery path is the available
integration surface today.
