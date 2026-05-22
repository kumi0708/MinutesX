from __future__ import annotations

import threading
import time
import warnings
import wave
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from tempfile import NamedTemporaryFile
from typing import Callable

import numpy as np


SAMPLE_RATE = 16_000
CHANNELS = 1


@dataclass(frozen=True)
class AudioDevice:
    id: str
    name: str
    is_loopback: bool


@dataclass(frozen=True)
class AudioChunk:
    source: str
    path: Path
    started_at: float
    ended_at: float


def _soundcard():
    try:
        import soundcard as sc
    except ImportError as exc:
        raise RuntimeError(
            "soundcard is not installed. Run `uv sync`, then start MinutesX again."
        ) from exc
    return sc


def list_input_devices() -> list[AudioDevice]:
    sc = _soundcard()
    devices: list[AudioDevice] = []
    for mic in sc.all_microphones(include_loopback=True):
        name = str(mic.name)
        is_loopback = bool(getattr(mic, "isloopback", False))
        devices.append(AudioDevice(id=name, name=name, is_loopback=is_loopback))
    return devices


def default_microphone_id() -> str | None:
    sc = _soundcard()
    try:
        return str(sc.default_microphone().name)
    except Exception:
        return None


def default_loopback_id() -> str | None:
    sc = _soundcard()
    try:
        speaker_name = str(sc.default_speaker().name)
    except Exception:
        speaker_name = None

    devices = list_input_devices()
    if speaker_name:
        for device in devices:
            if device.is_loopback and device.id == speaker_name:
                return device.id

    for device in devices:
        if device.is_loopback:
            return device.id
    return None


def write_wav(path: Path, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    samples = np.asarray(samples)
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * np.iinfo(np.int16).max).astype(np.int16)

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


class Recorder(threading.Thread):
    def __init__(
        self,
        *,
        device_id: str,
        source: str,
        chunk_queue: Queue[AudioChunk],
        stop_event: threading.Event,
        on_status: Callable[[str], None],
        on_level: Callable[[str, float], None] | None = None,
        chunk_seconds: int = 4,
        level_seconds: float = 0.2,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        super().__init__(daemon=True)
        self.device_id = device_id
        self.source = source
        self.chunk_queue = chunk_queue
        self.stop_event = stop_event
        self.on_status = on_status
        self.on_level = on_level
        self.chunk_seconds = chunk_seconds
        self.level_seconds = level_seconds
        self.sample_rate = sample_rate

    def run(self) -> None:
        sc = _soundcard()
        chunk_frames = self.chunk_seconds * self.sample_rate
        level_frames = max(1, int(self.level_seconds * self.sample_rate))
        try:
            mic = sc.get_microphone(self.device_id, include_loopback=True)
            with mic.recorder(samplerate=self.sample_rate, channels=CHANNELS) as recorder:
                self.on_status(f"{self.source}: recording from {self.device_id}")
                chunk_parts: list[np.ndarray] = []
                chunk_started = time.time()
                buffered_frames = 0
                while not self.stop_event.is_set():
                    with warnings.catch_warnings():
                        try:
                            from soundcard.mediafoundation import SoundcardRuntimeWarning

                            warnings.filterwarnings(
                                "ignore",
                                category=SoundcardRuntimeWarning,
                                message="data discontinuity in recording",
                            )
                        except Exception:
                            warnings.filterwarnings(
                                "ignore",
                                message="data discontinuity in recording",
                            )
                        data = recorder.record(numframes=level_frames)
                    if self.stop_event.is_set() and len(data) == 0:
                        break

                    self._publish_level(data)
                    chunk_parts.append(data)
                    buffered_frames += len(data)

                    if buffered_frames >= chunk_frames:
                        self._queue_chunk(chunk_parts, chunk_started, time.time())
                        chunk_parts = []
                        chunk_started = time.time()
                        buffered_frames = 0

                if chunk_parts:
                    self._queue_chunk(chunk_parts, chunk_started, time.time())
        except Exception as exc:
            self.on_status(f"{self.source}: recording failed: {exc}")
        finally:
            if self.on_level:
                self.on_level(self.source, 0.0)

    def _publish_level(self, data: np.ndarray) -> None:
        if not self.on_level or len(data) == 0:
            return
        samples = np.asarray(data)
        if samples.ndim == 2:
            samples = samples.mean(axis=1)
        rms = float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0.0
        peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
        level = min(100.0, max(rms * 400.0, peak * 100.0))
        self.on_level(self.source, level)

    def _queue_chunk(
        self,
        chunk_parts: list[np.ndarray],
        started: float,
        ended: float,
    ) -> None:
        data = np.concatenate(chunk_parts, axis=0)
        seconds = max(0.0, ended - started)
        with NamedTemporaryFile(
            prefix=f"minutesx-{self.source}-",
            suffix=".wav",
            delete=False,
        ) as tmp:
            path = Path(tmp.name)
        write_wav(path, data, self.sample_rate)
        self.chunk_queue.put(AudioChunk(self.source, path, started, ended))
        self.on_status(f"{self.source}: queued {seconds:.1f}s audio for transcription")
