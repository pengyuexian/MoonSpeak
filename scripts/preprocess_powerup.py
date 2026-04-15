#!/usr/bin/env python3
"""
Preprocess Power Up Audio Scripts PDF using word-level extraction.
Properly handles two-column layout by sorting words by position.
"""

import os
import re
import pdfplumber

PU2_DIR = "/Users/pengziran/development/pengyuexian/MoonSpeak/books/Power Up 2级别"
OUTPUT_DIR = "/Users/pengziran/development/pengyuexian/MoonSpeak/books/Power-Up-2"


def extract_page_text(page):
    """Extract text from a page, properly handling two-column layout."""
    words = page.extract_words()
    
    if not words:
        return ""
    
    # Group words by y-coordinate (line)
    lines = {}
    for w in words:
        y = round(w['top'], 1)
        if y not in lines:
            lines[y] = []
        lines[y].append(w)
    
    # Sort lines by y, then words by x
    sorted_lines = []
    for y in sorted(lines.keys()):
        line_words = sorted(lines[y], key=lambda w: w['x0'])
        line_text = ' '.join([w['text'] for w in line_words])
        sorted_lines.append(line_text)
    
    return '\n'.join(sorted_lines)


def clean_line(line):
    """Clean a single line of text."""
    if not line:
        return None
    if '© Cambridge University Press' in line:
        return None
    if 'University Press and UCLES' in line:
        return None
    if 'PHOTOCOPIABLE' in line:
        return None
    if re.match(r"^Pupil's Book \d*$", line.strip()):
        return None
    if re.match(r"^Activity Book \d*$", line.strip()):
        return None
    if line.strip() == 'Audioscripts':
        return None
    # Fix column split artifacts
    line = line.replace('nT ', 'T ')
    line = line.replace('aft ernoon', 'afternoon')
    return line


def extract_units(pdf_path, source_name):
    """Extract all units from PDF using word-level extraction."""
    all_text = ""
    
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = extract_page_text(page)
            all_text += f"\n=== PAGE {page_num+1} ===\n{text}\n"
    
    # Find all Track references and their positions
    pattern = r'Track (\d+)\.(\d+)'
    matches = list(re.finditer(pattern, all_text))
    
    # Find unit boundaries (where unit number increases)
    unit_boundaries = []
    for i in range(len(matches)):
        unit = int(matches[i].group(1))
        pos = matches[i].start()
        
        if not unit_boundaries or unit_boundaries[-1][0] != unit:
            unit_boundaries.append((unit, pos))
    
    # Extract content for each unit
    units = {}
    for i, (unit, start) in enumerate(unit_boundaries):
        end = unit_boundaries[i+1][1] if i+1 < len(unit_boundaries) else len(all_text)
        
        content = all_text[start:end]
        
        # Clean line by line, preserving line breaks
        lines = content.split('\n')
        cleaned_lines = []
        for line in lines:
            cleaned = clean_line(line)
            if cleaned is not None and cleaned.strip():
                cleaned_lines.append(cleaned)
        
        cleaned_content = '\n'.join(cleaned_lines)
        
        # Extract track list
        tracks_in_unit = re.findall(r'Track (\d+)\.(\d+)', content)
        track_list = [f"{u}.{s}" for u, s in tracks_in_unit]
        
        if len(cleaned_content.strip()) > 50:
            units[str(unit)] = {
                'source': source_name,
                'tracks': track_list,
                'text': cleaned_content.strip()
            }
    
    return units


def save_units(units, output_dir):
    """Save units as markdown files."""
    os.makedirs(output_dir, exist_ok=True)
    
    # Save index
    index_path = os.path.join(output_dir, "_index.md")
    with open(index_path, 'w') as f:
        f.write("# Power Up 2 - Audio Scripts Index\n\n")
        f.write(f"Total units: {len(units)}\n\n")
        f.write("| Unit | Source | Tracks | Preview |\n")
        f.write("|------|--------|--------|--------|\n")
        for unit_num in sorted(units.keys(), key=int):
            data = units[unit_num]
            tracks_str = ', '.join(data['tracks'][:8])
            if len(data['tracks']) > 8:
                tracks_str += f'... (+{len(data["tracks"])-8})'
            preview = data['text'][:80].replace('\n', ' ') + '...'
            f.write(f"| Unit {unit_num} | {data['source']} | {tracks_str} | {preview} |\n")
    
    # Save individual units
    for unit_num, data in units.items():
        filename = f"Unit_{unit_num}.md"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# Unit {unit_num}\n\n")
            f.write(f"**Source:** {data['source']}\n\n")
            f.write(f"**Tracks:** {', '.join(data['tracks'])}\n\n")
            f.write(f"## Original Text\n\n{data['text']}\n")
    
    return len(units)


def main():
    print("🔄 Processing Power Up 2 Audio Scripts...\n")
    
    all_units = {}
    
    # Process PB2 only
    pb2_pdf = os.path.join(PU2_DIR, "Power Up Level 2 Audio scripts", "Power Up PB2 Audioscripts.pdf")
    if os.path.exists(pb2_pdf):
        print("  📖 Pupil's Book 2 Audioscripts...")
        pb2_units = extract_units(pb2_pdf, "Pupil's Book 2")
        print(f"     Found {len(pb2_units)} units: {sorted(pb2_units.keys())}")
        all_units.update(pb2_units)
    
    print(f"\n  💾 Saving to {OUTPUT_DIR}...")
    total = save_units(all_units, OUTPUT_DIR)
    print(f"\n✅ Done! {total} units saved")
    
    # Show Unit 5 Track 5.05
    if '5' in all_units:
        text = all_units['5']['text']
        # Find Track 5.05
        idx = text.find("Track 5.05")
        if idx >= 0:
            end_idx = text.find("Track 5.07", idx)
            if end_idx < 0:
                end_idx = idx + 800
            print(f"\n📝 Unit 5 - Track 5.05:")
            print(text[idx:end_idx])


if __name__ == "__main__":
    main()
