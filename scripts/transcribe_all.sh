#!/bin/bash
# Transcribe all stages sequentially

BASE_DIR="/Users/pengziran/development/pengyuexian/MoonSpeak"
PYTHON="/opt/miniconda3/envs/moonspeak/bin/python"

for stage in 1 2 3 4 5 6 7 8 9 10 11 12 13 14; do
    echo "=========================================="
    echo "Starting Stage $stage at $(date)"
    echo "=========================================="
    $PYTHON "$BASE_DIR/scripts/transcribe_stage.py" $stage
    echo "Stage $stage complete at $(date)"
    echo ""
done

echo "=========================================="
echo "ALL STAGES COMPLETE at $(date)"
echo "=========================================="
