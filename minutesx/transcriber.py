from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Callable

from .audio import AudioChunk


@dataclass(frozen=True)
class TranscriptLine:
    source: str
    started_at: float
    ended_at: float
    text: str


def format_transcript_time(line: TranscriptLine) -> str:
    if line.started_at < 86_400:
        total_seconds = max(0, int(line.started_at))
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"
    return time.strftime("%H:%M:%S", time.localtime(line.started_at))


class LocalWhisperTranscriber(threading.Thread):
    def __init__(
        self,
        *,
        chunk_queue: Queue[AudioChunk],
        line_queue: Queue[TranscriptLine],
        stop_event: threading.Event,
        on_status: Callable[[str], None],
        model_size: str = "small",
        device: str = "cpu",
        language: str = "ja",
    ) -> None:
        super().__init__(daemon=True)
        self.chunk_queue = chunk_queue
        self.line_queue = line_queue
        self.stop_event = stop_event
        self.on_status = on_status
        self.model_size = model_size
        self.device = "cuda" if device == "cuda" else "cpu"
        self.language = language
        self._model = None
        self._model_device = self.device

    def _load_model(self, *, force_cpu: bool = False):
        if force_cpu:
            self._model = None
            self._model_device = "cpu"
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed. Run `uv sync`, then start MinutesX again."
            ) from exc

        if self._model_device == "cpu":
            self.on_status(f"Loading local Whisper model on CPU: {self.model_size}")
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        else:
            self.on_status(f"Loading local Whisper model on GPU: {self.model_size}")
            self._model = WhisperModel(self.model_size, device="cuda", compute_type="auto")
        loaded_device = "GPU" if self._model_device == "cuda" else "CPU"
        self.on_status(f"Whisper model loaded ({loaded_device})")
        return self._model

    def run(self) -> None:
        idle_after_stop_started: float | None = None
        while True:
            if self.stop_event.is_set() and self.chunk_queue.empty():
                if idle_after_stop_started is None:
                    idle_after_stop_started = time.time()
                elif time.time() - idle_after_stop_started > 5:
                    self.on_status("Transcription worker stopped")
                    break
            else:
                idle_after_stop_started = None

            try:
                chunk = self.chunk_queue.get(timeout=0.25)
            except Empty:
                continue

            try:
                seconds = max(0.0, chunk.ended_at - chunk.started_at)
                self.on_status(f"{chunk.source}: transcribing {seconds:.1f}s audio")
                text = self._transcribe(chunk.path)
                if text:
                    self.on_status(f"{chunk.source}: recognized text")
                    self.line_queue.put(
                        TranscriptLine(
                            source=chunk.source,
                            started_at=chunk.started_at,
                            ended_at=chunk.ended_at,
                            text=text,
                        )
                    )
                else:
                    self.on_status(f"{chunk.source}: no speech recognized")
            except Exception as exc:
                self.on_status(f"{chunk.source}: transcription failed: {exc}")
            finally:
                chunk.path.unlink(missing_ok=True)
                self.chunk_queue.task_done()

    def _transcribe(self, path: Path) -> str:
        try:
            return self._transcribe_with_model(path)
        except RuntimeError as exc:
            message = str(exc).lower()
            if "cublas" not in message and "cuda" not in message:
                raise
            self.on_status("GPU transcription failed. Retrying on CPU.")
            return self._transcribe_with_model(path, force_cpu=True)

    def _transcribe_with_model(self, path: Path, *, force_cpu: bool = False) -> str:
        model = self._load_model(force_cpu=force_cpu)
        segments, _info = model.transcribe(
            str(path),
            language=self.language or None,
            vad_filter=True,
            beam_size=5,
        )
        return "".join(segment.text for segment in segments).strip()


def transcribe_audio_file(
    path: Path,
    *,
    model_size: str,
    device: str = "cpu",
    language: str = "ja",
    source: str = "File",
    on_status: Callable[[str], None] | None = None,
) -> list[TranscriptLine]:
    def status(value: str) -> None:
        if on_status:
            on_status(value)

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Run `uv sync`, then start MinutesX again."
        ) from exc

    def run_model(*, device: str, compute_type: str):
        status(f"Loading local Whisper model for file: {model_size} ({device})")
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        status(f"Transcribing imported audio: {path.name}")
        segments, _info = model.transcribe(
            str(path),
            language=language or None,
            vad_filter=True,
            beam_size=5,
        )
        return list(segments)

    selected_device = "cuda" if device == "cuda" else "cpu"
    selected_compute_type = "auto" if selected_device == "cuda" else "int8"
    try:
        segments = run_model(device=selected_device, compute_type=selected_compute_type)
    except RuntimeError as exc:
        message = str(exc).lower()
        if "cublas" not in message and "cuda" not in message:
            raise
        status("GPU transcription failed for file. Retrying on CPU.")
        segments = run_model(device="cpu", compute_type="int8")

    lines: list[TranscriptLine] = []
    for segment in segments:
        text = str(segment.text).strip()
        if not text:
            continue
        lines.append(
            TranscriptLine(
                source=source,
                started_at=float(segment.start),
                ended_at=float(segment.end),
                text=text,
            )
        )
    status(f"Imported audio transcription finished: {len(lines)} lines")
    return lines
