# Repository Guidelines

## Project Structure & Module Organization
- `app.py`: Tkinter GUI entry point and user workflow.
- `processor.py`: Core video/image timestamp logic (metadata parsing, FFmpeg/Pillow/pillow-heif pipeline). Keep this module GUI-free.
- `install.sh`: One-time macOS setup (Homebrew, FFmpeg, Python venv, Pillow, pillow-heif, default folders/config).
- `run.sh`: Launch wrapper that uses the interpreter recorded in `.python_path`.
- `config.json`: Persisted defaults (timezone, text style, output mode, still time, input/output folders).
- Runtime folders created by setup: `input/`, `output/`, `logs/`.
- `Scope/` contains sample assets and investigation artifacts; treat as reference data, not source code.

## Build, Test, and Development Commands
- `bash install.sh`: Bootstrap local environment and dependencies.
- `bash run.sh`: Start the desktop app with the configured Python interpreter.
- `.venv/bin/python app.py`: Direct launch for development/debugging.
- `.venv/bin/python -m py_compile app.py processor.py`: Quick syntax validation before committing.

## Coding Style & Naming Conventions
- Python style is PEP 8-oriented with 4-space indentation.
- Use `snake_case` for functions/variables, `UPPER_SNAKE_CASE` for constants, and `PascalCase` for classes.
- Preserve module boundaries: GUI/event-thread code in `app.py`, processing/timezone/video logic in `processor.py`.
- Prefer small, single-purpose functions and explicit docstrings for metadata/timezone behavior.
- Bash scripts should remain portable, explicit, and fail fast (`set -e`).

## Testing Guidelines
- No automated test suite is currently committed.
- Minimum validation for changes:
- Run `.venv/bin/python -m py_compile app.py processor.py` or `python3 -m py_compile app.py processor.py` when the venv is unavailable.
- Process at least one Apple `.mov` and one Sony/MP4 sample (for example from `Scope/Original/`).
- For image-mode changes, process JPEG/PNG/HEIC samples when available and verify EXIF/XMP metadata is preferred over filename fallback.
- Verify timestamp correctness, rotation handling, output playback/image compatibility, HEIC-to-JPEG output, and session log creation in `logs/`.
- If you add automated tests, place them under `tests/` and use `test_*.py` naming (pytest-compatible).

## Timestamp & Media Behavior
- Video modes support `.mp4`, `.mov`, `.avi`, `.mkv`, `.mts`, `.m4v`, and `.wmv`.
- Image mode supports `.jpg`, `.jpeg`, `.png`, `.heic`, and `.heif`.
- HEIC/HEIF inputs require `pillow-heif`; `install.sh` installs it alongside Pillow.
- HEIC/HEIF outputs are written as `.jpg` because HEIC encoding support is not assumed.
- Metadata-derived timestamps must remain the primary source. For images, prefer embedded EXIF/XMP dates, including nested EXIF blocks, before using controlled filename date/time fallbacks.
- Do not silently switch to filesystem timestamps.

## Commit & Pull Request Guidelines
- Follow the repository’s existing commit pattern: short imperative subjects (for example, `Fix video rotation handling`).
- Keep commits focused to one logical change.
- PRs should include:
- What changed and why (root cause if bug fix).
- Commands or manual steps used to validate.
- Evidence for behavior/UI output changes (log snippet or screenshot).
- Linked issue/task when available.

## Security & Configuration Tips
- Do not commit case-sensitive media, generated outputs, or local logs unless explicitly needed.
- Avoid hardcoding user-specific absolute paths in code or `config.json`.
- Preserve metadata-derived timestamp behavior; do not silently switch to filesystem timestamps.
