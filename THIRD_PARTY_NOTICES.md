# Third-party notices

ToneWatch is distributed under the MIT License. Python and web dependencies
retain their upstream licenses. CI rejects GPL and AGPL libraries linked into
the application.

PyAV wheels bundle FFmpeg components under the LGPL. This is permitted here
because the FFmpeg library is dynamically linked by the wheel; the LGPL notice
must remain with any redistributed wheel or image.

The zeroconf package is licensed LGPL-2.1-or-later and is used as a Python
library for mDNS discovery; its license and notices must remain with any
redistributed installation.

The container includes Debian's `rtl-sdr` executable under GPL-2.0. ToneWatch
invokes it as a separate subprocess and does not link it into the application;
the GPL-2.0 notice is included with the Debian package and must remain with any
redistributed image.

The Windows build includes `pywin32`, licensed under the Python Software
Foundation License (PSF-2.0), for the native Windows service wrapper.

The complete dependency inventories are generated in CI by `pip-licenses` and
`license-checker`.
