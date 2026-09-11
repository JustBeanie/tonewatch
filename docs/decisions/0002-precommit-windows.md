# ADR 0002: Windows pre-commit compatibility

## Status

Accepted for M0.

## Decision

Portable Python/Node hooks run locally on Windows. ShellCheck uses the
wheel-distributed `shellcheck-py` package; the other local hook tools are
resolved by uv or pnpm. `actionlint`, `hadolint`, and `gitleaks` are declared
as manual/CI-only hooks because Windows-compatible variants are not provisioned
in this bootstrap environment. They are intentionally skipped by the default
`pre-commit` stage and must be run in CI or explicitly with `--hook-stage
manual`; this is the documented skip, rather than a silent omission.

In the PM local-mode worktree, file-scoped hooks also report `no files to
check` for newly created untracked files because pre-commit's `--all-files`
enumerates tracked files. The equivalent checks are covered by `just check`;
the hooks will run normally once the PM commits the bootstrap files.
