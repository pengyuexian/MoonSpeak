#!/usr/bin/env python3
"""Generate rename map for Oxford Reading Tree Stage 01."""

import requests
import os
import json

# Get all files in Stage01
stage_dir = "/Users/pengziran/development/pengyuexian/MoonSpeak/books/Oxford-Reading-Tree/Stage01"
files = sorted(os.listdir(stage_dir))

# Group by base story name (without extension)
stories = {}
for f in files:
    base = os.path.splitext(f)[0]
    ext = os.path.splitext(f)[1].lower()
    # Extract story name (remove source tag if present)
    name = base.replace("【公益知识库zscc.club】", "")
    # Handle HTML entities
    name = name.replace("&#39;", "'")
    # Get core name (for grouping)
    core = name.lower().strip()
    if core not in stories:
        stories[core] = {"name": name, "files": []}
    stories[core]["files"].append((f, ext))

# Build file list for AI
file_list = "\n".join([f"  - {f}" for f in files[:60]])  # first 60

API_KEY = os.environ.get("GLM_API_KEY", "073aa04bf72c4d728771ea54215d27f8.fTFFwJJZVodUBObi")
url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

prompt = f"""You are standardizing Oxford Reading Tree (Stage 1) filenames.

RULES:
1. Remove 【公益知识库zscc.club】 prefix
2. Convert to lowercase
3. Replace spaces with underscores
4. Remove special characters (!, comma, etc)
5. Replace &#39; with nothing or keep apostrophe
6. Keep consistent naming across pdf/mp3/txt (same story = same base name)
7. NO double underscores

File list (first 60 of 147):
{file_list}

Respond with a JSON array of rename commands:
[
  {{"from": "original_filename", "to": "standardized_filename"}},
  ...
]

Keep the most accurate/standard English title for each story.
Examples:
- "A Good Trick.txt" -> "a_good_trick.txt"
- "【公益知识库zscc.club】A Good Trick.mp3" -> "a_good_trick.mp3"
- "WHat a DIN!.txt" -> "what_a_din.txt"
- "the hedgehog.txt" -> "the_hedgehog.txt"

Respond ONLY with the JSON array, nothing else."""

try:
    resp = requests.post(url, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }, json={
        "model": "glm-4-flash",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4000,
        "temperature": 0.1
    }, timeout=60)
    result = resp.json()
    if "choices" in result:
        output = result["choices"][0]["message"]["content"].strip()
        # Extract JSON
        if "```json" in output:
            output = output.split("```json")[1].split("```")[0]
        elif "```" in output:
            output = output.split("```")[1].split("```")[0]
        rename_map = json.loads(output)
        print(json.dumps(rename_map[:50], indent=2))
        print(f"\nTotal: {len(rename_map)} renames")
except Exception as e:
    print(f"Error: {e}")
