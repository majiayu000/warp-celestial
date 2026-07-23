# Changelog

All notable changes to Warp Celestial are documented here. Versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Added traced photon-sphere caustics and turbulent bright knots to the black
  hole without increasing the configured geodesic step limits.
- Added localized magnetic prominence arches to the sun and reduced procedural
  ember counts to 12/20/28 for low/balanced/high quality.

## [0.1.0] - 2026-07-23

### Added

- Geodesic-traced black hole with terminal-content lensing, accretion-disk
  imaging, Doppler lighting and three bounded GPU quality levels.
- Animated sun mode with limb darkening, granulation, sunspots and corona.
- Claude Code context bridge with per-session records and pane-local aggregation.
- Focus-aware behavior across Warp tabs, split panes, rich input and cursor blink.
- Guided macOS installer, prerequisite checks, upgrade migration and demo mode.
- Safe diagnostics, uninstall, Claude settings restoration and build-cache cleanup.
- English and Chinese documentation plus automated installer, patch, Rust and
  Metal validation.

[Unreleased]: https://github.com/majiayu000/warp-celestial/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/majiayu000/warp-celestial/releases/tag/v0.1.0
