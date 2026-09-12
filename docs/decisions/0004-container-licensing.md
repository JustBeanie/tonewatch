# ADR 0004: Container licensing

ToneWatch remains MIT-licensed. Runtime libraries linked into the Python or web
application must comply with the existing dependency policy; strong copyleft
libraries are rejected and LGPL libraries are recorded in
`THIRD_PARTY_NOTICES.md`.

The container includes Debian's `rtl-sdr` executable. It is GPL-2.0, is invoked
as a separate subprocess by ToneWatch, and is not linked into the application.
Its notice is included in `THIRD_PARTY_NOTICES.md`. The policy checker therefore
continues to reject GPL libraries while allowing separately invoked bundled
executables with a recorded notice.
