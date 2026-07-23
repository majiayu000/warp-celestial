#!/usr/bin/env bash

set -Eeuo pipefail

WARP_REPOSITORY="https://github.com/warpdotdev/warp.git"
WARP_COMMIT="69ce3728acae0b01c2f457b65a90c144664686aa"
CARGO_BUNDLE_REVISION="739f92c37c789b5511a448a389cbc76fcebd99df"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="${WARP_CELESTIAL_HOME:-${HOME}/.local/share/warp-celestial}"
APP_DIR="${WARP_CELESTIAL_APP_DIR:-${HOME}/Applications}"
CLAUDE_SETTINGS="${CLAUDE_SETTINGS_FILE:-${HOME}/.claude/settings.json}"
SOURCE_DIR="${INSTALL_ROOT}/warp"
TARGET_DIR="${INSTALL_ROOT}/target"
CARGO_BUNDLE_ROOT="${INSTALL_ROOT}/cargo-bundle"
BIN_DIR="${HOME}/.local/bin"
APP_PATH="${APP_DIR}/Warp Celestial.app"
HOOK_PATH="${INSTALL_ROOT}/claude-token.py"
LAUNCHER_IMPL_PATH="${INSTALL_ROOT}/warp_celestial_launcher.py"
CLAUDE_STATE="${INSTALL_ROOT}/claude-settings-state.json"
CONTEXT_DIR="${WARP_CELESTIAL_CACHE_DIR:-${HOME}/.cache/warp/blackhole_contexts}"
CONTEXT_CONFIG_PATH="${INSTALL_ROOT}/context-cache-dir"
LAUNCHER_PATH="${BIN_DIR}/warp-celestial"
CELESTIAL_PATCH="${SCRIPT_DIR}/patches/celestial-effect.patch"
LEGACY_CELESTIAL_PATCH="${SCRIPT_DIR}/patches/celestial-effect-v1.patch"
INSTALL_MARKER="${INSTALL_ROOT}/.warp-celestial-managed"
CACHE_MARKER="${CONTEXT_DIR}/.warp-celestial-managed"
CARGO_BUNDLE_MARKER="${CARGO_BUNDLE_ROOT}/.warp-celestial-revision"
MANAGED_MARKER_VERSION="warp-celestial-managed-v1"

ASSUME_YES=false
CHECK_ONLY=false
CONFIGURE_CLAUDE=true
LAUNCH_APP=true
ACTION="install"

log() {
  printf '[warp-celestial] %s\n' "$*"
}

fail() {
  printf '[warp-celestial] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Options:
  --check                 Check prerequisites without installing anything.
  --doctor                Diagnose prerequisites and the current installation.
  --uninstall             Remove the app, support files, cache and managed settings.
  --clean-build-cache     Remove compiled build artifacts but keep the installation.
  --skip-claude-config    Do not update ~/.claude/settings.json.
  --no-launch             Do not launch the app after installation.
  --yes                   Accept installer prompts.
  -h, --help              Show this help.

Optional environment variables:
  WARP_CELESTIAL_HOME       Build and support files directory.
  WARP_CELESTIAL_APP_DIR    Destination directory for the .app bundle.
  WARP_CELESTIAL_CACHE_DIR  Context record cache directory.
  CLAUDE_SETTINGS_FILE      Claude Code settings file to update.
EOF
}

select_action() {
  local requested="$1"
  if [[ "$ACTION" != install && "$ACTION" != "$requested" ]]; then
    fail "Choose only one of --check, --doctor, --uninstall, or --clean-build-cache."
  fi
  ACTION="$requested"
}

confirm() {
  local prompt="$1"
  local default_answer="${2:-yes}"
  local answer

  if [[ "$ASSUME_YES" == true ]]; then
    return 0
  fi
  if [[ ! -t 0 ]]; then
    printf '%s\n' \
      "[warp-celestial] Non-interactive confirmation requires the explicit --yes option." \
      >&2
    return 1
  fi

  if [[ "$default_answer" == yes ]]; then
    read -r -p "${prompt} [Y/n] " answer
    [[ -z "$answer" || "$answer" =~ ^[Yy]$ ]]
  else
    read -r -p "${prompt} [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]]
  fi
}

while (($#)); do
  case "$1" in
    --check)
      select_action "check"
      CHECK_ONLY=true
      ;;
    --doctor)
      select_action "doctor"
      ;;
    --uninstall)
      select_action "uninstall"
      ;;
    --clean-build-cache)
      select_action "clean-build-cache"
      ;;
    --skip-claude-config)
      CONFIGURE_CLAUDE=false
      ;;
    --no-launch)
      LAUNCH_APP=false
      ;;
    --yes)
      ASSUME_YES=true
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      fail "Unknown option: $1"
      ;;
  esac
  shift
done

if [[ ! -t 0 && "$ASSUME_YES" != true && "$ACTION" != check && "$ACTION" != doctor ]]; then
  fail "Non-interactive changes require the explicit --yes option."
fi

check_command() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required. $2"
}

resolve_xcode() {
  local selected
  selected="${DEVELOPER_DIR:-$(xcode-select -p 2>/dev/null || true)}"

  if [[ "$selected" == "/Library/Developer/CommandLineTools" ]] &&
    [[ -x "/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild" ]]; then
    selected="/Applications/Xcode.app/Contents/Developer"
  fi

  [[ -n "$selected" ]] || fail "Install the full Xcode app, open it once, then rerun this installer."
  [[ -x "${selected}/usr/bin/xcodebuild" ]] ||
    fail "The full Xcode app is required; Command Line Tools alone are not enough."

  export DEVELOPER_DIR="$selected"
  xcrun --find metal >/dev/null 2>&1 ||
    fail "Xcode's Metal compiler is unavailable. Open Xcode once and install its additional components."
  xcrun --find metallib >/dev/null 2>&1 ||
    fail "Xcode's metallib tool is unavailable. Open Xcode once and install its additional components."
  xcodebuild -checkFirstLaunchStatus >/dev/null 2>&1 ||
    fail "Xcode setup is incomplete. Run: sudo xcodebuild -runFirstLaunch"
}

check_disk_space() {
  local available_kb
  local required_kb=$((25 * 1024 * 1024))
  available_kb="$(df -Pk "$HOME" | awk 'NR == 2 {print $4}')"
  [[ "$available_kb" =~ ^[0-9]+$ ]] || fail "Could not determine available disk space."
  ((available_kb >= required_kb)) ||
    fail "At least 25 GB of free disk space is required for the Warp source and build artifacts."
}

# shellcheck source=scripts/install_safety.sh
source "${SCRIPT_DIR}/scripts/install_safety.sh"

install_build_helpers() {
  if ! command -v jq >/dev/null 2>&1; then
    if [[ "$CHECK_ONLY" == true ]]; then
      fail "jq is missing. Install it with: brew install jq"
    fi
    check_command brew "Install Homebrew from https://brew.sh, then rerun this installer."
    confirm "jq is required by Warp's macOS bundler. Install it with Homebrew?" ||
      fail "Installation cancelled because jq is required."
    brew install jq
  fi

  if ! installed_cargo_bundle_is_pinned; then
    if [[ "$CHECK_ONLY" == true ]]; then
      fail "The project-local pinned cargo-bundle is missing. Rerun without --check."
    fi
    confirm "Install the project-local pinned cargo-bundle required by Warp?" ||
      fail "Installation cancelled because cargo-bundle is required."
    cargo install cargo-bundle \
      --force \
      --root "$CARGO_BUNDLE_ROOT" \
      --git https://github.com/burtonageo/cargo-bundle \
      --rev "$CARGO_BUNDLE_REVISION"
    printf '%s\n' "$CARGO_BUNDLE_REVISION" >"$CARGO_BUNDLE_MARKER"
  fi
}

check_prerequisites() {
  [[ "$(uname -s)" == Darwin ]] || fail "This project currently supports macOS only."
  check_command git "Install Xcode or Git, then rerun this installer."
  check_command python3 "Install Python 3, then rerun this installer."
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' ||
    fail "Python 3.8 or newer is required."
  check_command cargo "Install Rust with rustup from https://rustup.rs."
  check_command rustc "Install Rust with rustup from https://rustup.rs."
  check_command xcode-select "Install the full Xcode app from the App Store."
  check_command xcrun "Install the full Xcode app from the App Store."
  check_command xcodebuild "Install the full Xcode app from the App Store."
  check_command ditto "ditto is included with macOS."
  resolve_xcode
  check_disk_space
  if [[ "$CHECK_ONLY" != true ]]; then
    prepare_install_root
  else
    assert_dedicated_root_path "$INSTALL_ROOT" "warp-celestial"
  fi
  install_build_helpers
  log "Prerequisites are ready (Xcode: ${DEVELOPER_DIR})."
}

DOCTOR_FAILURES=0
DOCTOR_WARNINGS=0

doctor_ok() {
  printf '[warp-celestial] [OK] %s\n' "$*"
}

doctor_warn() {
  printf '[warp-celestial] [WARN] %s\n' "$*"
  DOCTOR_WARNINGS=$((DOCTOR_WARNINGS + 1))
}

doctor_problem() {
  printf '[warp-celestial] [FAIL] %s\n' "$*"
  DOCTOR_FAILURES=$((DOCTOR_FAILURES + 1))
}

run_doctor() {
  local selected commit

  if [[ "$(uname -s)" == Darwin ]]; then
    doctor_ok "macOS is supported."
  else
    doctor_problem "This project currently supports macOS only."
  fi

  for command_name in git python3 cargo rustc xcode-select xcrun xcodebuild ditto; do
    if command -v "$command_name" >/dev/null 2>&1; then
      doctor_ok "${command_name} is available."
    else
      doctor_problem "${command_name} is missing."
    fi
  done

  if command -v python3 >/dev/null 2>&1; then
    if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'; then
      doctor_ok "Python is 3.8 or newer."
    else
      doctor_problem "Python 3.8 or newer is required."
    fi
  fi

  selected="${DEVELOPER_DIR:-$(xcode-select -p 2>/dev/null || true)}"
  if [[ "$selected" == "/Library/Developer/CommandLineTools" ]] &&
    [[ -x "/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild" ]]; then
    selected="/Applications/Xcode.app/Contents/Developer"
  fi
  if [[ -x "${selected}/usr/bin/xcodebuild" ]]; then
    doctor_ok "Full Xcode is available at ${selected}."
    if DEVELOPER_DIR="$selected" xcrun --find metal >/dev/null 2>&1 &&
      DEVELOPER_DIR="$selected" xcrun --find metallib >/dev/null 2>&1; then
      doctor_ok "Metal compiler tools are available."
    else
      doctor_problem "Metal compiler tools are unavailable; finish Xcode setup."
    fi
  else
    doctor_problem "The full Xcode app is not available."
  fi

  if [[ -d "$APP_PATH" ]]; then
    doctor_ok "App bundle exists at ${APP_PATH}."
  else
    doctor_problem "App bundle is missing at ${APP_PATH}."
  fi
  if [[ -x "$LAUNCHER_PATH" ]]; then
    doctor_ok "Launcher is executable at ${LAUNCHER_PATH}."
  else
    doctor_problem "Launcher is missing or not executable at ${LAUNCHER_PATH}."
  fi
  if [[ -x "$HOOK_PATH" ]]; then
    doctor_ok "Context bridge is executable at ${HOOK_PATH}."
  else
    doctor_problem "Context bridge is missing or not executable at ${HOOK_PATH}."
  fi
  if [[ -x "$LAUNCHER_IMPL_PATH" ]]; then
    doctor_ok "Launcher implementation is executable."
  else
    doctor_problem "Launcher implementation is missing or not executable."
  fi
  if [[ -f "$CONTEXT_CONFIG_PATH" ]] &&
    [[ "$(cat "$CONTEXT_CONFIG_PATH")" == "$CONTEXT_DIR" ]]; then
    doctor_ok "Context cache configuration matches ${CONTEXT_DIR}."
  else
    doctor_problem "Context cache configuration is missing or inconsistent."
  fi
  if installed_cargo_bundle_is_pinned; then
    doctor_ok "Project-local cargo-bundle matches the pinned revision."
  else
    doctor_problem "Project-local cargo-bundle is missing or not pinned."
  fi
  if [[ -f "$INSTALL_MARKER" ]] &&
    [[ "$(cat "$INSTALL_MARKER")" == "$(marker_payload "$INSTALL_ROOT")" ]]; then
    doctor_ok "Installation ownership marker is valid."
  else
    doctor_problem "Installation ownership marker is missing or invalid."
  fi
  if [[ -f "$CACHE_MARKER" ]] &&
    [[ "$(cat "$CACHE_MARKER")" == "$(marker_payload "$CONTEXT_DIR")" ]]; then
    doctor_ok "Context cache ownership marker is valid."
  else
    doctor_problem "Context cache ownership marker is missing or invalid."
  fi

  if [[ -e "${SOURCE_DIR}/.git" ]]; then
    commit="$(git -C "$SOURCE_DIR" rev-parse HEAD 2>/dev/null || true)"
    if [[ "$commit" == "$WARP_COMMIT" ]]; then
      doctor_ok "Managed Warp source is at the tested commit."
    else
      doctor_problem "Managed Warp source is at ${commit:-an unreadable commit}."
    fi
    if git -C "$SOURCE_DIR" apply --reverse --check "$CELESTIAL_PATCH" >/dev/null 2>&1; then
      doctor_ok "Current celestial renderer patch is applied."
    elif git -C "$SOURCE_DIR" apply --reverse --check "$LEGACY_CELESTIAL_PATCH" >/dev/null 2>&1; then
      doctor_warn "Legacy renderer patch is applied; rerun the installer to upgrade."
    else
      doctor_problem "Managed Warp source does not match a supported patch state."
    fi
  else
    doctor_problem "Managed Warp source is missing at ${SOURCE_DIR}."
  fi

  if [[ -f "$CLAUDE_STATE" ]]; then
    doctor_ok "Claude settings ownership record exists."
  else
    doctor_warn "Claude settings ownership record is missing (expected on legacy or skipped configuration)."
  fi

  if [[ -f "$CLAUDE_SETTINGS" && -x "$HOOK_PATH" ]] &&
    python3 - "$CLAUDE_SETTINGS" "$HOOK_PATH" <<'PY'
import json
import shlex
import sys
from pathlib import Path

settings = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
command = shlex.quote(str(Path(sys.argv[2]).expanduser().resolve()))
status_ok = settings.get("statusLine") == {"type": "command", "command": command}
hooks = settings.get("hooks", {})
events_ok = all(
    any(
        isinstance(matcher, dict)
        and any(
            isinstance(item, dict)
            and item.get("type") == "command"
            and item.get("command") == command
            for item in matcher.get("hooks", [])
        )
        for matcher in hooks.get(event, [])
    )
    for event in ("SessionStart", "SessionEnd")
)
sys.exit(0 if status_ok and events_ok else 1)
PY
  then
    doctor_ok "Claude Code status line and lifecycle hooks are configured."
  else
    doctor_warn "Claude Code integration is absent, incomplete, or intentionally skipped."
  fi

  printf '[warp-celestial] Doctor finished: %d failure(s), %d warning(s).\n' \
    "$DOCTOR_FAILURES" "$DOCTOR_WARNINGS"
  ((DOCTOR_FAILURES == 0))
}

absolute_path() {
  python3 - "$1" <<'PY'
import os
import sys

print(os.path.abspath(os.path.expanduser(sys.argv[1])))
PY
}

assert_exact_child() {
  local target="$1"
  local parent="$2"
  local expected_name="$3"
  local expected

  expected="$(absolute_path "${parent}/${expected_name}")"
  [[ "$(absolute_path "$target")" == "$expected" ]] ||
    fail "Refusing to remove unexpected path: ${target}"
}

remove_owned_root() {
  local target="$1"
  local expected_name="$2"
  local marker="$3"

  assert_dedicated_root_path "$target" "$expected_name"
  assert_valid_managed_marker "$marker" "$target"
  if [[ -e "$target" || -L "$target" ]]; then
    rm -rf -- "$target"
    log "Removed ${target}."
  else
    log "Already absent: ${target}."
  fi
}

remove_owned_child() {
  local target="$1"
  local parent="$2"
  local expected_name="$3"
  local marker="$4"

  assert_valid_managed_marker "$marker" "$parent"
  assert_exact_child "$target" "$parent" "$expected_name"
  if [[ -e "$target" || -L "$target" ]]; then
    rm -rf -- "$target"
    log "Removed ${target}."
  else
    log "Already absent: ${target}."
  fi
}

remove_download_stage() {
  local target="$1"
  local name

  name="$(basename "$target")"
  [[ "$name" == .warp-download.* ]] ||
    fail "Refusing to remove unexpected download staging path: ${target}"
  remove_owned_child "$target" "$INSTALL_ROOT" "$name" "$INSTALL_MARKER"
}

settings_reference_hook() {
  python3 - "$CLAUDE_SETTINGS" "$HOOK_PATH" <<'PY'
import json
import os
import shlex
import sys
from pathlib import Path

hook = Path(sys.argv[2]).expanduser().resolve()


def command_references_hook(command):
    if not isinstance(command, str):
        return False
    if str(hook) in command:
        return True
    try:
        tokens = shlex.split(command)
    except ValueError:
        # An unparseable command cannot be proven independent of the bridge.
        return True
    for token in tokens:
        expanded = os.path.expandvars(os.path.expanduser(token))
        if expanded == str(hook):
            return True
        if expanded.startswith("/"):
            try:
                if Path(expanded).resolve() == hook:
                    return True
            except OSError:
                return True
    return False


try:
    settings = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    # Preserve the bridge when settings cannot be inspected reliably.
    sys.exit(0)

status = settings.get("statusLine")
if isinstance(status, dict) and command_references_hook(status.get("command")):
    sys.exit(0)
hooks = settings.get("hooks", {})
if isinstance(hooks, dict):
    for matchers in hooks.values():
        if not isinstance(matchers, list):
            continue
        for matcher in matchers:
            if not isinstance(matcher, dict):
                continue
            commands = matcher.get("hooks", [])
            if any(
                isinstance(item, dict)
                and item.get("type") == "command"
                and command_references_hook(item.get("command"))
                for item in commands
            ):
                sys.exit(0)
sys.exit(1)
PY
}

clean_build_cache() {
  assert_dedicated_root_path "$INSTALL_ROOT" "warp-celestial"
  assert_valid_managed_marker "$INSTALL_MARKER" "$INSTALL_ROOT"
  confirm "Remove compiled build artifacts at ${TARGET_DIR}?" no ||
    fail "Build-cache cleanup cancelled."
  remove_owned_child "$TARGET_DIR" "$INSTALL_ROOT" "target" "$INSTALL_MARKER"
}

uninstall_all() {
  assert_dedicated_root_path "$INSTALL_ROOT" "warp-celestial"
  assert_valid_managed_marker "$INSTALL_MARKER" "$INSTALL_ROOT"
  assert_exact_child "$APP_PATH" "$APP_DIR" "Warp Celestial.app"
  assert_exact_child "$LAUNCHER_PATH" "$BIN_DIR" "warp-celestial"
  if [[ -e "$CONTEXT_DIR" ]]; then
    assert_dedicated_root_path "$CONTEXT_DIR" "blackhole_contexts"
    assert_valid_managed_marker "$CACHE_MARKER" "$CONTEXT_DIR"
  fi

  confirm "Remove Warp Celestial and its managed Claude Code integration?" no ||
    fail "Uninstall cancelled."

  if [[ -f "$CLAUDE_SETTINGS" ]]; then
    python3 "${SCRIPT_DIR}/scripts/configure_claude.py" \
      --remove "$CLAUDE_SETTINGS" "$HOOK_PATH" "$CLAUDE_STATE"
  else
    log "Claude Code settings are already absent."
  fi

  if [[ -f "$CLAUDE_SETTINGS" ]] && settings_reference_hook; then
    fail "Claude Code still references the bridge. Preserve or remove that pre-existing configuration before uninstalling."
  fi

  if [[ -e "$APP_PATH" || -L "$APP_PATH" ]]; then
    rm -rf -- "$APP_PATH"
    log "Removed ${APP_PATH}."
  fi
  if [[ -e "$LAUNCHER_PATH" || -L "$LAUNCHER_PATH" ]]; then
    rm -f -- "$LAUNCHER_PATH"
    log "Removed ${LAUNCHER_PATH}."
  fi
  if [[ -e "$CONTEXT_DIR" ]]; then
    remove_owned_root "$CONTEXT_DIR" "blackhole_contexts" "$CACHE_MARKER"
  fi
  remove_owned_root "$INSTALL_ROOT" "warp-celestial" "$INSTALL_MARKER"
  log "Warp Celestial was uninstalled. Existing timestamped Claude settings backups were preserved."
}

prepare_warp_source() {
  mkdir -p "$INSTALL_ROOT"

  if [[ ! -e "$SOURCE_DIR" ]]; then
    local stage_root stage_source fetched
    stage_root="$(mktemp -d "${INSTALL_ROOT}/.warp-download.XXXXXX")"
    stage_source="${stage_root}/warp"
    fetched=false
    mkdir -p "$stage_source"

    log "Downloading the pinned Warp source. This can take several minutes."
    if ! git -C "$stage_source" init --quiet ||
      ! git -C "$stage_source" remote add origin "$WARP_REPOSITORY" ||
      ! git -C "$stage_source" config http.version HTTP/1.1; then
      remove_download_stage "$stage_root"
      fail "Could not initialize the temporary Warp checkout."
    fi

    for attempt in 1 2 3; do
      if git -C "$stage_source" fetch --depth=1 origin "$WARP_COMMIT"; then
        fetched=true
        break
      fi
      log "Warp download attempt ${attempt} failed."
    done

    if [[ "$fetched" != true ]]; then
      remove_download_stage "$stage_root"
      fail "Could not download the tested Warp commit after 3 attempts."
    fi
    if ! git -C "$stage_source" checkout --detach FETCH_HEAD; then
      remove_download_stage "$stage_root"
      fail "Downloaded Warp but could not check out the tested commit."
    fi
    if ! mv "$stage_source" "$SOURCE_DIR"; then
      remove_download_stage "$stage_root"
      fail "Could not move the verified Warp checkout into ${SOURCE_DIR}."
    fi
    rmdir "$stage_root"
  elif [[ ! -e "${SOURCE_DIR}/.git" ]]; then
    fail "${SOURCE_DIR} exists but is not a managed Warp checkout. Move it away and rerun."
  fi

  local current_commit
  current_commit="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
  if [[ "$current_commit" != "$WARP_COMMIT" ]]; then
    fail "Managed Warp checkout is at ${current_commit}, expected ${WARP_COMMIT}. Remove ${SOURCE_DIR} to rebuild it."
  fi

  if git -C "$SOURCE_DIR" apply --reverse --check "$CELESTIAL_PATCH"; then
    log "Celestial patch is already applied."
  elif git -C "$SOURCE_DIR" apply --check "$CELESTIAL_PATCH"; then
    log "Applying the celestial renderer patch."
    git -C "$SOURCE_DIR" apply "$CELESTIAL_PATCH"
  elif git -C "$SOURCE_DIR" apply --reverse --check "$LEGACY_CELESTIAL_PATCH"; then
    log "Upgrading the previous celestial renderer patch in place."
    git -C "$SOURCE_DIR" apply --reverse "$LEGACY_CELESTIAL_PATCH"

    if ! git -C "$SOURCE_DIR" apply --check "$CELESTIAL_PATCH"; then
      git -C "$SOURCE_DIR" apply "$LEGACY_CELESTIAL_PATCH" ||
        fail "Upgrade validation failed and the previous patch could not be restored."
      fail "Upgrade validation failed; the previous celestial patch was restored."
    fi

    if ! git -C "$SOURCE_DIR" apply "$CELESTIAL_PATCH"; then
      git -C "$SOURCE_DIR" apply "$LEGACY_CELESTIAL_PATCH" ||
        fail "Upgrade failed and the previous patch could not be restored."
      fail "Upgrade failed; the previous celestial patch was restored."
    fi
  else
    fail "The managed Warp checkout has unexpected changes. Remove ${SOURCE_DIR} and rerun."
  fi
}

build_app() {
  mkdir -p "$TARGET_DIR"
  log "Building Warp Celestial. The first build can take 10-30 minutes and several GB of disk space."
  (
    cd "$SOURCE_DIR"
    PATH="${CARGO_BUNDLE_ROOT}/bin:${PATH}" \
    CARGO_TARGET_DIR="$TARGET_DIR" \
      WARP_BIN_NAME="warp-oss" \
      WARP_CHANNEL="oss" \
      FEATURES="gui" \
      ./script/macos/run --dont-open
  )

  local built_app="${TARGET_DIR}/debug/bundle/osx/WarpOss.app"
  [[ -d "$built_app" ]] || fail "Build completed without producing ${built_app}."

  mkdir -p "$APP_DIR"
  local stage_dir
  stage_dir="$(mktemp -d "${APP_DIR}/.warp-celestial.XXXXXX")"
  ditto "$built_app" "${stage_dir}/Warp Celestial.app"

  if [[ -e "$APP_PATH" ]]; then
    rm -rf "${APP_PATH}.previous"
    mv "$APP_PATH" "${APP_PATH}.previous"
  fi
  if mv "${stage_dir}/Warp Celestial.app" "$APP_PATH"; then
    rm -rf "${APP_PATH}.previous"
  else
    [[ ! -e "${APP_PATH}.previous" ]] || mv "${APP_PATH}.previous" "$APP_PATH"
    fail "Could not install the app bundle."
  fi
  rm -rf "$stage_dir"
  log "Installed ${APP_PATH}."
}

install_support_files() {
  prepare_context_root
  mkdir -p "$INSTALL_ROOT" "$BIN_DIR"
  install -m 0755 "${SCRIPT_DIR}/claude-token.py" "$HOOK_PATH"
  install -m 0755 \
    "${SCRIPT_DIR}/scripts/warp_celestial_launcher.py" \
    "$LAUNCHER_IMPL_PATH"
  (umask 077 && printf '%s\n' "$(canonical_path "$CONTEXT_DIR")" >"$CONTEXT_CONFIG_PATH")

  local quoted_app quoted_launcher_impl
  printf -v quoted_app '%q' "$APP_PATH"
  printf -v quoted_launcher_impl '%q' "$LAUNCHER_IMPL_PATH"
  cat >"$LAUNCHER_PATH" <<EOF
#!/usr/bin/env bash
set -euo pipefail

APP_PATH=${quoted_app}
exec python3 ${quoted_launcher_impl} "\$APP_PATH" "\$@"
EOF
  chmod 0755 "$LAUNCHER_PATH"
  log "Installed launcher ${LAUNCHER_PATH}."
}

configure_claude() {
  [[ "$CONFIGURE_CLAUDE" == true ]] || return 0
  confirm "Back up and configure Claude Code's statusLine and lifecycle hooks?" || {
    log "Skipped Claude Code configuration."
    return 0
  }
  python3 "${SCRIPT_DIR}/scripts/configure_claude.py" \
    "$CLAUDE_SETTINGS" "$HOOK_PATH" "$CLAUDE_STATE"
}

case "$ACTION" in
  doctor)
    run_doctor
    exit $?
    ;;
  uninstall)
    uninstall_all
    exit 0
    ;;
  clean-build-cache)
    clean_build_cache
    exit 0
    ;;
esac

check_prerequisites
if [[ "$CHECK_ONLY" == true ]]; then
  log "Preflight check passed. No files were changed."
  exit 0
fi

prepare_warp_source
build_app
install_support_files
configure_claude

if [[ "$LAUNCH_APP" == true ]]; then
  log "Launching Warp Celestial. The effect appears after Claude Code reports context usage."
  WARP_CELESTIAL="blackhole" /usr/bin/open -na "$APP_PATH"
fi

cat <<EOF

Warp Celestial is installed.

App:      ${APP_PATH}
Launcher: ${LAUNCHER_PATH}
Support:  ${INSTALL_ROOT}

Commands:
  ${LAUNCHER_PATH} blackhole
  ${LAUNCHER_PATH} sun
  ${LAUNCHER_PATH} --demo

Restart Claude Code after the first install so it reloads statusLine settings.
EOF
