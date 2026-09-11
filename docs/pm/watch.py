"""Human-readable live stream of a Codex engineer run.

Reads the `codex exec --json` JSONL event stream written by `docs/pm/dispatch.sh`
and prints what the engineer is doing: its messages, each command and its exit
code (with the output tail on failure), file edits, web searches, errors and the
final token usage.

usage:
  uv run --project backend python docs/pm/watch.py --latest --follow
  uv run --project backend python docs/pm/watch.py docs/pm/runs/S2-20260910-221500.jsonl
  ... --brief        only messages, failures, errors and completion (for chat monitors)

In --follow mode it keeps tailing until the dispatcher writes `<log>.done`.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

RUNS = Path(__file__).resolve().parent / "runs"
REPO_PREFIX = re.compile(
    r"[A-Za-z]:\\\\?Users\\\\?[^\\]+\\\\?Documents\\\\?Proj\\\\?tonewatch\\\\?"
)
PATH_PREFIX = re.compile(r'^set\s+\\?"PATH=[^"]*\\?"\s*&&\s*')
SHELL_WRAPPER = re.compile(
    r'^"?[A-Za-z]:\\\\?WINDOWS\\\\?system32\\\\?(?:cmd\.exe"?\s+/c|WindowsPowerShell\\\\?v1\.0\\\\?powershell\.exe"?\s+-Command)\s+',
    re.IGNORECASE,
)
PS_PATH_PREFIX = re.compile(r"""^['"]?\$env:PATH\s*=\s*.*?\$env:PATH"?;\s*""")


def stamp() -> str:
    return datetime.now().astimezone().strftime("%H:%M:%S")


def clean_command(command: str) -> str:
    """Strip the cmd.exe wrapper, quoting and the sandbox PATH prefix."""
    text = SHELL_WRAPPER.sub("", command.strip())
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1]
    text = text.replace('\\"', '"').replace("\\\\", "\\")
    text = PATH_PREFIX.sub("", text)
    text = PS_PATH_PREFIX.sub("", text)
    return REPO_PREFIX.sub("", text)


def short(text: str, limit: int) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1] + "…"


class Renderer:
    def __init__(self, *, brief: bool) -> None:
        self.brief = brief
        self.commands = 0
        self.failed = 0
        self.edits = 0

    def emit(self, marker: str, text: str) -> None:
        sys.stdout.write(f"{stamp()} {marker} {text}\n")
        sys.stdout.flush()

    def raw(self, line: str) -> None:
        if "ERROR" in line or "error" in line.lower():
            self.emit("!!", short(line, 300))

    def event(self, ev: dict[str, Any]) -> None:
        kind = ev.get("type")
        item = ev.get("item") or {}
        itype = item.get("type")
        if kind == "thread.started":
            self.emit("==", f"thread {ev.get('thread_id')}")
        elif kind == "turn.started" and not self.brief:
            self.emit("==", "turn started")
        elif kind == "item.completed" and itype == "agent_message":
            self.emit("💬", short(item.get("text", ""), 600 if self.brief else 1200))
        elif kind == "item.started" and itype == "command_execution" and not self.brief:
            self.emit("▶ ", short(clean_command(item.get("command", "")), 220))
        elif kind == "item.completed" and itype == "command_execution":
            self.commands += 1
            code = item.get("exit_code")
            cmd = short(clean_command(item.get("command", "")), 160)
            if code in (0, None):
                if not self.brief:
                    self.emit("  ✓", cmd)
            else:
                self.failed += 1
                tail = [
                    ln
                    for ln in (item.get("aggregated_output") or "").splitlines()
                    if ln.strip()
                ]
                self.emit(f"  ✗ exit {code}", cmd)
                for ln in tail[-4:]:
                    sys.stdout.write(f"             │ {short(ln, 200)}\n")
        elif kind == "item.completed" and itype == "file_change":
            changes = item.get("changes") or []
            self.edits += len(changes)
            if not self.brief:
                paths = ", ".join(
                    f"{c.get('kind', '?')}:{REPO_PREFIX.sub('', c.get('path', ''))}"
                    for c in changes
                )
                self.emit("✎ ", short(paths, 300))
        elif kind == "item.completed" and itype == "web_search" and not self.brief:
            queries = (item.get("action") or {}).get("queries") or [
                item.get("query", "")
            ]
            self.emit("🔎", short("; ".join(q for q in queries if q), 200))
        elif kind in {"error", "turn.failed"}:
            self.emit("!!", short(json.dumps(ev), 400))
        elif kind == "turn.completed":
            u = ev.get("usage") or {}
            uncached = u.get("input_tokens", 0) - u.get("cached_input_tokens", 0)
            self.emit(
                "==",
                f"turn completed: {self.commands} commands ({self.failed} failed), "
                f"{self.edits} file edits, uncached in {uncached / 1e3:.1f}k, "
                f"out {u.get('output_tokens', 0) / 1e3:.1f}k "
                f"(reasoning {u.get('reasoning_output_tokens', 0) / 1e3:.1f}k)",
            )

    def line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            self.raw(line)
            return
        if isinstance(ev, dict):
            self.event(ev)


def latest_log() -> Path:
    logs = sorted(RUNS.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not logs:
        sys.exit("no runs in docs/pm/runs")
    return logs[-1]


def main() -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("log", nargs="?", type=Path)
    parser.add_argument("--latest", action="store_true", help="use the most recent run")
    parser.add_argument(
        "--follow", action="store_true", help="keep tailing until the run is done"
    )
    parser.add_argument(
        "--brief", action="store_true", help="messages, failures and completion only"
    )
    args = parser.parse_args()

    log = latest_log() if args.latest or args.log is None else args.log
    done_marker = log.with_suffix(log.suffix + ".done")
    report = RUNS.parent / "reports" / f"{log.stem}.md"

    def finished() -> bool:
        # The dispatcher appends a `model=...` trailer to the report once codex exits.
        return done_marker.exists() or (
            report.exists()
            and "model=" in report.read_text(encoding="utf-8", errors="replace")
        )

    renderer = Renderer(brief=args.brief)
    sys.stdout.write(f"{stamp()} == watching {log.name}\n")

    while args.follow and not log.exists():
        time.sleep(0.5)
    with log.open(encoding="utf-8", errors="replace") as fh:
        buffer = ""
        while True:
            chunk = fh.readline()
            if chunk:
                buffer += chunk
                if buffer.endswith("\n"):
                    renderer.line(buffer)
                    buffer = ""
                continue
            if not args.follow or finished():
                if buffer:
                    renderer.line(buffer)
                break
            time.sleep(0.5)
    sys.stdout.write(f"{stamp()} == end of {log.name}\n")


if __name__ == "__main__":
    main()
