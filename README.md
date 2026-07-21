# warp-celestial

A full-screen celestial post-process for the [Warp](https://github.com/warpdotdev/warp)
terminal on macOS (Metal renderer): a wandering **black hole** with gravitational
lensing (default) or a glowing **sun** with corona, sunspots and ejected ember
particles (`WARP_CELESTIAL=sun`). The body's size and activity scale with your
**Claude Code context-window fill rate** (a 0..1 value).

![blackhole](blackhole.png)

## How it works

1. `claude-token.py` is a Claude Code `statusLine` hook. On every status-line
   update it computes the context fill ratio and writes it to
   `~/.cache/warp/blackhole_context` (`SessionStart` → `0.0`, `SessionEnd` →
   file removed).
2. The patched Warp reads that file and passes the fill value plus a time
   uniform into a two-pass Metal composite: the scene renders to an offscreen
   texture, then a full-screen fragment shader warps/overlays the celestial
   body (blending disabled on the composite pipeline).
3. `WARP_CELESTIAL` selects the fragment entry point at renderer init:
   `sun` → `sun_fragment`, anything else → `blackhole_fragment`. Vertex stage
   and uniforms are shared.

The effect only runs while fill > 0 (i.e. an active Claude Code session), and
redraws continuously at display rate while active.

## Contents

| Path | What |
|------|------|
| `patches/celestial-effect.patch` | All Warp source changes (shaders, renderer, build script, window redraw hook) |
| `claude-token.py` | statusLine hook writing the fill value |
| `warp-channel-config.example` | Sanitized build-time stub template (see below) |
| `PLAN.md` | Original design notes |
| `src/main.rs`, `Cargo.toml`, `Cargo.lock` | Early standalone scaffold (historical, not needed for the effect) |

## Applying the patch

The patch targets `warpdotdev/warp` at base commit `69ce3728`. It may need a
rebase for newer upstream revisions.

```sh
git clone --filter=blob:none https://github.com/warpdotdev/warp.git
cd warp
git checkout 69ce3728
git apply /path/to/patches/celestial-effect.patch
```

Build requires Xcode's Metal toolchain:

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
cargo build -p warp
```

`build.rs` shells out to a `warp-channel-config` binary that is not part of the
public Warp repo. Copy `warp-channel-config.example` to a directory on your
`PATH` as `warp-channel-config` (drop the suffix, `chmod +x`) and fill in the
`firebase_auth_api_key` placeholder if your build needs it. **Do not commit
your real channel config — it contains credentials.**

Run:

```sh
./target/debug/warp                # black hole
WARP_CELESTIAL=sun ./target/debug/warp   # sun
```

Wire up the statusLine hook in your Claude Code settings:

```json
{
  "statusLine": {
    "type": "command",
    "command": "/path/to/claude-token.py"
  }
}
```

## Notes

- macOS Metal path only; the patch does not touch other platforms.
- The patch modifies Warp, which is AGPL-3.0; these changes are meant to be
  applied to and redistributed with that source under the same terms.
- The sun's particles are procedural: the post-process pass has no particle
  buffer, so 32 embers are faked in-shader (hashed launch angle/speed/lifetime,
  distance-culled per fragment).
