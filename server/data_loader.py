from __future__ import annotations

import json
import re
from pathlib import Path


def build_evaluation_paths(
    evaluations_root: Path, date: str, name: str
) -> dict[str, Path]:
    base_dir = evaluations_root / date
    return {
        "standard": base_dir / f"{name}.standard.txt",
        "azure": base_dir / f"{name}.azure.json",
        "feedback_cn": base_dir / f"{name}.feedback.cn.md",
        "feedback_en": base_dir / f"{name}.feedback.md",
    }


def parse_feedback_cn_markdown(markdown: str) -> dict[str, object]:
    sections: dict[str, list[str]] = {}
    current = ""
    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
            continue
        if current and line.strip():
            sections[current].append(line.strip())

    problem_word_lines = []
    for line in sections.get("重点问题词", []):
        if line.startswith("- "):
            problem_word_lines.append(line[2:])
        else:
            problem_word_lines.append(line)

    return {
        "matched_unit": "\n".join(sections.get("匹配 Unit", [])),
        "matched_tracks": sections.get("匹配 Track", []),
        "score_lines": sections.get("评分", []),
        "problem_word_lines": problem_word_lines,
        "feedback_lines": sections.get("反馈", []),
    }


def classify_word_color(word_result: dict) -> str:
    error_type = word_result.get("error_type")
    score = float(word_result.get("score", 0) or 0)
    if error_type == "Omission":
        return "red"
    if error_type == "Mispronunciation":
        if score < 35:
            return "red"
        if score < 70:
            return "yellow"
        return "green"
    if score >= 85:
        return "green"
    if score >= 70:
        return "yellow"
    return "yellow"


def build_word_detail_cn(word_result: dict) -> str:
    error_type = word_result.get("error_type")
    score = int(float(word_result.get("score", 0) or 0))
    if error_type == "Omission":
        return f"这个词这次漏读了。当前分数：{score}"
    if error_type == "Mispronunciation":
        if score < 35:
            return f"这个词读得不太清楚，还需要重点练习。当前分数：{score}"
        if score < 70:
            return f"这个词还不够稳定，可以再放慢一点读。当前分数：{score}"
    return f"这个词整体比较稳定。当前分数：{score}"


def _normalize_token(text: str) -> str:
    token = text.replace("’", "'").lower()
    token = re.sub(r"[^a-z0-9']+", "", token)
    if token.endswith("'s"):
        return token[:-2]
    return token


def align_standard_text_with_azure(standard_text: str, azure_words: list[dict]) -> list[dict]:
    azure_index = 0
    lines: list[dict] = []
    for line in standard_text.splitlines():
        tokens = []
        for raw in re.findall(r"[A-Za-z0-9'’]+|[^A-Za-z0-9'’\s]+|\s+", line):
            if raw.isspace():
                tokens.append({"text": raw, "kind": "space"})
                continue
            if not re.match(r"[A-Za-z0-9'’]+$", raw):
                tokens.append({"text": raw, "kind": "punct"})
                continue
            aligned = None
            normalized_raw = _normalize_token(raw)
            for candidate_index in range(azure_index, len(azure_words)):
                candidate = azure_words[candidate_index]
                if _normalize_token(str(candidate.get("word", ""))) == normalized_raw:
                    aligned = candidate
                    azure_index = candidate_index + 1
                    break
            if aligned is None:
                tokens.append({"text": raw, "kind": "word", "color": "neutral", "detail": ""})
            else:
                tokens.append(
                    {
                        "text": raw,
                        "kind": "word",
                        "color": classify_word_color(aligned),
                        "detail": aligned,
                    }
                )
        lines.append({"text": line, "tokens": tokens})
    return lines


def load_speech_review_page_data(
    evaluations_root: Path, date: str, name: str
) -> dict[str, object]:
    paths = build_evaluation_paths(evaluations_root, date, name)
    standard_text = paths["standard"].read_text(encoding="utf-8")
    azure_data = json.loads(paths["azure"].read_text(encoding="utf-8"))
    feedback_cn = parse_feedback_cn_markdown(paths["feedback_cn"].read_text(encoding="utf-8"))
    aligned_lines = align_standard_text_with_azure(standard_text, azure_data.get("words", []))
    for line in aligned_lines:
        for token in line["tokens"]:
            if token.get("kind") != "word":
                continue
            detail = token.get("detail")
            token["detail_text_cn"] = build_word_detail_cn(detail) if isinstance(detail, dict) else ""

    # Audio paths
    repo_root = evaluations_root.parent
    
    # 1. Detect Book Level
    book_level = None
    # Priority A: Parse from feedback.md (EN)
    if paths["feedback_en"].exists():
        en_md = paths["feedback_en"].read_text(encoding="utf-8")
        level_match = re.search(r"## Matched Level\n+(\d+)", en_md)
        if level_match:
            book_level = level_match.group(1)

    # Priority B: Detect based on standard text content (fallback)
    if not book_level and standard_text:
        # Extract a reasonably unique snippet (exclude common intro lines)
        lines = [line.strip() for line in standard_text.splitlines() if line.strip()]
        search_snippet = lines[min(2, len(lines)-1)] if len(lines) > 2 else lines[0]
        
        for level_dir in (repo_root / "books" / "Power_Up").glob("*"):
            if not level_dir.is_dir(): continue
            for script in (level_dir / "Audioscripts").glob("*.md"):
                try:
                    if search_snippet in script.read_text(encoding="utf-8"):
                        book_level = level_dir.name
                        break
                except:
                    continue
            if book_level: break

    # Recording: check .wav then .m4a
    recording_wav = paths["standard"].parent / f"{name}.wav"
    recording_m4a = paths["standard"].parent / f"{name}.m4a"
    recording_url = None
    if recording_wav.exists():
        recording_url = f"/audio/user/{date}/{name}.wav"
    elif recording_m4a.exists():
        recording_url = f"/audio/user/{date}/{name}.m4a"

    # Track: use detected book level
    track_url = None
    if feedback_cn["matched_tracks"] and book_level:
        match = re.search(r"(\d+\.\d+)", feedback_cn["matched_tracks"][0])
        if match:
            track_id = match.group(1)
            # Only search in the detected book level
            track_path = repo_root / "books" / "Power_Up" / book_level / "Tracks" / f"{track_id}.mp3"
            if track_path.exists():
                track_url = f"/audio/track/{book_level}/{track_id}.mp3"

    return {
        "name": name,
        "date": date,
        "matched_unit": feedback_cn["matched_unit"],
        "matched_tracks": feedback_cn["matched_tracks"],
        "scores": azure_data.get("scores", {}),
        "score_lines_cn": feedback_cn["score_lines"],
        "problem_word_lines_cn": feedback_cn["problem_word_lines"],
        "feedback_lines_cn": feedback_cn["feedback_lines"],
        "standard_lines": aligned_lines,
        "audio_url_user": recording_url,
        "audio_url_track": track_url,
    }
