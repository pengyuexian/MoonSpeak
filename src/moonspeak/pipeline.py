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
import math
import difflib
import multiprocessing
import queue
import threading
import wave
import contextlib
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


def _timeout_worker(result_queue: multiprocessing.Queue, func, args: tuple) -> None:
    try:
        result_queue.put(("result", func(*args)))
    except Exception as exc:  # pragma: no cover
        result_queue.put(("error", repr(exc)))


def _run_with_timeout(func, args: tuple, timeout_sec: float):
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()
    process = ctx.Process(target=_timeout_worker, args=(result_queue, func, args))
    process.start()
    process.join(timeout_sec)

    if process.is_alive():
        process.terminate()
        process.join()
        raise TimeoutError(f"Operation timed out after {int(timeout_sec)}s")

    try:
        status, payload = result_queue.get_nowait()
    except queue.Empty as exc:  # pragma: no cover
        raise RuntimeError("Timed operation exited without returning a result") from exc

    if status == "error":
        raise RuntimeError(payload)
    return payload


def _normalize_match_text(text: str) -> str:
    return text.replace("’", "'").lower()


def _tokenize_match_words(text: str) -> list[str]:
    normalized = _normalize_match_text(text)
    words = re.findall(r"[a-z']+", normalized)
    cleaned: list[str] = []
    for word in words:
        if not word or word in MATCH_STOPWORDS:
            continue
        cleaned.append(word)
        if word.endswith("'s") and len(word) > 2:
            base = word[:-2]
            if base and base not in MATCH_STOPWORDS:
                cleaned.append(base)
    return cleaned


def _build_ngrams(tokens: list[str], size: int) -> set[tuple[str, ...]]:
    if len(tokens) < size:
        return set()
    return {tuple(tokens[index:index + size]) for index in range(len(tokens) - size + 1)}


def _ensure_track_match_features(track: dict) -> dict:
    tokens = track.get("match_tokens")
    if not isinstance(tokens, list):
        tokens = _tokenize_match_words(str(track.get("text", "")))
        track["match_tokens"] = tokens
    track_words = track.get("match_words")
    if not isinstance(track_words, set):
        track_words = set(tokens)
        track["match_words"] = track_words
    bigrams = track.get("match_bigrams")
    if not isinstance(bigrams, set):
        bigrams = _build_ngrams(tokens, 2)
        track["match_bigrams"] = bigrams
    trigrams = track.get("match_trigrams")
    if not isinstance(trigrams, set):
        trigrams = _build_ngrams(tokens, 3)
        track["match_trigrams"] = trigrams
    return track


def normalize_book_path(current_book: str | None, books_root: Path = BOOKS_ROOT) -> Path:
    current_book = (current_book or os.environ.get("CURRENT_BOOK") or DEFAULT_CURRENT_BOOK).strip().strip("/")
    book_path = books_root / current_book
    return book_path


def get_audioscripts_dir(current_book: str | None = None) -> Path:
    return normalize_book_path(current_book) / "Audioscripts"


def get_current_level(current_book: str | None = None) -> str:
    normalized = (current_book or os.environ.get("CURRENT_BOOK") or DEFAULT_CURRENT_BOOK).strip().strip("/")
    parts = [part for part in normalized.split("/") if part]
    return parts[-1] if parts else "unknown"


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


def get_audio_duration_seconds(wav_path: str) -> float:
    try:
        with contextlib.closing(wave.open(wav_path, "rb")) as wav_file:
            return wav_file.getnframes() / wav_file.getframerate()
    except Exception:
        return 0.0


def _estimate_minimum_word_count(duration_sec: float) -> int:
    if duration_sec <= 0:
        return 0
    return max(12, int(duration_sec * 0.85))


def _count_prepared_reference_words(reference_text: str) -> int:
    return len(re.findall(r"[A-Za-z']+", prepare_reference_text_for_llm(reference_text)))


def _strip_track_markers(standard_text: str) -> str:
    kept_lines = [
        line for line in clean_reference_text(standard_text).splitlines()
        if not re.match(r"^##\s+\d+\.\d+\s*$", line.strip())
    ]
    return clean_reference_text("\n".join(kept_lines))


def _trim_repeated_intro_phrase(line: str, transcript_text: str) -> str:
    word_matches = list(re.finditer(r"[A-Za-z']+", line.replace("’", "'")))
    if len(word_matches) < 4 or len(word_matches) % 2 != 0:
        return line.strip()
    half = len(word_matches) // 2
    first_half = [match.group(0).lower() for match in word_matches[:half]]
    second_half = [match.group(0).lower() for match in word_matches[half:]]
    if first_half != second_half:
        return line.strip()
    phrase = " ".join(first_half)
    transcript_normalized = " ".join(re.findall(r"[A-Za-z']+", transcript_text.replace("’", "'").lower()))
    if transcript_normalized.count(phrase) > 1:
        return line.strip()
    end_idx = word_matches[half - 1].end()
    return line[:end_idx].rstrip(" ,.;:!?…")


def _normalize_line_for_evidence(line: str) -> str:
    stripped = line.strip()
    stripped = re.sub(r"^\[Frame\s+\d+\]\s*$", "", stripped)
    stripped = re.sub(r"^\d+\s+", "", stripped)
    stripped = re.sub(r"^[A-Za-z][A-Za-z ,&']{0,60}:\s+", "", stripped)
    return stripped.strip()


def _line_has_any_evidence(line: str, transcript_words: set[str]) -> bool:
    line_words = _tokenize_content_words(_normalize_line_for_evidence(line))
    return bool(line_words and (line_words & transcript_words))

def _line_match_strength(
    line: str,
    transcript_words: set[str],
    transcript_bigrams: set[tuple[str, ...]],
) -> int:
    normalized_line = _normalize_line_for_evidence(line)
    tokens = _tokenize_match_words(normalized_line)
    if not tokens:
        return 0
    token_set = set(tokens)
    overlap = len(token_set & transcript_words)
    coverage = overlap / len(token_set)
    line_bigrams = _build_ngrams(tokens, 2)
    bigram_overlap = len(line_bigrams & transcript_bigrams)
    starts_with_matching_bigram = bool(tokens[:2] and tuple(tokens[:2]) in transcript_bigrams)

    if overlap >= 3:
        return 3
    if overlap >= 2 and (starts_with_matching_bigram or coverage >= 0.6):
        return 2
    if overlap >= 2 and bigram_overlap >= 2:
        return 2
    if overlap >= 1 and starts_with_matching_bigram:
        return 1
    return 0


def _select_track_lines(
    track_text: str,
    transcript_text: str,
    transcript_words: set[str],
    transcript_bigrams: set[tuple[str, ...]],
) -> list[str]:
    candidate_lines = [
        line for line in clean_reference_text(track_text).splitlines() if _normalize_line_for_evidence(line)
    ]
    if not candidate_lines:
        return []

    strengths = [_line_match_strength(line, transcript_words, transcript_bigrams) for line in candidate_lines]
    matched_indexes = [idx for idx, strength in enumerate(strengths) if strength >= 2]
    if not matched_indexes:
        matched_indexes = [idx for idx, strength in enumerate(strengths) if strength >= 1]
    if not matched_indexes:
        return []

    clusters: list[list[int]] = [[matched_indexes[0]]]
    for idx in matched_indexes[1:]:
        if idx - clusters[-1][-1] <= 2:
            clusters[-1].append(idx)
        else:
            clusters.append([idx])

    def cluster_key(indexes: list[int]) -> tuple[int, int, int]:
        total_strength = sum(strengths[idx] for idx in indexes)
        return (total_strength, len(indexes), indexes[-1])

    best_cluster = max(clusters, key=cluster_key)
    selected_clusters = [best_cluster]
    best_strength = sum(strengths[idx] for idx in best_cluster)
    for cluster in clusters:
        if cluster is best_cluster:
            continue
        cluster_strength = sum(strengths[idx] for idx in cluster)
        if len(cluster) >= 2 and cluster_strength >= max(8, int(best_strength * 0.5)):
            selected_clusters.append(cluster)

    selected_indexes: set[int] = set()
    for cluster in selected_clusters:
        selected_indexes.update(cluster)

        intro_candidates = [
            idx
            for idx in range(cluster[0])
            if strengths[idx] >= 1 and len(_tokenize_match_words(candidate_lines[idx])) <= 8
        ]
        if intro_candidates:
            selected_indexes.add(intro_candidates[0])

        for current, following in zip(cluster, cluster[1:]):
            gap = following - current - 1
            if gap <= 1:
                for idx in range(current + 1, following):
                    if strengths[idx] >= 1 or (
                        gap == 1
                        and strengths[current] >= 3
                        and strengths[following] >= 3
                        and len(_tokenize_match_words(candidate_lines[idx])) <= 8
                    ):
                        selected_indexes.add(idx)

        last_idx = cluster[-1]
        if last_idx + 1 < len(candidate_lines):
            next_line = candidate_lines[last_idx + 1]
            next_tokens = _tokenize_match_words(_normalize_line_for_evidence(next_line))
            if len(next_tokens) <= 3 and _line_matches_transcript_suffix_windows(next_line, transcript_text):
                selected_indexes.add(last_idx + 1)

    selected_lines: list[str] = []
    for idx in sorted(selected_indexes):
        line = candidate_lines[idx]
        if idx == min(selected_indexes):
            line = _trim_repeated_intro_phrase(line, transcript_text)
        selected_lines.append(line)
    return selected_lines


def _line_is_subsumed(normalized_line: str, seen_lines: set[str]) -> bool:
    if not normalized_line:
        return True
    for seen_line in seen_lines:
        if normalized_line == seen_line:
            return True
        if normalized_line in seen_line or seen_line in normalized_line:
            return True
    return False


def _render_selected_track_lines(selected_lines: list[tuple[str, str]]) -> str:
    rendered: list[str] = []
    active_track: str | None = None
    for track_num, raw_line in selected_lines:
        cleaned_line = _normalize_line_for_evidence(raw_line)
        if not cleaned_line:
            continue
        if track_num != active_track:
            rendered.append(f"## {track_num}")
            active_track = track_num
        rendered.append(cleaned_line)
    return clean_reference_text("\n".join(rendered))


def _expand_reference_span(track_sections: list[tuple[str, str]], transcript_text: str, minimum_word_count: int) -> str:
    if not track_sections:
        return ""

    transcript_tokens = _tokenize_match_words(transcript_text)
    transcript_words = set(transcript_tokens)
    transcript_bigrams = _build_ngrams(transcript_tokens, 2)
    if not transcript_words:
        flattened = [
            (track_num, line)
            for track_num, track_text in track_sections
            for line in clean_reference_text(track_text).splitlines()
        ]
        return _render_selected_track_lines(flattened)

    selected_lines: list[tuple[str, str]] = []
    seen_normalized_lines: set[str] = set()
    for track_num, track_text in track_sections:
        track_lines = _select_track_lines(track_text, transcript_text, transcript_words, transcript_bigrams)
        deduped_track_lines: list[tuple[str, str]] = []
        for raw_line in track_lines:
            normalized_line = _normalize_line_for_compare(_normalize_line_for_evidence(raw_line))
            if _line_is_subsumed(normalized_line, seen_normalized_lines):
                continue
            deduped_track_lines.append((track_num, raw_line))
            seen_normalized_lines.add(normalized_line)
        selected_lines.extend(deduped_track_lines)

    if not selected_lines:
        flattened = [
            (track_num, line)
            for track_num, track_text in track_sections
            for line in clean_reference_text(track_text).splitlines()
        ]
        return _render_selected_track_lines(flattened)
    return _render_selected_track_lines(selected_lines)


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


def _standard_is_substantially_shorter_than_transcript(standard_text: str, transcript_text: str) -> bool:
    transcript_word_count = len(re.findall(r"[A-Za-z']+", transcript_text))
    if transcript_word_count == 0:
        return False
    standard_word_count = _count_prepared_reference_words(standard_text)
    return standard_word_count < int(transcript_word_count * 0.75)


def build_output_paths(output_dir: str, base_name: str) -> dict[str, str]:
    return {
        "reference": os.path.join(output_dir, f"{base_name}.standard.txt"),
        "azure": os.path.join(output_dir, f"{base_name}.azure.json"),
        "results": os.path.join(output_dir, f"{base_name}.feedback.md"),
    }


def _format_matched_tracks(matched_tracks: list[str]) -> str:
    if not matched_tracks:
        return "unknown"
    return "\n".join(matched_tracks)


def _line_matches_transcript_tail(line: str, transcript_tail: str) -> bool:
    normalized_line = _normalize_line_for_compare(_normalize_line_for_evidence(line))
    normalized_tail = _normalize_line_for_compare(transcript_tail)
    if not normalized_line or not normalized_tail:
        return False
    line_tokens = normalized_line.split()
    tail_tokens = set(normalized_tail.split())
    overlap = sum(1 for token in line_tokens if token in tail_tokens)
    coverage = overlap / len(line_tokens)
    if len(line_tokens) <= 2 and overlap >= 1:
        return True
    if len(line_tokens) <= 3:
        ratio = difflib.SequenceMatcher(None, normalized_line, normalized_tail).ratio()
        if overlap >= 1 and ratio >= 0.45:
            return True
    if overlap >= 3 and coverage >= 0.5:
        return True
    return difflib.SequenceMatcher(None, normalized_line, normalized_tail).ratio() >= 0.6


def _line_matches_transcript_suffix_windows(line: str, transcript_text: str) -> bool:
    transcript_words = re.findall(r"[A-Za-z']+", transcript_text.replace("’", "'"))
    normalized_line = _normalize_line_for_compare(line)
    line_tokens = normalized_line.split()
    if not transcript_words or not line_tokens:
        return False
    for size in sorted({len(line_tokens), len(line_tokens) + 1, len(line_tokens) + 2}):
        suffix = " ".join(transcript_words[-size:])
        if _line_matches_transcript_tail(line, suffix):
            return True
    return False


def _best_track_closes_transcript(best_match: dict, transcript_text: str) -> bool:
    prepared = prepare_reference_text_for_llm(str(best_match.get("text", "")))
    lines = [line for line in prepared.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    transcript_words = re.findall(r"[A-Za-z']+", transcript_text.replace("’", "'"))
    transcript_tail = " ".join(transcript_words[-20:])
    if not transcript_tail:
        return False
    penultimate_matches = _line_matches_transcript_tail(lines[-2], transcript_tail)
    final_matches = _line_matches_transcript_tail(lines[-1], transcript_tail)
    return penultimate_matches and final_matches


def choose_report_tracks(matches: list[dict], transcript_text: str = "") -> list[str]:
    if not matches:
        return []
    best = matches[0]
    if transcript_text.strip() and _best_track_closes_transcript(best, transcript_text):
        return [best["track_num"]]
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
    matched_level: str,
    matched_unit: int | None,
    matched_tracks: list[str],
    standard_text: str,
    scores: dict,
    problem_words: list[dict],
    feedback_en: str,
) -> str:
    return f"""# Assessment Report: {base_name}

## Matched Level
{matched_level}

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
    matched_level: str,
    matched_unit: int | None,
    matched_tracks: list[str],
    standard_text: str,
    scores: dict,
    problem_words: list[dict],
    feedback_cn: str,
) -> str:
    return f"""# 评测报告：{base_name}

## 匹配 Level
{matched_level}

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
                "match_tokens": _tokenize_match_words(text),
            }
            tracks[track_num]["match_words"] = set(tracks[track_num]["match_tokens"])
            tracks[track_num]["match_bigrams"] = _build_ngrams(tracks[track_num]["match_tokens"], 2)
            tracks[track_num]["match_trigrams"] = _build_ngrams(tracks[track_num]["match_tokens"], 3)
    return tracks


def find_best_match(whisper_text: str, tracks: dict[str, dict], top_n: int = 5) -> list[dict]:
    """Find the best matching tracks using weighted lexical similarity plus phrase overlap."""
    whisper_tokens = _tokenize_match_words(whisper_text)
    whisper_words = set(whisper_tokens)
    if not whisper_words:
        return []

    track_items: list[tuple[str, dict]] = []
    document_frequency: dict[str, int] = {}
    for track_num, data in tracks.items():
        prepared = _ensure_track_match_features(data)
        track_items.append((track_num, prepared))
        for word in prepared["match_words"]:
            document_frequency[word] = document_frequency.get(word, 0) + 1

    total_tracks = len(track_items)
    if total_tracks == 0:
        return []

    whisper_bigrams = _build_ngrams(whisper_tokens, 2)
    whisper_trigrams = _build_ngrams(whisper_tokens, 3)
    matches: list[dict] = []
    for track_num, data in track_items:
        track_words = data["match_words"]
        if not track_words:
            continue

        weighted_overlap = 0.0
        weighted_total = 0.0
        for word in whisper_words:
            idf = math.log(1 + (total_tracks + 1) / (document_frequency.get(word, 0) + 1))
            weighted_total += idf
            if word in track_words:
                weighted_overlap += idf
        lexical_score = weighted_overlap / weighted_total if weighted_total else 0.0

        bigram_overlap = len(whisper_bigrams & data["match_bigrams"])
        trigram_overlap = len(whisper_trigrams & data["match_trigrams"])
        bigram_score = bigram_overlap / len(whisper_bigrams) if whisper_bigrams else 0.0
        trigram_score = trigram_overlap / len(whisper_trigrams) if whisper_trigrams else 0.0
        coverage_score = len(whisper_words & track_words) / len(whisper_words)
        score = (lexical_score * 0.6) + (coverage_score * 0.15) + (bigram_score * 0.15) + (trigram_score * 0.10)
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


def generate_standard_content(
    reference_text: str,
    whisper_text: str,
    track_header: str,
    unit: int,
    *,
    wav_path: str | None = None,
    track_sections: list[tuple[str, str]] | None = None,
) -> str:
    if not whisper_text.strip():
        return reference_text

    minimum_word_count = _estimate_minimum_word_count(get_audio_duration_seconds(wav_path)) if wav_path else 0
    sections = track_sections or [(track_header.replace("Track ", "").strip(), reference_text)]
    expanded_reference = _expand_reference_span(sections, whisper_text, minimum_word_count)
    prepared_reference = clean_reference_text(expanded_reference)
    if not prepared_reference.strip():
        return clean_reference_text(reference_text)
    return prepared_reference


def _normalize_alignment_word(word: str) -> str:
    return word.replace("’", "'").lower()


def _reference_words(reference_text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", reference_text.replace("’", "'"))


def _mark_mispronunciations(words: list[dict]) -> list[dict]:
    marked: list[dict] = []
    for word in words:
        updated = dict(word)
        if updated.get("error_type") in (None, "", "None") and float(updated.get("score", 0) or 0) < 60:
            updated["error_type"] = "Mispronunciation"
        marked.append(updated)
    return marked


def _align_assessment_words(reference_text: str, recognized_words: list[dict]) -> list[dict]:
    reference_words = _reference_words(reference_text)
    normalized_reference = [_normalize_alignment_word(word) for word in reference_words]
    normalized_recognized = [_normalize_alignment_word(str(word.get("word", ""))) for word in recognized_words]
    ref_len = len(reference_words)
    rec_len = len(recognized_words)

    dp = [[0] * (rec_len + 1) for _ in range(ref_len + 1)]
    for i in range(ref_len - 1, -1, -1):
        dp[i][rec_len] = ref_len - i
    for j in range(rec_len - 1, -1, -1):
        dp[ref_len][j] = rec_len - j

    for i in range(ref_len - 1, -1, -1):
        for j in range(rec_len - 1, -1, -1):
            best = math.inf
            if normalized_reference[i] == normalized_recognized[j]:
                best = dp[i + 1][j + 1]
            best = min(best, 1 + dp[i + 1][j], 1 + dp[i][j + 1])
            dp[i][j] = int(best)

    final_words: list[dict] = []
    i = 0
    j = 0
    while i < ref_len and j < rec_len:
        if normalized_reference[i] == normalized_recognized[j] and dp[i][j] == dp[i + 1][j + 1]:
            matched = dict(recognized_words[j])
            matched["word"] = reference_words[i]
            final_words.append(matched)
            i += 1
            j += 1
            continue
        if dp[i][j] == 1 + dp[i + 1][j]:
            final_words.append({"word": reference_words[i], "error_type": "Omission", "score": 0})
            i += 1
            continue
        insertion = dict(recognized_words[j])
        insertion["error_type"] = "Insertion"
        final_words.append(insertion)
        j += 1

    while i < ref_len:
        final_words.append({"word": reference_words[i], "error_type": "Omission", "score": 0})
        i += 1
    while j < rec_len:
        insertion = dict(recognized_words[j])
        insertion["error_type"] = "Insertion"
        final_words.append(insertion)
        j += 1

    return _mark_mispronunciations(final_words)


def _average_score(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _compute_pronunciation_score(
    *,
    accuracy: float,
    fluency: float,
    completeness: float,
    prosody: float | None = None,
) -> float:
    parts = [accuracy, fluency, completeness]
    if prosody is not None:
        parts.append(prosody)
    ordered = sorted(parts)
    if len(ordered) == 4:
        return 0.4 * ordered[0] + 0.2 * ordered[1] + 0.2 * ordered[2] + 0.2 * ordered[3]
    return 0.6 * ordered[0] + 0.2 * ordered[1] + 0.2 * ordered[2]


def _build_scores_from_aligned_words(
    reference_text: str,
    recognized_text: str,
    aligned_words: list[dict],
    fluency_scores: list[float],
    prosody_scores: list[float],
) -> dict:
    scored_words = [word for word in aligned_words if word.get("error_type") != "Insertion"]
    accuracy = _average_score([float(word.get("score", 0) or 0) for word in scored_words]) if scored_words else 0.0
    reference_count = len(_reference_words(reference_text))
    pronounced_count = sum(1 for word in aligned_words if word.get("error_type") not in ("Omission", "Insertion"))
    completeness = (pronounced_count / reference_count * 100) if reference_count else 0.0
    fluency = _average_score(fluency_scores)
    prosody = _average_score(prosody_scores) if prosody_scores else None
    pronunciation = _compute_pronunciation_score(
        accuracy=accuracy,
        fluency=fluency,
        completeness=completeness,
        prosody=prosody,
    )
    return {
        "recognized_text": recognized_text,
        "reference_text": reference_text,
        "scores": {
            "pronunciation": round(pronunciation, 1),
            "accuracy": round(accuracy, 1),
            "fluency": round(fluency, 1),
            "completeness": round(completeness, 1),
        },
        "words": [
            {
                "word": str(word.get("word", "")),
                "error_type": word.get("error_type"),
                "score": round(float(word.get("score", 0) or 0), 1),
            }
            for word in aligned_words
        ],
    }


def _azure_score_continuous(wav_path: str, reference_text: str, speechsdk) -> dict:
    speech_key = os.environ.get("AZURE_SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION", "westus")

    speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=region)
    speech_config.speech_recognition_language = "en-US"

    audio_config = speechsdk.AudioConfig(filename=wav_path)
    recognizer = speechsdk.SpeechRecognizer(speech_config, audio_config=audio_config)

    pronunciation_config = speechsdk.PronunciationAssessmentConfig(
        reference_text=reference_text,
        grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
        granularity=speechsdk.PronunciationAssessmentGranularity.Word,
        enable_miscue=False,
    )
    pronunciation_config.apply_to(recognizer)

    done = threading.Event()
    recognized_text_parts: list[str] = []
    recognized_words: list[dict] = []
    fluency_scores: list[float] = []
    prosody_scores: list[float] = []
    canceled_error: list[str] = []

    def on_recognized(evt) -> None:
        if evt.result.reason != speechsdk.ResultReason.RecognizedSpeech:
            return
        text = (evt.result.text or "").strip()
        if text:
            recognized_text_parts.append(text)
        pronunciation_result = speechsdk.PronunciationAssessmentResult(evt.result)
        fluency_scores.append(float(getattr(pronunciation_result, "fluency_score", 0.0) or 0.0))
        prosody_score = getattr(pronunciation_result, "prosody_score", None)
        if prosody_score is not None:
            prosody_scores.append(float(prosody_score))
        if getattr(pronunciation_result, "words", None):
            for word_result in pronunciation_result.words:
                recognized_words.append(
                    {
                        "word": word_result.word,
                        "error_type": getattr(word_result, "error_type", None) or "None",
                        "score": round(float(getattr(word_result, "accuracy_score", 0.0) or 0.0), 1),
                    }
                )

    def on_stop(evt) -> None:
        done.set()

    def on_cancel(evt) -> None:
        details = getattr(evt, "cancellation_details", None)
        canceled_error.append(str(details) if details else "Recognition canceled")
        done.set()

    recognizer.recognized.connect(on_recognized)
    recognizer.session_stopped.connect(on_stop)
    recognizer.canceled.connect(on_cancel)
    recognizer.start_continuous_recognition()
    done.wait()
    recognizer.stop_continuous_recognition()

    if canceled_error and not recognized_words:
        return {
            "error": canceled_error[0],
            "recognized_text": "",
            "reference_text": reference_text,
            "scores": {},
            "words": [],
        }

    aligned_words = _align_assessment_words(reference_text, recognized_words)
    recognized_text = " ".join(part for part in recognized_text_parts if part).strip()
    return _build_scores_from_aligned_words(
        reference_text,
        recognized_text,
        aligned_words,
        fluency_scores,
        prosody_scores,
    )


def _azure_score_impl(wav_path: str, reference_text: str) -> dict:
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

    if get_audio_duration_seconds(wav_path) > 30:
        return _azure_score_continuous(wav_path, reference_text, speechsdk)

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


def azure_score(wav_path: str, reference_text: str) -> dict:
    timeout_sec = float(os.environ.get("AZURE_SCORE_TIMEOUT_SEC", "120") or 120)
    try:
        return _run_with_timeout(_azure_score_impl, (wav_path, reference_text), timeout_sec=timeout_sec)
    except TimeoutError:
        return {
            "error": f"Azure pronunciation scoring timed out after {int(timeout_sec)}s",
            "recognized_text": "",
            "reference_text": reference_text,
            "scores": {},
            "words": [],
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
    matched_level = get_current_level()

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
    matched_tracks = choose_report_tracks(matches, whisper_text) if matches else [matched_track]
    track_sections = [
        (
            track_num,
            tracks[track_num]["text"],
        )
        for track_num in matched_tracks
        if track_num in tracks
    ]

    print("  ✨ Generating standard content...")
    if matches:
        standard_text = generate_standard_content(
            canonical_text,
            whisper_text,
            best_match["track_header"],
            best_match["unit"],
            wav_path=wav_path,
            track_sections=track_sections,
        )
    else:
        standard_text = whisper_text
    scoring_reference_text = _strip_track_markers(standard_text)

    output_paths = build_output_paths(output_dir, base_name)
    with open(output_paths["reference"], "w", encoding="utf-8") as file:
        file.write(standard_text)
    print(f"      Saved standard content: {os.path.basename(output_paths['reference'])}")

    print("  ⭐ Azure scoring...")
    scores = azure_score(wav_path, scoring_reference_text)
    if "error" in scores:
        print(f"      ⚠️ {scores['error']}")
    else:
        print(f"      Pronunciation: {scores['scores']['pronunciation']}/100")

    if matches and should_retry_standard_generation(scores) and _standard_is_substantially_shorter_than_transcript(standard_text, whisper_text):
        print("      Refining standard content from Azure recognized text...")
        retry_evidence_text = " ".join(
            part.strip()
            for part in [whisper_text, str(scores.get("recognized_text", ""))]
            if part and part.strip()
        )
        retry_standard_text = generate_standard_content(
            canonical_text,
            retry_evidence_text,
            best_match["track_header"],
            best_match["unit"],
            wav_path=wav_path,
            track_sections=track_sections,
        )
        retry_scoring_reference = _strip_track_markers(retry_standard_text)
        retry_scores = azure_score(wav_path, retry_scoring_reference)
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
    feedback_cn = build_feedback_fallback_cn(problem_words, scores.get("scores", {}))

    result_md = render_feedback_report_cn(
        base_name=base_name,
        matched_level=matched_level,
        matched_unit=matched_unit,
        matched_tracks=matched_tracks,
        standard_text=standard_text,
        scores=scores.get("scores", {}),
        problem_words=problem_words,
        feedback_cn=feedback_cn,
    )
    with open(output_paths["results"], "w", encoding="utf-8") as file:
        file.write(result_md)

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
