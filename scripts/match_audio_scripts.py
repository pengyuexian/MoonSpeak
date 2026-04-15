#!/usr/bin/env python3
"""
Matching using preprocessed Markdown files.
Matches whisper text to the best track within units.
"""

import os
import re

SCRIPTS_DIR = "/Users/pengziran/development/pengyuexian/MoonSpeak/books/Power-Up-2"


def load_tracks_from_units():
    """Load individual track sections from unit markdown files."""
    tracks = {}
    
    for filename in os.listdir(SCRIPTS_DIR):
        if filename.startswith('Unit_') and filename.endswith('.md'):
            filepath = os.path.join(SCRIPTS_DIR, filename)
            with open(filepath, encoding='utf-8') as f:
                content = f.read()
            
            unit_match = re.search(r'Unit_(\d+)', filename)
            if not unit_match:
                continue
            unit_num = unit_match.group(1)
            
            # Find all Track sections using the header format
            # Tracks appear as "Track X.XX" in the text (not as markdown headers)
            track_pattern = r'(?:^|\n)(Track \d+\.\d+)\s*\n(.*?)(?=\nTrack \d+\.\d+\s*\n|$)'
            matches = re.findall(track_pattern, content, re.DOTALL)
            
            for track_header, track_text in matches:
                # Extract track number from header like "Track 5.05"
                track_match = re.search(r'Track (\d+\.\d+)', track_header)
                if track_match:
                    track_num = track_match.group(1)
                    tracks[track_num] = {
                        'text': track_text.strip(),
                        'unit': unit_num,
                        'header': track_header
                    }
    
    return tracks


def word_set_match(whisper, script_text):
    """Match based on word overlap (Jaccard)."""
    w_words = set(re.findall(r"[a-z']+", whisper.lower()))
    s_words = set(re.findall(r"[a-z']+", script_text.lower()))
    
    if not w_words or not s_words:
        return 0.0
    
    intersection = w_words & s_words
    union = w_words | s_words
    
    return len(intersection) / len(union) if union else 0.0


def match_to_tracks(whisper_text, tracks, top_n=5):
    """Match whisper text to tracks, return top N matches."""
    scores = []
    
    for track_num, data in tracks.items():
        score = word_set_match(whisper_text, data['text'])
        preview = data['text'][:80].replace('\n', ' ')
        scores.append((track_num, score, preview))
    
    # Sort by score descending
    scores.sort(key=lambda x: x[1], reverse=True)
    
    return scores[:top_n]


def get_track_text(tracks, track_num):
    """Get the full text for a specific track."""
    if track_num in tracks:
        return tracks[track_num]['text']
    return None


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: match_audio_scripts.py <whisper_text>")
        sys.exit(1)
    
    whisper_text = sys.argv[1]
    
    tracks = load_tracks_from_units()
    print(f"Loaded {len(tracks)} tracks\n")
    
    # Show some track numbers
    track_nums = sorted(tracks.keys())[:10]
    print(f"Sample tracks: {track_nums}\n")
    
    # Match to tracks
    matches = match_to_tracks(whisper_text, tracks)
    
    print(f"Whisper: {whisper_text[:80]}...\n")
    print(f"Top {len(matches)} matches:")
    for track_num, score, preview in matches:
        print(f"  Track {track_num}: {score:.3f}")
        print(f"    Preview: {preview}...")
        print()
