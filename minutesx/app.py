from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .audio import (
    AudioChunk,
    default_loopback_id,
    default_microphone_id,
    list_input_devices,
    Recorder,
)
from .settings import load_settings, save_settings
from .summarizer import DEFAULT_OLLAMA_MODEL, SummaryBlock, list_ollama_models, summarize_lines
from .transcriber import (
    LocalWhisperTranscriber,
    TranscriptLine,
    format_transcript_time,
    transcribe_audio_file,
)
from .writer import append_line, append_summary, create_transcript, new_transcript_path


os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

MODEL_OPTIONS = ("base", "small", "medium")


@dataclass(frozen=True)
class DisplayEvent:
    tag: str
    text: str


class MinutesXApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.title("MinutesX")
        self.geometry("920x640")
        self.minsize(760, 480)
        self.rowconfigure(3, weight=1)

        self.devices: list[str] = []
        self.stop_event: threading.Event | None = None
        self.chunk_queue: queue.Queue[AudioChunk] = queue.Queue()
        self.line_queue: queue.Queue[TranscriptLine] = queue.Queue()
        self.summary_queue: queue.Queue[SummaryBlock] = queue.Queue()
        self.workers: list[threading.Thread] = []
        self.transcript_lines: list[TranscriptLine] = []
        self.display_events: list[DisplayEvent] = []
        self.transcript_path: Path | None = None
        self.final_summary_requested = False
        self.final_summary_running = False

        self.mic_var = tk.StringVar()
        self.loopback_var = tk.StringVar()
        self.model_var = tk.StringVar(value=str(self.settings["whisper_model"]))
        self.ollama_model_var = tk.StringVar(
            value=str(self.settings.get("ollama_model") or DEFAULT_OLLAMA_MODEL)
        )
        self.status_var = tk.StringVar(value="Ready")
        self.show_logs_var = tk.BooleanVar(value=bool(self.settings["show_logs"]))
        self.show_transcript_var = tk.BooleanVar(
            value=bool(self.settings["show_transcript"])
        )
        self.show_summary_var = tk.BooleanVar(value=bool(self.settings["show_summary"]))
        self.mute_mic_var = tk.BooleanVar(value=bool(self.settings["mute_mic"]))
        self.mute_pc_var = tk.BooleanVar(value=bool(self.settings["mute_pc"]))
        self.mic_level_var = tk.DoubleVar(value=0)
        self.pc_level_var = tk.DoubleVar(value=0)
        self.mic_level_text = tk.StringVar(value="Mic 0%")
        self.pc_level_text = tk.StringVar(value="PC 0%")

        self._build_ui()
        self.refresh_devices()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(250, self._drain_lines)
        self.after(500, self._drain_summaries)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        toolbar = ttk.Frame(self, padding=12)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)
        toolbar.columnconfigure(4, weight=1)

        ttk.Label(toolbar, text="Mic").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.mic_combo = ttk.Combobox(toolbar, textvariable=self.mic_var, state="readonly")
        self.mic_combo.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        ttk.Checkbutton(
            toolbar,
            text="Mute",
            variable=self.mute_mic_var,
            command=self._on_audio_option_changed,
        ).grid(row=0, column=2, sticky="w", padx=(0, 12))

        ttk.Label(toolbar, text="PC audio").grid(row=0, column=3, sticky="w", padx=(0, 6))
        self.loopback_combo = ttk.Combobox(
            toolbar, textvariable=self.loopback_var, state="readonly"
        )
        self.loopback_combo.grid(row=0, column=4, sticky="ew", padx=(0, 12))
        ttk.Checkbutton(
            toolbar,
            text="Mute",
            variable=self.mute_pc_var,
            command=self._on_audio_option_changed,
        ).grid(row=0, column=5, sticky="w", padx=(0, 12))

        ttk.Label(toolbar, text="Model").grid(row=0, column=6, sticky="w", padx=(0, 6))
        ttk.Combobox(
            toolbar,
            textvariable=self.model_var,
            values=MODEL_OPTIONS,
            width=8,
            state="readonly",
        ).grid(row=0, column=7, sticky="w", padx=(0, 12))

        self.refresh_button = ttk.Button(toolbar, text="Refresh", command=self.refresh_devices)
        self.refresh_button.grid(row=0, column=8, padx=(0, 8))
        self.start_button = ttk.Button(toolbar, text="Start", command=self.start_recording)
        self.start_button.grid(row=0, column=9, padx=(0, 8))
        self.stop_button = ttk.Button(
            toolbar, text="Stop", command=self.stop_recording, state="disabled"
        )
        self.stop_button.grid(row=0, column=10)
        self.import_button = ttk.Button(
            toolbar,
            text="Import Audio",
            command=self.import_audio,
        )
        self.import_button.grid(row=0, column=11, padx=(8, 0))
        self.summary_button = ttk.Button(
            toolbar,
            text="Summarize All",
            command=self.summarize_all,
            state="disabled",
        )
        self.summary_button.grid(row=0, column=12, padx=(8, 0))

        filters = ttk.Frame(self, padding=(12, 0, 12, 8))
        filters.grid(row=1, column=0, sticky="ew")
        filters.columnconfigure(6, weight=1)
        ttk.Label(filters, text="Show").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Checkbutton(
            filters,
            text="Transcript",
            variable=self.show_transcript_var,
            command=self._on_filter_changed,
        ).grid(row=0, column=1, sticky="w", padx=(0, 12))
        ttk.Checkbutton(
            filters,
            text="Summary",
            variable=self.show_summary_var,
            command=self._on_filter_changed,
        ).grid(row=0, column=2, sticky="w", padx=(0, 12))
        ttk.Checkbutton(
            filters,
            text="Logs",
            variable=self.show_logs_var,
            command=self._on_filter_changed,
        ).grid(row=0, column=3, sticky="w")
        ttk.Label(filters, text="Ollama").grid(row=0, column=4, sticky="w", padx=(24, 6))
        self.ollama_combo = ttk.Combobox(
            filters,
            textvariable=self.ollama_model_var,
            values=self._ollama_model_values(),
        )
        self.ollama_combo.grid(row=0, column=5, sticky="ew", padx=(0, 8))
        self.ollama_combo.bind("<<ComboboxSelected>>", self._on_ollama_model_changed)
        self.ollama_combo.bind("<FocusOut>", self._on_ollama_model_changed)
        ttk.Button(
            filters,
            text="Models",
            command=self.refresh_ollama_models,
        ).grid(row=0, column=6, sticky="w")

        meters = ttk.Frame(self, padding=(12, 0, 12, 8))
        meters.grid(row=2, column=0, sticky="ew")
        meters.columnconfigure(1, weight=1)
        meters.columnconfigure(3, weight=1)

        ttk.Label(meters, textvariable=self.mic_level_text, width=8).grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        ttk.Progressbar(
            meters,
            variable=self.mic_level_var,
            maximum=100,
            mode="determinate",
        ).grid(row=0, column=1, sticky="ew", padx=(0, 16))

        ttk.Label(meters, textvariable=self.pc_level_text, width=8).grid(
            row=0, column=2, sticky="w", padx=(0, 6)
        )
        ttk.Progressbar(
            meters,
            variable=self.pc_level_var,
            maximum=100,
            mode="determinate",
        ).grid(row=0, column=3, sticky="ew")

        body = ttk.Frame(self, padding=(12, 0, 12, 12))
        body.grid(row=3, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.text = tk.Text(body, wrap="word", font=("Yu Gothic UI", 11), undo=False)
        self.text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scrollbar.set)

        status = ttk.Label(self, textvariable=self.status_var, anchor="w", padding=(12, 6))
        status.grid(row=4, column=0, sticky="ew")

    def refresh_devices(self) -> None:
        try:
            devices = list_input_devices()
        except Exception as exc:
            messagebox.showerror("MinutesX", str(exc))
            return

        self.devices = [device.id for device in devices]
        self.mic_combo.configure(values=self.devices)
        self.loopback_combo.configure(values=self.devices)

        mic = default_microphone_id()
        loopback = default_loopback_id()
        saved_mic = str(self.settings.get("mic_device") or "")
        saved_pc = str(self.settings.get("pc_device") or "")
        if saved_mic in self.devices:
            self.mic_var.set(saved_mic)
        elif mic:
            self.mic_var.set(mic)
        if saved_pc in self.devices:
            self.loopback_var.set(saved_pc)
        elif loopback:
            self.loopback_var.set(loopback)
        self.status_var.set(f"Found {len(self.devices)} audio input devices")

    def refresh_ollama_models(self) -> None:
        values = self._ollama_model_values()
        self.ollama_combo.configure(values=values)
        if self.ollama_model_var.get() not in values and values:
            self.ollama_model_var.set(values[0])
        self._save_settings()
        self._log(f"Ollama models refreshed: {', '.join(values) if values else 'none'}")

    def _ollama_model_values(self) -> list[str]:
        values = list_ollama_models()
        selected = self.ollama_model_var.get()
        if selected and selected not in values:
            values.insert(0, selected)
        if DEFAULT_OLLAMA_MODEL not in values:
            values.append(DEFAULT_OLLAMA_MODEL)
        return values

    def start_recording(self) -> None:
        mic_id = self.mic_var.get()
        loopback_id = self.loopback_var.get()
        use_mic = bool(mic_id) and not self.mute_mic_var.get()
        use_pc = bool(loopback_id) and not self.mute_pc_var.get()
        if not use_mic and not use_pc:
            messagebox.showwarning(
                "MinutesX",
                "Select at least one unmuted audio device.",
            )
            return

        self.stop_event = threading.Event()
        self._prepare_new_transcript()
        self._save_settings()

        if use_mic:
            self.workers.append(
                Recorder(
                    device_id=mic_id,
                    source="Mic",
                    chunk_queue=self.chunk_queue,
                    stop_event=self.stop_event,
                    on_status=self._set_status,
                    on_level=self._set_level,
                )
            )
        else:
            self._set_level("Mic", 0)
            self._log("Mic is muted by app setting.")

        if use_pc and loopback_id != mic_id:
            self.workers.append(
                Recorder(
                    device_id=loopback_id,
                    source="PC",
                    chunk_queue=self.chunk_queue,
                    stop_event=self.stop_event,
                    on_status=self._set_status,
                    on_level=self._set_level,
                )
            )
        elif self.mute_pc_var.get():
            self._set_level("PC", 0)
            self._log("PC audio is muted by app setting.")

        self.workers.append(
            LocalWhisperTranscriber(
                chunk_queue=self.chunk_queue,
                line_queue=self.line_queue,
                stop_event=self.stop_event,
                on_status=self._set_status,
                model_size=self.model_var.get(),
                language="ja",
            )
        )
        for worker in self.workers:
            worker.start()

        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.refresh_button.configure(state="disabled")
        self.import_button.configure(state="disabled")
        self.summary_button.configure(state="disabled")
        self._set_level("Mic", 0)
        self._set_level("PC", 0)
        self.status_var.set(f"Recording / saving to {self.transcript_path.resolve()}")

    def _prepare_new_transcript(self) -> None:
        self.chunk_queue = queue.Queue()
        self.line_queue = queue.Queue()
        self.summary_queue = queue.Queue()
        self.workers = []
        self.transcript_lines = []
        self.display_events = []
        self.final_summary_requested = False
        self.final_summary_running = False
        self.transcript_path = new_transcript_path()
        create_transcript(self.transcript_path)
        self.text.delete("1.0", "end")
        self._add_event("meta", f"# Transcript: {self.transcript_path.resolve()}\n\n")

    def stop_recording(self) -> None:
        if self.stop_event:
            self.stop_event.set()
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.refresh_button.configure(state="normal")
        self.import_button.configure(state="normal")
        self._log("Stopping. Remaining audio will still be transcribed.")
        self.status_var.set("Stopping. Waiting for remaining transcription, then final summary.")
        self.final_summary_requested = True
        self.after(1000, self._maybe_start_final_summary)
        self._set_level("Mic", 0)
        self._set_level("PC", 0)

    def summarize_all(self) -> None:
        self.final_summary_requested = True
        self._maybe_start_final_summary(force=True)

    def import_audio(self) -> None:
        file_name = filedialog.askopenfilename(
            title="Import audio",
            filetypes=[
                ("Audio files", "*.wav *.mp3 *.m4a *.mp4 *.aac *.flac *.ogg *.wma"),
                ("All files", "*.*"),
            ],
        )
        if not file_name:
            return

        self._save_settings()
        self._prepare_new_transcript()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.import_button.configure(state="disabled")
        self.summary_button.configure(state="disabled")
        threading.Thread(
            target=self._run_import_audio,
            args=(Path(file_name),),
            daemon=True,
        ).start()

    def _run_import_audio(self, path: Path) -> None:
        try:
            self._set_status(f"Importing audio file: {path.name}")
            lines = transcribe_audio_file(
                path,
                model_size=self.model_var.get(),
                language="ja",
                source="File",
                on_status=self._set_status,
            )
            for line in lines:
                self.line_queue.put(line)
            self._set_status(f"Imported {len(lines)} transcript lines from {path.name}")
            self.after(500, self._summarize_imported_audio)
        except Exception as exc:
            self._set_status(f"Audio import failed: {exc}")
        finally:
            self.after(0, self._finish_import_audio)

    def _summarize_imported_audio(self) -> None:
        self.final_summary_requested = True
        self._maybe_start_final_summary(force=True)

    def _finish_import_audio(self) -> None:
        self.start_button.configure(state="normal")
        self.import_button.configure(state="normal")
        self.refresh_button.configure(state="normal")
        if self.transcript_lines:
            self.summary_button.configure(state="normal")

    def _drain_lines(self) -> None:
        while True:
            try:
                line = self.line_queue.get_nowait()
            except queue.Empty:
                break
            timestamp = format_transcript_time(line)
            rendered = f"[{timestamp}] [{line.source}] {line.text}\n"
            self._add_event("transcript", rendered)
            self.transcript_lines.append(line)
            self.summary_button.configure(state="normal")
            if self.transcript_path:
                append_line(self.transcript_path, line)
                self.status_var.set(f"Saved: {self.transcript_path.resolve()}")
            self.line_queue.task_done()
        self.after(250, self._drain_lines)

    def _drain_summaries(self) -> None:
        while True:
            try:
                summary = self.summary_queue.get_nowait()
            except queue.Empty:
                break
            label = "final summary" if summary.is_final else "summary"
            timestamp = datetime.now().strftime("%H:%M:%S")
            rendered = (
                f"\n[{timestamp}] [{label} from {summary.line_count} lines]\n"
                f"{summary.text}\n\n"
            )
            self._add_event("summary", rendered)
            if self.transcript_path:
                append_summary(self.transcript_path, summary.text)
                self.status_var.set(f"Summary saved: {self.transcript_path.resolve()}")
            self.summary_button.configure(state="normal")
            self.summary_queue.task_done()
        self.after(500, self._drain_summaries)

    def _maybe_start_final_summary(self, *, force: bool = False) -> None:
        if self.final_summary_running:
            return
        if not self.transcript_lines:
            if force:
                self._log("No transcript lines to summarize yet.")
            elif self.final_summary_requested:
                self.after(1000, self._maybe_start_final_summary)
            return
        if not force and not self._transcription_finished():
            self.after(1000, self._maybe_start_final_summary)
            return

        lines = list(self.transcript_lines)
        self.final_summary_running = True
        self.summary_button.configure(state="disabled")
        self._set_status(f"Creating final summary from {len(lines)} transcript lines")
        ollama_model = self.ollama_model_var.get() or DEFAULT_OLLAMA_MODEL
        threading.Thread(
            target=self._run_final_summary,
            args=(lines, ollama_model),
            daemon=True,
        ).start()

    def _transcription_finished(self) -> bool:
        transcriber_running = any(
            isinstance(worker, LocalWhisperTranscriber) and worker.is_alive()
            for worker in self.workers
        )
        return (
            not transcriber_running
            and self.chunk_queue.empty()
            and self.line_queue.empty()
        )

    def _run_final_summary(self, lines: list[TranscriptLine], ollama_model: str) -> None:
        try:
            self._set_status(f"Using Ollama model: {ollama_model}")
            summary = summarize_lines(lines, model=ollama_model)
            self.summary_queue.put(summary)
            self._set_status("Final summary created")
        except Exception as exc:
            self._set_status(f"Final summary failed: {exc}")
        finally:
            self.after(0, self._finish_final_summary)

    def _finish_final_summary(self) -> None:
        self.final_summary_running = False
        if self.transcript_lines:
            self.summary_button.configure(state="normal")

    def _add_event(self, tag: str, value: str) -> None:
        self.display_events.append(DisplayEvent(tag=tag, text=value))
        if self._should_show(tag):
            self.text.insert("end", value)
            self.text.see("end")

    def _should_show(self, tag: str) -> bool:
        if tag == "meta":
            return True
        if tag == "log":
            return self.show_logs_var.get()
        if tag == "transcript":
            return self.show_transcript_var.get()
        if tag == "summary":
            return self.show_summary_var.get()
        return True

    def _redraw_events(self) -> None:
        self.text.delete("1.0", "end")
        for event in self.display_events:
            if self._should_show(event.tag):
                self.text.insert("end", event.text)
        self.text.see("end")

    def _set_status(self, value: str) -> None:
        self.after(0, self._apply_status, value)

    def _apply_status(self, value: str) -> None:
        self.status_var.set(value)
        self._log(value)

    def _log(self, value: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._add_event("log", f"[{timestamp}] [log] {value}\n")

    def _set_level(self, source: str, level: float) -> None:
        self.after(0, self._apply_level, source, level)

    def _apply_level(self, source: str, level: float) -> None:
        level = max(0.0, min(100.0, level))
        if source == "Mic":
            display = 0.0 if self.mute_mic_var.get() else level
            self.mic_level_var.set(display)
            suffix = " muted" if self.mute_mic_var.get() else f" {display:.0f}%"
            self.mic_level_text.set(f"Mic{suffix}")
        elif source == "PC":
            display = 0.0 if self.mute_pc_var.get() else level
            self.pc_level_var.set(display)
            suffix = " muted" if self.mute_pc_var.get() else f" {display:.0f}%"
            self.pc_level_text.set(f"PC{suffix}")

    def _on_audio_option_changed(self) -> None:
        self._save_settings()
        self._apply_level("Mic", self.mic_level_var.get())
        self._apply_level("PC", self.pc_level_var.get())

    def _on_filter_changed(self) -> None:
        self._save_settings()
        self._redraw_events()

    def _on_ollama_model_changed(self, _event: object | None = None) -> None:
        self._save_settings()

    def _save_settings(self) -> None:
        save_settings(
            {
                "show_logs": self.show_logs_var.get(),
                "show_transcript": self.show_transcript_var.get(),
                "show_summary": self.show_summary_var.get(),
                "whisper_model": self.model_var.get(),
                "ollama_model": self.ollama_model_var.get(),
                "mic_device": self.mic_var.get(),
                "pc_device": self.loopback_var.get(),
                "mute_mic": self.mute_mic_var.get(),
                "mute_pc": self.mute_pc_var.get(),
            }
        )

    def _on_close(self) -> None:
        self._save_settings()
        self.destroy()


def main() -> None:
    app = MinutesXApp()
    app.mainloop()
