# Contributing

Bug reports, compatibility results and focused pull requests are welcome.

## Before opening an issue

Run:

```bash
./install.sh --doctor
```

Include the complete result, macOS version, Mac model, display resolution and
refresh rate, Xcode version, selected effect/quality, and whether `--demo`
reproduces the problem. Remove personal paths or terminal content before
attaching screenshots.

## Local checks

For installer or context-bridge changes:

```bash
bash -n install.sh
python3 scripts/check_compatibility.py
python3 -m unittest discover -s tests -v
```

For the standalone Metal proof of concept:

```bash
cargo check --locked
cargo test --locked
```

Renderer changes must also apply cleanly to the commit declared in
`COMPATIBILITY.json`, compile the combined Metal library, pass the focused Warp
tests and pass strict clippy. GitHub CI performs those checks on macOS.

## Renderer patch changes

Treat `patches/celestial-effect.patch` as the shipped source. Keep shader loops
and ray-step limits bounded, preserve the bottom work-area early exit, and
update its SHA-256 in `COMPATIBILITY.json` after every intentional patch edit:

```bash
shasum -a 256 patches/celestial-effect.patch
python3 scripts/check_compatibility.py
```

Do not weaken tests to make a patch pass. Include real screenshots or video for
visual changes and measured GPU frame time for performance claims.

## Pull requests

Keep each pull request focused. Update `CHANGELOG.md`, English documentation and
the corresponding Chinese page when behavior changes. Do not commit generated
Warp source, build output, credentials, signing material or private terminal
content.
