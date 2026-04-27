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

**Video rotation (iPhone landscape recordings)**: iPhones store landscape video as portrait pixel data with a 90° rotation flag in the `tkhd` Display Matrix. The old pipeline ignored this flag, so the output video was sideways. Fixed: `_get_rotation()` reads the rotation from ffprobe's `side_data_list`, `get_video_info()` swaps width/height for 90°/270° rotations, and `process_video()` applies the matching `transpose` filter to the decode step. ffprobe rotation -90° normalises to 270 → `transpose=1` (90° CW).

**H.264 High 4:4:4 Predictive (profile 244)**: When libx264 receives `rgb24` raw frames without an output `-pix_fmt`, it defaults to profile 244 instead of the standard High profile. Profile 244 is not supported by most hardware decoders. Fixed by adding `-pix_fmt yuv420p` to the encode command.

**Videos with no embedded timestamp**: If a video's `mvhd` creation_time is zero AND the `com.apple.quicktime.creationdate` tag is absent (e.g. a file re-encoded by FFmpeg), the file is skipped with a "No metadata timestamp" warning. This cannot be fixed automatically — the user must process the original source file which has the intact recording time.

**Defensive fps parsing**: `_parse_fps()` prefers `avg_frame_rate` over `r_frame_rate`. For H.264, `r_frame_rate` is sourced from the SPS VUI timing fields; some encoders write garbage values (e.g. `time_scale=16777216, num_units_in_tick=6` → ~1.4 M fps). `avg_frame_rate` is always container-derived and reliable.
