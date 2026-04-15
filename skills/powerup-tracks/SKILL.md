---
name: powerup-tracks
description: Transcribe Power Up Student Audio (Whisper), semantically match to Audioscripts (Ollama nomic-embed-text), copy matched files to Tracks/ with Unit.Track naming. Use when processing a new Power Up level (e.g. Level 2, 3, 4...) — transcribe all mp3, match each to the correct Track number from Audioscripts md files, and organize into a Tracks directory.
---

# Power Up Tracks

Transcribe Student Audio → Match to Audioscripts → Organize into Tracks/

## Directory Structure (per level)

```
books/Power_Up/<LEVEL>/
├── Student_Audio/    # Source mp3 files (CD 1-N), named like "PEC X Power Up CD N Track_YY.mp3"
├── Activity_Audio/   # Activity Book audio (CD N+1), not processed
├── Audioscripts/     # Unit_*.md files with Track X.YY sections
└── Tracks/           # OUTPUT: matched pairs named "X.YY.mp3" + "X.YY.txt"
```

## Workflow

### Step 1: Transcribe

Run in **tmux** (takes 8-12 min per level):

```bash
tmux new-session -d -s pu<N>-transcribe
# Inside tmux:
cd "<PROJECT>/books/Power_Up/<LEVEL>/Student_Audio"
for f in PEC*.mp3; do
    bn=$(basename "$f" .mp3)
    echo "[$(date +%H:%M:%S)] $bn"
    whisper-cli -m ~/.cache/whisper.cpp/ggml-large-v3-turbo.bin -l en -f "$f" --no-timestamps 2>/dev/null > "${bn}.txt"
done
echo "ALL DONE"
```

### Step 2: Semantic Match

Use the bundled script `scripts/match_tracks.py`. It:
1. Parses all `## Track X.YY` sections from `Audioscripts/Unit_*.md`
2. Embeds both transcripts and script tracks via **Ollama nomic-embed-text** (local, no API key)
3. Matches each audio to best script track by cosine similarity
4. Copies matched pairs to `Tracks/` with `X.YY` naming

```bash
python3 scripts/match_tracks.py --audio-dir "books/Power_Up/<LEVEL>/Student_Audio" \
                               --scripts-dir "books/Power_Up/<LEVEL>/Audioscripts" \
                               --output-dir "books/Power_Up/<LEVEL>/Tracks" \
                               --threshold 0.4
```

**Thresholds:**
- `>0.6`: High confidence, auto-copy
- `0.4-0.6`: Medium, auto-copy but flag for review
- `<0.4`: Skip (Karaoke, Intro, or no matching audio)

### Step 3: Review & Fix Chants

After matching, some Chant tracks will have low scores because Whisper only transcribes the instruction ("Say the chant") not the lyrics. These need **manual matching** by page number:

- Audio transcript says "page X, activity N" → look at Audioscripts for the corresponding Track
- Typically: activity 1 = Track X.01, activity 2 = Track X.02, etc.
- Karaoke tracks (pure music, no speech) → skip, no script exists

Check which script tracks are missing from Tracks/:
```bash
# List script tracks without audio
python3 scripts/match_tracks.py --audio-dir "..." --scripts-dir "..." --output-dir "..." --check-missing
```

Manually copy unmatched tracks:
```bash
# Example: if CD1 Track_08 is page 7 activity 2 = Track 1.02
cp "Student_Audio/PEC X Power Up CD 1 Track_08.mp3" "Tracks/1.02.mp3"
cp "Student_Audio/PEC X Power Up CD 1 Track_08.txt" "Tracks/1.02.txt"
```

### Step 4: Verify

Verify all files in Tracks/ match their Audioscripts content:

```bash
python3 scripts/match_tracks.py --audio-dir "..." --scripts-dir "..." --output-dir "..." --verify
```

This re-embeds each Tracks/ file against its expected script and reports any mismatches.

## Key Notes

- **CD Track numbers ≠ Script Track numbers**: CD uses sequential numbering (Track_01, Track_02...), Scripts use Unit.Track format (Track 1.01, 5.05). Always use content-based matching.
- **Some Script tracks have no audio**: Stories/poems at the end of units (e.g. Track 9.14, 9.15) may only exist in the PDF, not on the Student Audio CDs.
- **Activity Audio (CD N+1)** is for the Activity Book, not processed here.
- **Whisper model**: whisper-cli with `ggml-large-v3-turbo` (Metal GPU accelerated)
- **Embedding model**: Ollama `nomic-embed-text` (must be running: `ollama serve`)
