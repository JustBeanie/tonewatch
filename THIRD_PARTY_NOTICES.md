# Third-party notices

ToneWatch is distributed under the MIT License. Python and web dependencies
retain their upstream licenses; CI rejects GPL and AGPL dependencies in the
distribution.

PyAV wheels bundle FFmpeg components under the LGPL. This is permitted here
because the FFmpeg library is dynamically linked by the wheel; the LGPL notice
must remain with any redistributed wheel or image.

The zeroconf package is licensed LGPL-2.1-or-later and is used as a Python
library for mDNS discovery; its license and notices must remain with any
redistributed installation.

The complete dependency inventories are generated in CI by `pip-licenses` and
`license-checker`.
