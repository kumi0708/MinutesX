from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass

from .transcriber import TranscriptLine, format_transcript_time


DEFAULT_OLLAMA_MODEL = "gemma4:latest"


@dataclass(frozen=True)
class SummaryBlock:
    text: str
    line_count: int
    is_final: bool = True


def list_ollama_models() -> list[str]:
    try:
        completed = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except Exception:
        return []
    if completed.returncode != 0:
        return []

    models: list[str] = []
    for line in completed.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])
    return models


def summarize_lines(
    lines: list[TranscriptLine],
    *,
    model: str = DEFAULT_OLLAMA_MODEL,
) -> SummaryBlock:
    transcript = "\n".join(
        f"[{format_transcript_time(line)}] [{line.source}] {line.text}"
        for line in lines
    )
    summary = call_ollama_summary(transcript, model=model)
    return SummaryBlock(text=summary, line_count=len(lines), is_final=True)


def call_ollama_summary(
    transcript: str,
    *,
    model: str = DEFAULT_OLLAMA_MODEL,
) -> str:
    prompt = (
        "You are a meeting-minutes assistant. Write the answer in Japanese.\n"
        "The transcript below is from the whole meeting. Do not summarize too briefly. "
        "Create detailed meeting minutes so that a reader can understand the topics, "
        "discussion flow, important statements, reasons, concerns, decisions, and open items.\n"
        "Try to infer speaker personas from wording, repeated opinions, responsibilities, "
        "and conversational role. For example, infer labels such as Speaker A, Speaker B, "
        "facilitator, requester, reviewer, implementation owner, or business side when the "
        "transcript gives enough clues. This is only for the summary. Do not claim a real "
        "name unless it appears in the transcript. Mark inferred speaker roles as inferred, "
        "and include the reason or evidence briefly.\n"
        "When several [PC] lines may contain different people, do your best to separate them "
        "by content and phrasing, but keep uncertainty visible. If separation is not reliable, "
        "write that it is unclear.\n"
        "Do not invent facts. If an owner, date, or deadline is unclear, write 'fumei'. "
        "Use timestamps when they help explain important points.\n\n"
        "Required structure in Japanese:\n"
        "# Shosai gijiroku\n\n"
        "## Suitei shiwake / speaker personas\n"
        "- List inferred speakers or roles, evidence, and uncertainty. If unclear, say so.\n\n"
        "## Kaigi no gaiyo\n"
        "- 3 to 6 bullets describing what was discussed.\n\n"
        "## Jikeiretsu no nagare\n"
        "- Explain the flow of the meeting in chronological order with important timestamps "
        "and inferred speakers when useful.\n\n"
        "## Omo na ronten\n"
        "- For each issue, explain the problem, opinions, reasons, who seemed to hold each "
        "position, and how it was handled.\n\n"
        "## Kettei jikou\n"
        "- Decisions. If none, write 'nashi'.\n\n"
        "## TODO / action items\n"
        "- Write task / owner / deadline / notes. Use 'fumei' for unclear fields.\n\n"
        "## Kenen / kaiketsu shite inai koto\n"
        "- Concerns, pending points, and things that need confirmation. If none, write 'nashi'.\n\n"
        "## Jikai kakunin suru to yoi koto\n"
        "- Concrete items to check next.\n\n"
        f"Transcript:\n{transcript}"
    )
    payload = {
        "model": model or DEFAULT_OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_ctx": 8192,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError("Ollama is not reachable at 127.0.0.1:11434") from exc
    return str(body.get("response", "")).strip()
