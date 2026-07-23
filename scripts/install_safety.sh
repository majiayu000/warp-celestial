#!/usr/bin/env bash

# Path ownership helpers sourced by install.sh. They intentionally rely on the
# installer's fail/check_command functions and resolved path constants.

canonical_path() {
  check_command python3 "Python 3.8 or newer is required for safe path validation."
  python3 - "$1" <<'PY'
import os
import sys

print(os.path.realpath(os.path.abspath(os.path.expanduser(sys.argv[1]))))
PY
}

assert_dedicated_root_path() {
  local target="$1"
  local expected_name="$2"
  local canonical_target canonical_home

  [[ "$target" == /* ]] || fail "Managed directory must be absolute: ${target}"
  canonical_target="$(canonical_path "$target")"
  canonical_home="$(canonical_path "$HOME")"
  [[ "$(basename "$canonical_target")" == "$expected_name" ]] ||
    fail "Managed directory must end in ${expected_name}: ${target}"
  case "$canonical_target" in
    "${canonical_home}/"*) ;;
    *) fail "Managed directory must be below HOME (${canonical_home}): ${target}" ;;
  esac
}

marker_payload() {
  printf '%s\n%s' "$MANAGED_MARKER_VERSION" "$(canonical_path "$1")"
}

write_managed_marker() {
  local marker="$1"
  local root="$2"
  local temporary

  temporary="${marker}.tmp.$$"
  (umask 077 && marker_payload "$root" >"$temporary")
  mv "$temporary" "$marker"
}

assert_valid_managed_marker() {
  local marker="$1"
  local root="$2"
  local actual expected

  [[ -f "$marker" && ! -L "$marker" ]] ||
    fail "Refusing to remove unowned directory without a managed marker: ${root}"
  actual="$(cat "$marker")"
  expected="$(marker_payload "$root")"
  [[ "$actual" == "$expected" ]] ||
    fail "Managed marker does not match directory: ${root}"
}

assert_adoptable_install_root() {
  local entry name remote commit

  [[ -d "$INSTALL_ROOT" ]] || return 0
  while IFS= read -r -d '' entry; do
    name="$(basename "$entry")"
    case "$name" in
      .warp-celestial-managed | .warp-download.* | warp.failed-download-* | \
        warp | target | cargo-bundle | claude-token.py | \
        warp_celestial_launcher.py | claude-settings-state.json | \
        context-cache-dir)
        ;;
      *) fail "Refusing to adopt non-empty unmanaged directory (${entry})." ;;
    esac
  done < <(find "$INSTALL_ROOT" -mindepth 1 -maxdepth 1 -print0)

  if [[ -e "$SOURCE_DIR" ]]; then
    [[ -e "${SOURCE_DIR}/.git" ]] ||
      fail "Existing managed source is not a Git checkout: ${SOURCE_DIR}"
    remote="$(git -C "$SOURCE_DIR" remote get-url origin 2>/dev/null || true)"
    commit="$(git -C "$SOURCE_DIR" rev-parse HEAD 2>/dev/null || true)"
    [[ "$remote" == "$WARP_REPOSITORY" && "$commit" == "$WARP_COMMIT" ]] ||
      fail "Existing source cannot be safely adopted as Warp Celestial."
  fi
}

prepare_install_root() {
  assert_dedicated_root_path "$INSTALL_ROOT" "warp-celestial"
  if [[ -e "$INSTALL_MARKER" ]]; then
    assert_valid_managed_marker "$INSTALL_MARKER" "$INSTALL_ROOT"
    return
  fi

  assert_adoptable_install_root
  mkdir -p "$INSTALL_ROOT"
  write_managed_marker "$INSTALL_MARKER" "$INSTALL_ROOT"
}

prepare_context_root() {
  local entry name

  assert_dedicated_root_path "$CONTEXT_DIR" "blackhole_contexts"
  if [[ -e "$CACHE_MARKER" ]]; then
    assert_valid_managed_marker "$CACHE_MARKER" "$CONTEXT_DIR"
    return
  fi

  if [[ -d "$CONTEXT_DIR" ]]; then
    while IFS= read -r -d '' entry; do
      name="$(basename "$entry")"
      if [[ -d "$entry" && "$name" =~ ^[0-9a-f]{32}$ ]]; then
        continue
      fi
      if [[ -f "$entry" ]] &&
        [[ "$name" == ".lock" || "$name" =~ ^\..+\.lock$ ]]; then
        continue
      fi
      fail "Refusing to adopt unrelated cache entry: ${entry}"
    done < <(find "$CONTEXT_DIR" -mindepth 1 -maxdepth 1 -print0)
  fi

  mkdir -p "$CONTEXT_DIR"
  write_managed_marker "$CACHE_MARKER" "$CONTEXT_DIR"
}

installed_cargo_bundle_is_pinned() {
  [[ -x "${CARGO_BUNDLE_ROOT}/bin/cargo-bundle" ]] &&
    [[ -f "$CARGO_BUNDLE_MARKER" ]] &&
    [[ "$(cat "$CARGO_BUNDLE_MARKER")" == "$CARGO_BUNDLE_REVISION" ]]
}
