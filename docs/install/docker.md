# Docker

Docker is the primary deployment path. The published image is
`ghcr.io/justbeanie/tonewatch:latest`; the example compose files expose the UI
on port `8099` and store application data in the `tonewatch-data` volume.

The image is built for amd64 and arm64. This page covers an amd64 host; for a
Raspberry Pi, use the [Pi guide](raspberry-pi.md).

## Stream input

For a network stream, copy the example and edit the ToneWatch source in the UI
after the container starts:

```sh
docker compose -f docker/compose.stream.yml up -d
```

Open `http://127.0.0.1:8099`, sign in with the token created in the data
directory, and add a stream source. Stream URLs must use `http`, `https`,
`rtsp`, or `rtsps`.

## Sound card input

Use the sound card compose file when the host audio device should be passed to
the container:

```sh
docker compose -f docker/compose.soundcard.yml up -d
```

The file passes `/dev/snd` through and adds the container to the `audio` group.
The host must expose a usable ALSA device.

## Updating and data

The compose examples use `restart: unless-stopped`, a read-only container root,
an in-memory `/tmp`, dropped Linux capabilities, and `no-new-privileges`.
Configuration, the SQLite database, logs, and recordings live in the named
`tonewatch-data` volume. Back up that volume before replacing it or using the
`replace` option in an import.
