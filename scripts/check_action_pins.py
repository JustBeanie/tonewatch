"""Check SHA-pinned GitHub Actions against their exact version comments."""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ACTION = re.compile(
    r"uses:\s+(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@(?P<sha>[0-9a-f]{40})\s+#\s+(?P<tag>v\d+\.\d+\.\d+)(?:\s|$)"
)
USES = re.compile(r"^\s*-\s+uses:")

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


class OfflineError(Exception):
    """GitHub could not be reached (no network, or no TLS inside a sandbox)."""


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False, timeout=15)


def resolve_tag(repo: str, tag: str, runner: Runner = _run) -> tuple[str, str] | None:
    """Return (commit_sha, tag_object_sha) for a tag, or None when the tag does not exist.

    Lightweight tags point straight at a commit, so both values are that commit. Annotated
    tags list the tag object under refs/tags/<tag> and the commit under refs/tags/<tag>^{}.
    """
    try:
        result = runner(
            [
                "git",
                "ls-remote",
                "--tags",
                f"https://github.com/{repo}.git",
                f"refs/tags/{tag}",
                f"refs/tags/{tag}^{{}}",
            ]
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OfflineError(str(exc)) from exc
    if result.returncode != 0:
        raise OfflineError(result.stderr.strip())
    refs: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if line.strip():
            sha, name = line.split(maxsplit=1)
            refs[name.strip()] = sha
    direct = refs.get(f"refs/tags/{tag}")
    if direct is None:
        return None
    return refs.get(f"refs/tags/{tag}^{{}}", direct), direct


def main(paths: list[str], runner: Runner = _run) -> int:
    """Validate every action pin; skip with a notice only when GitHub is unreachable."""
    references: list[tuple[str, re.Match[str]]] = []
    for raw_path in paths:
        text = Path(raw_path).read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if USES.search(line) and not ACTION.search(line):
                sys.stderr.write(
                    f"{raw_path}:{line_number}: action must use a full SHA and exact # vX.Y.Z tag\n"
                )
                return 1
        references.extend((raw_path, match) for match in ACTION.finditer(text))
    failures: list[str] = []
    for raw_path, match in references:
        repo, sha, tag = match["repo"], match["sha"], match["tag"]
        try:
            resolved = resolve_tag(repo, tag, runner)
        except OfflineError:
            sys.stdout.write(
                "NOTICE: action pin verification skipped: GitHub unreachable (network or TLS).\n"
            )
            return 0
        if resolved is None:
            failures.append(f"{raw_path}: {repo} tag {tag} does not exist")
            continue
        commit, tag_object = resolved
        if sha == commit:
            continue
        if sha == tag_object:
            failures.append(
                f"{raw_path}: {repo}@{sha} is the annotated tag object for {tag}; pin commit {commit}"
            )
        else:
            failures.append(
                f"{raw_path}: {repo}@{sha} is not {tag} (expected commit {commit})"
            )
    for failure in failures:
        sys.stderr.write(f"action pin mismatch: {failure}\n")
    if failures:
        return 1
    sys.stdout.write(f"action pins verified: {len(references)} reference(s)\n")
    return 0


if __name__ == "__main__":
    sys.exit(
        main(
            sys.argv[1:]
            or [".github/workflows/docker.yml", ".github/workflows/release.yml"]
        )
    )
