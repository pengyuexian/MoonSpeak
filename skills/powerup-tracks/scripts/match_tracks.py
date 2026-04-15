#!/usr/bin/env python3
"""
Power Up Tracks: Match Student Audio transcripts to Audioscripts using Ollama embeddings.

Usage:
  # Full match + copy
  python3 match_tracks.py --audio-dir ... --scripts-dir ... --output-dir ... --threshold 0.4

  # Check which script tracks are missing from output
  python3 match_tracks.py --audio-dir ... --scripts-dir ... --output-dir ... --check-missing

  # Verify existing Tracks/ directory
  python3 match_tracks.py --audio-dir ... --scripts-dir ... --output-dir ... --verify
"""

import os, re, glob, json, urllib.request, shutil, argparse
from difflib import SequenceMatcher

OLLAMA_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"


def get_embedding(text):
    body = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
    return result["embedding"]


def cosine_sim(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na > 0 and nb > 0 else 0


def load_script_tracks(scripts_dir):
    """Parse all Unit_*.md files and extract Track X.YY sections."""
    tracks = {}
    for md_file in sorted(glob.glob(os.path.join(scripts_dir, "Unit_*.md"))):
        unit_name = os.path.basename(md_file)
        with open(md_file) as f:
            content = f.read()
        parts = re.split(r'(##\s*Track\s+\d+\.\d+)', content)
        for i in range(1, len(parts), 2):
            label_raw = parts[i].strip().replace('## ', '')
            text = parts[i + 1].strip() if i + 1 < len(parts) else ""
            text = re.split(r'\n##\s*Track\s+\d+\.\d+', text)[0].strip()
            m = re.match(r'Track\s+(\d+)\.(\d+)', label_raw)
            if m:
                label = f"{int(m.group(1))}.{int(m.group(2)):02d}"
                tracks[label] = {'text': text, 'unit': unit_name}
    return tracks


def load_audio_transcripts(audio_dir):
    """Load all whisper transcripts from Student_Audio/."""
    transcripts = {}
    for f in sorted(os.listdir(audio_dir)):
        if not f.endswith('.txt'):
            continue
        m = re.match(r'PEC \d+ Power Up CD (\d+) Track_(\d+)', f)
        if not m:
            continue
        cd, track = int(m.group(1)), int(m.group(2))
        label = f"CD{cd} Track_{track:02d}"
        with open(os.path.join(audio_dir, f)) as tf:
            transcripts[label] = tf.read().strip()
    return transcripts


def cmd_match(audio_dir, scripts_dir, output_dir, threshold):
    """Match audio to scripts and copy to output_dir."""
    print(f"Loading script tracks from {scripts_dir}...")
    script_tracks = load_script_tracks(scripts_dir)
    print(f"  Found {len(script_tracks)} script tracks")

    print(f"Loading audio transcripts from {audio_dir}...")
    audio_transcripts = load_audio_transcripts(audio_dir)
    print(f"  Found {len(audio_transcripts)} audio transcripts")

    # Embed script tracks
    print("Embedding script tracks...")
    script_embs = {}
    for label, data in script_tracks.items():
        if data['text']:
            script_embs[label] = get_embedding(data['text'][:500])

    # Embed audio transcripts
    print("Embedding audio transcripts...")
    audio_embs = {}
    for label, text in audio_transcripts.items():
        if text:
            audio_embs[label] = get_embedding(text[:500])

    # Match
    print("Matching...")
    results = []
    for audio_label, audio_emb in audio_embs.items():
        best_score = 0
        best_track = None
        for track_label, script_emb in script_embs.items():
            score = cosine_sim(audio_emb, script_emb)
            if score > best_score:
                best_score = score
                best_track = track_label
        results.append({
            'audio': audio_label,
            'track': best_track,
            'score': best_score
        })

    # Sort by score descending
    results.sort(key=lambda x: x['score'], reverse=True)

    # Report
    good, weak, bad = 0, 0, 0
    for r in results:
        if r['score'] > 0.6:
            status = "✅"
            good += 1
        elif r['score'] >= threshold:
            status = "⚠️"
            weak += 1
        else:
            status = "❌"
            bad += 1
        print(f"  {r['audio']:<20} → {r['track'] or 'NONE':<10} {r['score']:.3f} {status}")

    print(f"\n  Good(>0.6): {good}, Weak(0.4-0.6): {weak}, Bad(<{threshold}): {bad}")

    # Copy matched files
    os.makedirs(output_dir, exist_ok=True)
    copied = 0
    for r in results:
        if r['score'] < threshold or not r['track']:
            continue
        # Find source files
        audio_label = r['audio']
        m = re.match(r'CD(\d+) Track_(\d+)', audio_label)
        if not m:
            continue
        cd, track = int(m.group(1)), int(m.group(2))

        # Find matching source file
        src_pattern = os.path.join(audio_dir, f"PEC * Power Up CD {cd} Track_{track:02d}")
        src_mp3 = glob.glob(src_pattern + ".mp3")
        src_txt = glob.glob(src_pattern + ".txt")

        if not src_mp3 or not src_txt:
            print(f"  ⚠️ Source not found for {audio_label}")
            continue

        dst_mp3 = os.path.join(output_dir, f"{r['track']}.mp3")
        dst_txt = os.path.join(output_dir, f"{r['track']}.txt")

        if os.path.exists(dst_mp3):
            continue  # Already copied (dedup: keep first/highest score)

        shutil.copy2(src_mp3[0], dst_mp3)
        shutil.copy2(src_txt[0], dst_txt)
        copied += 1

    print(f"\n  Copied {copied} pairs to {output_dir}")

    # Report missing script tracks
    matched_tracks = set(r['track'] for r in results if r['score'] >= threshold)
    missing = sorted(set(script_tracks.keys()) - matched_tracks)
    if missing:
        print(f"\n  ⚠️ Script tracks without audio match ({len(missing)}):")
        for t in missing:
            # Find best score even if below threshold
            best = max((r for r in results if r['track'] == t), key=lambda x: x['score'], default=None)
            if best:
                print(f"    {t}: best={best['audio']} score={best['score']:.3f}")
            else:
                print(f"    {t}: no match")


def cmd_check_missing(audio_dir, scripts_dir, output_dir):
    """Check which script tracks are missing from Tracks/."""
    script_tracks = load_script_tracks(scripts_dir)
    audio_transcripts = load_audio_transcripts(audio_dir)

    # Get existing tracks
    existing = set()
    if os.path.isdir(output_dir):
        for f in os.listdir(output_dir):
            if f.endswith('.mp3'):
                existing.add(f.replace('.mp3', ''))

    missing = sorted(set(script_tracks.keys()) - existing)
    print(f"Script tracks: {len(script_tracks)}, In Tracks/: {len(existing)}, Missing: {len(missing)}")

    if missing:
        print(f"\nMissing tracks:")
        for t in missing:
            data = script_tracks[t]
            print(f"  {t} ({data['unit']}): {data['text'][:80].replace(chr(10), ' ')}")


def cmd_verify(audio_dir, scripts_dir, output_dir):
    """Verify all files in Tracks/ match their expected script content."""
    script_tracks = load_script_tracks(scripts_dir)

    if not os.path.isdir(output_dir):
        print(f"Output dir not found: {output_dir}")
        return

    results = []
    for f in sorted(os.listdir(output_dir)):
        if not f.endswith('.txt'):
            continue
        track_label = f.replace('.txt', '')

        if track_label not in script_tracks:
            results.append((track_label, -1, "NOT IN SCRIPTS"))
            continue

        with open(os.path.join(output_dir, f)) as tf:
            transcript = tf.read().strip()

        if not transcript:
            results.append((track_label, -1, "EMPTY"))
            continue

        script_text = script_tracks[track_label]['text']
        if not script_text:
            results.append((track_label, -1, "NO SCRIPT TEXT"))
            continue

        emb_trans = get_embedding(transcript[:500])
        emb_script = get_embedding(script_text[:500])
        score = cosine_sim(emb_trans, emb_script)
        results.append((track_label, score, ""))

    # Report
    ok, warn, fail = 0, 0, 0
    for label, score, note in results:
        if score == -1:
            status = "❌"
            fail += 1
            print(f"  {label}: {note}")
        elif score > 0.5:
            status = "✅"
            ok += 1
        elif score > 0.3:
            status = "⚠️"
            warn += 1
        else:
            status = "❌"
            fail += 1
        if score >= 0:
            print(f"  {label}: {score:.3f} {status}")

    print(f"\n  OK(>0.5): {ok}, Warning(0.3-0.5): {warn}, Fail(<0.3): {fail}")


def main():
    parser = argparse.ArgumentParser(description="Power Up Tracks: match audio to scripts")
    parser.add_argument('--audio-dir', required=True, help='Student_Audio directory')
    parser.add_argument('--scripts-dir', required=True, help='Audioscripts directory')
    parser.add_argument('--output-dir', required=True, help='Output Tracks directory')
    parser.add_argument('--threshold', type=float, default=0.4, help='Min cosine similarity (default: 0.4)')
    parser.add_argument('--check-missing', action='store_true', help='List script tracks missing from output')
    parser.add_argument('--verify', action='store_true', help='Verify Tracks/ content matches scripts')
    args = parser.parse_args()

    if args.check_missing:
        cmd_check_missing(args.audio_dir, args.scripts_dir, args.output_dir)
    elif args.verify:
        cmd_verify(args.audio_dir, args.scripts_dir, args.output_dir)
    else:
        cmd_match(args.audio_dir, args.scripts_dir, args.output_dir, args.threshold)


if __name__ == '__main__':
    main()
