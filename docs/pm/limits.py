"""Print the Codex (ChatGPT) account rate limits the PM schedules engineers against.

Uses the Codex CLI's first-party app-server protocol over stdio: ``initialize`` then the
read-only ``account/rateLimits/read`` request. It never calls the reset-credit consume
method and never reads auth files.

Usage: uv run --no-project python docs/pm/limits.py [--json]
"""

from __future__ import annotations

import glob
import json
import os
import queue
import subprocess
import sys
import threading
from datetime import UTC, datetime
from typing import Any

TIMEOUT_S = 60


def find_codex() -> str:
    """Return the Codex CLI path: $CODEX, else the newest bundled desktop-app binary."""
    explicit = os.environ.get("CODEX")
    if explicit:
        return explicit
    local = os.environ.get("LOCALAPPDATA", "")
    pattern = os.path.join(local, "OpenAI", "Codex", "bin", "*", "codex.exe")
    candidates = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    if not candidates:
        raise SystemExit("codex.exe not found; set CODEX=/path/to/codex")
    return candidates[0]


def rpc_read_limits(codex: str) -> dict[str, Any]:
    """Run app-server just long enough to read the account rate limits."""
    proc = subprocess.Popen(
        [codex, "app-server", "-c", "mcp_servers={}"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    lines: queue.Queue[str] = queue.Queue()
    threading.Thread(
        target=lambda: [lines.put(line) for line in proc.stdout], daemon=True
    ).start()

    def send(message: dict[str, Any]) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    def wait_for(request_id: int) -> dict[str, Any]:
        deadline = datetime.now(UTC).timestamp() + TIMEOUT_S
        while True:
            remaining = deadline - datetime.now(UTC).timestamp()
            if remaining <= 0:
                raise SystemExit(
                    f"timed out waiting for app-server response {request_id}"
                )
            try:
                line = lines.get(timeout=remaining)
            except queue.Empty as exc:
                raise SystemExit(
                    f"timed out waiting for app-server response {request_id}"
                ) from exc
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == request_id:
                if "error" in message:
                    raise SystemExit(f"app-server error: {message['error']}")
                return message.get("result") or {}

    try:
        send(
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "tonewatch-pm-limits", "version": "1"}
                },
            }
        )
        wait_for(1)
        send({"method": "initialized"})
        send({"id": 2, "method": "account/rateLimits/read", "params": None})
        return wait_for(2)
    finally:
        proc.kill()
        proc.wait(timeout=10)


def snapshots(node: Any) -> list[dict[str, Any]]:
    """Collect every RateLimitSnapshot-shaped object (has primary/secondary windows)."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if "primary" in node or "secondary" in node:
            found.append(node)
        for value in node.values():
            found.extend(snapshots(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(snapshots(value))
    return found


def describe_window(label: str, window: dict[str, Any] | None) -> str:
    if not window:
        return f"  {label}: n/a"
    minutes = window.get("windowDurationMins")
    span = (
        f"{minutes // 60} h"
        if isinstance(minutes, int) and minutes < 24 * 60
        else (f"{minutes // (24 * 60)} d" if isinstance(minutes, int) else "?")
    )
    resets = window.get("resetsAt")
    when = (
        datetime.fromtimestamp(resets, UTC)
        .astimezone()
        .strftime("%a %Y-%m-%d %H:%M %Z")
        if isinstance(resets, int)
        else "?"
    )
    return (
        f"  {label} ({span} window): {window.get('usedPercent')}% used, resets {when}"
    )


def main() -> int:
    result = rpc_read_limits(find_codex())
    if "--json" in sys.argv:
        print(json.dumps(result, indent=2))
        return 0
    found = snapshots(result)
    if not found:
        print(json.dumps(result, indent=2))
        return 1
    seen: set[str] = set()
    for snap in found:
        key = json.dumps(snap, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        name = snap.get("limitName") or snap.get("limitId") or "codex"
        print(
            f"{name} (plan: {snap.get('planType')}, reached: {snap.get('rateLimitReachedType')})"
        )
        print(describe_window("session/primary", snap.get("primary")))
        print(describe_window("weekly/secondary", snap.get("secondary")))
        credits = snap.get("credits")
        if credits:
            print(f"  credits: {credits}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
