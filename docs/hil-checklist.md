# ToneWatch hardware-in-the-loop checklist

Run this checklist on the target hardware after the container image or native
build changes. Each result line is intentionally left for the operator; CI and
local tests do not claim these hardware results.

## Docker sound card

Steps:

1. Connect a supported ALSA sound card and confirm the host exposes `/dev/snd`.
2. Review `docker/compose.soundcard.yml` and run `docker compose -f docker/compose.soundcard.yml up -d`.
3. Confirm the service is healthy with `docker compose -f docker/compose.soundcard.yml ps`.
4. Open the UI, select the mapped sound card, and play a known test tone.
5. Key a signal generator or scanner with a configured two-tone page followed by
   voice, and note when the final tone reaches its `min_s`.
6. Inspect the container with `docker inspect` and confirm `ReadonlyRootfs` is
   true, `CapDrop` contains `ALL`, and `no-new-privileges:true` is present.

Expected results: the service reaches healthy, the sound card is selectable,
the test tone produces a live level, the pre-alert arrives less than 1 s after
the final tone reaches `min_s`, the recording contains the voice with the tones
trimmed, and the hardened container remains usable.

Result: [ ]

## Docker RTL-SDR

Steps:

1. Connect the RTL-SDR and confirm the host exposes it under `/dev/bus/usb`.
2. If required by the host, blacklist `dvb_usb_rtl28xxu` so `rtl_fm` can claim
   the dongle.
3. Review `docker/compose.rtlsdr.yml` and run `docker compose -f docker/compose.rtlsdr.yml up -d`.
4. Configure a known local frequency and verify the channel starts.
5. Confirm the same read-only root, dropped capabilities, no-new-privileges,
   tmpfs and healthcheck settings remain active.

Expected results: the service reaches healthy, `rtl_fm` opens the mapped dongle,
audio levels update, and the hardening flags do not prevent device access.

Result: [ ]

## Home Assistant add-on

Steps:

1. Install the ToneWatch add-on build in Home Assistant and start it with the
   documented data and media mappings.
2. Confirm the add-on log reports a healthy app and that Supervisor discovery
   completes without exposing the API token.
3. Open the add-on through ingress and verify the dashboard loads.
4. Confirm the add-on container uses a read-only root, drops all capabilities,
   enables no-new-privileges and provides a writable `/tmp` tmpfs.
5. With `mqtt_mode: supervisor`, confirm the target obtains MQTT credentials
   through Supervisor and that a reconnect uses rotated credentials; inspect
   logs and the UI/API for the absence of credential values.
6. Confirm MQTT discovery creates the ToneWatch entities and that the M11
   integration auto-discovers the add-on when it is installed.
7. Trigger a recording and confirm it appears under **Media → tonewatch** and
   that its alert payload uses the documented absolute or relative URL behavior.
8. Run `tonewatch db checkpoint` during an active call and confirm the hot
   backup completes without stopping the paging monitor.
9. Follow [ADR 0009](decisions/0009-addon-mode.md)'s device-mapping decision:
   verify the exposed ALSA input is selectable and capture a real page. Do not
   treat PulseAudio visibility as verified unless the add-on mapping provides it.

Expected results: the add-on starts, ingress loads the UI, Supervisor discovery
works, MQTT credentials are rotated without disclosure, discovery and the M11
integration find the device, recordings appear in Media → tonewatch, hot backup
does not stop monitoring, the mapped audio input captures a page, and the
hardening contract is visible in the add-on inspection output. These results are
`PENDING-HIL` until run on a real Home Assistant host.

Result: [ ]

## Windows build

Steps:

1. Run the Windows build workflow artifact or build the documented PyInstaller
   package on a supported Windows host.
2. Run `tonewatch --version`, `tonewatch devices`, and `tonewatch analyze` on a
   fixture WAV.
3. Connect a sound card and repeat the device and live-level checks.
4. Record the installed sounddevice and NumPy versions for the release notes.

Expected results: the executable starts, lists devices, analyzes the fixture,
and the sound card path produces audio without a callback warning or crash.

Result: [ ]

## Stream reconnect

Steps:

1. Configure a local test stream that produces a known audio signal.
2. Confirm the channel detects audio and records a call.
3. Stop the stream server for longer than one reconnect interval, then start it
   again.
4. Watch the channel status and logs through the reconnect sequence.

Expected results: the channel reports the disconnect, retries with backoff,
reconnects without a process restart, and resumes detection with monotonic
timestamps.

Result: [ ]

## Feed-health sensor

Steps:

1. Start a healthy sound card or stream channel and verify the feed-health value
   in the UI and Home Assistant entity.
2. Remove or stop the input and wait for the documented no-data threshold.
3. Restore the input and observe the recovery transition.

Expected results: the sensor reports healthy while frames arrive, changes to the
documented unavailable or unhealthy state after the bounded threshold, and
returns to healthy after input resumes without repeated transition spam.

Result: [ ]
