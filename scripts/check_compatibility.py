#!/usr/bin/env python3
"""Validate the release manifest against installer constants and a Warp checkout."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def installer_constant(installer: str, name: str) -> Optional[str]:
    match = re.search(rf'^{re.escape(name)}="([^"]+)"$', installer, re.MULTILINE)
    return match.group(1) if match else None


def validate_repository(repository: Path) -> List[str]:
    errors = []
    manifest_path = repository / "COMPATIBILITY.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"cannot read {manifest_path}: {error}"]

    version = (repository / "VERSION").read_text(encoding="utf-8").strip()
    if manifest.get("schema_version") != 1:
        errors.append("unsupported compatibility schema")
    if manifest.get("project_version") != version:
        errors.append("VERSION and COMPATIBILITY.json disagree")

    warp = manifest.get("warp")
    cargo_bundle = manifest.get("cargo_bundle")
    if not isinstance(warp, dict) or not isinstance(cargo_bundle, dict):
        return errors + ["warp and cargo_bundle entries must be objects"]

    commit = warp.get("commit")
    if not isinstance(commit, str) or not SHA_PATTERN.fullmatch(commit):
        errors.append("warp.commit must be a lowercase 40-character SHA")

    patch_value = warp.get("patch")
    if not isinstance(patch_value, str):
        errors.append("warp.patch must be a repository-relative path")
    else:
        patch_path = repository / patch_value
        if not patch_path.is_file():
            errors.append(f"patch is missing: {patch_value}")
        else:
            digest = hashlib.sha256(patch_path.read_bytes()).hexdigest()
            if digest != warp.get("patch_sha256"):
                errors.append("renderer patch SHA-256 does not match the manifest")

    installer = (repository / "install.sh").read_text(encoding="utf-8")
    expected_constants = {
        "WARP_REPOSITORY": warp.get("repository"),
        "WARP_COMMIT": commit,
        "CARGO_BUNDLE_REVISION": cargo_bundle.get("revision"),
    }
    for name, expected in expected_constants.items():
        if installer_constant(installer, name) != expected:
            errors.append(f"{name} disagrees with COMPATIBILITY.json")
    return errors


def validate_warp_checkout(repository: Path, warp_checkout: Path) -> List[str]:
    manifest = json.loads(
        (repository / "COMPATIBILITY.json").read_text(encoding="utf-8")
    )
    expected_commit = manifest["warp"]["commit"]
    patch_path = repository / manifest["warp"]["patch"]
    result = subprocess.run(
        ["git", "-C", str(warp_checkout), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return [f"cannot read Warp checkout: {result.stderr.strip()}"]
    if result.stdout.strip() != expected_commit:
        return [
            f"Warp checkout is at {result.stdout.strip()}, expected {expected_commit}"
        ]

    forward = subprocess.run(
        ["git", "-C", str(warp_checkout), "apply", "--check", str(patch_path)],
        capture_output=True,
        check=False,
    )
    reverse = subprocess.run(
        [
            "git",
            "-C",
            str(warp_checkout),
            "apply",
            "--reverse",
            "--check",
            str(patch_path),
        ],
        capture_output=True,
        check=False,
    )
    if forward.returncode != 0 and reverse.returncode != 0:
        return ["Warp checkout is neither clean nor patched with the declared patch"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository", type=Path, default=REPOSITORY_ROOT, help=argparse.SUPPRESS
    )
    parser.add_argument("--warp-dir", type=Path)
    arguments = parser.parse_args()

    errors = validate_repository(arguments.repository)
    if not errors and arguments.warp_dir is not None:
        errors.extend(validate_warp_checkout(arguments.repository, arguments.warp_dir))
    if errors:
        for error in errors:
            sys.stderr.write(f"compatibility error: {error}\n")
        return 1
    sys.stdout.write("Compatibility manifest is internally consistent.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
