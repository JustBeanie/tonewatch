# ADR 0003: Dependency update ownership

## Status

Accepted for S2.

## Decision

Renovate is the only automated dependency updater. Dependabot remains enabled
for security alerts, but version-update and security-update jobs are not used:
Dependabot's current pnpm 11 resolver is incompatible with this repository's
pnpm 10 lockfile. The project stays on pnpm 10 until a dedicated upgrade task
updates `packageManager`, the lockfile, and the `.tools` provisioning note
together.

The existing web lockfile resolves the reported `js-yaml` and `markdown-it`
alerts to maintained major versions. The PM must verify the seven alert records
are closed with `gh api repos/JustBeanie/tonewatch/dependabot/alerts` after the
next push.
