# Raspberry Pi

ToneWatch's Docker image supports arm64. Use a 64-bit Raspberry Pi operating
system with Docker and Docker Compose installed.

## Sound card

The sound card example passes the host audio devices through and grants the
container the `audio` group:

```sh
docker compose -f docker/compose.soundcard.yml up -d
```

The compose file maps `/dev/snd:/dev/snd`. If the host has more than one input,
choose the device and `left`, `right`, or `mix` channel in the Sources page.

## RTL-SDR

Before starting the RTL-SDR example, prevent the kernel DVB driver from
claiming the dongle. Blacklist `dvb_usb_rtl28xxu` on the host, then reboot or
unload the driver according to your distribution's normal procedure.

```sh
docker compose -f docker/compose.rtlsdr.yml up -d
```

The compose file passes `/dev/bus/usb:/dev/bus/usb` through. Configure the
source's `freq_hz`, optional `gain`, `ppm`, and `squelch` values in the UI.

## Access

The example binds port `8099` as `8099:8099`. Keep the host firewall and any
reverse proxy restricted to the networks that need access. The default bind
host inside ToneWatch is `127.0.0.1`; the compose examples are intended for
local access unless you deliberately change the deployment.
