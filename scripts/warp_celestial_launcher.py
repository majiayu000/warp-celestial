#!/usr/bin/env python3
"""Validate launcher arguments and open an isolated Warp Celestial process."""

import subprocess
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional, Sequence


EFFECTS = ("blackhole", "sun")
QUALITIES = ("low", "balanced", "high")
USAGE = """Usage:
  warp-celestial [blackhole|sun] [low|balanced|high]
  warp-celestial --demo [blackhole|sun] [low|balanced|high] [0.0-1.0]
"""


class LaunchConfig(NamedTuple):
    effect: str
    quality: str
    demo_fill: Optional[float]


def parse_fill(value: str) -> float:
    try:
        fill = float(value)
    except ValueError as error:
        raise ValueError("demo fill must be a number from 0.0 to 1.0") from error
    if not 0.0 <= fill <= 1.0:
        raise ValueError("demo fill must be a number from 0.0 to 1.0")
    return fill


def parse_arguments(arguments: Sequence[str]) -> LaunchConfig:
    remaining = list(arguments)
    if not remaining:
        return LaunchConfig("blackhole", "balanced", None)

    if remaining[0] != "--demo":
        effect = remaining.pop(0)
        if effect not in EFFECTS:
            raise ValueError(f"unknown effect: {effect}")
        quality = remaining.pop(0) if remaining else "balanced"
        if quality not in QUALITIES:
            raise ValueError(f"unknown quality: {quality}")
        if remaining:
            raise ValueError("too many launcher arguments")
        return LaunchConfig(effect, quality, None)

    remaining.pop(0)
    effect = remaining.pop(0) if remaining and remaining[0] in EFFECTS else "blackhole"
    quality = (
        remaining.pop(0) if remaining and remaining[0] in QUALITIES else "high"
    )
    fill = parse_fill(remaining.pop(0)) if remaining else 0.65
    if remaining:
        raise ValueError("too many demo arguments")
    return LaunchConfig(effect, quality, fill)


def open_arguments(app_path: Path, config: LaunchConfig) -> List[str]:
    arguments = [
        "/usr/bin/open",
        "-na",
        str(app_path),
        "--env",
        f"WARP_CELESTIAL={config.effect}",
        "--env",
        f"WARP_CELESTIAL_QUALITY={config.quality}",
    ]
    if config.demo_fill is not None:
        arguments.extend(["--env", f"WARP_CELESTIAL_DEMO={config.demo_fill:.6f}"])
    return arguments


def main(arguments: Sequence[str]) -> int:
    if not arguments:
        sys.stderr.write(USAGE)
        return 2
    app_path = Path(arguments[0]).expanduser()
    try:
        config = parse_arguments(arguments[1:])
    except ValueError as error:
        sys.stderr.write(f"{error}\n{USAGE}")
        return 2
    result = subprocess.run(open_arguments(app_path, config), check=False)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
