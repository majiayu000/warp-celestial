#!/usr/bin/env python3
"""Validate that a release tag exactly matches VERSION and belongs to main."""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CORE_IDENTIFIER = r"(?:0|[1-9][0-9]*)"
PRERELEASE_IDENTIFIER = (
    r"(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
)
BUILD_IDENTIFIER = r"[0-9A-Za-z-]+"
VERSION_PATTERN = re.compile(
    rf"^{CORE_IDENTIFIER}\.{CORE_IDENTIFIER}\.{CORE_IDENTIFIER}"
    rf"(?:-{PRERELEASE_IDENTIFIER}(?:\.{PRERELEASE_IDENTIFIER})*)?"
    rf"(?:\+{BUILD_IDENTIFIER}(?:\.{BUILD_IDENTIFIER})*)?$"
)


def git(
    repository: Path, arguments: List[str]
) -> Tuple[int, str, str]:
    """Run git without raising so every git failure can fail the contract closed."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repository)] + arguments,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        return 127, "", str(error)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def resolve_commit(repository: Path, reference: str) -> Tuple[Optional[str], str]:
    returncode, stdout, stderr = git(
        repository, ["rev-parse", "--verify", f"{reference}^{{commit}}"]
    )
    if returncode != 0:
        detail = stderr or stdout or f"git exited with status {returncode}"
        return None, detail
    if not re.fullmatch(r"[0-9a-f]{40}", stdout):
        return None, f"git returned an invalid commit ID: {stdout!r}"
    return stdout, ""


def read_version(repository: Path) -> Tuple[Optional[str], List[str]]:
    version_path = repository / "VERSION"
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        return None, [f"cannot read {version_path}: {error}"]
    if not VERSION_PATTERN.fullmatch(version):
        return None, ["VERSION must contain one valid semantic version"]
    return version, []


def validate_release_contract(
    repository: Path, tag: str, commit: str, main_ref: str
) -> List[str]:
    errors = []
    version, version_errors = read_version(repository)
    errors.extend(version_errors)
    if version is None:
        return errors

    expected_tag = f"v{version}"
    if tag != expected_tag:
        errors.append(f"release tag is {tag!r}, expected {expected_tag!r}")
        return errors

    tag_commit, detail = resolve_commit(repository, f"refs/tags/{expected_tag}")
    if tag_commit is None:
        errors.append(f"cannot resolve release tag {expected_tag!r}: {detail}")

    requested_commit, detail = resolve_commit(repository, commit)
    if requested_commit is None:
        errors.append(f"cannot resolve release commit {commit!r}: {detail}")

    main_commit, detail = resolve_commit(repository, main_ref)
    if main_commit is None:
        errors.append(f"cannot resolve main reference {main_ref!r}: {detail}")

    if tag_commit is None or requested_commit is None or main_commit is None:
        return errors
    if tag_commit != requested_commit:
        errors.append(
            f"release tag resolves to {tag_commit}, not requested commit {requested_commit}"
        )
        return errors

    returncode, stdout, stderr = git(
        repository, ["merge-base", "--is-ancestor", tag_commit, main_commit]
    )
    if returncode == 1:
        errors.append(
            f"release commit {tag_commit} is not an ancestor of {main_ref}"
        )
    elif returncode != 0:
        detail = stderr or stdout or f"git exited with status {returncode}"
        errors.append(f"cannot verify main ancestry: {detail}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository", type=Path, default=REPOSITORY_ROOT, help=argparse.SUPPRESS
    )
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--main-ref", default="refs/remotes/origin/main")
    arguments = parser.parse_args()

    errors = validate_release_contract(
        arguments.repository, arguments.tag, arguments.commit, arguments.main_ref
    )
    if errors:
        for error in errors:
            sys.stderr.write(f"release contract error: {error}\n")
        return 1
    sys.stdout.write("Release tag matches VERSION and belongs to main.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
