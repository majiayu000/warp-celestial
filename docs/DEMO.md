# Demo capture guide

Use the installed patched app for every published image or video. The demo
launcher supplies a fixed context level without writing fake session records.

## Recommended setup

- Use a 16:10 window around 1440 × 900 logical pixels.
- Choose a dark theme with readable, unsaturated text.
- Hide unrelated notifications and personal paths.
- Record at 60 fps. Use `high` for capture and `low` for battery demonstrations.
- Keep at least one command block and one text-heavy region visible so lensing
  can be judged against straight lines.

## Required shots

### Black-hole hero

```bash
warp-celestial --demo blackhole high 0.85
```

Hold for 6–8 seconds. Show the shadow, photon caustic, multiple disk images and
terminal-content distortion. Do not crop away the protected bottom work area.

### Sun hero

```bash
warp-celestial --demo sun high 0.75
```

Hold for 6–8 seconds so granulation, sunspots, prominences and embers are all
visible.

### Context progression

Capture the black hole at `0.15`, `0.45`, `0.70` and `0.95` with identical
window geometry. For a continuous clip, use a real Claude Code session and show
the context percentage changing; do not splice fixed levels while claiming they
are live telemetry.

### Tabs and split panes

Run Claude Code in two panes with different context levels. Record a tab switch
and a split-focus switch, showing that the window effect follows only the
focused pane.

### Performance comparison

Record the same scene with:

```bash
warp-celestial --demo blackhole low 0.85
warp-celestial --demo blackhole balanced 0.85
warp-celestial --demo blackhole high 0.85
```

Report hardware, logical window size, display refresh rate and measured GPU
frame time. Do not infer performance from fan noise or visual smoothness alone.

## Export

Keep a lossless or high-bitrate master. Export a short MP4 for social media and
an optimized GIF only when a platform cannot autoplay video. Add the final file
under `docs/media/`, update the README, and include the capture environment in
the pull request.
