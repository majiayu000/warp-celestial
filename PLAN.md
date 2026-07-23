# Warp Celestial roadmap

This file tracks product work after the original Metal proof of concept. The
proof established two-pass BGRA rendering, correct UV orientation and a
blend-disabled composite pass; those results now live in the integrated Warp
renderer patch and the standalone Rust project.

## Current architecture

Warp Celestial is a source patch against one tested public Warp commit. It:

1. renders the normal terminal scene into a reusable offscreen texture;
2. publishes the focused pane's signed Claude context value in its Scene;
3. runs a black-hole or sun fragment shader in a second Metal pass;
4. redraws continuously only while an effect is active;
5. installs, diagnoses, upgrades and uninstalls through `install.sh`.

`COMPATIBILITY.json` is the machine-checked release contract. Changes to the
Warp pin, patch, Cargo bundler revision or project version must update it and
pass CI.

## Completed

- [x] Physical Schwarzschild ray integration and terminal-content lensing
- [x] Accretion disk, Doppler lighting, photon caustics and bounded quality modes
- [x] Sun photosphere, sunspots, corona, prominences and scaled embers
- [x] Claude Code lifecycle integration and per-pane multi-session aggregation
- [x] Tab, split-pane, cursor-blink and rich-input focus behavior
- [x] Guided install, preflight, doctor, upgrade, cache cleanup and uninstall
- [x] English/Chinese usage and troubleshooting documentation
- [x] Installer, Python, Rust, patch and Metal CI
- [x] Versioned compatibility manifest and source-release automation

## Next

- [ ] Test a clean installation on a second Apple Silicon Mac
- [ ] Capture real black-hole growth, sun and tab/split demo videos
- [ ] Measure GPU frame time on representative Retina 60 Hz and 120 Hz displays
- [ ] Rebase onto a newer public Warp revision after the weekly probe identifies
      a suitable update point
- [ ] Add Apple Developer signing and notarization only when a signing identity
      and corresponding AGPL binary-source publication process are available

## Release gates

A release is ready only when:

- `python3 -m unittest discover -s tests -v` passes;
- `cargo check --locked` and `cargo test --locked` pass;
- the patch applies and reverses at the declared Warp commit;
- the combined Metal shader library compiles;
- focused Warp renderer tests and strict clippy pass in CI;
- README commands match the installer and launcher;
- any distributed binary is signed, notarized and accompanied by corresponding
  AGPL source.
