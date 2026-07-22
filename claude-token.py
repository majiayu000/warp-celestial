#!/usr/bin/env python3
"""Claude Code -> Warp blackhole bridge.

Reads Claude Code's status-line JSON from stdin and writes the current context
window fill ratio (0.0..1.0) to a cache record that Warp's Metal renderer polls.
Records are isolated by Warp terminal pane and Claude session, so tabs and
concurrent Claude sessions cannot overwrite one another.

Intended to be invoked as Claude Code's top-level `statusLine` command in
`~/.claude/settings.json`:

    {
      "statusLine": {
        "type": "command",
        "command": "/path/to/claude-token.py"
      },
      "hooks": {
        "SessionStart": [{
          "hooks": [{"type": "command", "command": "/path/to/claude-token.py"}]
        }],
        "SessionEnd": [{
          "hooks": [{"type": "command", "command": "/path/to/claude-token.py"}]
        }]
      }
    }

The script is intentionally standalone and lives outside the Warp AGPL source
tree. It only writes to a configurable cache file and prints a small status
line for the terminal.
"""

import json
import os
import sys
import hashlib
import tempfile
from pathlib import Path

# Cache directory. Override it when testing or when Warp uses a nonstandard home.
DEFAULT_CONTEXT_DIR = Path.home() / ".cache" / "warp" / "blackhole_contexts"
CONTEXT_DIR = Path(os.environ.get("BLACKHOLE_CONTEXT_DIR", DEFAULT_CONTEXT_DIR))


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


def context_record(data: dict) -> Path | None:
    """Return the safe cache record for this Warp pane and Claude session."""
    pane_id = os.environ.get("WARP_TERMINAL_SESSION_UUID", "").lower()
    session_id = data.get("session_id")
    if (
        len(pane_id) != 32
        or any(character not in "0123456789abcdef" for character in pane_id)
        or not isinstance(session_id, str)
        or not session_id
    ):
        return None

    session_key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return CONTEXT_DIR / pane_id / f"{session_key}.context"


def write_fill(record: Path, level: float) -> None:
    """Atomically write the fill level to one Claude session record."""
    level = max(0.0, min(1.0, level))
    record.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{record.name}.", dir=record.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(f"{level:.6f}\n")
        os.replace(temporary_name, record)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def remove_fill(record: Path) -> None:
    """Remove only this Claude session's cache record."""
    record.unlink(missing_ok=True)
    try:
        record.parent.rmdir()
    except OSError:
        # The pane directory is intentionally retained while other sessions use it.
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
    record = context_record(data)

    if event == "SessionEnd":
        if record is not None:
            remove_fill(record)
        return 0

    if event == "SessionStart":
        if record is not None:
            write_fill(record, 0.0)
        return 0

    # statusLine / Status / any other regular event: track context fill.
    level = context_fill(data)
    if record is not None:
        write_fill(record, level)
    print(status_line(data, level))
    return 0


if __name__ == "__main__":
    sys.exit(main())
