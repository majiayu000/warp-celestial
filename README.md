# Warp Celestial

[Chinese version](README.zh-CN.md)

Warp Celestial adds an animated black hole or sun to the macOS Metal renderer
in [Warp](https://github.com/warpdotdev/warp). The effect bends or illuminates
the terminal scene, and its size follows the current Claude Code context-window
usage.

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

To check the machine without installing anything:

```bash
./install.sh --check
```

Useful options:

```text
--skip-claude-config    Build the app without editing Claude Code settings
--no-launch             Do not open the app after installation
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

The default is `blackhole`. The effect is intentionally hidden when Claude Code
reports no active context usage. To preview it without waiting for a session:

```bash
~/.local/bin/warp-celestial --demo
```

`--demo` writes a temporary 65% fill record under
`~/.cache/warp/blackhole_contexts` and removes it after 30 seconds.

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
          |  writes one 0.0-to-1.0 record per Claude session
          v
~/.cache/warp/blackhole_contexts/<pane>/<session>.context
          |
          |  maximum sampled by Warp, at most once every 100 ms
          v
Warp Metal renderer
  1. render the normal scene to an offscreen BGRA texture
  2. sample that texture in a full-screen fragment shader
  3. apply lensing, disk/corona light and animation
  4. present the composited frame
```

### Context bridge

Claude Code sends JSON to its configured `statusLine` command. The standalone
`claude-token.py` script calculates the fill ratio from `used_percentage`, or
from total tokens divided by context-window size when needed. It clamps the
result to `0.0..1.0` and writes it atomically as a short text value understood
by the renderer.

The installer registers the same script for Claude Code's `SessionStart` and
`SessionEnd` hooks. A start resets the value to zero, and an end removes the
cache file. Missing or invalid data means zero activity; the renderer does not
invent a value.

### Metal renderer

The patch changes only Warp's macOS Metal backend. The normal terminal scene is
rendered into a reusable offscreen texture. A second full-screen pass samples
that texture and runs one of two fragment shaders:

- `blackhole_fragment`: gravitational lensing, event horizon, photon ring,
  Doppler-brightened accretion disk and slow drift
- `sun_fragment`: limb-darkened photosphere, granulation, sunspots, corona and
  procedural embers

Set `WARP_CELESTIAL=sun` before launch to select the sun. Any other value selects
the black hole. Both effects use the same viewport size, time and context-fill
uniforms.

### Resource use

While the fill value is zero, the window uses Warp's normal event-driven redraw
behavior and the effect is not continuously animated. While it is above zero,
the window redraws at display rate so the shader can move. The implementation
reuses the offscreen texture, preserves the cached scene between animation
frames and scans the small context cache no more than once every 100 ms.

This still costs more GPU time and memory bandwidth than stock Warp because an
active effect adds a full-screen render pass. Larger windows, Retina resolution
and high-refresh-rate displays cost more. Close the custom app or end the Claude
Code session to stop that continuous rendering.

### Tabs, panes and concurrent sessions

Each Claude session writes its own record under the stable Warp terminal pane
ID inherited through `WARP_TERMINAL_SESSION_UUID`. Ending one session removes
only that record, so it cannot erase another running session. Multiple sessions
inside one pane and sessions in different tabs are currently combined by taking
the highest context usage.

The Metal effect is still window-wide. It does not yet switch to only the
focused pane when you change tabs or split-pane focus; doing that requires the
active pane ID to be carried through Warp's UI scene into the renderer. The
cache layout is already pane-aware so that mapping can be added without another
data migration.

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

After saving anything you need, remove these project-owned paths:

```text
~/Applications/Warp Celestial.app
~/.local/bin/warp-celestial
~/.local/share/warp-celestial
~/.cache/warp/blackhole_contexts
```

Restore the timestamped `~/.claude/settings.json.backup.*` file, or remove the
`statusLine` entry and the two lifecycle hook commands added by this project.

## Repository contents

| Path | Purpose |
| --- | --- |
| `install.sh` | Preflight, build, app installation and safe Claude configuration |
| `scripts/configure_claude.py` | Atomic, preserving update of Claude Code settings |
| `patches/celestial-effect.patch` | Complete Warp source patch |
| `claude-token.py` | Claude Code context-to-renderer bridge |
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
