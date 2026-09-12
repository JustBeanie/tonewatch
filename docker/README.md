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

Published images are pushed to GHCR and signed and attested in the release
workflow. For this private repository, GHCR pushes still work, but GitHub's
public attestation UI may not be available.

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
