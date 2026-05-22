from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SETTINGS_PATH = Path("minutesx-settings.json")

DEFAULT_SETTINGS: dict[str, Any] = {
    "show_logs": False,
    "show_transcript": True,
    "show_summary": True,
    "whisper_model": "small",
    "ollama_model": "gemma4:latest",
    "mic_device": "",
    "pc_device": "",
    "mute_mic": False,
    "mute_pc": False,
}


def load_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        with SETTINGS_PATH.open("r", encoding="utf-8") as file:
            loaded = json.load(file)
    except Exception:
        return dict(DEFAULT_SETTINGS)
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(loaded, dict):
        settings.update(loaded)
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    with SETTINGS_PATH.open("w", encoding="utf-8") as file:
        json.dump(settings, file, ensure_ascii=False, indent=2)
        file.write("\n")
