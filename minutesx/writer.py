from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .transcriber import TranscriptLine, format_transcript_time


def new_transcript_path(root: Path = Path("transcripts")) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return root / f"minutes-{stamp}.md"


def create_transcript(path: Path) -> None:
    title = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("w", encoding="utf-8") as file:
        file.write(f"# MinutesX Transcript\n\nStarted: {title}\n\n")


def append_line(path: Path, line: TranscriptLine) -> None:
    timestamp = format_transcript_time(line)
    with path.open("a", encoding="utf-8") as file:
        file.write(f"- [{timestamp}] [{line.source}] {line.text}\n")


def append_summary(path: Path, summary: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    with path.open("a", encoding="utf-8") as file:
        file.write(f"\n## Summary {timestamp}\n\n{summary}\n\n")
