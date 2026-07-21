#!/usr/bin/env python3
"""Claude Code -> Warp blackhole bridge.

Reads Claude Code's status-line JSON from stdin and writes the current context
window fill ratio (0.0..1.0) to a file that Warp's Metal renderer polls.

Intended to be invoked from Claude Code's `statusLine` hook in
`~/.claude/settings.json`:

    {
      "hooks": {
        "statusLine": {
          "command": ["/path/to/claude-token.py"]
        }
      }
    }

The script is intentionally standalone and lives outside the Warp AGPL source
tree. It only writes to a configurable cache file and prints a small status
line for the terminal.
"""

import json
import os
import sys
from pathlib import Path

# Cache file path. Override with BLACKHOLE_CONTEXT_FILE if you want it elsewhere.
DEFAULT_CONTEXT_FILE = Path.home() / ".cache" / "warp" / "blackhole_context"
CONTEXT_FILE = Path(os.environ.get("BLACKHOLE_CONTEXT_FILE", DEFAULT_CONTEXT_FILE))


def context_fill(data: dict) -> float:
    """Extract fill ratio 0.0..1.0 from Claude Code status JSON."""
    ctx = data.get("context_window") or {}

    used_percentage = ctx.get("used_percentage")
    if isinstance(used_percentage, (int, float)):
        return max(0.0, min(1.0, used_percentage / 100.0))

    total = ctx.get("total_input_tokens")
    size = ctx.get("context_window_size")
    if isinstance(total, (int, float)) and isinstance(size, (int, float)) and size > 0:
        return max(0.0, min(1.0, total / size))

    # Older versions only expose this boolean.
    if data.get("exceeds_200k_tokens"):
        return 1.0

    return 0.0


def write_fill(level: float) -> None:
    """Write the fill level to the cache file."""
    level = max(0.0, min(1.0, level))
    CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONTEXT_FILE.write_text(f"{level:.6f}\n", encoding="utf-8")


def remove_fill() -> None:
    """Remove the cache file so the blackhole is hidden."""
    try:
        CONTEXT_FILE.unlink()
    except FileNotFoundError:
        pass


def status_line(data: dict, level: float) -> str:
    """Build a short status line for Claude Code's status bar."""
    model = (data.get("model") or {}).get("display_name", "Claude")
    pct = level * 100.0
    bar_width = 10
    filled = int(round(level * bar_width))
    bar = "█" * filled + "░" * (bar_width - filled)
    return f"{model} · ctx {bar} {pct:5.1f}%"


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}

    event = data.get("hook_event_name", "")

    if event == "SessionEnd":
        remove_fill()
        return 0

    if event == "SessionStart":
        write_fill(0.0)
        return 0

    # statusLine / Status / any other regular event: track context fill.
    level = context_fill(data)
    write_fill(level)
    print(status_line(data, level))
    return 0


if __name__ == "__main__":
    sys.exit(main())
