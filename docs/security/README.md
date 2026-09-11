# Security assurance

ToneWatch uses three complementary views:

- OWASP SAMM v2 measures the maturity of the software assurance process across
  five business functions and fifteen practices.
- OWASP DSOMM measures DevSecOps activities across the dimensions and levels in
  the pinned official data model listed in `dsomm/activities.yaml`.
- OWASP ASVS 5.0 Level 2 is the implementation-oriented requirements checklist
  for the API, authentication, WebSocket, file, webhook, and script-hook
  surfaces. It complements rather than replaces SAMM or DSOMM.

To re-assess, update the YAML evidence and status fields, preserve the source
version/SHA, and run `just security-scorecard`. The generator is deterministic.
Evidence is mandatory for every claimed SAMM level above zero and every
implemented DSOMM activity. Repository paths must exist; URLs are accepted as
external evidence links. Planned work is scored as planned/zero and belongs in
`gaps.md` until it exists.
