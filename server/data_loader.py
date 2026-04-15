from __future__ import annotations

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
