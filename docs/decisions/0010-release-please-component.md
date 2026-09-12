# ADR 0010: Release Please component branches

## Status

Accepted for release automation.

## Context

The release workflow uses `googleapis/release-please-action` v4.4.0, whose
lockfile resolves the bundled `release-please` dependency to the exact version
`17.1.3`. In that release-please version, `buildRelease` accepts a standalone
release only when
the normalized component in the release branch matches `getBranchComponent()`.

Our single package is configured with component `backend`, but grouped release
PRs from `separate-pull-requests: false` use the branch
`release-please--branches--main`, which has no component. The configured
component therefore never matched and no release was built.

## Decision

Set `separate-pull-requests` to `true`. The backend release PR now uses
`release-please--branches--main--components--backend`, which matches the
configured component and lets release-please build the release. Keep
`include-component-in-tag` false so tags remain `vX.Y.Z` and the release
workflow's tag validation and manifest output continue to work.

The backend package also uses release-please v17.1.3's generic TOML updater for
`backend/uv.lock`, with JSONPath
`$.package[?(@.name == "tonewatch")].version`. The updater evaluates that path
with `jsonpath-plus` and replaces the selected TOML value in place.

## References

- [release-please-action v4.4.0 package metadata](https://github.com/googleapis/release-please-action/blob/v4.4.0/package.json)
- [release-please v17.1.3 release strategy](https://github.com/googleapis/release-please/blob/v17.1.3/src/strategies/base.ts)
- [release-please v17.1.3 generic TOML updater](https://github.com/googleapis/release-please/blob/v17.1.3/src/updaters/generic-toml.ts)
