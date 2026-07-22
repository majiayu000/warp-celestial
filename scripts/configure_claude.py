#!/usr/bin/env python3
"""Safely configure Claude Code for the Warp Celestial context bridge."""

import json
import os
import shlex
import shutil
import stat
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple


LIFECYCLE_EVENTS = ("SessionStart", "SessionEnd")


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


def configure(settings_path: Path, hook_path: Path) -> Tuple[bool, Optional[Path]]:
    """Update settings atomically and return the backup path when one is made."""
    resolved_hook = str(hook_path.expanduser().resolve())
    hook_command = shlex.quote(resolved_hook)
    desired_status_line = {"type": "command", "command": hook_command}

    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON in {settings_path}: {error}") from error
        if not isinstance(data, dict):
            raise ValueError(f"Expected a JSON object in {settings_path}")
        mode = stat.S_IMODE(settings_path.stat().st_mode)
    else:
        data = {}
        mode = 0o600

    changed = data.get("statusLine") != desired_status_line
    data["statusLine"] = desired_status_line
    for event in LIFECYCLE_EVENTS:
        changed = ensure_lifecycle_hook(data, event, hook_command) or changed

    if not changed:
        return False, None

    backup = None
    if settings_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = settings_path.with_name(f"{settings_path.name}.backup.{timestamp}")
        shutil.copy2(settings_path, backup)

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".settings.", suffix=".json", dir=settings_path.parent
    )
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, settings_path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise

    return True, backup


def main() -> int:
    if len(sys.argv) != 3:
        sys.stderr.write(
            "Usage: configure_claude.py SETTINGS_FILE CLAUDE_TOKEN_SCRIPT\n"
        )
        return 2

    settings_path = Path(sys.argv[1]).expanduser()
    hook_path = Path(sys.argv[2]).expanduser()
    try:
        changed, backup = configure(settings_path, hook_path)
    except ValueError as error:
        sys.stderr.write(f"{error}\n")
        return 1

    if changed:
        if backup:
            sys.stdout.write(f"Backed up Claude Code settings to {backup}\n")
        sys.stdout.write(f"Configured Claude Code in {settings_path}\n")
    else:
        sys.stdout.write(f"Claude Code is already configured: {settings_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
