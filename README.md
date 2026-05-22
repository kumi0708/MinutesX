# MinutesX

MinutesX is a local-first meeting transcription app for Windows. It captures:

- Your PC microphone
- PC output audio from web meetings via Windows loopback audio

Transcription runs locally with `faster-whisper`. No cloud transcription API is used.
Meeting summaries are generated through a local Ollama server when available.

## Requirements

- Windows
- Python 3.10, 3.11, or 3.12
- [uv](https://docs.astral.sh/uv/)
- Optional: [Ollama](https://ollama.com/) for meeting summaries

## Setup

Install dependencies:

```powershell
uv sync
```

Run the app:

```powershell
uv run minutesx
```

The first transcription run may download the selected Whisper model. After the model is cached locally, transcription can run offline.

If you want summaries, install Ollama and pull a model, for example:

```powershell
ollama pull gemma4:latest
```

Then choose the model in the app's Ollama field.

## Notes

- For Japanese meetings, start with the `small` model. Use `base` for faster but less accurate transcription, or `medium` for better accuracy on a stronger PC.
- The system-audio device is usually shown as a loopback device. If it does not appear, make sure Windows audio output is active, then press refresh.
- Output is written to `transcripts/` as a timestamped `.md` file.
- Personal settings are written to `minutesx-settings.json`.
- Generated transcripts, debug audio, local settings, virtual environments, and package metadata are excluded from Git.
