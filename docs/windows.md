# Windows installation

Download the `tonewatch-windows` zip from the workflow artifact, extract it to
a directory such as `C:\Program Files\ToneWatch`, and run
`tonewatch.exe --version` from that directory. The onedir folder must stay
intact because it contains the bundled web UI, PortAudio, FFmpeg, and Python
runtime files.

When the frozen executable starts without `TONEWATCH_DATA_DIR`, it stores its
configuration, API token, SQLite database, recordings, and logs in
`%PROGRAMDATA%\tonewatch`. Set `TONEWATCH_DATA_DIR` to choose another directory.

The service commands are:

```text
tonewatch.exe service install
tonewatch.exe service start
tonewatch.exe service status
tonewatch.exe service stop
tonewatch.exe service uninstall
```

Use `tonewatch.exe token show` and `tonewatch.exe token rotate` to inspect or
replace the API token. The default bind host is `127.0.0.1`; set
`TONEWATCH_BIND_HOST` deliberately before opening the service through a
firewall. If the bind host is changed to a network interface, allow TCP 8099
only from the networks that need it.

On Windows, PyAV's FFmpeg uses schannel. It ignores the `ca_file` option and
uses the Windows certificate store for TLS verification, so public-CA HTTPS
feeds need a trusted Windows certificate. The product still supplies
`tls_verify=1` and `ca_file` for cross-platform consistency.

To uninstall, stop the service, run `tonewatch.exe service uninstall`, and
remove the extracted application directory and `%PROGRAMDATA%\tonewatch` after
preserving any recordings you need.

## Known issues

The bundled sounddevice 0.5.6 callback path is covered by a fake-stream unit
test. A future NumPy removal of the `ndarray.shape` setter remains a hardware
in-the-loop item because the deprecation originates inside sounddevice and is
not reachable without exercising its native PortAudio callback.
