# Warp Celestial

[Chinese version](README.zh-CN.md)

Warp Celestial adds a geodesic-traced black hole or animated sun to the macOS
Metal renderer in [Warp](https://github.com/warpdotdev/warp). The black hole
physically lenses terminal content through a Schwarzschild ray integrator, and
its size follows the focused Claude Code pane's context-window usage.

![Warp Celestial black hole](blackhole.png)

## Requirements

- macOS
- The full Xcode app, opened at least once with its additional components installed
- Rust and Cargo from [rustup](https://rustup.rs)
- Git and Python 3.8 or newer
- At least 25 GB of free disk space for the Warp source and build artifacts
- Homebrew only when `jq` is not already installed

The installer checks these requirements before changing anything. Xcode Command
Line Tools alone are not enough because the shader must be compiled with the
Metal toolchain included in the full Xcode app.

## Quick install

```bash
git clone https://github.com/majiayu000/warp-celestial.git
cd warp-celestial
./install.sh
```

The first build can take 10-30 minutes. The installer explains each long-running
step and asks before installing build helpers or changing Claude Code settings.
To upgrade an existing installation, pull the latest repository changes and run
`./install.sh` again. The installer migrates the previous managed renderer patch
in place, so the Warp source does not need to be cloned again.

To check the machine without installing anything:

```bash
./install.sh --check
```

To diagnose both prerequisites and an existing installation:

```bash
./install.sh --doctor
```

Useful options:

```text
--skip-claude-config    Build the app without editing Claude Code settings
--no-launch             Do not open the app after installation
--clean-build-cache     Reclaim compiled build space without uninstalling the app
--uninstall             Safely remove the app and its managed Claude integration
--yes                   Accept prompts; required for non-interactive installation
```

## What the installer does

1. Verifies macOS, full Xcode, Metal tools, Rust, Python, Git and disk space.
2. Installs `jq` through Homebrew when needed and installs Warp's pinned
   `cargo-bundle` version through Cargo.
3. Clones Warp at the tested commit `69ce3728` into
   `~/.local/share/warp-celestial/warp`.
4. Applies `patches/celestial-effect.patch` and builds the public OSS app. No
   Firebase key or private Warp repository is required.
5. Installs the app as `~/Applications/Warp Celestial.app`.
6. Installs the context bridge at
   `~/.local/share/warp-celestial/claude-token.py` and the launcher at
   `~/.local/bin/warp-celestial`.
7. With confirmation, backs up `~/.claude/settings.json`, adds the top-level
   `statusLine` command, and merges `SessionStart`/`SessionEnd` lifecycle hooks
   without changing unrelated settings or hooks.
8. Records which Claude settings it owns, allowing uninstall to restore a
   previous status line without overwriting changes made after installation.

The installer is repeatable. Running it again reuses the pinned source checkout
and Cargo build cache. If it cannot verify the pinned commit and patch state, it
stops instead of resetting or deleting the checkout.

## Running it

Restart Claude Code after the first installation so it reloads the status-line
configuration. Then open `Warp Celestial.app` from `~/Applications`, or use:

```bash
~/.local/bin/warp-celestial blackhole
~/.local/bin/warp-celestial sun
```

The optional second argument selects the GPU cost: `low` (24 trace steps),
`balanced` (36, the default), or `high` (48). For example:

```bash
~/.local/bin/warp-celestial blackhole low
```

The default is `blackhole`. The effect is intentionally hidden when Claude Code
reports no active context usage. To preview it without waiting for a session:

```bash
~/.local/bin/warp-celestial --demo
```

`--demo` launches a separate app process with a fixed 65% context level. It
does not modify context records and remains active until that app process exits.
You can combine it with a quality level, for example `--demo low`.

If `~/.local/bin` is on your `PATH`, the shorter commands work too:

```bash
warp-celestial blackhole
warp-celestial sun
warp-celestial --demo
```

## How it works

The system has two small parts and one patched renderer:

```text
Claude Code statusLine JSON
          |
          v
claude-token.py
          |
          |  stores one record per session, aggregates within this pane
          v
~/.cache/warp/blackhole_contexts/<pane>/<session>.context
          |
          |  signed OSC 12 cursor-color signal
          v
focused Warp tab / split pane
          |
          v
Warp Metal renderer (smoothed 0.0-to-1.0 uniform)
  1. render the normal scene to an offscreen BGRA texture
  2. integrate near-field Schwarzschild photon paths per pixel
  3. apply terminal lensing, repeated disk crossings and relativistic light
  4. present the composited frame
```

### Context bridge

Claude Code sends JSON to its configured `statusLine` command. The standalone
`claude-token.py` calculates the fill ratio from `used_percentage`, or from
total tokens divided by context-window size when needed. It clamps the result
to `0.0..1.0`, writes the session record atomically, takes the maximum of the
live sessions in the same pane, and encodes that value into a checksummed OSC
12 cursor color. Ordinary theme cursor colors cannot accidentally match the
signature.

The installer registers the same script for Claude Code's `SessionStart` and
`SessionEnd` hooks. A start creates a zero record; an end removes only that
session and republishes the remaining pane maximum. With no sessions left, the
script restores the normal cursor color. The OSC sequence is written directly
to the inherited terminal instead of polluting the status-line output.

### Metal renderer

The patch changes only Warp's macOS Metal backend. The normal terminal scene is
rendered into a reusable offscreen texture. A second full-screen pass samples
that texture and runs one of two fragment shaders:

- `blackhole_fragment`: numerically integrated Schwarzschild geodesics,
  physically captured rays, multi-image accretion disk, blackbody temperature,
  Doppler shift/beaming, time dilation and weak-field lensing
- `sun_fragment`: limb-darkened photosphere, granulation, sunspots, corona and
  procedural embers

Set `WARP_CELESTIAL=sun` before launch to select the sun. Any other value selects
the black hole. The focused pane publishes a zero-sized transparent marker into
the current scene, so the signal survives cursor blinks and CLI rich input while
the renderer glides between context updates rather than changing size in one frame.

### Resource use

While the fill value is zero, the window uses Warp's normal event-driven redraw
behavior and the effect is not continuously animated. While it is above zero,
the window redraws at display rate so the shader can move. The implementation
reuses the offscreen texture and preserves the cached scene between animation
frames. Warp performs no filesystem scan: the pane-local value arrives in the
scene it already renders.

This costs more GPU time and memory bandwidth than stock Warp because an active
effect adds a full-screen pass, and pixels near the hole integrate 24-48 ray
steps. Pixels in the protected bottom work area exit early; distant pixels use
a cheaper analytic approximation. Larger Retina windows and high-refresh-rate
displays cost more. Use `low` on a laptop or `high` for recordings; close the
custom app or end the focused Claude session to stop continuous rendering.

### Tabs, panes and concurrent sessions

Each Claude session writes its own record under the stable Warp terminal pane
ID inherited through `WARP_TERMINAL_SESSION_UUID`. Multiple Claude sessions in
one pane aggregate by maximum, so ending one cannot erase another. Different
tabs and split panes publish independent cursor signals. Warp renders only the
active tab, and only the focused split publishes an invisible scene marker, so
changing tab or split focus changes the window-wide effect to that pane's level.
An active pane with no Claude signal fades the effect out after the short signal
grace period.

## Manual installation

The installer is recommended, but the exact source procedure is:

```bash
git clone --filter=blob:none https://github.com/warpdotdev/warp.git
cd warp
git checkout 69ce3728acae0b01c2f457b65a90c144664686aa
git apply /path/to/warp-celestial/patches/celestial-effect.patch

cargo install cargo-bundle \
  --git https://github.com/burtonageo/cargo-bundle \
  --rev ae4c76e92c08774bf54ff077b1c52e3d1cd6c16d

export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
export WARP_BIN_NAME=warp-oss
export WARP_CHANNEL=oss
export FEATURES=gui
./script/macos/run --dont-open
```

The bundle is created at `target/debug/bundle/osx/WarpOss.app` unless Cargo is
configured to use a different target directory.

To configure Claude Code manually:

```json
{
  "statusLine": {
    "type": "command",
    "command": "/absolute/path/to/claude-token.py"
  },
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "/absolute/path/to/claude-token.py"
      }]
    }],
    "SessionEnd": [{
      "hooks": [{
        "type": "command",
        "command": "/absolute/path/to/claude-token.py"
      }]
    }]
  }
}
```

Preserve any other keys already present in `~/.claude/settings.json`.

## Troubleshooting

### The installer says the Metal compiler is missing

Install the full Xcode app, open it once, and allow its additional components to
finish installing. If first-launch setup is incomplete, run:

```bash
sudo xcodebuild -runFirstLaunch
```

Then retry `./install.sh --check`.

### The app opens but no effect appears

Run `~/.local/bin/warp-celestial --demo`. If the demo works, restart Claude Code
so it reloads `statusLine`, then confirm that this file changes during a session:

```bash
find ~/.cache/warp/blackhole_contexts -maxdepth 3 -name '*.context' -print -exec cat {} \;
```

### Claude Code already has a custom status line

The installer creates a timestamped backup before replacing `statusLine`. It
preserves existing lifecycle hooks and adds its commands beside them, but it
does not merge two status-line programs. Use `--skip-claude-config` if you want
to combine the status lines manually.

### The managed Warp checkout has unexpected changes

The installer refuses to reset or delete modified source. Move
`~/.local/share/warp-celestial/warp` elsewhere, or remove it after saving any
work you need, then run the installer again.

## Removing the local installation

Run:

```bash
./install.sh --uninstall
```

The uninstaller removes the app, launcher, managed source/build directory and
context cache. It removes only the exact Claude hooks installed by this project.
If the installer replaced an earlier status line, it restores that value only
when the current value is still managed by Warp Celestial; later user edits are
left untouched. Timestamped Claude settings backups are preserved.

To keep the installed app but reclaim the large Cargo build directory:

```bash
./install.sh --clean-build-cache
```

## Repository contents

| Path | Purpose |
| --- | --- |
| `install.sh` | Preflight, build, app installation and safe Claude configuration |
| `scripts/configure_claude.py` | Atomic, preserving update of Claude Code settings |
| `patches/celestial-effect.patch` | Complete Warp source patch |
| `claude-token.py` | Claude Code context-to-renderer bridge |
| `THIRD_PARTY_NOTICES.md` | Attribution and MIT notice for adapted work |
| `blackhole.png` | README preview captured from the real patched app |
| `warp-channel-config.example` | Optional local-development stub; not used by the installer |
| `src/main.rs` | Historical standalone Metal proof of concept |
| `PLAN.md` | Original integration plan |

## Limitations and license

- The renderer patch currently supports macOS Metal only.
- The patch is pinned to Warp commit `69ce3728`; newer Warp revisions may need a
  rebase.
- The locally built OSS app is ad-hoc signed, not Apple-notarized.
- Warp is AGPL-3.0. The patch is intended to be applied to and distributed with
  Warp under the same license obligations.
- The geodesic renderer and cursor-channel protocol retain the upstream MIT
  attribution documented in `THIRD_PARTY_NOTICES.md`.
