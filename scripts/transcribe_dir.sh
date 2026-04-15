#!/bin/bash
# Transcribe all audio files in a directory using whisper-cli
# Usage: ./transcribe_dir.sh <audio_directory>

DIR="${1:-.}"
MODEL="${WHISPER_MODEL:-ggml-large-v3-turbo}"
MODEL_PATH="$HOME/.cache/whisper.cpp/${MODEL}.bin"

if [ ! -f "$MODEL_PATH" ]; then
    echo "Model not found: $MODEL_PATH"
    exit 1
fi

total=0
done=0
skipped=0
failed=0

cd "$DIR"

# Find all audio files
shopt -s nullglob
files=(*.mp3 *.m4a *.wav *.mp4 *.ogg *.flac *.wma)

total=${#files[@]}
echo "Found $total audio files in $DIR"
echo "Model: $MODEL_PATH"
echo "Starting at $(date)"
echo ""

for f in "${files[@]}"; do
    base="${f%.*}"
    txt_file="${base}.txt"

    if [ -f "$txt_file" ]; then
        skipped=$((skipped + 1))
        echo "[$((done + skipped + failed))/$total] SKIP: $f"
        continue
    fi

    echo -n "[$((done + skipped + failed + 1))/$total] $f -> "

    # Convert to wav first if needed
    wav_file="/tmp/whisper_transcribe.wav"
    if [[ "$f" == *.wav ]]; then
        wav_file="$f"
    else
        ffmpeg -y -i "$f" -ar 16000 -ac 1 -c:a pcm_s16le "$wav_file" 2>/dev/null
    fi

    # Transcribe
    result=$(whisper-cli -m "$MODEL_PATH" -l en -t 4 --no-timestamps "$wav_file" 2>/dev/null)

    if [ $? -eq 0 ] && [ -n "$result" ]; then
        echo "$result" > "$txt_file"
        echo "OK (${#result} chars)"
        done=$((done + 1))
    else
        echo "FAILED"
        failed=$((failed + 1))
    fi

    # Cleanup temp wav
    if [ "$wav_file" != "$f" ] && [ -f "$wav_file" ]; then
        rm -f "$wav_file"
    fi
done

echo ""
echo "Finished at $(date)"
echo "Done: $done | Skipped: $skipped | Failed: $failed | Total: $total"
