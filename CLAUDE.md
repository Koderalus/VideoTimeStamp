# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

VideoTimeStamp is a macOS desktop app for private investigators. It burns frame-accurate visible timestamps onto video files for use as court evidence. The timestamp is read from video metadata (not the filesystem) and rendered as a moving overlay that advances per frame.

## Running the app

```bash
# One-time setup (macOS only — installs Homebrew, FFmpeg, Python, Pillow via venv)
bash install.sh

# Launch
bash run.sh

# Or directly after setup
.venv/bin/python app.py
```

`install.sh` writes the venv Python path to `.python_path`; `run.sh` reads it.

## Architecture

Two files contain all code:

**`processor.py`** — pure processing logic, no GUI imports. Contains:
- Device detection from the `ftyp` container atom (`qt  ` → Apple, `MSNV` → Sony)
- Metadata extraction: `com.apple.quicktime.creationdate` tag (Apple primary), `mvhd` atom fallback
- The encode pipeline: FFmpeg decodes raw RGB frames → Pillow draws text per-frame → FFmpeg re-encodes with `libx264 CRF 18`; audio is extracted to a temp `.m4a` and stream-copied
- `process_folder()` is the main entry point for batch processing

**`app.py`** — Tkinter GUI. Runs processing on a daemon thread and communicates results back via `queue.Queue` polled with `self.after(100, ...)`. Never call GUI methods from the worker thread — only put messages on the queue.

**`config.json`** — persisted user settings (timezone, text style, last-used folder paths).

## Key design decisions

**Pillow instead of FFmpeg `drawtext`**: The overlay is rendered frame-by-frame in Python so it works regardless of how FFmpeg was compiled (drawtext requires `libfreetype` support).

**Timestamp sources by device type**:
- Apple (MOV/QuickTime): uses the `com.apple.quicktime.creationdate` embedded tag — a timezone-aware ISO string with the actual recording time. Falls back to `mvhd` (UTC) if absent.
- Sony MSNV containers: `mvhd` stores UTC; attach UTC then convert to the user-selected timezone.
- Unknown: same UTC treatment as Sony.

**Timezone handling**: All Australian timezones are fixed-offset (`timedelta`), not `zoneinfo` rules. The user must select the timezone that was active at recording time (relevant for DST transitions in historical footage). This is intentional — `zoneinfo` would silently apply the current DST rule, which may be wrong for past recordings.

**Font scaling**: `font_size`, `edge_padding`, and `outline_w` all scale with video resolution so the overlay looks consistent across SD/HD/4K footage.

## Adding timezones or text styles

Timezones live in the `TIMEZONES` list in `processor.py`. Each entry needs `label`, `abbreviation`, `offset` (timedelta), and `posix_tz`. The GUI dropdown is built from `TIMEZONE_LABELS` automatically.

Text styles live in the `TEXT_STYLES` list. The style name string is matched in `process_video()` with `if style_name == "..."` branches.

## Supported video formats

`.mp4 .mov .avi .mkv .mts .m4v .wmv` — defined in `VIDEO_EXTENSIONS` in `processor.py`.

## Known edge cases

**iOS Photos app edited videos**: When a user edits (crops, reorients, trims) an iPhone video in the Photos app and exports it, the resulting H.264 file contains a garbage SPS VUI clock (`time_scale = 16,777,216`, `num_units_in_tick = 6`), which makes ffprobe report `r_frame_rate ≈ 1,398,101 fps`. Using that value would produce a 0.67 ms output video (effectively invisible). Fixed in `_parse_fps()` by preferring `avg_frame_rate` (always container-derived, always correct) and validating the result is within 1–300 fps.

Photos-edited videos are also re-encoded as H.264 profile 244 (High 4:4:4 Predictive) instead of the usual High profile, and the H.264 SPS frame_crop dimensions (1228×1636 in tested sample) may differ slightly from the container's tkhd dimensions (1238×1650). The output video will be at the SPS display size; this is expected.
