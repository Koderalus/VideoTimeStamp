"""
app.py — VideoTimeStamp GUI

Tkinter application for burning timestamps onto video files.
Run with:  python3 app.py
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import json
import queue
from pathlib import Path

import processor

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR    = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
LOG_DIR     = BASE_DIR / "logs"

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "timezone":      processor.TIMEZONE_LABELS[0],
    "text_style":    processor.TEXT_STYLE_LABELS[0],
    "input_folder":  "",
    "output_folder": "",
}


# ── Main application ──────────────────────────────────────────────────────────

class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("VideoTimeStamp")
        self.resizable(False, False)

        self._config = self._load_config()
        self._queue  = queue.Queue()

        self._build_ui()
        self._check_ffmpeg()
        self._poll_queue()

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, encoding="utf-8") as f:
                    saved = json.load(f)
                return {**DEFAULT_CONFIG, **saved}
            except (json.JSONDecodeError, OSError):
                pass
        return DEFAULT_CONFIG.copy()

    def _save_defaults(self):
        """Persist current dropdown selections as defaults."""
        data = {
            "timezone":      self._tz_var.get(),
            "text_style":    self._style_var.get(),
            "input_folder":  self._input_var.get(),
            "output_folder": self._output_var.get(),
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._config = data
            messagebox.showinfo("Saved", "Default settings saved.")
        except OSError as exc:
            messagebox.showerror("Error", f"Could not save settings:\n{exc}")

    # ── FFmpeg check ──────────────────────────────────────────────────────────

    def _check_ffmpeg(self):
        if not processor.check_ffmpeg():
            messagebox.showerror(
                "FFmpeg not found",
                "FFmpeg is required but was not found on your PATH.\n\n"
                "Run the setup script to install it:\n"
                "    bash install.sh",
            )
            self._process_btn.configure(state="disabled")

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        PAD = {"padx": 12, "pady": 6}
        LABEL_W = 14

        # Title
        tk.Label(
            self, text="VideoTimeStamp",
            font=("Helvetica", 18, "bold"),
        ).grid(row=0, column=0, columnspan=3, pady=(16, 10))

        # ── Input folder ──────────────────────────────────────────────────────
        tk.Label(self, text="Input folder:", anchor="w", width=LABEL_W).grid(
            row=1, column=0, **PAD, sticky="w")
        self._input_var = tk.StringVar(value=self._config["input_folder"])
        tk.Entry(self, textvariable=self._input_var, width=50).grid(
            row=1, column=1, **PAD, sticky="ew")
        tk.Button(self, text="Browse…", command=self._browse_input).grid(
            row=1, column=2, padx=(0, 12))

        # ── Output folder ─────────────────────────────────────────────────────
        tk.Label(self, text="Output folder:", anchor="w", width=LABEL_W).grid(
            row=2, column=0, **PAD, sticky="w")
        self._output_var = tk.StringVar(value=self._config["output_folder"])
        tk.Entry(self, textvariable=self._output_var, width=50).grid(
            row=2, column=1, **PAD, sticky="ew")
        tk.Button(self, text="Browse…", command=self._browse_output).grid(
            row=2, column=2, padx=(0, 12))

        # ── Timezone ──────────────────────────────────────────────────────────
        tk.Label(self, text="Timezone:", anchor="w", width=LABEL_W).grid(
            row=3, column=0, **PAD, sticky="w")
        self._tz_var = tk.StringVar(value=self._config["timezone"])
        ttk.Combobox(
            self,
            textvariable=self._tz_var,
            values=processor.TIMEZONE_LABELS,
            width=48,
            state="readonly",
        ).grid(row=3, column=1, **PAD, sticky="ew")

        # ── Text style + Save as default ──────────────────────────────────────
        tk.Label(self, text="Text style:", anchor="w", width=LABEL_W).grid(
            row=4, column=0, **PAD, sticky="w")
        self._style_var = tk.StringVar(value=self._config["text_style"])
        style_row = tk.Frame(self)
        style_row.grid(row=4, column=1, **PAD, sticky="w")
        ttk.Combobox(
            style_row,
            textvariable=self._style_var,
            values=processor.TEXT_STYLE_LABELS,
            width=37,
            state="readonly",
        ).pack(side="left")
        tk.Button(
            style_row, text="Save as default",
            command=self._save_defaults,
        ).pack(side="left", padx=(10, 0))

        # ── Separator ─────────────────────────────────────────────────────────
        ttk.Separator(self, orient="horizontal").grid(
            row=5, column=0, columnspan=3, sticky="ew", padx=12, pady=8)

        # ── Process button ────────────────────────────────────────────────────
        self._process_btn = tk.Button(
            self,
            text="Process Videos",
            command=self._start_processing,
            bg="#1a6fc4", fg="white",
            font=("Helvetica", 13, "bold"),
            padx=28, pady=8,
            relief="flat",
            cursor="hand2",
            activebackground="#155aa0",
            activeforeground="white",
        )
        self._process_btn.grid(row=6, column=0, columnspan=3, pady=(0, 10))

        # ── Progress ──────────────────────────────────────────────────────────
        self._progress_label = tk.Label(self, text="", font=("Helvetica", 10))
        self._progress_label.grid(row=7, column=0, columnspan=3)

        self._progress_bar = ttk.Progressbar(
            self, length=550, mode="determinate")
        self._progress_bar.grid(
            row=8, column=0, columnspan=3, padx=12, pady=(2, 8))

        # ── Log area ──────────────────────────────────────────────────────────
        log_frame = tk.Frame(self, bd=1, relief="sunken")
        log_frame.grid(
            row=9, column=0, columnspan=3,
            padx=12, pady=(0, 14), sticky="ew")

        self._log = tk.Text(
            log_frame,
            height=10, width=74,
            state="disabled",
            font=("Courier", 10),
            bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="white",
            padx=6, pady=4,
        )
        scrollbar = tk.Scrollbar(log_frame, command=self._log.yview)
        self._log.configure(yscrollcommand=scrollbar.set)
        self._log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Colour tags for log entries
        self._log.tag_config("ok",   foreground="#4ec94e")   # green  — success
        self._log.tag_config("warn", foreground="#e5a100")   # amber  — skipped / error
        self._log.tag_config("info", foreground="#9cdcfe")   # blue   — status lines

    # ── Folder browsers ───────────────────────────────────────────────────────

    def _browse_input(self):
        folder = filedialog.askdirectory(title="Select input folder")
        if folder:
            self._input_var.set(folder)

    def _browse_output(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self._output_var.set(folder)

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log_line(self, message, tag="info"):
        self._log.configure(state="normal")
        self._log.insert("end", message + "\n", tag)
        self._log.see("end")
        self._log.configure(state="disabled")

    # ── Queue polling (thread-safe GUI updates) ───────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                msg  = self._queue.get_nowait()
                kind = msg[0]

                if kind == "progress":
                    _, current, total, filename = msg
                    if total > 0:
                        self._progress_bar["value"] = (current / total) * 100
                    if current < total:
                        self._progress_label.configure(
                            text=f"Processing {current + 1} of {total}: {filename}")
                    else:
                        self._progress_label.configure(
                            text=f"Complete — {total} file(s) processed")

                elif kind == "result":
                    _, filename, device, success, message = msg
                    device_label = processor.DEVICE_LABELS.get(device, "Unknown")
                    if success:
                        out_name = Path(message).name
                        self._log_line(
                            f"  \u2713  {filename}  [{device_label}]  \u2192  {out_name}",
                            "ok")
                    else:
                        self._log_line(
                            f"  \u26a0  {filename}  [{device_label}]  \u2014  {message}",
                            "warn")

                elif kind == "done":
                    self._process_btn.configure(state="normal")

        except queue.Empty:
            pass

        self.after(100, self._poll_queue)

    # ── Processing ────────────────────────────────────────────────────────────

    def _start_processing(self):
        input_dir  = self._input_var.get().strip()
        output_dir = self._output_var.get().strip()

        if not input_dir or not output_dir:
            messagebox.showerror(
                "Missing folders",
                "Please select both an input and an output folder.")
            return

        if not Path(input_dir).is_dir():
            messagebox.showerror(
                "Invalid folder",
                f"Input folder does not exist:\n{input_dir}")
            return

        # Reset UI
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")
        self._progress_bar["value"] = 0
        self._progress_label.configure(text="")
        self._process_btn.configure(state="disabled")

        tz_short = self._tz_var.get().split("\u2014")[0].strip()
        self._log_line(
            f"  Starting  |  Timezone: {tz_short}  |  Style: {self._style_var.get()}",
            "info")

        threading.Thread(
            target=self._run_processing,
            args=(input_dir, output_dir),
            daemon=True,
        ).start()

    def _run_processing(self, input_dir, output_dir):
        def on_progress(current, total, filename):
            self._queue.put(("progress", current, total, filename))

        def on_result(filename, device, success, message):
            self._queue.put(("result", filename, device, success, message))

        processor.process_folder(
            input_dir        = input_dir,
            output_dir       = output_dir,
            timezone_label   = self._tz_var.get(),
            text_style_label = self._style_var.get(),
            on_progress      = on_progress,
            on_result        = on_result,
            log_dir          = str(LOG_DIR),
        )

        self._queue.put(("done",))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
