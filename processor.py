"""
processor.py — Core video processing logic for VideoTimeStamp.

Text overlay uses Pillow (frame-by-frame) rather than FFmpeg's drawtext filter,
so it works regardless of how FFmpeg was compiled.
"""

import json
import os
import struct
import subprocess
import mmap
import tempfile
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

# ── Constants ─────────────────────────────────────────────────────────────────

MAC_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.mts', '.m4v', '.wmv'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}

TIMEZONES = [
    {
        "label":        "AEST (UTC+10:00) \u2014 QLD, NSW, VIC, TAS, ACT",
        "abbreviation": "AEST",
        "offset":       timedelta(hours=10),
        "posix_tz":     "AEST-10",
    },
    {
        "label":        "AEDT (UTC+11:00) \u2014 NSW, VIC, TAS, ACT (DST)",
        "abbreviation": "AEDT",
        "offset":       timedelta(hours=11),
        "posix_tz":     "AEDT-11",
    },
    {
        "label":        "ACST (UTC+09:30) \u2014 SA, NT",
        "abbreviation": "ACST",
        "offset":       timedelta(hours=9, minutes=30),
        "posix_tz":     "ACST-9:30",
    },
    {
        "label":        "ACDT (UTC+10:30) \u2014 SA (DST)",
        "abbreviation": "ACDT",
        "offset":       timedelta(hours=10, minutes=30),
        "posix_tz":     "ACDT-10:30",
    },
    {
        "label":        "AWST (UTC+08:00) \u2014 WA",
        "abbreviation": "AWST",
        "offset":       timedelta(hours=8),
        "posix_tz":     "AWST-8",
    },
]

TEXT_STYLES = [
    {
        "label": "White text only",
    },
    {
        "label": "White text with black outline",
    },
    {
        "label": "White text with background box",
    },
]

TIMEZONE_LABELS     = [tz["label"] for tz in TIMEZONES]
TIMEZONE_BY_LABEL   = {tz["label"]: tz for tz in TIMEZONES}
TEXT_STYLE_LABELS   = [s["label"] for s in TEXT_STYLES]
TEXT_STYLE_BY_LABEL = {s["label"]: s for s in TEXT_STYLES}

DEVICE_LABELS = {
    "apple":   "Apple",
    "sony":    "Sony",
    "image":   "Image",
    "unknown": "Unknown",
}

OUTPUT_MODE_VIDEO = "Video (timestamped)"
OUTPUT_MODE_STILL = "Still image (timestamped)"
OUTPUT_MODE_IMAGE = "Image (timestamped)"
OUTPUT_MODE_SCREENSHOT = "Screenshot image (timestamped)"
OUTPUT_MODE_LABELS = [OUTPUT_MODE_VIDEO, OUTPUT_MODE_STILL, OUTPUT_MODE_IMAGE]


# ── FFmpeg / Pillow checks ────────────────────────────────────────────────────

def check_ffmpeg():
    """Return True if ffmpeg is available on PATH."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def check_pillow():
    """Return True if Pillow is importable."""
    return PILLOW_AVAILABLE


# ── Device detection ──────────────────────────────────────────────────────────

def detect_device(filepath):
    """
    Detect the recording device from the ftyp container header.

    Returns:
        'apple'   — QuickTime (iPhone/iPad). mvhd stores UTC.
        'sony'    — Sony MSNV container. mvhd stores local time.
        'unknown' — Unrecognised header. Treat mvhd as local time.
    """
    with open(filepath, "rb") as f:
        header = f.read(32)
    idx = header.find(b"ftyp")
    if idx == -1:
        return "unknown"
    brand = header[idx + 4: idx + 8]
    if brand == b"qt  ":
        return "apple"
    if brand == b"MSNV":
        return "sony"
    return "unknown"


# ── Metadata extraction ───────────────────────────────────────────────────────

import re as _re

def _parse_iso_with_offset(s):
    """
    Parse an ISO datetime string that may have a timezone offset without a colon,
    e.g. '2026-03-26T07:59:15+1000' or '2026-03-26T07:59:15+10:00'.
    Returns a timezone-aware datetime or None.
    """
    m = _re.match(
        r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})([+-])(\d{2}):?(\d{2})', s.strip())
    if not m:
        return None
    dt_str, sign, hh, mm_ = m.groups()
    dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
    offset = timedelta(hours=int(hh), minutes=int(mm_))
    if sign == "-":
        offset = -offset
    return dt.replace(tzinfo=timezone(offset))


def _clean_metadata_text(value):
    """Normalize common EXIF/XMP text values to a plain Python string."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value).strip().strip("\x00")


def _parse_datetime_value(value, offset_value=None):
    """
    Parse EXIF/XMP datetime values.

    EXIF usually stores local wall time as 'YYYY:MM:DD HH:MM:SS'. Newer files
    may also include OffsetTime tags, which make the result timezone-aware.
    """
    raw = _clean_metadata_text(value)
    if not raw:
        return None

    raw = raw.replace("\x00", "").strip()
    offset_raw = _clean_metadata_text(offset_value)
    iso_candidate = raw.replace("Z", "+00:00")

    try:
        return datetime.fromisoformat(iso_candidate)
    except ValueError:
        pass

    parsed = _parse_iso_with_offset(raw)
    if parsed is not None:
        return parsed

    m = _re.match(
        r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\s*([+-]\d{2}:?\d{2}))?$",
        raw,
    )
    if not m:
        return None

    year, month, day, hour, minute, second, inline_offset = m.groups()
    dt = datetime(
        int(year), int(month), int(day),
        int(hour), int(minute), int(second),
    )
    offset_text = inline_offset or offset_raw
    offset_match = _re.match(r"^([+-])(\d{2}):?(\d{2})$", offset_text)
    if offset_match:
        sign, hh, mm_ = offset_match.groups()
        offset = timedelta(hours=int(hh), minutes=int(mm_))
        if sign == "-":
            offset = -offset
        dt = dt.replace(tzinfo=timezone(offset))
    return dt


def _parse_image_filename_time(filepath):
    """
    Parse common image filename timestamps.

    This is a fallback for exported images that dropped EXIF/XMP capture dates.
    It only accepts explicit date+time filename patterns, never bare dates.
    """
    stem = Path(filepath).stem

    patterns = [
        (
            r"(?P<date>\d{4}-\d{2}-\d{2})\s+at\s+"
            r"(?P<hour>\d{1,2})[.:](?P<minute>\d{2})[.:](?P<second>\d{2})\s*"
            r"(?P<ampm>AM|PM)",
            "%Y-%m-%d %I:%M:%S %p",
        ),
        (
            r"(?P<date>\d{4}-\d{2}-\d{2})[\s_-]+"
            r"(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})",
            "%Y-%m-%d %H:%M:%S",
        ),
        (
            r"(?P<date>\d{8})[\s_-]+"
            r"(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})",
            "%Y%m%d %H:%M:%S",
        ),
        (
            r"(?P<date>\d{4}-\d{2}-\d{2})[\s_-]+"
            r"(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})",
            "%Y-%m-%d %H:%M:%S",
        ),
        (
            r"(?P<date>\d{4})(?P<month>\d{2})(?P<day>\d{2})[_-]"
            r"(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})",
            "%Y-%m-%d %H:%M:%S",
        ),
    ]

    for pattern, fmt in patterns:
        match = _re.search(pattern, stem, _re.IGNORECASE)
        if not match:
            continue
        parts = match.groupdict()
        date_text = parts.get("date")
        if parts.get("month") and parts.get("day"):
            date_text = f"{parts['date']}-{parts['month']}-{parts['day']}"
        text = f"{date_text} {parts['hour']}:{parts['minute']}:{parts['second']}"
        if parts.get("ampm"):
            text += f" {parts['ampm'].upper()}"
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def get_apple_recording_time(filepath):
    """
    Read the com.apple.quicktime.creationdate tag from a QuickTime MOV file.

    iPhones write the actual recording time here as a timezone-aware ISO string
    (e.g. '2026-03-26T07:59:15+1000'). This is more reliable than mvhd because
    the mvhd creation time is updated whenever the file is transferred or copied.

    Returns a timezone-aware datetime or None if the tag is absent.
    """
    with open(filepath, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        m = _re.search(
            rb'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:?\d{2})', mm)
        result = None
        if m:
            result = _parse_iso_with_offset(m.group(1).decode("ascii", errors="replace"))
        mm.close()
    return result


def get_mvhd_time(filepath):
    """
    Extract creation_time from the mvhd atom.

    Returns a NAIVE datetime (no tzinfo). The caller is responsible for
    timezone interpretation — Apple mvhd is UTC, Sony/Unknown is local time.
    Returns None if the atom is missing or the timestamp is zero.
    """
    with open(filepath, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        idx = mm.find(b"mvhd")
        if idx == -1:
            mm.close()
            return None
        version = mm[idx + 4]
        if version == 1:
            ts = struct.unpack(">Q", bytes(mm[idx + 8: idx + 16]))[0]
        else:
            ts = struct.unpack(">I", bytes(mm[idx + 8: idx + 12]))[0]
        mm.close()
    if ts == 0:
        return None
    # Strip tzinfo — return naive so the caller can attach the correct timezone
    return (MAC_EPOCH + timedelta(seconds=ts)).replace(tzinfo=None)


def get_creation_time(filepath, device_type):
    """
    Return the best available creation time for the given device type.

    Apple  → com.apple.quicktime.creationdate tag (timezone-aware, actual recording time).
             Falls back to mvhd with UTC attached if the tag is absent.
    Sony / Unknown → mvhd as a naive datetime (caller attaches the selected timezone).

    Returns (datetime, source_label) or (None, None).
    """
    if device_type == "apple":
        dt = get_apple_recording_time(filepath)
        if dt is not None:
            return dt, "Apple creationdate tag"
        # mvhd fallback — Apple mvhd is UTC, so attach UTC tzinfo explicitly
        dt = get_mvhd_time(filepath)
        if dt is not None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt, "mvhd (UTC fallback)"
    else:
        # Sony MSNV (Action Cam / Handycam) stores UTC in mvhd — attach UTC so it
        # is correctly converted to the user-selected timezone for display.
        dt = get_mvhd_time(filepath)
        if dt is not None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt, "mvhd (UTC)"


def _extract_xmp_datetime(info):
    """Return the first usable datetime found in Pillow image text/XMP fields."""
    candidate_keys = (
        "DateTimeOriginal",
        "DateTimeDigitized",
        "CreateDate",
        "CreationDate",
        "ModifyDate",
        "date:create",
        "date:modify",
    )
    for key in candidate_keys:
        dt = _parse_datetime_value(info.get(key))
        if dt is not None:
            return dt, key

    xmp_values = []
    for key in ("XML:com.adobe.xmp", "xmp"):
        value = info.get(key)
        if value:
            xmp_values.append(_clean_metadata_text(value))

    for xmp in xmp_values:
        for tag in (
            "DateTimeOriginal",
            "DateTimeDigitized",
            "CreateDate",
            "CreationDate",
            "DateCreated",
            "ModifyDate",
        ):
            patterns = [
                rf"<[^>]*{tag}[^>]*>([^<]+)</[^>]+>",
                rf"\b[^:=\s]*{tag}\s*=\s*[\"']([^\"']+)[\"']",
            ]
            for pattern in patterns:
                match = _re.search(pattern, xmp, _re.IGNORECASE)
                if match:
                    dt = _parse_datetime_value(match.group(1))
                    if dt is not None:
                        return dt, f"XMP {tag}"
    return None, None


def get_image_creation_time(filepath):
    """
    Return the best available creation time for an image file.

    Embedded EXIF/XMP dates are preferred. Some export/share workflows omit
    embedded capture dates, so common image filename timestamps are accepted as
    a controlled fallback. Returned filename/EXIF datetimes are usually naive
    and are interpreted in the user-selected timezone by resolve_unix_timestamp().
    """
    if PILLOW_AVAILABLE:
        try:
            with Image.open(filepath) as img:
                exif = img.getexif()
                exif_candidates = (
                    (36867, 36881, "EXIF DateTimeOriginal"),
                    (36868, 36882, "EXIF DateTimeDigitized"),
                    (306, 36880, "EXIF DateTime"),
                )
                for date_tag, offset_tag, source in exif_candidates:
                    dt = _parse_datetime_value(exif.get(date_tag), exif.get(offset_tag))
                    if dt is not None:
                        return dt, source

                dt, source = _extract_xmp_datetime(img.info)
                if dt is not None:
                    return dt, source
        except OSError:
            return None, None

    dt = _parse_image_filename_time(filepath)
    if dt is not None:
        return dt, "image filename"
    return None, None


# ── Timezone resolution ───────────────────────────────────────────────────────

def resolve_unix_timestamp(creation_time, device_type, tz_offset):
    """
    Convert the creation datetime to a UTC Unix timestamp for display.

    Timezone-aware datetime (Apple) → use .timestamp() directly.
    Naive datetime (Sony/Unknown)   → attach user-selected timezone first.
    """
    if creation_time.tzinfo is not None:
        return int(creation_time.timestamp())
    else:
        local_dt = creation_time.replace(tzinfo=timezone(tz_offset))
        return int(local_dt.timestamp())


# ── Font discovery ────────────────────────────────────────────────────────────

def find_system_font():
    """Return a path to a usable TrueType font on macOS or Linux."""
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


# ── Timestamp formatting ──────────────────────────────────────────────────────

def format_timestamp(unix_ts, tz_offset):
    """Format a Unix timestamp as dd/mm/yyyy hh:mm:ss AM/PM in the given timezone."""
    dt = datetime.fromtimestamp(unix_ts, tz=timezone(tz_offset))
    return dt.strftime("%d/%m/%Y %I:%M:%S %p")


def _rotation_filter(rotation):
    """Map display rotation to an ffmpeg video filter string."""
    if rotation == 270:
        return "transpose=1"  # 90° CW
    if rotation == 90:
        return "transpose=2"  # 90° CCW
    if rotation == 180:
        return "hflip,vflip"
    return None


def _build_text_style(width, height):
    """Resolve font and scale-aware drawing parameters for a frame/image size."""
    font_path    = find_system_font()
    font_size    = max(20, height // 28)
    edge_padding = max(20, width  // 60)
    outline_w    = max(2,  font_size // 10)
    try:
        font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
    return font, font_size, edge_padding, outline_w


def _draw_timestamp(img, ts_text, text_style_label, font, font_size, edge_padding, outline_w):
    """Draw timestamp text onto an RGB Pillow image and return the modified image."""
    draw = ImageDraw.Draw(img)

    bbox   = draw.textbbox((0, 0), ts_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = img.width  - text_w - edge_padding
    y = img.height - text_h - edge_padding

    if text_style_label == "White text only":
        draw.text((x, y), ts_text, font=font, fill=(255, 255, 255))

    elif text_style_label == "White text with black outline":
        ow = outline_w
        for ox, oy in [(-ow, 0), (ow, 0), (0, -ow), (0, ow),
                       (-ow, -ow), (ow, -ow), (-ow, ow), (ow, ow)]:
            draw.text((x + ox, y + oy), ts_text, font=font, fill=(0, 0, 0))
        draw.text((x, y), ts_text, font=font, fill=(255, 255, 255))

    elif text_style_label == "White text with background box":
        box_pad = max(6, font_size // 8)
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ov_draw = ImageDraw.Draw(overlay)
        ov_draw.rectangle(
            [x - box_pad, y - box_pad, x + text_w + box_pad, y + text_h + box_pad],
            fill=(0, 0, 0, 128),
        )
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)
        draw.text((x, y), ts_text, font=font, fill=(255, 255, 255))

    return img


# ── Video info ────────────────────────────────────────────────────────────────

def _parse_fps(stream):
    """
    Resolve playback fps from a ffprobe stream dict.

    avg_frame_rate is preferred over r_frame_rate as a defensive measure:
    some H.264 encoders write garbage SPS VUI timing values that can make
    r_frame_rate report millions of fps.  avg_frame_rate is derived from the
    container's stts table and is always reliable.
    """
    for key in ("avg_frame_rate", "r_frame_rate"):
        raw = stream.get(key, "0/0")
        parts = raw.split("/")
        if len(parts) != 2:
            continue
        try:
            num, den = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if den > 0:
            fps = num / den
            if 1.0 <= fps <= 300.0:
                return fps
    return 25.0


def _get_rotation(stream):
    """
    Return the display rotation (0, 90, 180, or 270) from the stream's Display Matrix.

    ffprobe returns the degrees CCW to rotate the frame for correct display.
    -90 (iPhone landscape) normalises to 270.
    """
    for sd in stream.get("side_data_list", []):
        if sd.get("side_data_type") == "Display Matrix":
            rot = sd.get("rotation", 0)
            return int(round(rot)) % 360
    return 0


def get_video_info(filepath):
    """Return width, height, fps, and rotation of the first video stream via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        str(filepath),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width    = int(stream["width"])
            height   = int(stream["height"])
            fps      = _parse_fps(stream)
            rotation = _get_rotation(stream)
            # ffprobe reports stored dimensions; swap for 90°/270° so callers
            # always receive the correct display (output) dimensions.
            if rotation in (90, 270):
                width, height = height, width
            return {"width": width, "height": height, "fps": fps, "rotation": rotation}
    raise ValueError(f"No video stream found in {filepath}")


# ── Frame-by-frame processing with Pillow ─────────────────────────────────────

def process_video(input_path, output_path, unix_ts, text_style_label, tz_offset):
    """
    Burn the timestamp overlay onto a video using Pillow for text rendering.

    FFmpeg decodes raw frames → Python/Pillow draws text → FFmpeg re-encodes.
    Quality: libx264 CRF 18. Audio is stream-copied.

    Returns: (success: bool, stderr: str)
    """
    if not PILLOW_AVAILABLE:
        return False, "Pillow is not installed. Run: bash install.sh"

    info = get_video_info(input_path)
    width, height, fps = info["width"], info["height"], info["fps"]
    rotation  = info.get("rotation", 0)
    frame_size = width * height * 3  # RGB24 bytes per frame

    # ── Font and scale-aware measurements ────────────────────────────────────
    font, font_size, edge_padding, outline_w = _build_text_style(width, height)

    # ── Extract audio to a temp file ──────────────────────────────────────────
    tmp_audio = tempfile.NamedTemporaryFile(suffix=".m4a", delete=False)
    tmp_audio.close()

    audio_result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(input_path), "-vn", "-acodec", "copy", tmp_audio.name],
        capture_output=True,
    )
    has_audio = audio_result.returncode == 0 and os.path.getsize(tmp_audio.name) > 0

    # ── Decode process (video frames → stdout) ────────────────────────────────
    # Apply rotation from the Display Matrix so the output is correctly oriented.
    # ffprobe rotation = degrees CCW to rotate for correct display.
    # 270 = iPhone landscape (-90 normalised): rotate 90° CW.
    # Disable ffmpeg's implicit auto-rotation so we apply rotation exactly once
    # via the explicit filters below. Without this, iPhone clips with a display
    # matrix can be rotated twice and produce corrupted-looking frames.
    decode_cmd = ["ffmpeg", "-noautorotate", "-i", str(input_path)]
    rot_filter = _rotation_filter(rotation)
    if rot_filter:
        decode_cmd += ["-vf", rot_filter]
    decode_cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-an", "pipe:1"]

    # ── Encode process (stdin → output file) ──────────────────────────────────
    # -pix_fmt yuv420p forces standard H.264 High profile.  Without it, libx264
    # receives rgb24 and defaults to High 4:4:4 Predictive (profile 244), which
    # is incompatible with most hardware decoders.
    encode_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "pipe:0",
    ]
    if has_audio:
        encode_cmd += ["-i", tmp_audio.name]
    encode_cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p"]
    if has_audio:
        encode_cmd += ["-c:a", "copy"]
    encode_cmd += [str(output_path)]

    decode_proc = subprocess.Popen(
        decode_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    encode_proc = subprocess.Popen(
        encode_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    success = True
    stderr  = ""
    frame_num = 0

    try:
        while True:
            raw = decode_proc.stdout.read(frame_size)
            if len(raw) < frame_size:
                break

            frame_unix_ts = unix_ts + (frame_num / fps)
            ts_text = format_timestamp(frame_unix_ts, tz_offset)

            img = Image.frombytes("RGB", (width, height), raw)
            img = _draw_timestamp(
                img, ts_text, text_style_label, font, font_size, edge_padding, outline_w
            )

            encode_proc.stdin.write(img.tobytes())
            frame_num += 1

    except BrokenPipeError:
        success = False
    finally:
        try:
            encode_proc.stdin.close()
        except Exception:
            pass
        decode_proc.wait()
        _, enc_err = encode_proc.communicate()
        stderr = enc_err.decode("utf-8", errors="replace")
        if encode_proc.returncode != 0:
            success = False
        try:
            os.unlink(tmp_audio.name)
        except Exception:
            pass

    return success, stderr


def process_still(input_path, output_path, unix_ts, text_style_label, tz_offset, still_time_seconds):
    """
    Extract one frame from input_path, burn the timestamp, and save as JPG.

    Returns: (success: bool, stderr: str)
    """
    if not PILLOW_AVAILABLE:
        return False, "Pillow is not installed. Run: bash install.sh"

    info = get_video_info(input_path)
    width, height = info["width"], info["height"]
    rotation = info.get("rotation", 0)
    frame_size = width * height * 3
    still_time_seconds = max(0.0, float(still_time_seconds))

    decode_cmd = [
        "ffmpeg", "-v", "error",
        "-noautorotate",
        "-ss", f"{still_time_seconds:.3f}",
        "-i", str(input_path),
    ]
    rot_filter = _rotation_filter(rotation)
    if rot_filter:
        decode_cmd += ["-vf", rot_filter]
    decode_cmd += ["-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-an", "pipe:1"]

    result = subprocess.run(decode_cmd, capture_output=True)
    if result.returncode != 0:
        return False, result.stderr.decode("utf-8", errors="replace")
    if len(result.stdout) < frame_size:
        return False, f"No frame decoded at {still_time_seconds:.3f}s"

    img = Image.frombytes("RGB", (width, height), result.stdout[:frame_size])
    ts_text = format_timestamp(unix_ts + still_time_seconds, tz_offset)
    font, font_size, edge_padding, outline_w = _build_text_style(width, height)
    img = _draw_timestamp(img, ts_text, text_style_label, font, font_size, edge_padding, outline_w)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        img.save(output_path, format="JPEG", quality=95)
    except OSError as exc:
        return False, str(exc)
    return True, ""


def process_image(input_path, output_path, unix_ts, text_style_label, tz_offset):
    """
    Burn the timestamp overlay onto a JPEG/PNG image.

    Returns: (success: bool, stderr: str)
    """
    if not PILLOW_AVAILABLE:
        return False, "Pillow is not installed. Run: bash install.sh"

    try:
        with Image.open(input_path) as src:
            img = ImageOps.exif_transpose(src).convert("RGB")
    except OSError as exc:
        return False, str(exc)

    ts_text = format_timestamp(unix_ts, tz_offset)
    font, font_size, edge_padding, outline_w = _build_text_style(img.width, img.height)
    img = _draw_timestamp(img, ts_text, text_style_label, font, font_size, edge_padding, outline_w)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    suffix = output_path.suffix.lower()
    try:
        if suffix in (".jpg", ".jpeg"):
            img.save(output_path, format="JPEG", quality=95)
        elif suffix == ".png":
            img.save(output_path, format="PNG")
        else:
            img.save(output_path)
    except OSError as exc:
        return False, str(exc)
    return True, ""


# ── Batch processing ──────────────────────────────────────────────────────────

def process_folder(
    input_dir,
    output_dir,
    timezone_label,
    text_style_label,
    output_mode_label=OUTPUT_MODE_VIDEO,
    still_time_seconds=0.0,
    on_progress=None,
    on_result=None,
    log_dir=None,
):
    """
    Process supported files found in input_dir for the selected output mode.

    Args:
        input_dir       : Source folder containing videos or images.
        output_dir      : Destination folder for timestamped output.
        timezone_label  : Key from TIMEZONE_LABELS selected in the GUI.
        text_style_label: Key from TEXT_STYLE_LABELS selected in the GUI.
        output_mode_label: OUTPUT_MODE_VIDEO, OUTPUT_MODE_STILL, or OUTPUT_MODE_IMAGE.
        still_time_seconds: Frame time used in still mode.
        on_progress     : Optional callback(current, total, filename).
        on_result       : Optional callback(filename, device, success, message).
        log_dir         : Optional path for session log file.
    """
    input_dir  = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tz_info   = TIMEZONE_BY_LABEL[timezone_label]
    tz_offset = tz_info["offset"]
    still_mode = (output_mode_label == OUTPUT_MODE_STILL)
    image_mode = output_mode_label in (OUTPUT_MODE_IMAGE, OUTPUT_MODE_SCREENSHOT)

    # ── Session log ───────────────────────────────────────────────────────────
    logger = None
    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        log_file = log_path / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        handler  = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
        logger = logging.getLogger(f"vts.{log_file.stem}")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.propagate = False

    # ── File discovery ────────────────────────────────────────────────────────
    allowed_extensions = IMAGE_EXTENSIONS if image_mode else VIDEO_EXTENSIONS
    files = sorted(
        f for f in input_dir.iterdir()
        if f.is_file() and f.suffix.lower() in allowed_extensions
    )
    total = len(files)

    if logger:
        logger.info(
            f"Session start — {total} file(s) | "
            f"Timezone: {tz_info['abbreviation']} | "
            f"Style: {text_style_label} | "
            f"Mode: {output_mode_label} | "
            f"Still time: {still_time_seconds:.3f}s | "
            f"Pillow: {PILLOW_AVAILABLE}"
        )

    # ── Per-file loop ─────────────────────────────────────────────────────────
    for i, filepath in enumerate(files):
        if on_progress:
            on_progress(i, total, filepath.name)

        if image_mode:
            device = "image"
            creation_time, ts_source = get_image_creation_time(filepath)
        else:
            device = detect_device(filepath)
            creation_time, ts_source = get_creation_time(filepath, device)

        if creation_time is None:
            msg = "No metadata timestamp — skipped"
            if on_result:
                on_result(filepath.name, device, False, msg)
            if logger:
                logger.warning(f"SKIP  {filepath.name}  [{DEVICE_LABELS[device]}]  — {msg}")
            continue

        unix_ts = resolve_unix_timestamp(creation_time, device, tz_offset)
        if logger:
            local_display = format_timestamp(unix_ts, tz_offset)
            logger.info(
                f"TS    {filepath.name}  [{DEVICE_LABELS[device]}]  "
                f"source={ts_source}  display={local_display}"
            )
        if image_mode:
            output_path = output_dir / filepath.name
            success, stderr = process_image(
                filepath,
                output_path,
                unix_ts,
                text_style_label,
                tz_offset,
            )
        elif still_mode:
            output_path = output_dir / f"{filepath.stem}_still.jpg"
            success, stderr = process_still(
                filepath,
                output_path,
                unix_ts,
                text_style_label,
                tz_offset,
                still_time_seconds,
            )
        else:
            output_path = output_dir / filepath.name
            success, stderr = process_video(
                filepath, output_path, unix_ts, text_style_label, tz_offset
            )

        if success:
            msg = str(output_path)
            if logger:
                logger.info(f"OK    {filepath.name}  [{DEVICE_LABELS[device]}]  → {output_path}")
        else:
            msg = "Processing error — check session log"
            if logger:
                logger.error(
                    f"FAIL  {filepath.name}  [{DEVICE_LABELS[device]}]\n"
                    f"{stderr[-800:].strip()}"
                )

        if on_result:
            on_result(filepath.name, device, success, msg)

    if on_progress:
        on_progress(total, total, "")

    if logger:
        logger.info("Session complete")
        for h in logger.handlers:
            h.close()
        logger.handlers.clear()
