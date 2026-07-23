#!/usr/bin/env python3
"""Claude Code -> Warp blackhole bridge.

Reads Claude Code's status-line JSON from stdin, stores one context-window fill
ratio (0.0..1.0) per Claude session, and publishes the pane aggregate through a
signed OSC cursor-color sequence. Warp decodes the focused pane's signal from
its rendered cursor, so tabs and concurrent sessions stay isolated.

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

import errno
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

# Cache directory. Override it when testing or when Warp uses a nonstandard home.
DEFAULT_CONTEXT_DIR = Path.home() / ".cache" / "warp" / "blackhole_contexts"
CONTEXT_CONFIG_PATH = Path(__file__).resolve().with_name("context-cache-dir")


def configured_context_dir() -> Path:
    """Resolve the explicit, installed, or default context cache directory."""
    explicit = os.environ.get("BLACKHOLE_CONTEXT_DIR") or os.environ.get(
        "WARP_CELESTIAL_CACHE_DIR"
    )
    if explicit:
        return Path(explicit).expanduser()
    try:
        configured = CONTEXT_CONFIG_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return DEFAULT_CONTEXT_DIR
    except OSError as error:
        raise RuntimeError(
            f"unable to read context cache configuration: {error}"
        ) from error
    configured_path = Path(configured).expanduser()
    if not configured or not configured_path.is_absolute():
        raise RuntimeError(
            f"invalid context cache configuration in {CONTEXT_CONFIG_PATH}"
        )
    return configured_path


CONTEXT_DIR = configured_context_dir()

# Cursor-channel encoding adapted from s0xDk/ghostty-blackhole (MIT).
# The high nibbles are a signature; the low nibbles hold a quantized fill and
# checksum so ordinary theme cursor colors cannot activate the effect.
CURSOR_BASE = (0xF0, 0xB0, 0x00)


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


def context_record(data: dict) -> Optional[Path]:
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


@contextmanager
def cache_lock(record: Path):
    """Serialize one pane's cache and cursor operations across hook processes."""
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = CONTEXT_DIR / f".{record.parent.name}.lock"
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def write_fill(record: Path, level: float) -> None:
    """Atomically write the fill level to one Claude session record."""
    level = max(0.0, min(1.0, level))
    with cache_lock(record):
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
    with cache_lock(record):
        record.unlink(missing_ok=True)
        try:
            record.parent.rmdir()
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ENOTEMPTY):
                raise


def _pane_fill_unlocked(record: Path) -> Optional[float]:
    maximum = None
    try:
        records = record.parent.glob("*.context")
        for candidate in records:
            fill = float(candidate.read_text(encoding="utf-8").strip())
            fill = max(0.0, min(1.0, fill))
            maximum = fill if maximum is None else max(maximum, fill)
    except (OSError, ValueError) as error:
        raise RuntimeError(f"unable to aggregate context records: {error}") from error
    return maximum


def pane_fill(record: Path) -> Optional[float]:
    """Return the highest live Claude fill in this Warp pane."""
    with cache_lock(record):
        return _pane_fill_unlocked(record)


def cursor_sequence(level: Optional[float]) -> bytes:
    """Encode a fill as OSC 12, or reset the cursor with OSC 112."""
    if level is None:
        return b"\033]112\007"

    fill = max(0, min(250, int(round(level * 250.0))))
    high, low = fill >> 4, fill & 0xF
    rgb = (
        CURSOR_BASE[0] | (high ^ low ^ 0x5),
        CURSOR_BASE[1] | high,
        CURSOR_BASE[2] | low,
    )
    return b"\033]12;#%02x%02x%02x\007" % rgb


def session_tty() -> Optional[Path]:
    """Find the terminal inherited by Claude when hooks have no controlling tty."""
    process_id = os.getppid()
    for _ in range(10):
        try:
            result = subprocess.run(
                ["ps", "-o", "ppid=,tty=", "-p", str(process_id)],
                capture_output=True,
                check=False,
                text=True,
                timeout=1,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError(f"unable to inspect Claude terminal ancestry: {error}") from error

        fields = result.stdout.split()
        if len(fields) < 2:
            return None
        if fields[1] != "??":
            return Path("/dev") / fields[1]
        if not fields[0].isdigit() or int(fields[0]) <= 1:
            return None
        process_id = int(fields[0])
    return None


def emit_cursor(level: Optional[float]) -> bool:
    """Write the pane-local fill directly to its terminal cursor state."""
    sequence = cursor_sequence(level)
    errors = []
    try:
        with Path("/dev/tty").open("wb") as terminal:
            terminal.write(sequence)
        return True
    except OSError as error:
        errors.append(f"/dev/tty: {error}")

    inherited_tty = session_tty()
    if inherited_tty is not None:
        try:
            with inherited_tty.open("wb") as terminal:
                terminal.write(sequence)
            return True
        except OSError as error:
            errors.append(f"{inherited_tty}: {error}")

    print("blackhole cursor update failed: " + "; ".join(errors), file=sys.stderr)
    return False


def sync_cursor(record: Path) -> bool:
    """Atomically read and publish this pane's latest aggregate fill."""
    with cache_lock(record):
        return emit_cursor(_pane_fill_unlocked(record))


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
            sync_cursor(record)
        return 0

    if event == "SessionStart":
        if record is not None:
            write_fill(record, 0.0)
            sync_cursor(record)
        return 0

    # statusLine / Status / any other regular event: track context fill.
    level = context_fill(data)
    if record is not None:
        write_fill(record, level)
        sync_cursor(record)
    print(status_line(data, level))
    return 0


if __name__ == "__main__":
    sys.exit(main())
