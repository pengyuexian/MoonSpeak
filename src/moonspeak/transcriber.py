"""
MoonSpeak Transcriber

Uses whisper-cli for speech-to-text transcription.
"""

import subprocess
import os
import tempfile


def transcribe(audio_path: str, model: str = None, language: str = "en") -> str:
    """
    Transcribe audio file using whisper-cli.

    Args:
        audio_path: Path to audio file (.m4a, .wav, .mp3, etc.)
        model: Whisper model to use. Defaults to ggml-large-v3-turbo.
        language: Language code (en, zh, etc.)

    Returns:
        Transcribed text string.
    """
    model = model or os.environ.get("WHISPER_MODEL", "ggml-large-v3-turbo")

    # whisper-cli command
    cmd = [
        "whisper-cli",
        "-m", f"~/.cache/whisper.cpp/{model}.bin",
        "-l", language,
        "-t", "4",  # threads
        "--no-timestamps",  # text only
        audio_path
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60
    )

    if result.returncode != 0:
        raise RuntimeError(f"Whisper transcription failed: {result.stderr}")

    return result.stdout.strip()


def transcribe_with_file(audio_path: str, output_json: str = None) -> dict:
    """
    Transcribe audio and optionally save full result to JSON.

    Args:
        audio_path: Path to audio file
        output_json: Optional path to save full whisper JSON output

    Returns:
        Dictionary with transcribed text and timing info (if available)
    """
    # First get plain text
    text = transcribe(audio_path)

    result = {"text": text, "audio_file": audio_path}

    if output_json:
        import json
        with open(output_json, 'w') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m moonspeak.transcriber <audio_file>")
        sys.exit(1)

    text = transcribe(sys.argv[1])
    print(f"Transcribed: {text}")
