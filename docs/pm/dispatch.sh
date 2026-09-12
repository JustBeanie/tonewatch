#!/usr/bin/env bash
# PM dispatcher: runs one Codex engineer on a brief as a goal and streams what it does.
# usage: [MODEL=gpt-5.6-luna|gpt-5.6-terra|gpt-5.6-sol|gpt-6-astra] [EFFORT=medium|high|xhigh] \
#        docs/pm/dispatch.sh <brief-name> [resume-session-id]
#
# Live stream: stdout, and docs/pm/runs/<brief>-<stamp>.log (readable). The raw event
# stream stays in the matching .jsonl. Follow any run from another terminal with:
#   uv run --project backend python docs/pm/watch.py --latest --follow
#
# Parallel runs: WORKTREE=/c/Users/beanie/Documents/Proj/tonewatch-<name> runs the engineer in
# that git worktree (it needs its own .tools/bin copy). PM files (briefs, runs, reports,
# ledger) always live in the main checkout.
set -euo pipefail
BRIEF="$1"; RESUME="${2:-}"; EFFORT="${EFFORT:-medium}"; MODEL="${MODEL:-gpt-5.6-luna}"
ROOT="/c/Users/beanie/Documents/Proj/tonewatch"
WORK="${WORKTREE:-$ROOT}"
# The bin/<hash> directory changes when the Codex app updates; take the newest codex.exe.
CODEX=""
for candidate in /c/Users/beanie/AppData/Local/OpenAI/Codex/bin/*/codex.exe; do
  if [ -z "$CODEX" ] || [ "$candidate" -nt "$CODEX" ]; then CODEX="$candidate"; fi
done
UV="$ROOT/.tools/bin/uv.exe"
export PATH="/c/Program Files/nodejs:$APPDATA/npm:$ROOT/.tools/bin:$PATH"
mkdir -p "$ROOT/docs/pm/runs" "$ROOT/docs/pm/reports"
STAMP=$(date +%Y%m%d-%H%M%S)
RUN="$BRIEF-$STAMP"
LOG="$ROOT/docs/pm/runs/$RUN.jsonl"
READABLE="$ROOT/docs/pm/runs/$RUN.log"
REPORT="$ROOT/docs/pm/reports/$RUN.md"
PROMPT_FILE="$ROOT/docs/pm/runs/$RUN.prompt.md"
if [ -z "$RESUME" ]; then
  {
    echo "/goal Complete docs/pm/briefs/$BRIEF.md for the ToneWatch repo until its Definition of done is fully met; verify with just check before finishing."
    echo
    echo "You are a Codex engineer on the ToneWatch project. Claude is your project manager."
    echo "If the /goal line above was not registered as a goal, create one yourself with that objective."
    echo "Do not stop to ask questions: make reasonable decisions, record them, and keep going until the goal is complete or truly blocked."
    echo "Narrate briefly as you go: before each phase of work, send a one-sentence message saying what you are about to do and why."
    echo "HARD RULES (a violation fails review regardless of results): never edit anything under docs/pm/; never change .pre-commit-config.yaml excludes or otherwise weaken a gate (no skips, deselects, exclusions, widened policies); never delete, truncate or replace files your brief did not ask you to touch; report blockers in your final message instead."
    echo
    cat "$ROOT/docs/pm/briefs/$BRIEF.md"
  } > "$PROMPT_FILE"
else
  {
    echo "Narrate briefly as you go: before each phase of work, send a one-sentence message saying what you are about to do and why."
    echo "HARD RULES (a violation fails review regardless of results): never edit anything under docs/pm/; never change .pre-commit-config.yaml excludes or otherwise weaken a gate (no skips, deselects, exclusions, widened policies); never delete, truncate or replace files your brief did not ask you to touch; report blockers in your final message instead."
    echo
    cat "$ROOT/docs/pm/briefs/$BRIEF.md"
  } > "$PROMPT_FILE"
fi
W="$(cygpath -m "$LOCALAPPDATA/uv")","$(cygpath -m "$APPDATA/uv")","$(cygpath -m "$LOCALAPPDATA/pnpm")","$(cygpath -m "$LOCALAPPDATA/npm-cache")","$(cygpath -m "$APPDATA/npm")","$(cygpath -m "$USERPROFILE/.cache")"
ROOTS="[\"${W//,/\",\"}\"]"
COMMON=( -m "$MODEL" -c "model_reasoning_effort=\"$EFFORT\""
  -c 'sandbox_mode="workspace-write"' -c 'sandbox_workspace_write.network_access=true'
  -c "sandbox_workspace_write.writable_roots=$ROOTS"
  --json -o "$REPORT" )
cd "$WORK"
echo "$RUN" > "$ROOT/docs/pm/runs/CURRENT"
echo "dispatch $RUN model=$MODEL effort=$EFFORT resume=${RESUME:-new} work=$WORK codex=$CODEX"

set +e
: > "$LOG"
if [ -z "$RESUME" ]; then
  "$CODEX" exec -C "$WORK" "${COMMON[@]}" - < "$PROMPT_FILE" > "$LOG" 2>&1 &
else
  "$CODEX" exec resume "$RESUME" "${COMMON[@]}" - < "$PROMPT_FILE" > "$LOG" 2>&1 &
fi
CODEX_PID=$!
# Stream readable events to stdout and the .log until the run is marked done.
"$UV" run --project "$ROOT/backend" python "$ROOT/docs/pm/watch.py" "$LOG" --follow | tee "$READABLE" &
WATCH_PID=$!
wait "$CODEX_PID"
RC=$?
echo "model=$MODEL effort=$EFFORT resume=${RESUME:-new}" >> "$REPORT"
touch "$LOG.done"
wait "$WATCH_PID"
"$UV" run --project "$ROOT/backend" python "$ROOT/docs/pm/ledger.py" || true
set -e
echo "exit=$RC log=$LOG readable=$READABLE report=$REPORT"
