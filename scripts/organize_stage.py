#!/usr/bin/env python3
"""
Standardize Oxford Reading Tree filenames.
1. Remove source tag 【公益知识库zscc.club】
2. Convert to lowercase
3. Replace spaces with underscores
4. Replace &#39; with apostrophe, then sanitize
"""

import os
import re
import sys
import shutil

BASE_DIR = "/Users/pengziran/development/pengyuexian/MoonSpeak/books/Oxford-Reading-Tree"
STAGE_DIR = os.path.join(BASE_DIR, "Stage01")
SOURCE_TAG = "【公益知识库zscc.club】"


def clean_name(filename: str) -> str:
    """Clean filename to standardized format."""
    # Remove source tag
    name = filename.replace(SOURCE_TAG, "")

    # Replace HTML entities
    name = name.replace("&#39;", "'")
    name = name.replace("&amp;", "&")

    # Get base (without extension)
    if '.' in name:
        base, ext = name.rsplit('.', 1)
        ext = ext.lower()
    else:
        base = name
        ext = ""

    # Convert to lowercase
    base = base.lower()

    # Replace apostrophes with nothing (or keep for readability)
    # e.g., "chip's_robot" stays as is

    # Replace multiple spaces/special chars with single underscore
    base = re.sub(r"[_\s,]+", "_", base)  # spaces and commas to underscore
    base = re.sub(r"[!]+", "", base)  # remove exclamation marks
    base = re.sub(r"[^a-z0-9'_-]", "", base)  # remove other special chars
    base = re.sub(r"_+", "_", base)  # collapse multiple underscores
    base = base.strip('_')

    return f"{base}.{ext}" if ext else base


def standardize_all_files():
    """List all files and their standardized names."""
    pdf_dir = "/Users/pengziran/development/pengyuexian/MoonSpeak/books/牛津树1-14级/stage-01/PDF"
    mp3_dir = "/Users/pengziran/development/pengyuexian/MoonSpeak/books/牛津树1-14级/stage-01/音频"
    txt_dir = "/Users/pengziran/development/pengyuexian/MoonSpeak/books/牛津树1-14级/stage-01/音频/transcripts"

    all_files = []

    for f in os.listdir(pdf_dir):
        if f.endswith('.pdf'):
            clean = clean_name(f)
            all_files.append((os.path.join(pdf_dir, f), clean))

    for f in os.listdir(mp3_dir):
        if f.endswith('.mp3'):
            clean = clean_name(f)
            all_files.append((os.path.join(mp3_dir, f), clean))

    for f in os.listdir(txt_dir):
        if f.endswith('.txt'):
            clean = clean_name(f)
            all_files.append((os.path.join(txt_dir, f), clean))

    # Group by standardized name
    by_clean = {}
    for original, clean in all_files:
        if clean not in by_clean:
            by_clean[clean] = []
        by_clean[clean].append(original)

    print("=" * 70)
    print("STANDARDIZATION MAP")
    print("=" * 70)

    for clean, originals in sorted(by_clean.items()):
        print(f"\n{clean}:")
        for o in originals:
            fname = os.path.basename(o)
            if fname != clean:
                print(f"  {fname}")

    return by_clean


def rename_files(dry_run: bool = True):
    """Rename files to standardized names."""
    by_clean = standardize_all_files()

    if dry_run:
        print("\n\n🔍 DRY RUN - no files renamed. Run with --apply to apply.")

    changes = 0
    for clean, originals in by_clean.items():
        for original in originals:
            if os.path.basename(original) == clean:
                continue  # already clean

            if dry_run:
                print(f"  Would rename: {os.path.basename(original)} -> {clean}")
            else:
                dst = os.path.join(os.path.dirname(original), clean)
                print(f"  Renaming: {os.path.basename(original)} -> {clean}")
                os.rename(original, dst)
            changes += 1

    if not dry_run:
        print(f"\n✅ Renamed {changes} files")
    else:
        print(f"\n🔍 Would rename {changes} files. Run with --apply to apply.")


if __name__ == "__main__":
    dry_run = "--apply" not in sys.argv
    if not dry_run:
        print("⚠️  Running with --apply - will actually rename files!")

    standardize_all_files()
