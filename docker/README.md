# Docker deployment

The backend serves the bundled web UI on port 8099. Copy a compose example and
set its source configuration in the named `tonewatch-data` volume, then run
`docker compose -f docker/compose.stream.yml up -d` (or the soundcard/rtlsdr
file for that source). Open <http://127.0.0.1:8099/> after startup. Stream input needs no device mapping. Soundcard uses
`/dev/snd`; RTL-SDR uses `/dev/bus/usb` and the host must blacklist
`dvb_usb_rtl28xxu`.

The final image size is enforced below 350,000,000 uncompressed bytes by the
`docker.yml` size job, which prints the exact byte count and `docker history`.
The pre-cleanup diagnostic measured 353,979,998 bytes; its largest layers were
the `/opt/venv` copy at about 218 MB, the Python base at about 48 MB, and the
APT runtime packages at about 9.5 MB. The removed packaging tools are in the
Python base layer; the CI size log is authoritative for the final byte count.

The runtime stage explicitly upgrades the four packages currently flagged by
Trivy in the pinned Debian base image, in the same APT layer before installing
ToneWatch's runtime packages:

```text
apt-get install --only-upgrade --no-install-recommends -y \
  gzip libpcre2-8-0 libsqlite3-0 perl-base
```

This closes fixed Debian security updates that may land in `trixie-security`
before the upstream Python image digest is refreshed. The list is intentionally
next to the Dockerfile command: CI's Trivy `--exit-code 1` remains the guard for
any future finding, which must be investigated and added explicitly if needed.
Once the pinned upstream digest includes these fixes, the explicit upgrade can
be removed and the image should be rebuilt and rescanned.

The builder trims third-party `tests/`, `test/`, `__pycache__/` and numpy C
headers before copying the venv, then strips unneeded symbols from shared
objects. These files are not imported at runtime; the in-image import walk,
container smoke, e2e and DAST checks cover the retained runtime closure.

Published images are pushed to GHCR and signed and attested in the release
workflow only after the locally loaded image passes Trivy at HIGH and CRITICAL
severity with unfixed findings ignored. Release Please opens one release PR per
component; the current repository has one `backend` component, so its release PR
branch includes `components/backend` while tags remain `vX.Y.Z`.

By decision, v0.2.0 was released as a tag and GitHub release without an image.
The v0.3.0 release from current `main` is the first image publication, and its
GHCR package remains private until v1.0.

The compose examples apply a read-only root filesystem, a tmpfs at `/tmp`, all
Linux capabilities dropped, and `no-new-privileges`. Hardware access with
`cap_drop: ALL` and a non-root user in `audio`/`plugdev` is a known caveat and
requires hardware verification; the project does not claim either mapping works
until the PM's HIL checklist records it.

Put HTTPS ingress in a reverse proxy or Home Assistant ingress and keep port
8099 private. Rotate the token with:

```text
docker compose exec tonewatch tonewatch token rotate
```

## Home Assistant add-on mode

The add-on uses the same image and reads `/data/options.json` when
`SUPERVISOR_TOKEN` is present. Its fixed options are:

| Option | Values | Behavior |
| --- | --- | --- |
| `log_level` | `debug`, `info`, `warning`, `error` | Sets structured log verbosity. |
| `public_base_url` | optional `http`/`https` URL | Makes recording links absolute; the trailing slash is normalized. |
| `mqtt_mode` | `supervisor`, `manual`, `off` | Defaults to `supervisor`; `off` disables MQTT at runtime. |
| `ui_password` | optional password | Enables the local UI password. |

Environment variables override add-on options. Unknown option names are ignored
with a warning that lists only the names. In supervisor mode, a first boot with
no MQTT target creates `Home Assistant MQTT` in the editable config. The target
fetches rotated credentials from Supervisor at each MQTT connection; credentials
are never persisted or returned by the API. A direct `public_base_url` must be a
host and port reachable by the consumer. An HA ingress URL requires an HA
session, so it is not suitable for external recording links.

Recordings default to `/media/tonewatch`, where Home Assistant can show them in
Media. The add-on backup hook should run `tonewatch db checkpoint` before a hot
backup; the command waits briefly for a live SQLite writer and reports a bounded
failure if it cannot checkpoint safely.

Audio follows the device-mapping decision in [ADR 0009](../docs/decisions/0009-addon-mode.md):
the add-on must expose a usable host audio device and the operator selects its
ALSA input. PulseAudio routing is not claimed by the image. Real MQTT,
discovery, media, backup, and audio behavior still needs the HIL checks.
