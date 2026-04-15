"""
MoonSpeak Assessment Pipeline - Power Up Edition

流程：
1. 音频 (.m4a/.mp3/.wav) → ffmpeg 转换为 WAV
2. Whisper 转录获取文字
3. 从 CURRENT_BOOK 对应的 Audioscripts 中匹配 unit/track
4. 用 LLM 基于“原文 + 实际朗读”生成标准内容，保存为同名 .txt
5. Azure 按标准内容打分，保存结果为 .md
6. LLM 翻译结果为中文，保存为 .cn.md
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOKS_ROOT = REPO_ROOT / "books"
DEFAULT_CURRENT_BOOK = "Power_Up/2"
LOW_VALUE_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "do",
    "does",
    "for",
    "from",
    "he",
    "her",
    "him",
    "his",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "she",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "to",
    "us",
    "we",
    "you",
    "your",
}
MATCH_STOPWORDS = LOW_VALUE_WORDS | {
    "look",
    "oh",
    "yes",
    "well",
    "hmm",
    "so",
}


def normalize_book_path(current_book: str | None, books_root: Path = BOOKS_ROOT) -> Path:
    current_book = (current_book or os.environ.get("CURRENT_BOOK") or DEFAULT_CURRENT_BOOK).strip().strip("/")
    book_path = books_root / current_book
    return book_path


def get_audioscripts_dir(current_book: str | None = None) -> Path:
    return normalize_book_path(current_book) / "Audioscripts"


def convert_to_wav(audio_path: str) -> str:
    """Convert audio to WAV format."""
    if audio_path.lower().endswith(".wav"):
        return audio_path
    wav_path = audio_path.rsplit(".", 1)[0] + ".wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            audio_path,
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            wav_path,
        ],
        capture_output=True,
        check=False,
    )
    return wav_path


def whisper_transcribe(wav_path: str) -> str:
    """Transcribe audio using whisper-cli."""
    model = os.environ.get("WHISPER_MODEL", "ggml-large-v3-turbo")
    model_path = os.path.expanduser(f"~/.cache/whisper.cpp/{model}.bin")

    result = subprocess.run(
        [
            "whisper-cli",
            "-m",
            model_path,
            "-l",
            "en",
            "-t",
            "4",
            "--no-timestamps",
            wav_path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def clean_reference_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("  \n", "\n")
    lines = [line.rstrip() for line in text.splitlines()]
    cleaned: list[str] = []
    blank_pending = False
    for line in lines:
        if not line.strip():
            if cleaned and not blank_pending:
                cleaned.append("")
            blank_pending = True
            continue
        blank_pending = False
        cleaned.append(line)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return "\n".join(cleaned)


def _tokenize_content_words(text: str) -> set[str]:
    raw_words = set(re.findall(r"[a-z']+", text.lower()))
    normalized_words = set()
    for word in raw_words:
        normalized_words.add(word)
        if word.endswith("'s"):
            normalized_words.add(word[:-2])
    return normalized_words - MATCH_STOPWORDS


def _line_overlap_count(line: str, transcript_words: set[str]) -> int:
    line_words = _tokenize_content_words(line)
    return len(line_words & transcript_words)


def _is_strong_line_match(line: str, transcript_words: set[str]) -> bool:
    line_words = _tokenize_content_words(line)
    if not line_words:
        return False
    overlap = len(line_words & transcript_words)
    if overlap >= 3:
        return True
    return overlap >= 2 and (overlap / len(line_words)) >= 0.6


def narrow_reference_text(reference_text: str, transcript_text: str) -> str:
    reference_text = clean_reference_text(reference_text)
    transcript_words = _tokenize_content_words(transcript_text)
    if not transcript_words:
        return reference_text

    lines = reference_text.splitlines()
    overlaps = [_line_overlap_count(line, transcript_words) for line in lines]
    matched_indexes = [idx for idx, line in enumerate(lines) if _is_strong_line_match(line, transcript_words)]
    if not matched_indexes:
        matched_indexes = [idx for idx, overlap in enumerate(overlaps) if overlap >= 1]
    if not matched_indexes:
        return reference_text

    selected_indexes: set[int] = set(matched_indexes)
    if matched_indexes:
        first_idx = matched_indexes[0]
        for idx in range(max(0, first_idx - 2), first_idx):
            selected_indexes.add(idx)

    for current, following in zip(matched_indexes, matched_indexes[1:]):
        gap = following - current - 1
        if gap <= 2:
            for idx in range(current + 1, following):
                selected_indexes.add(idx)

    narrowed_lines = [line for idx, line in enumerate(lines) if idx in selected_indexes]
    return clean_reference_text("\n".join(narrowed_lines))


def prepare_reference_text_for_llm(reference_text: str) -> str:
    prepared_lines: list[str] = []
    for line in clean_reference_text(reference_text).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("[Frame"):
            continue
        stripped = re.sub(r"^\d+\s+", "", stripped)
        stripped = re.sub(r"^[A-Za-z][A-Za-z ,&']{0,60}:\s+", "", stripped)
        prepared_lines.append(stripped)
    return clean_reference_text("\n".join(prepared_lines))


def _normalize_line_for_compare(text: str) -> str:
    text = text.replace("’", "'").replace("…", "...")
    words = re.findall(r"[a-z0-9']+", text.lower())
    normalized_words = []
    for word in words:
        normalized_words.append(word)
        if word.endswith("'s"):
            normalized_words.append(word[:-2])
    return " ".join(normalized_words)


def standard_matches_canonical_lines(standard_text: str, prepared_reference: str) -> bool:
    candidate_lines = [line for line in clean_reference_text(prepared_reference).splitlines() if line.strip()]
    output_lines = [line for line in clean_reference_text(standard_text).splitlines() if line.strip()]
    candidate_idx = 0
    for output_idx, output_line in enumerate(output_lines):
        normalized_output = _normalize_line_for_compare(output_line)
        matched = False
        while candidate_idx < len(candidate_lines):
            normalized_candidate = _normalize_line_for_compare(candidate_lines[candidate_idx])
            is_last_output_line = output_idx == len(output_lines) - 1
            if normalized_output == normalized_candidate or (
                is_last_output_line and normalized_candidate.startswith(normalized_output)
            ):
                matched = True
                candidate_idx += 1
                break
            candidate_idx += 1
        if not matched:
            return False
    return True


def should_retry_standard_generation(score_result: dict) -> bool:
    recognized_text = str(score_result.get("recognized_text", "")).strip()
    completeness = float(score_result.get("scores", {}).get("completeness", 100) or 100)
    words = score_result.get("words", [])
    omission_count = sum(1 for item in words if item.get("error_type") == "Omission")
    mispronunciation_count = sum(1 for item in words if item.get("error_type") == "Mispronunciation")
    return bool(recognized_text) and completeness < 60 and omission_count >= max(3, mispronunciation_count)


def build_output_paths(output_dir: str, base_name: str) -> dict[str, str]:
    return {
        "reference": os.path.join(output_dir, f"{base_name}.standard.txt"),
        "azure": os.path.join(output_dir, f"{base_name}.azure.json"),
        "results": os.path.join(output_dir, f"{base_name}.feedback.md"),
        "results_cn": os.path.join(output_dir, f"{base_name}.feedback.cn.md"),
    }


def _format_matched_tracks(matched_tracks: list[str]) -> str:
    if not matched_tracks:
        return "unknown"
    return "\n".join(matched_tracks)


def choose_report_tracks(matches: list[dict]) -> list[str]:
    if not matches:
        return []
    best = matches[0]
    threshold = best["score"] * 0.55
    chosen: list[str] = []
    for match in matches:
        if match["unit"] != best["unit"]:
            continue
        if match["score"] < threshold:
            continue
        chosen.append(match["track_num"])
    return chosen or [best["track_num"]]


def _is_content_problem_word(item: dict) -> bool:
    word = str(item.get("word", "")).strip()
    if not word:
        return False
    if _looks_like_name(word):
        return False
    lowered = word.lower()
    alpha_only = re.sub(r"[^a-z]", "", lowered)
    if not alpha_only:
        return False
    if lowered in LOW_VALUE_WORDS:
        return False
    if alpha_only in LOW_VALUE_WORDS:
        return False
    if len(alpha_only) <= 2:
        return False
    return True


def _looks_like_name(word: str) -> bool:
    alpha_word = re.sub(r"[^A-Za-z]", "", word)
    if len(alpha_word) < 3:
        return False
    if "'" in word:
        return False
    return word[:1].isupper() and word[1:].islower()


def _problem_word_priority(item: dict) -> tuple[int, float, str]:
    error_type = str(item.get("error_type", ""))
    if error_type == "Omission":
        severity = 0
    elif error_type == "Mispronunciation":
        severity = 1
    elif error_type == "Insertion":
        severity = 2
    else:
        severity = 3
    return (severity, item.get("score", 1000), str(item.get("word", "")))


def _is_preferred_omission_word(word: str) -> bool:
    lowered = word.lower()
    alpha_only = re.sub(r"[^a-z]", "", lowered)
    if not alpha_only:
        return False
    if lowered in LOW_VALUE_WORDS or alpha_only in LOW_VALUE_WORDS:
        return True
    return not (word[:1].isupper() and word[1:].islower())


def extract_problem_words(score_result: dict, limit: int = 4) -> list[dict]:
    words = score_result.get("words", [])
    filtered = [word for word in words if word.get("error_type")]
    deduped: dict[tuple[str, str], dict] = {}
    for item in filtered:
        key = (str(item.get("word", "")).lower(), str(item.get("error_type", "")))
        current = deduped.get(key)
        if current is None or item.get("score", 1000) < current.get("score", 1000):
            deduped[key] = item

    candidates = list(deduped.values())
    candidates.sort(key=_problem_word_priority)

    omission_candidates = [
        item
        for item in candidates
        if str(item.get("error_type")) == "Omission"
        and _is_preferred_omission_word(str(item.get("word", "")))
    ]
    content_candidates = [
        item
        for item in candidates
        if _is_content_problem_word(item) and str(item.get("error_type")) != "Insertion"
    ]
    mispronunciation_content_candidates = [
        item for item in content_candidates if str(item.get("error_type")) == "Mispronunciation"
    ]
    remaining_content_candidates = [
        item for item in content_candidates if item not in mispronunciation_content_candidates
    ]
    fallback_candidates = [
        item
        for item in candidates
        if item not in content_candidates
        and not (
            str(item.get("error_type")) == "Omission"
            and not _is_preferred_omission_word(str(item.get("word", "")))
        )
    ]

    selected: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()

    def add_item(item: dict) -> None:
        key = (str(item.get("word", "")).lower(), str(item.get("error_type", "")))
        if key in seen_keys:
            return
        selected.append(item)
        seen_keys.add(key)

    for item in omission_candidates:
        add_item(item)
        break

    for item in mispronunciation_content_candidates:
        if len(selected) >= limit:
            break
        add_item(item)

    for item in remaining_content_candidates:
        if len(selected) >= limit:
            break
        add_item(item)

    for item in fallback_candidates:
        if len(selected) >= limit:
            break
        add_item(item)

    return selected[:limit]


def render_problem_words_section_en(problem_words: list[dict]) -> str:
    if not problem_words:
        return "No major problem words were found."

    lines = []
    for item in problem_words:
        word = item.get("word", "")
        error_type = item.get("error_type")
        score = item.get("score", "N/A")
        if error_type == "Omission":
            detail = "this word was skipped"
        elif error_type == "Insertion":
            detail = "this extra word was added"
        else:
            detail = "pronunciation was unclear"
        lines.append(f"- {word}: {detail} (score: {score})")
    return "\n".join(lines)


def render_problem_words_section_cn(problem_words: list[dict]) -> str:
    if not problem_words:
        return "这次没有明显的重点问题词。"

    lines = []
    for item in problem_words:
        word = item.get("word", "")
        error_type = item.get("error_type")
        score = item.get("score", "N/A")
        if error_type == "Omission":
            detail = "这个英文单词漏读了"
        elif error_type == "Insertion":
            detail = "这里多读了这个英文单词"
        else:
            detail = "这个英文单词发得不清楚"
        lines.append(f"- {word}：{detail}（分数：{score}）")
    return "\n".join(lines)


def _problem_word_list(problem_words: list[dict]) -> str:
    return ", ".join(f'"{item.get("word", "")}"' for item in problem_words if item.get("word"))


def build_feedback_fallback_en(problem_words: list[dict], scores: dict | None = None) -> str:
    scores = scores or {}
    if not problem_words:
        return "You kept reading all the way through. Keep going, and read each line slowly and clearly."

    sentences = ["You kept reading all the way through. That showed good focus."]
    fluency = float(scores.get("fluency", 0) or 0)
    if fluency >= 70:
        sentences.append("Your reading pace was quite smooth, so keep that steady rhythm.")
    else:
        sentences.append("Try to slow down a little so each word can sound clearer.")

    for item in problem_words:
        word = item.get("word", "")
        error_type = item.get("error_type")
        score = float(item.get("score", 0) or 0)
        if error_type == "Omission":
            sentences.append(f'Remember to say "{word}" aloud next time. It was skipped in this reading.')
        elif error_type == "Insertion":
            sentences.append(f'Do not add "{word}" here. Stay closer to the book text.')
        else:
            if score < 25:
                detail = "needs a lot more practice"
            elif score < 60:
                detail = "still needs more practice"
            else:
                detail = "was a little unclear"
            sentences.append(f'Practice "{word}" again. Its pronunciation {detail}, so say each part more clearly.')
    return " ".join(sentences[: 2 + len(problem_words)])


def build_feedback_fallback_cn(problem_words: list[dict], scores: dict | None = None) -> str:
    scores = scores or {}
    if not problem_words:
        return "你这次一直坚持读完了，很不错。继续练习，读每一行的时候慢一点、清楚一点。"

    sentences = ["你这次一直坚持读完了，这说明你的专注力很好。"]
    fluency = float(scores.get("fluency", 0) or 0)
    if fluency >= 70:
        sentences.append("这次读得比较顺，继续保持这个节奏。")
    else:
        sentences.append("下次可以再慢一点，这样每个单词会更清楚。")

    for item in problem_words:
        word = item.get("word", "")
        error_type = item.get("error_type")
        score = float(item.get("score", 0) or 0)
        if error_type == "Omission":
            sentences.append(f'下次读到这里时，要把 "{word}" 这个英文单词读出来，这次它被漏掉了。')
        elif error_type == "Insertion":
            sentences.append(f'这次多读了 "{word}"，下次要更贴着原文来读。')
        else:
            if score < 25:
                detail = "还需要重点练习"
            elif score < 60:
                detail = "还需要继续练习"
            else:
                detail = "这次有一点不够清楚"
            sentences.append(f'请再练习 "{word}"。这个英文单词{detail}，可以放慢一点，把每个部分读清楚。')
    return " ".join(sentences[: 2 + len(problem_words)])


def _feedback_covers_problem_words(text: str, problem_words: list[dict]) -> bool:
    lowered = text.lower()
    required_words = [str(item.get("word", "")).lower() for item in problem_words if item.get("word")]
    return all(word in lowered for word in required_words)


def _feedback_has_contradictions(text: str, problem_words: list[dict]) -> bool:
    positive_cues = ("great", "well", "clear", "clearly", "fantastic", "excellent", "good")
    negative_cues = ("practice", "tricky", "work on", "more clearly", "more carefully", "miss", "skip")
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    for item in problem_words:
        word = str(item.get("word", "")).lower()
        if not word:
            continue
        for sentence in sentences:
            lowered = sentence.lower()
            if word not in lowered:
                continue
            if any(cue in lowered for cue in positive_cues) and not any(cue in lowered for cue in negative_cues):
                return True
    return False


def _feedback_looks_complete(text: str) -> bool:
    stripped = text.strip()
    return len(stripped) >= 60 and stripped[-1] in ".!?"


def _normalize_for_match(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9']+", " ", text)
    return " ".join(text.split())


def render_feedback_report_en(
    *,
    base_name: str,
    matched_unit: int | None,
    matched_tracks: list[str],
    standard_text: str,
    scores: dict,
    problem_words: list[dict],
    feedback_en: str,
) -> str:
    return f"""# Assessment Report: {base_name}

## Matched Unit
{matched_unit if matched_unit is not None else "unknown"}

## Matched Track
{_format_matched_tracks(matched_tracks)}

## Standard Content
{standard_text}

## Scores
Pronunciation: {scores.get('pronunciation', 'N/A')}/100
Accuracy: {scores.get('accuracy', 'N/A')}/100
Fluency: {scores.get('fluency', 'N/A')}/100
Completeness: {scores.get('completeness', 'N/A')}/100

## Problem Words
{render_problem_words_section_en(problem_words)}

## Feedback
{feedback_en}
"""


def render_feedback_report_cn(
    *,
    base_name: str,
    matched_unit: int | None,
    matched_tracks: list[str],
    standard_text: str,
    scores: dict,
    problem_words: list[dict],
    feedback_cn: str,
) -> str:
    return f"""# 评测报告：{base_name}

## 匹配 Unit
{matched_unit if matched_unit is not None else "unknown"}

## 匹配 Track
{_format_matched_tracks(matched_tracks)}

## 标准内容
{standard_text}

## 评分
发音：{scores.get('pronunciation', 'N/A')}/100
准确度：{scores.get('accuracy', 'N/A')}/100
流利度：{scores.get('fluency', 'N/A')}/100
完整度：{scores.get('completeness', 'N/A')}/100

## 重点问题词
{render_problem_words_section_cn(problem_words)}

## 反馈
{feedback_cn}
"""


def load_audioscripts(scripts_dir: str | None = None) -> dict[str, dict]:
    """Load all audioscripts from unit-based markdown files."""
    scripts_path = Path(scripts_dir) if scripts_dir else get_audioscripts_dir()
    if not scripts_path.exists():
        raise FileNotFoundError(f"Audioscripts directory not found: {scripts_path}")

    tracks: dict[str, dict] = {}
    for file_path in sorted(scripts_path.glob("Unit_*.md")):
        content = file_path.read_text(encoding="utf-8")

        unit_match = re.search(r"Unit_(\d+)", file_path.name)
        if not unit_match:
            continue
        unit_num = int(unit_match.group(1))

        pattern = re.compile(r"^##\s+(Track[s]?\s+[^\n]+)\n+(.*?)(?=^##\s+Track[s]?\s+|\Z)", re.MULTILINE | re.DOTALL)
        for match in pattern.finditer(content):
            track_header = match.group(1).strip()
            raw_text = match.group(2).strip()
            text = clean_reference_text(raw_text)

            track_num_match = re.search(r"(\d+\.\d+)", track_header)
            if not track_num_match:
                continue

            track_num = track_num_match.group(1)
            tracks[track_num] = {
                "unit": unit_num,
                "filename": file_path.name,
                "track_header": track_header,
                "text": text,
                "words": set(re.findall(r"[a-z']+", text.lower())),
            }
    return tracks


def find_best_match(whisper_text: str, tracks: dict[str, dict], top_n: int = 5) -> list[dict]:
    """Find the best matching tracks using word-level similarity."""
    whisper_words = set(re.findall(r"[a-z']+", whisper_text.lower()))
    stopwords = {
        "the", "a", "an", "is", "are", "am", "to", "in", "on", "at", "and", "or",
        "it", "this", "that", "i", "you", "he", "she", "we", "they", "my", "your",
        "his", "her", "what", "how", "where", "who", "name", "s", "re", "ve", "not", "don",
    }
    whisper_words -= stopwords
    if not whisper_words:
        return []

    matches: list[dict] = []
    for track_num, data in tracks.items():
        track_words = data["words"] - stopwords
        if not track_words:
            continue

        intersection = len(whisper_words & track_words)
        union = len(whisper_words | track_words)
        score = intersection / union if union else 0
        if score <= 0.05:
            continue

        matches.append(
            {
                "score": score,
                "track_num": track_num,
                "track_header": data["track_header"],
                "unit": data["unit"],
                "text": data["text"],
                "filename": data["filename"],
            }
        )

    matches.sort(key=lambda item: item["score"], reverse=True)
    return matches[:top_n]


def llm_chat(system_prompt: str, user_prompt: str, temperature: float = 0.2, max_tokens: int = 1200) -> str:
    import requests

    minimax_api_key = os.environ.get("MINIMAX_API_KEY") or os.environ.get("OPENAI_API_KEY")
    minimax_group_id = os.environ.get("MINIMAX_GROUP_ID")
    minimax_model = os.environ.get("MINIMAX_MODEL") or os.environ.get("DEEP_THINK_MODEL") or "MiniMax-M2.7"
    glm_api_key = os.environ.get("GLM_API_KEY")
    minimax_error: Exception | None = None

    if minimax_api_key:
        try:
            base_url = (
                os.environ.get("MINIMAX_BASE_URL")
                or os.environ.get("OPENAI_BASE_URL")
                or "https://api.minimaxi.com/v1"
            ).rstrip("/")
            if not base_url.endswith("/text/chatcompletion_v2"):
                base_url = f"{base_url}/text/chatcompletion_v2"
            headers = {"Authorization": f"Bearer {minimax_api_key}", "Content-Type": "application/json"}
            payload = {
                "model": minimax_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if minimax_group_id:
                payload["group_id"] = minimax_group_id

            response = requests.post(base_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()

            if isinstance(data.get("reply"), str):
                return data["reply"].strip()
            if data.get("choices"):
                return data["choices"][0]["message"]["content"].strip()
            raise RuntimeError(f"Unexpected MiniMax response: {data}")
        except Exception as exc:
            minimax_error = exc

    if glm_api_key:
        url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        headers = {"Authorization": f"Bearer {glm_api_key}", "Content-Type": "application/json"}
        response = requests.post(
            url,
            headers=headers,
            json={
                "model": "glm-4-flash",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("choices"):
            return data["choices"][0]["message"]["content"].strip()
        raise RuntimeError(f"Unexpected GLM response: {data}")

    if minimax_error is not None:
        raise minimax_error
    raise RuntimeError("No LLM configured. Set MINIMAX_API_KEY or GLM_API_KEY.")


def llm_chat_glm(system_prompt: str, user_prompt: str, temperature: float = 0.2, max_tokens: int = 1200) -> str:
    import requests

    glm_api_key = os.environ.get("GLM_API_KEY")
    if not glm_api_key:
        raise RuntimeError("GLM_API_KEY not configured.")

    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {"Authorization": f"Bearer {glm_api_key}", "Content-Type": "application/json"}
    response = requests.post(
        url,
        headers=headers,
        json={
            "model": "glm-4-flash",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("choices"):
        return data["choices"][0]["message"]["content"].strip()
    raise RuntimeError(f"Unexpected GLM response: {data}")


def build_standard_content_prompt(reference_text: str, whisper_text: str, track_header: str, unit: int) -> tuple[str, str]:
    system_prompt = (
        "You align child read-aloud transcripts to the canonical book text. "
        "Return only the corrected standard reading content."
    )
    user_prompt = f"""Task: Create the standard reading content for a child's audio.

Book unit: {unit}
Matched section: {track_header}

Canonical book text:
---
{reference_text}
---

Whisper transcript of what was actually read:
---
{whisper_text}
---

Rules:
1. Keep ONLY the part that was actually read in the audio.
2. Use the canonical book text wording as the source of truth for words and spelling.
3. Do NOT add section titles, track titles, unit titles, speaker names, frame labels, or narration labels unless the child actually read them.
4. If the audio skipped a sentence/line, do not include that skipped part.
5. If Whisper made mistakes or the child misread a word, correct it back to the canonical book wording, but only within the spoken range.
6. If the audio starts or ends in the middle of the matched text, output only that spoken span.
7. Use the line breaks from the canonical book text for every line you keep.
8. Do not merge multiple canonical lines into one paragraph.
9. If you keep a line, copy that line's wording from the canonical book text.
10. If you remove a line because it was not read, remove the whole line.
11. Do not explain your reasoning.
12. Output plain text only.

Output the final standard content only."""
    return system_prompt, user_prompt


def generate_standard_content(reference_text: str, whisper_text: str, track_header: str, unit: int) -> str:
    if not whisper_text.strip():
        return reference_text

    narrowed_reference = narrow_reference_text(reference_text, whisper_text)
    prepared_reference = prepare_reference_text_for_llm(narrowed_reference)
    if not prepared_reference.strip():
        return clean_reference_text(reference_text)
    system_prompt, user_prompt = build_standard_content_prompt(prepared_reference, whisper_text, track_header, unit)
    standard_text = clean_reference_text(llm_chat(system_prompt, user_prompt, temperature=0.1, max_tokens=4000))
    if standard_matches_canonical_lines(standard_text, prepared_reference):
        return standard_text

    retry_prompt = f"""{user_prompt}

Extra validation rules:
- Every output line must be copied from the canonical book text exactly.
- You may output a full canonical line, or for the final line only, an exact starting prefix of a canonical line.
- Do not drop the first word of any kept line.
- Do not paraphrase, simplify, or rewrite any line.
"""
    retry_text = clean_reference_text(llm_chat(system_prompt, retry_prompt, temperature=0.0, max_tokens=4000))
    if standard_matches_canonical_lines(retry_text, prepared_reference):
        return retry_text
    if standard_matches_canonical_lines(standard_text, prepared_reference):
        return standard_text
    return prepared_reference


def azure_score(wav_path: str, reference_text: str) -> dict:
    """Score pronunciation using Azure Speech SDK."""
    import azure.cognitiveservices.speech as speechsdk

    speech_key = os.environ.get("AZURE_SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION", "westus")

    if not speech_key:
        return {
            "error": "AZURE_SPEECH_KEY not configured",
            "recognized_text": "",
            "reference_text": reference_text,
            "scores": {},
        }

    speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=region)
    speech_config.speech_recognition_language = "en-US"

    audio_config = speechsdk.AudioConfig(filename=wav_path)
    recognizer = speechsdk.SpeechRecognizer(speech_config, audio_config=audio_config)

    pronunciation_config = speechsdk.PronunciationAssessmentConfig(
        reference_text=reference_text,
        grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
        granularity=speechsdk.PronunciationAssessmentGranularity.Word,
        enable_miscue=True,
    )
    pronunciation_config.apply_to(recognizer)

    result = recognizer.recognize_once()
    if result.reason != speechsdk.ResultReason.RecognizedSpeech:
        return {
            "error": f"Recognition failed: {result.reason}",
            "recognized_text": "",
            "reference_text": reference_text,
            "scores": {},
        }

    pron_result = speechsdk.PronunciationAssessmentResult(result)
    words: list[dict] = []
    if getattr(pron_result, "words", None):
        for word_result in pron_result.words:
            words.append(
                {
                    "word": word_result.word,
                    "error_type": getattr(word_result, "error_type", None),
                    "score": round(getattr(word_result, "accuracy_score", 0.0), 1),
                }
            )

    return {
        "recognized_text": result.text,
        "reference_text": reference_text,
        "scores": {
            "pronunciation": round(pron_result.pronunciation_score, 1),
            "accuracy": round(pron_result.accuracy_score, 1),
            "fluency": round(pron_result.fluency_score, 1),
            "completeness": round(pron_result.completeness_score, 1),
        },
        "words": words,
    }


def llm_generate_feedback_en(scores: dict, recognized_text: str, reference_text: str) -> str:
    """Generate English feedback for the child."""
    pron_score = scores.get("pronunciation", 0)
    problem_words = extract_problem_words({"words": scores.get("words", []) if "words" in scores else []})
    problem_summary = "\n".join(
        f"- {item['word']} ({item['error_type']}, score {item['score']})" for item in problem_words
    ) or "- none"
    prompt = f"""A child just read English aloud. Provide encouraging feedback.

Reference text: "{reference_text}"
Recognized text: "{recognized_text}"
Pronunciation score: {pron_score}/100
Word-level issues from pronunciation assessment:
{problem_summary}

Requirements:
- Be encouraging and positive for a young child
- Mention what they did well
- Point out 2-4 specific words or reading issues when scores are low
- If problem words are listed above, mention each selected problem word exactly as written
- Do not say that a listed problem word was correct, good, or clear
- Explain the issue in concrete terms when possible, e.g. missing small words, unclear ending sounds, skipped words
- Keep it short but detailed enough to be useful, around 3-5 sentences
- Use simple English

Return only the feedback."""

    try:
        result = llm_chat(
            "You are a warm, encouraging English teacher for young children.",
            prompt,
            temperature=0.2,
            max_tokens=700,
        )
        if (
            result
            and _feedback_looks_complete(result)
            and _feedback_covers_problem_words(result, problem_words)
            and not _feedback_has_contradictions(result, problem_words)
        ):
            return result.strip()
    except Exception:
        pass

    try:
        result = llm_chat_glm(
            "You are a warm, encouraging English teacher for young children.",
            prompt,
            temperature=0.2,
            max_tokens=700,
        )
        if (
            result
            and _feedback_looks_complete(result)
            and _feedback_covers_problem_words(result, problem_words)
            and not _feedback_has_contradictions(result, problem_words)
        ):
            return result.strip()
    except Exception:
        pass

    return build_feedback_fallback_en(problem_words)


def build_translation_prompt(feedback_en: str) -> str:
    return f"""Translate the following English feedback for a child's English pronunciation practice into Chinese.

English feedback:
{feedback_en}

Requirements:
- Translate faithfully and keep all details.
- Do not summarize or omit praise, advice, or concrete reading tips.
- Keep a similar number of sentences to the English feedback.
- Do not add score summaries, bullet points, labels, or extra explanations.
- Keep the tone warm and suitable for a child and parent.
- Keep every English problem word exactly as English in the Chinese text.
- Do NOT translate words like "And", "wildlife", "jim's", or "bringing" into Chinese.
- If the feedback mentions an English word in quotes, keep that quoted word unchanged.

Return only the Chinese translation."""


def _translation_keeps_english_words(text: str, feedback_en: str) -> bool:
    english_words = re.findall(r'"([A-Za-z][A-Za-z\'-]*)"', feedback_en)
    if not english_words:
        return len(text.strip()) >= 12
    lowered = text.lower()
    return all(word.lower() in lowered for word in english_words)


def llm_translate_to_chinese(feedback_en: str, scores: dict) -> str:
    """Translate feedback to Chinese."""
    prompt = build_translation_prompt(feedback_en)
    try:
        result = llm_chat(
            "You are a helpful translator for children's educational content.",
            prompt,
            temperature=0.1,
            max_tokens=500,
        )
        if result and len(result.strip()) >= 12 and _translation_keeps_english_words(result, feedback_en):
            return result.strip()
    except Exception:
        pass

    try:
        result = llm_chat_glm(
            "You are a helpful translator for children's educational content.",
            prompt,
            temperature=0.1,
            max_tokens=500,
        )
        if result and _translation_keeps_english_words(result, feedback_en):
            return result.strip()
    except Exception:
        pass

    problem_words = [{"word": word} for word in re.findall(r'"([A-Za-z][A-Za-z\'-]*)"', feedback_en)]
    return build_feedback_fallback_cn(problem_words)


def assess_audio(audio_path: str, output_dir: str | None = None, scripts_dir: str | None = None) -> dict:
    """Full assessment pipeline for one audio file."""
    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    output_dir = output_dir or os.path.dirname(audio_path) or "."
    scripts_dir = scripts_dir or str(get_audioscripts_dir())

    print(f"\n📝 Processing: {base_name}")

    print("  🔄 Converting to WAV...")
    wav_path = convert_to_wav(audio_path)

    print("  🎤 Whisper transcription...")
    whisper_text = whisper_transcribe(wav_path)
    if whisper_text:
        print(f"      Transcribed: {whisper_text[:80]}...")
    else:
        print("      ⚠️ Whisper failed to transcribe")

    print("  📚 Matching to AudioScripts...")
    tracks = load_audioscripts(scripts_dir)
    print(f"      Loaded {len(tracks)} tracks")
    matches = find_best_match(whisper_text, tracks)

    if matches:
        best_match = matches[0]
        print(
            f"      Best match: Unit {best_match['unit']} / {best_match['track_header']} "
            f"(score: {best_match['score']:.2f})"
        )
        matched_track = best_match["track_num"]
        matched_unit = best_match["unit"]
        canonical_text = best_match["text"]
    else:
        print("      ⚠️ No matching track found, falling back to Whisper text")
        matched_track = "unknown"
        matched_unit = None
        canonical_text = whisper_text
    matched_tracks = choose_report_tracks(matches) if matches else [matched_track]

    print("  ✨ Generating standard content...")
    if matches:
        standard_text = generate_standard_content(
            canonical_text,
            whisper_text,
            best_match["track_header"],
            best_match["unit"],
        )
    else:
        standard_text = whisper_text

    output_paths = build_output_paths(output_dir, base_name)
    with open(output_paths["reference"], "w", encoding="utf-8") as file:
        file.write(standard_text)
    print(f"      Saved standard content: {os.path.basename(output_paths['reference'])}")

    print("  ⭐ Azure scoring...")
    scores = azure_score(wav_path, standard_text)
    if "error" in scores:
        print(f"      ⚠️ {scores['error']}")
    else:
        print(f"      Pronunciation: {scores['scores']['pronunciation']}/100")

    if matches and should_retry_standard_generation(scores):
        print("      Refining standard content from Azure recognized text...")
        retry_standard_text = generate_standard_content(
            canonical_text,
            scores.get("recognized_text", ""),
            best_match["track_header"],
            best_match["unit"],
        )
        retry_scores = azure_score(wav_path, retry_standard_text)
        current_completeness = float(scores.get("scores", {}).get("completeness", 0) or 0)
        retry_completeness = float(retry_scores.get("scores", {}).get("completeness", 0) or 0)
        current_accuracy = float(scores.get("scores", {}).get("accuracy", 0) or 0)
        retry_accuracy = float(retry_scores.get("scores", {}).get("accuracy", 0) or 0)
        if retry_completeness > current_completeness or (
            retry_completeness == current_completeness and retry_accuracy >= current_accuracy
        ):
            standard_text = retry_standard_text
            scores = retry_scores
            with open(output_paths["reference"], "w", encoding="utf-8") as file:
                file.write(standard_text)
            print(
                f"      Improved standard content selected "
                f"(completeness: {retry_completeness}/100, accuracy: {retry_accuracy}/100)"
            )

    with open(output_paths["azure"], "w", encoding="utf-8") as file:
        json.dump(scores, file, ensure_ascii=False, indent=2)

    print("  💬 Generating feedback...")
    feedback_input = dict(scores.get("scores", {}))
    feedback_input["words"] = scores.get("words", [])
    problem_words = extract_problem_words(scores)
    feedback_en = build_feedback_fallback_en(problem_words, scores.get("scores", {}))

    result_md = render_feedback_report_en(
        base_name=base_name,
        matched_unit=matched_unit,
        matched_tracks=matched_tracks,
        standard_text=standard_text,
        scores=scores.get("scores", {}),
        problem_words=problem_words,
        feedback_en=feedback_en,
    )
    with open(output_paths["results"], "w", encoding="utf-8") as file:
        file.write(result_md)

    print("  🌏 Translating to Chinese...")
    feedback_cn = build_feedback_fallback_cn(problem_words, scores.get("scores", {}))

    result_cn_md = render_feedback_report_cn(
        base_name=base_name,
        matched_unit=matched_unit,
        matched_tracks=matched_tracks,
        standard_text=standard_text,
        scores=scores.get("scores", {}),
        problem_words=problem_words,
        feedback_cn=feedback_cn,
    )
    with open(output_paths["results_cn"], "w", encoding="utf-8") as file:
        file.write(result_cn_md)

    return {
        "audio": os.path.basename(audio_path),
        "whisper_text": whisper_text,
        "matched_unit": matched_unit,
        "matched_track": matched_track,
        "standard_text": standard_text,
        "recognized_text": scores.get("recognized_text", ""),
        "scores": scores.get("scores", {}),
        "feedback_en": feedback_en,
        "feedback_cn": feedback_cn,
        "files": {
            "reference": os.path.basename(output_paths["reference"]),
            "results": os.path.basename(output_paths["results"]),
            "results_cn": os.path.basename(output_paths["results_cn"]),
        },
    }


def assess_directory(audio_dir: str, output_dir: str | None = None, scripts_dir: str | None = None) -> list[dict]:
    results = []
    for name in sorted(os.listdir(audio_dir)):
        if name.lower().endswith((".m4a", ".wav", ".mp3", ".aac", ".m4b")):
            audio_path = os.path.join(audio_dir, name)
            try:
                results.append(assess_audio(audio_path, output_dir or audio_dir, scripts_dir))
            except Exception as exc:
                print(f"  ❌ Error processing {name}: {exc}")
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m moonspeak.pipeline <audio_file_or_directory> [scripts_dir]")
        sys.exit(1)

    path = sys.argv[1]
    scripts_dir = sys.argv[2] if len(sys.argv) > 2 else None

    if os.path.isdir(path):
        results = assess_directory(path, scripts_dir=scripts_dir)
        print(f"\n✅ Processed {len(results)} files")
    else:
        result = assess_audio(path, os.path.dirname(path) or ".", scripts_dir)
        print("\n✅ Assessment complete!")
        print(f"   Unit: {result['matched_unit']}")
        print(f"   Track: {result['matched_track']}")
        print(f"   Pronunciation: {result['scores'].get('pronunciation', 'N/A')}/100")
