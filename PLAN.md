# VideoTimeStamp — Project Plan

## Overview

A desktop application for private investigators to burn visible timestamps onto video files for use as court evidence. The timestamp is read from the video's embedded metadata and rendered as an on-screen overlay that advances frame-by-frame with the video.

---

## Requirements

| Setting | Value |
|---|---|
| Timestamp source | Video metadata (`creation_time`) — skip file with warning if missing |
| Display format | `15/01/2024 02:30:45 PM` (dd/mm/yyyy hh:mm:ss AM/PM) |
| Position | Bottom-right |
| Interface | Simple GUI |
| Platform | macOS (primary) |
| Timezone | User-selected from Australian timezone dropdown in GUI |

---

## Supported Video Formats

- MP4 (primary)
- MOV
- MTS
- AVI
- MKV
- M4V
- WMV

---

## Tech Stack

| Component | Tool |
|---|---|
| Language | Python 3 (pre-installed on Mac) |
| GUI | Tkinter (built into Python, no extra install) |
| Video processing | FFmpeg |
| Metadata reading | ffprobe (bundled with FFmpeg) |
| Mac package manager | Homebrew (for FFmpeg install) |

---

## File Structure

```
VideoTimeStamp/
├── app.py            ← GUI application (run this to start)
├── processor.py      ← video processing logic (separate from GUI)
├── install.sh        ← one-time setup: installs Homebrew + FFmpeg
├── config.json       ← persisted user defaults (timezone, text style)
├── PLAN.md           ← this file
├── input/            ← drop videos here before processing
├── output/           ← timestamped videos written here
└── logs/             ← one log file per session
```

---

## GUI Layout

```
┌──────────────────────────────────────────────────┐
│                 VideoTimeStamp                   │
├──────────────────────────────────────────────────┤
│  Input folder:  [/path/to/input]           [...]│
│  Output folder: [/path/to/output]          [...]│
│  Timezone:      [AEST (UTC+10) — QLD, NSW… ▼  ]│
│  Text style:    [White text only           ▼  ]│
├──────────────────────────────────────────────────┤
│               [ Process Videos ]                 │
├──────────────────────────────────────────────────┤
│  Progress: ████████░░░░  3 of 5                 │
├──────────────────────────────────────────────────┤
│  ✓ video1.mp4  [Apple]  →  output/video1.mp4   │
│  ✓ video2.mp4  [Sony ]  →  output/video2.mp4   │
│  ⚠ video3.mp4  [Unknown]  — no metadata, skip  │
└──────────────────────────────────────────────────┘
```

### Text Style Options

| # | Label | FFmpeg drawtext parameters | Default |
|---|---|---|---|
| 1 | White text only | `fontcolor=white` | Yes |
| 2 | White text with black outline | `fontcolor=white:borderw=2:bordercolor=black` | No |
| 3 | White text with background box | `fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=5` | No |

The selected style is applied to every video in the batch. The default (`White text only`) is saved to a local config file (`config.json`) so it persists between sessions. The PI can change the default at any time from the dropdown — a "Save as default" button sits beside it.

---

## Processing Logic (per video)

1. Read the first few KB of the file to detect device type from the container header (`ftyp` atom)
2. Extract `creation_time` from the `mvhd` atom
3. If `creation_time` is missing → log a warning, skip the file, show in GUI
4. Apply timezone logic based on detected device:
   - **Apple** (`ftypqt` / QuickTime): `mvhd` is UTC → convert to PI-selected timezone
   - **Sony** (`ftypMSNV`): `mvhd` is local time → use as-is
   - **Unknown**: treat as local time, flag with a warning in the log and GUI
5. Convert the resolved local timestamp to a Unix epoch value for FFmpeg
6. Build FFmpeg `drawtext` filter:
   - Format: `%d/%m/%Y %I:%M:%S %p`
   - Position: bottom-right with 10px padding from edges
   - Text style applied from GUI selection (white only / outline / background box)
   - Timestamp advances frame-by-frame with the video (not a static burn)
7. Re-encode video with `libx264 -crf 18 -preset slow` (high quality, visually lossless)
8. Audio is stream-copied — no re-encode, no quality loss
9. Output file: same filename as source, saved to the output folder
10. Originals in the input folder are never modified

---

## install.sh (one-time setup, macOS)

1. Check if Homebrew is installed — prompt to install if not
2. Run `brew install ffmpeg`
3. Create `input/`, `output/`, `logs/` folders if they don't exist
4. Verify `ffmpeg` and `ffprobe` are available on PATH

---

## Timezone Handling

### Device Behaviour (confirmed from sample files)

| Device Type | What mvhd stores | Timezone tag? |
|---|---|---|
| Apple iPhone (MOV) | UTC | Yes — local time tag with offset (e.g. `+1000`) |
| Sony camera (MP4/MSNV) | Local time | No — no timezone info embedded |

Because Sony and similar cameras store local time with no timezone context, the PI must select the correct timezone in the GUI before processing. The selected timezone is applied to **all files in the batch**.

For Apple files, the app will use the embedded UTC time and convert it to the selected timezone, ignoring the device's own local tag (for consistency across mixed batches).

### Australian Timezone Dropdown

The dropdown will be grouped and ordered geographically. The PI selects the timezone that was active **at the time of recording** (important for historical footage that may span DST transitions).

| Display Label | Abbreviation | UTC Offset | States |
|---|---|---|---|
| AEST — Australian Eastern Standard Time | AEST | UTC+10:00 | QLD, NSW, VIC, TAS, ACT |
| AEDT — Australian Eastern Daylight Time | AEDT | UTC+11:00 | NSW, VIC, TAS, ACT (DST) |
| ACST — Australian Central Standard Time | ACST | UTC+9:30 | SA, NT |
| ACDT — Australian Central Daylight Time | ACDT | UTC+10:30 | SA (DST — NT does not observe DST) |
| AWST — Australian Western Standard Time | AWST | UTC+8:00 | WA (no DST) |

**DST period for reference (for past footage):**
- Clocks go forward (standard → daylight) on the **first Sunday in October**
- Clocks go back (daylight → standard) on the **first Sunday in April**
- Queensland, NT, and WA do not observe DST

### Processing Logic — Timezone

1. PI selects timezone from dropdown before clicking Process
2. For each video, auto-detect the device type:

| Detection Method | Device | `mvhd` interpretation |
|---|---|---|
| Container = QuickTime (`ftypqt`) or has Apple metadata tag | Apple (iPhone/iPad) | UTC → convert to selected timezone |
| Container = `ftypMSNV` | Sony camera | Local time → display as-is, no conversion |
| Anything else | Unknown | Local time → display as-is, warn user |

3. Apply the resolved local time as the starting timestamp for the drawtext overlay
4. Log detected device type per file in the session log

---

## Quality Notes

- Re-encoding is unavoidable when burning a text overlay onto video frames
- `libx264 -crf 18` is visually indistinguishable from the source at typical PI recording quality
- A CRF of 0 is mathematically lossless but produces very large files — not recommended unless required
- Audio is always copied without re-encoding to preserve quality exactly
