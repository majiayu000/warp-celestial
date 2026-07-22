#!/usr/bin/env bash

set -Eeuo pipefail

WARP_REPOSITORY="https://github.com/warpdotdev/warp.git"
WARP_COMMIT="69ce3728acae0b01c2f457b65a90c144664686aa"
CARGO_BUNDLE_REVISION="ae4c76e92c08774bf54ff077b1c52e3d1cd6c16d"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="${WARP_CELESTIAL_HOME:-${HOME}/.local/share/warp-celestial}"
APP_DIR="${WARP_CELESTIAL_APP_DIR:-${HOME}/Applications}"
CLAUDE_SETTINGS="${CLAUDE_SETTINGS_FILE:-${HOME}/.claude/settings.json}"
SOURCE_DIR="${INSTALL_ROOT}/warp"
TARGET_DIR="${INSTALL_ROOT}/target"
BIN_DIR="${HOME}/.local/bin"
APP_PATH="${APP_DIR}/Warp Celestial.app"
HOOK_PATH="${INSTALL_ROOT}/claude-token.py"
LAUNCHER_PATH="${BIN_DIR}/warp-celestial"
CELESTIAL_PATCH="${SCRIPT_DIR}/patches/celestial-effect.patch"
LEGACY_CELESTIAL_PATCH="${SCRIPT_DIR}/patches/celestial-effect-v1.patch"

ASSUME_YES=false
CHECK_ONLY=false
CONFIGURE_CLAUDE=true
LAUNCH_APP=true

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
  --skip-claude-config    Do not update ~/.claude/settings.json.
  --no-launch             Do not launch the app after installation.
  --yes                   Accept installer prompts.
  -h, --help              Show this help.

Optional environment variables:
  WARP_CELESTIAL_HOME       Build and support files directory.
  WARP_CELESTIAL_APP_DIR    Destination directory for the .app bundle.
  CLAUDE_SETTINGS_FILE      Claude Code settings file to update.
EOF
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
      CHECK_ONLY=true
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

if [[ ! -t 0 && "$ASSUME_YES" != true && "$CHECK_ONLY" != true ]]; then
  fail "Non-interactive installation requires the explicit --yes option."
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

  if ! cargo bundle --help >/dev/null 2>&1; then
    if [[ "$CHECK_ONLY" == true ]]; then
      fail "cargo-bundle is missing. Rerun without --check to install the pinned version."
    fi
    confirm "cargo-bundle is required to create the macOS app. Install the pinned version?" ||
      fail "Installation cancelled because cargo-bundle is required."
    cargo install cargo-bundle \
      --git https://github.com/burtonageo/cargo-bundle \
      --rev "$CARGO_BUNDLE_REVISION"
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
  install_build_helpers
  log "Prerequisites are ready (Xcode: ${DEVELOPER_DIR})."
}

prepare_warp_source() {
  mkdir -p "$INSTALL_ROOT"

  if [[ ! -e "$SOURCE_DIR" ]]; then
    log "Cloning the pinned Warp source. This download can take several minutes."
    git clone --filter=blob:none --no-checkout "$WARP_REPOSITORY" "$SOURCE_DIR"
    git -C "$SOURCE_DIR" checkout --detach "$WARP_COMMIT"
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
  mkdir -p "$INSTALL_ROOT" "$BIN_DIR"
  install -m 0755 "${SCRIPT_DIR}/claude-token.py" "$HOOK_PATH"

  local quoted_app
  printf -v quoted_app '%q' "$APP_PATH"
  cat >"$LAUNCHER_PATH" <<EOF
#!/usr/bin/env bash
set -euo pipefail

APP_PATH=${quoted_app}
effect="\${1:-blackhole}"
quality="\${2:-balanced}"
demo_fill=""

case "\$effect" in
  blackhole | sun) ;;
  --demo)
    effect="blackhole"
    demo_fill="0.65"
    ;;
  *)
    printf 'Usage: warp-celestial [blackhole|sun|--demo] [low|balanced|high]\\n' >&2
    exit 2
    ;;
esac

case "\$quality" in
  low | balanced | high) ;;
  *)
    printf 'Quality must be low, balanced, or high.\\n' >&2
    exit 2
    ;;
esac

open_args=(-na "\$APP_PATH" --env "WARP_CELESTIAL=\$effect" --env "WARP_CELESTIAL_QUALITY=\$quality")
if [[ -n "\$demo_fill" ]]; then
  open_args+=(--env "WARP_CELESTIAL_DEMO=\$demo_fill")
fi
/usr/bin/open "\${open_args[@]}"
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
  python3 "${SCRIPT_DIR}/scripts/configure_claude.py" "$CLAUDE_SETTINGS" "$HOOK_PATH"
}

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
