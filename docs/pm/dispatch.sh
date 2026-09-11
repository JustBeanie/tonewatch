#!/usr/bin/env bash
# PM dispatcher: runs one Codex engineer on a brief as a goal.
# usage: docs/pm/dispatch.sh <brief-name> [resume-session-id]
set -euo pipefail
BRIEF="$1"; RESUME="${2:-}"
ROOT="/c/Users/beanie/Documents/Proj/tonewatch"
CODEX="/c/Users/beanie/AppData/Local/OpenAI/Codex/bin/7ac07f4ce733f89a/codex.exe"
export PATH="/c/Program Files/nodejs:$APPDATA/npm:$LOCALAPPDATA/Microsoft/WinGet/Packages/Casey.Just_Microsoft.Winget.Source_8wekyb3d8bbwe:$PATH"
mkdir -p "$ROOT/docs/pm/runs" "$ROOT/docs/pm/reports"
STAMP=$(date +%Y%m%d-%H%M%S)
LOG="$ROOT/docs/pm/runs/$BRIEF-$STAMP.jsonl"
REPORT="$ROOT/docs/pm/reports/$BRIEF-$STAMP.md"
PROMPT_FILE="$ROOT/docs/pm/runs/$BRIEF-$STAMP.prompt.md"
if [ -z "$RESUME" ]; then
  {
    echo "/goal Complete docs/pm/briefs/$BRIEF.md for the ToneWatch repo until its Definition of done is fully met; verify with just check before finishing."
    echo
    echo "You are a Codex engineer on the ToneWatch project. Claude is your project manager."
    echo "If the /goal line above was not registered as a goal, create one yourself with that objective."
    echo "Do not stop to ask questions: make reasonable decisions, record them, and keep going until the goal is complete or truly blocked."
    echo
    cat "$ROOT/docs/pm/briefs/$BRIEF.md"
  } > "$PROMPT_FILE"
else
  cp "$ROOT/docs/pm/briefs/$BRIEF.md" "$PROMPT_FILE"
fi
W="$(cygpath -m "$LOCALAPPDATA/uv")","$(cygpath -m "$APPDATA/uv")","$(cygpath -m "$LOCALAPPDATA/pnpm")","$(cygpath -m "$LOCALAPPDATA/npm-cache")","$(cygpath -m "$APPDATA/npm")","$(cygpath -m "$USERPROFILE/.cache")"
ROOTS="[\"${W//,/\",\"}\"]"
COMMON=( -m gpt-5.6-luna -c 'model_reasoning_effort="medium"'
  -c 'sandbox_mode="workspace-write"' -c 'sandbox_workspace_write.network_access=true'
  -c "sandbox_workspace_write.writable_roots=$ROOTS"
  --json -o "$REPORT" )
cd "$ROOT"
set +e
if [ -z "$RESUME" ]; then
  "$CODEX" exec -C "$ROOT" "${COMMON[@]}" - < "$PROMPT_FILE" > "$LOG" 2>&1
else
  "$CODEX" exec resume "$RESUME" "${COMMON[@]}" - < "$PROMPT_FILE" > "$LOG" 2>&1
fi
RC=$?
set -e
echo "exit=$RC log=$LOG report=$REPORT"
