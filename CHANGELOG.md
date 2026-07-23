# Changelog

All notable changes to Warp Celestial are documented here. Versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

### Changed

- Added traced photon-sphere caustics and turbulent bright knots to the black
  hole without increasing the configured geodesic step limits.
- Added localized magnetic prominence arches to the sun and reduced procedural
  ember counts to 12/20/28 for low/balanced/high quality.
- Expanded demo launching to select the effect, quality and fixed context fill,
  with reproducible English and Chinese capture guides.
- Made Warp downloads transactional and retry the pinned shallow fetch over
  HTTP/1.1, preventing a failed network transfer from poisoning later installs.
- Bound recursive cleanup to canonical dedicated directories with private
  ownership markers and negative destructive-path tests.
- Preserved the latest user status line across reinstall/uninstall cycles and
  stopped uninstall when an unowned Claude command still references the bridge.
- Expired stale per-session context records after 24 hours, including legacy
  float-only cache files, so unclean exits cannot leave a permanent pane value.
- Persisted custom context-cache paths for the runtime bridge and moved the
  verified cargo-bundle revision into the project support directory.
- Split release verification from write-enabled publication and required the
  complete Python, Rust, Metal, Warp patch and clippy gates.
