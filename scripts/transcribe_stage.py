#!/usr/bin/env python3
"""
Transcribe Oxford Reading Tree audio files for one stage.
Saves transcripts as .txt files with the same base name.

Usage:
    python scripts/transcribe_stage.py <stage_number>
    python scripts/transcribe_stage.py 1          # Stage 1
    python scripts/transcribe_stage.py 3          # Stage 3
"""

import os
import sys
import subprocess
import re

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def get_whisper_model() -> str:
    """Get whisper model path."""
    from dotenv import load_dotenv
    load_dotenv()
    model = os.environ.get("WHISPER_MODEL", "ggml-large-v3-turbo")
    return os.path.expanduser(f"~/.cache/whisper.cpp/{model}.bin")


def transcribe_audio(mp3_path: str, model_path: str) -> str:
    """Transcribe a single audio file using whisper-cli."""
    # Convert to WAV first
    wav_path = mp3_path.rsplit('.', 1)[0] + '_temp.wav'
    subprocess.run([
        'ffmpeg', '-y', '-i', mp3_path,
        '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le',
        wav_path
    ], capture_output=True)

    # Transcribe
    result = subprocess.run([
        'whisper-cli',
        '-m', model_path,
        '-l', 'en',
        '-t', '4',
        '--no-timestamps',
        wav_path
    ], capture_output=True, text=True)

    # Clean up temp WAV
    if os.path.exists(wav_path):
        os.remove(wav_path)

    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def transcribe_stage(stage_num: int, base_dir: str = None) -> dict:
    """
    Transcribe all audio files in a stage directory.

    Args:
        stage_num: Stage number (1-14)
        base_dir: Base books directory

    Returns:
        Dict mapping filename to transcript
    """
    if base_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.join(script_dir, '..', 'books', '牛津树1-14级')
        base_dir = os.path.normpath(base_dir)

    # Stage directories are named stage-01, stage-02, etc.
    stage_str = f"stage-{stage_num:02d}"
    stage_top = os.path.join(base_dir, stage_str)
    # Check both locations: stage-01 has 音频/ subfolder, others have mp3 directly
    audio_dir_candidates = [
        os.path.join(stage_top, '音频'),
        stage_top  # mp3 directly in stage folder
    ]
    stage_dir = None
    for candidate in audio_dir_candidates:
        if os.path.exists(candidate):
            mp3s = [f for f in os.listdir(candidate) if f.endswith('.mp3')]
            if mp3s:
                stage_dir = candidate
                break

    if not stage_dir:
        print(f"❌ Stage directory not found for Stage {stage_num}")
        return {}

    # Find all mp3 files
    mp3_files = [f for f in os.listdir(stage_dir) if f.endswith('.mp3')]
    mp3_files.sort()

    if not mp3_files:
        print(f"❌ No mp3 files found in {stage_dir}")
        return {}

    print(f"📚 Stage {stage_num}: found {len(mp3_files)} audio files")

    model_path = get_whisper_model()
    results = {}

    # Create transcripts subdirectory
    transcripts_dir = os.path.join(stage_dir, 'transcripts')
    os.makedirs(transcripts_dir, exist_ok=True)

    for i, mp3_file in enumerate(mp3_files, 1):
        mp3_path = os.path.join(stage_dir, mp3_file)
        base_name = mp3_file.rsplit('.', 1)[0]
        # Clean filename for output
        clean_name = re.sub(r'【公益知识库zscc\.club】', '', base_name)
        txt_file = os.path.join(transcripts_dir, f"{clean_name}.txt")

        print(f"  [{i}/{len(mp3_files)}] {clean_name}... ", end='', flush=True)

        # Check if already transcribed
        if os.path.exists(txt_file):
            with open(txt_file, 'r', encoding='utf-8') as f:
                transcript = f.read().strip()
            print("✅ (cached)")
        else:
            transcript = transcribe_audio(mp3_path, model_path)
            if transcript:
                with open(txt_file, 'w', encoding='utf-8') as f:
                    f.write(transcript)
                print("✅")
            else:
                print("❌ (failed)")

        results[clean_name] = transcript

    print(f"\n✅ Stage {stage_num} complete: {len(mp3_files)} files")
    print(f"   Transcripts saved to: {transcripts_dir}")

    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: python transcribe_stage.py <stage_number>")
        print("Example: python transcribe_stage.py 1")
        sys.exit(1)

    try:
        stage_num = int(sys.argv[1])
    except ValueError:
        print(f"❌ Invalid stage number: {sys.argv[1]}")
        sys.exit(1)

    if stage_num < 1 or stage_num > 14:
        print(f"❌ Stage number must be 1-14, got {stage_num}")
        sys.exit(1)

    print(f"🚀 Starting transcription for Stage {stage_num}")
    results = transcribe_stage(stage_num)

    if results:
        print(f"\n📊 Summary: {len(results)} files processed")


if __name__ == "__main__":
    main()
