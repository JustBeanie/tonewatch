# OWASP SAMM baseline

This assessment uses OWASP SAMM v2.0, specifically the official model at
<https://owaspsamm.org/model/> (retrieved 2026-09-10). The 30 rows are the 15
practices and their two streams. Official questions, stream names, and answer
options are vendored from `owaspsamm/core` commit
`f4ed4a13289db54499cb412ec4846ea12e747ac8`; see `model/README.md` for the
CC BY-SA 4.0 licence and source details.

Scores are a repository baseline, not a forecast. Each entry records the
official question and answer option for levels 1–3, plus a rationale. A
non-zero level requires evidence that exists today. Re-assess by updating
`assessment.yaml`, keeping the date and evidence current, then run
`just security-scorecard`.
