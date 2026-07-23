#!/usr/bin/env python3
"""Safely install or remove the Warp Celestial Claude Code integration."""

import json
import os
import shlex
import shutil
import stat
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple


LIFECYCLE_EVENTS = ("SessionStart", "SessionEnd")
STATE_VERSION = 1


def ensure_lifecycle_hook(settings: dict, event: str, command: str) -> bool:
    """Add one command hook for an event, preserving all existing hooks."""
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Claude Code's hooks setting must be a JSON object")

    matchers = hooks.setdefault(event, [])
    if not isinstance(matchers, list):
        raise ValueError(f"Claude Code's hooks.{event} setting must be a JSON array")

    for matcher in matchers:
        if not isinstance(matcher, dict):
            continue
        commands = matcher.get("hooks")
        if not isinstance(commands, list):
            continue
        if any(
            isinstance(item, dict)
            and item.get("type") == "command"
            and item.get("command") == command
            for item in commands
        ):
            return False

    matchers.append({"hooks": [{"type": "command", "command": command}]})
    return True


def read_settings(settings_path: Path) -> Tuple[dict, int]:
    """Read Claude settings and preserve the current file mode."""
    if not settings_path.exists():
        return {}, 0o600

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {settings_path}: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {settings_path}")
    return data, stat.S_IMODE(settings_path.stat().st_mode)


def write_json_atomic(path: Path, data: Any, mode: int = 0o600) -> None:
    """Write JSON atomically without exposing a partially written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def backup_settings(settings_path: Path) -> Optional[Path]:
    """Create a timestamped settings backup when the file exists."""
    if not settings_path.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = settings_path.with_name(f"{settings_path.name}.backup.{timestamp}")
    shutil.copy2(settings_path, backup)
    return backup


def configure(
    settings_path: Path, hook_path: Path, state_path: Optional[Path] = None
) -> Tuple[bool, Optional[Path]]:
    """Update settings atomically and record exactly which values we own."""
    resolved_hook = str(hook_path.expanduser().resolve())
    hook_command = shlex.quote(resolved_hook)
    desired_status_line = {"type": "command", "command": hook_command}
    data, mode = read_settings(settings_path)

    status_line_existed = "statusLine" in data
    previous_status_line = data.get("statusLine")
    status_line_changed = previous_status_line != desired_status_line

    changed = status_line_changed
    data["statusLine"] = desired_status_line
    added_events = []
    for event in LIFECYCLE_EVENTS:
        added = ensure_lifecycle_hook(data, event, hook_command)
        if added:
            added_events.append(event)
        changed = added or changed

    if not changed:
        if state_path is not None and not state_path.exists():
            write_json_atomic(
                state_path,
                {
                    "version": STATE_VERSION,
                    "managed_command": hook_command,
                    "status_line_changed": False,
                    "status_line_existed": status_line_existed,
                    "previous_status_line": previous_status_line,
                    "added_events": [],
                },
            )
        return False, None

    backup = backup_settings(settings_path)
    write_json_atomic(settings_path, data, mode)

    if state_path is not None and not state_path.exists():
        write_json_atomic(
            state_path,
            {
                "version": STATE_VERSION,
                "managed_command": hook_command,
                "status_line_changed": status_line_changed,
                "status_line_existed": status_line_existed,
                "previous_status_line": previous_status_line,
                "added_events": added_events,
            },
        )

    return True, backup


def remove_command_hook(settings: dict, event: str, command: str) -> bool:
    """Remove only the exact command hook installed for one event."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    matchers = hooks.get(event)
    if not isinstance(matchers, list):
        return False

    changed = False
    kept_matchers = []
    for matcher in matchers:
        if not isinstance(matcher, dict):
            kept_matchers.append(matcher)
            continue
        commands = matcher.get("hooks")
        if not isinstance(commands, list):
            kept_matchers.append(matcher)
            continue
        kept_commands = [
            item
            for item in commands
            if not (
                isinstance(item, dict)
                and item.get("type") == "command"
                and item.get("command") == command
            )
        ]
        if len(kept_commands) != len(commands):
            changed = True
        if kept_commands:
            updated_matcher = dict(matcher)
            updated_matcher["hooks"] = kept_commands
            kept_matchers.append(updated_matcher)

    if changed:
        if kept_matchers:
            hooks[event] = kept_matchers
        else:
            hooks.pop(event, None)
        if not hooks:
            settings.pop("hooks", None)
    return changed


def read_state(state_path: Path) -> dict:
    """Read and validate the install ownership record."""
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {state_path}: {error}") from error
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        raise ValueError(f"Unsupported Warp Celestial state in {state_path}")
    if not isinstance(state.get("managed_command"), str):
        raise ValueError(f"Missing managed command in {state_path}")
    return state


def unconfigure(
    settings_path: Path, hook_path: Path, state_path: Optional[Path] = None
) -> Tuple[bool, Optional[Path]]:
    """Undo only settings owned by Warp Celestial and preserve later user edits."""
    if not settings_path.exists():
        return False, None

    data, mode = read_settings(settings_path)
    hook_command = shlex.quote(str(hook_path.expanduser().resolve()))
    state = read_state(state_path) if state_path and state_path.exists() else None
    managed_command = state["managed_command"] if state else hook_command
    desired_status_line = {"type": "command", "command": managed_command}
    changed = False

    if data.get("statusLine") == desired_status_line:
        if state and state.get("status_line_changed"):
            if state.get("status_line_existed"):
                data["statusLine"] = state.get("previous_status_line")
            else:
                data.pop("statusLine", None)
            changed = True
        elif state is None:
            data.pop("statusLine", None)
            changed = True

    removable_events = (
        state.get("added_events", []) if state else list(LIFECYCLE_EVENTS)
    )
    for event in removable_events:
        if event in LIFECYCLE_EVENTS:
            changed = remove_command_hook(data, event, managed_command) or changed

    if not changed:
        return False, None

    backup = backup_settings(settings_path)
    write_json_atomic(settings_path, data, mode)
    return True, backup


def main() -> int:
    if len(sys.argv) not in (3, 4, 5):
        sys.stderr.write(
            "Usage: configure_claude.py [--remove] SETTINGS_FILE "
            "CLAUDE_TOKEN_SCRIPT [STATE_FILE]\n"
        )
        return 2

    remove = sys.argv[1] == "--remove"
    arguments = sys.argv[2:] if remove else sys.argv[1:]
    if len(arguments) not in (2, 3):
        sys.stderr.write(
            "Usage: configure_claude.py [--remove] SETTINGS_FILE "
            "CLAUDE_TOKEN_SCRIPT [STATE_FILE]\n"
        )
        return 2

    settings_path = Path(arguments[0]).expanduser()
    hook_path = Path(arguments[1]).expanduser()
    state_path = Path(arguments[2]).expanduser() if len(arguments) == 3 else None
    try:
        operation = unconfigure if remove else configure
        changed, backup = operation(settings_path, hook_path, state_path)
    except ValueError as error:
        sys.stderr.write(f"{error}\n")
        return 1

    if changed:
        if backup:
            sys.stdout.write(f"Backed up Claude Code settings to {backup}\n")
        verb = "Removed Warp Celestial from" if remove else "Configured Claude Code in"
        sys.stdout.write(f"{verb} {settings_path}\n")
    else:
        message = (
            "No managed Claude Code settings needed removal"
            if remove
            else "Claude Code is already configured"
        )
        sys.stdout.write(f"{message}: {settings_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
