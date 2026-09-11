# PM review: M0 is not done. Fix these issues and re-verify.

I reviewed your M0 work and ran it outside the sandbox. The scaffold is good, but the Definition of done was **not** met, and several defects surfaced only once Python actually ran. Tools are now provisioned. Re-read the new **Tooling inside the Codex sandbox** section at the end of `AGENTS.md` and use its PATH prefix for every command.

## Findings, all required
1. **`backend/pyproject.toml`: `readme = "../README.md"` breaks the build.** Hatchling rejects readme paths outside the project, so every `uv run` fails: `ValueError: Readme path must be within the project directory`. Fix: add `backend/README.md` (a short pointer to the root README) and reference that.
2. **`justfile` `windows-shell`: `pnpm.ps1` is blocked by the PowerShell execution policy.** Add `-ExecutionPolicy Bypass` to the windows-shell args. This is process-scoped only; do not change any system policy.
3. **`just setup`: `uv python install 3.13` errors on this machine** ("Missing expected target directory for Python minor version link"), although 3.13.13 is installed. Remove that line. Set `requires-python = ">=3.13,<3.14"` and let `uv sync` resolve the interpreter, or add a `.python-version` file.
4. **`just lint` does not check Python formatting.** Add `ruff format --check`. Confirm `pnpm --dir web format` runs Prettier in `--check` mode, not `--write`.
5. **`docs/PROGRESS.md`:**
   - You ticked M0.1–M0.6 while `just setup` and `just check` had never run. Untick anything that isn't verified.
   - Restore each task's original description text from `PLAN.md`, because your edits truncated them.
   - Leave the `— <PR link> — note` format as specified, using `local` in place of the PR link.
6. **Global installs.** You ran `npm install -g uv` (an unrelated npm package) and `just-install`, and tried to curl uv into `%LOCALAPPDATA%\uv`. The PM has already uninstalled these. Don't repeat it; see `AGENTS.md`.
7. **Run the M0.6 spike for real now.** Record the actual PyAV MP3/Opus encode results in ADR 0001, with the PyAV version and FFmpeg build info.
8. **GitHub Actions SHA pinning.** You have network access. Try again to resolve each action tag to its commit SHA with `git ls-remote https://github.com/<owner>/<repo> refs/tags/<tag>`, handling annotated tags via `^{}`. Keep `# TODO(pin-sha)` only where that genuinely fails.

## Definition of done (unchanged, now actually run)
- `just setup` exits 0.
- `just check` exits 0.
- `uv run --project backend pre-commit run --all-files` exits 0, with any skips explained in ADR 0002.
- Your final message pastes the tail of each of those three command outputs as evidence.
