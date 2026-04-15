# Speech Review Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a lightweight HTTP server that serves a polished speech review page from evaluation artifacts, while renaming evaluation filenames from spaces to underscores.

**Architecture:** Keep the implementation inside a new `server/` package with clear separation between file loading/alignment, HTML rendering, and HTTP routing. Reuse the existing evaluation artifacts as the source of truth, and render a single responsive server-side HTML page with minimal inline JavaScript for word detail popovers.

**Tech Stack:** Python standard library HTTP server, existing `.env` loading via `python-dotenv`, unittest, server-side HTML rendering, minimal inline CSS/JavaScript.

---

## File Structure

- Create: `server/__init__.py`
- Create: `server/data_loader.py`
- Create: `server/render.py`
- Create: `server/http_server.py`
- Create: `tests/test_speech_server.py`
- Modify: `.env`
- Modify: `.gitignore`
- Modify: `evaluations/2026-04-14/*` by renaming spaces to underscores

Responsibilities:

- `server/data_loader.py`
  Read renamed evaluation artifacts, parse markdown sections, align Azure words to standard text, and produce a normalized page model.
- `server/render.py`
  Render the responsive HTML page and styled error pages.
- `server/http_server.py`
  Load config, route `GET /speech/<date>/<name>`, and return rendered HTML.
- `tests/test_speech_server.py`
  Cover renaming, route resolution, markdown parsing, alignment, color classification, and HTML rendering.

### Task 1: Add Server Tests for File Resolution and Parsing

**Files:**
- Create: `tests/test_speech_server.py`
- Test: `tests/test_speech_server.py`

- [ ] **Step 1: Write the failing tests for file path resolution and markdown parsing**

```python
import json
import tempfile
import unittest
from pathlib import Path

from server.data_loader import (
    build_evaluation_paths,
    parse_feedback_cn_markdown,
)


class SpeechServerDataTests(unittest.TestCase):
    def test_build_evaluation_paths_uses_underscore_names(self) -> None:
        base = Path("/repo/evaluations")
        paths = build_evaluation_paths(base, "2026-04-14", "Read_PB58")
        self.assertEqual(
            base / "2026-04-14" / "Read_PB58.standard.txt",
            paths["standard"],
        )
        self.assertEqual(
            base / "2026-04-14" / "Read_PB58.azure.json",
            paths["azure"],
        )
        self.assertEqual(
            base / "2026-04-14" / "Read_PB58.feedback.cn.md",
            paths["feedback_cn"],
        )

    def test_parse_feedback_cn_markdown_extracts_summary_sections(self) -> None:
        markdown = (
            "# 评测报告：Read_PB58\n\n"
            "## 匹配 Unit\n5\n\n"
            "## 匹配 Track\n5.05\n\n"
            "## 评分\n"
            "发音：71.6/100\n"
            "准确度：70.0/100\n"
            "流利度：77.0/100\n"
            "完整度：71.0/100\n\n"
            "## 重点问题词\n"
            "- Is：这个英文单词漏读了（分数：0）\n\n"
            "## 反馈\n"
            "你这次一直坚持读完了。\n"
        )
        parsed = parse_feedback_cn_markdown(markdown)
        self.assertEqual("5", parsed["matched_unit"])
        self.assertEqual(["5.05"], parsed["matched_tracks"])
        self.assertEqual(
            [
                "发音：71.6/100",
                "准确度：70.0/100",
                "流利度：77.0/100",
                "完整度：71.0/100",
            ],
            parsed["score_lines"],
        )
        self.assertEqual(["Is：这个英文单词漏读了（分数：0）"], parsed["problem_word_lines"])
        self.assertEqual(["你这次一直坚持读完了。"], parsed["feedback_lines"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=src python -m unittest tests.test_speech_server -v`

Expected: FAIL with `ModuleNotFoundError` or import errors for `server.data_loader`.

- [ ] **Step 3: Create the minimal package and loader stubs**

```python
# server/__init__.py
"""Speech review HTTP server package."""
```

```python
# server/data_loader.py
from __future__ import annotations

from pathlib import Path


def build_evaluation_paths(evaluations_root: Path, date: str, name: str) -> dict[str, Path]:
    base_dir = evaluations_root / date
    return {
        "standard": base_dir / f"{name}.standard.txt",
        "azure": base_dir / f"{name}.azure.json",
        "feedback_cn": base_dir / f"{name}.feedback.cn.md",
        "feedback_en": base_dir / f"{name}.feedback.md",
    }


def parse_feedback_cn_markdown(markdown: str) -> dict[str, object]:
    return {
        "matched_unit": "",
        "matched_tracks": [],
        "score_lines": [],
        "problem_word_lines": [],
        "feedback_lines": [],
    }
```

- [ ] **Step 4: Run the tests to verify the path test passes and the parser test still fails**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=. python -m unittest tests.test_speech_server -v`

Expected: one test PASS, one test FAIL because `parse_feedback_cn_markdown` returns empty values.

- [ ] **Step 5: Implement the markdown parser minimally**

```python
def parse_feedback_cn_markdown(markdown: str) -> dict[str, object]:
    sections: dict[str, list[str]] = {}
    current = ""
    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
            continue
        if current:
            if line.strip():
                sections[current].append(line.strip())

    return {
        "matched_unit": "\n".join(sections.get("匹配 Unit", [])),
        "matched_tracks": sections.get("匹配 Track", []),
        "score_lines": sections.get("评分", []),
        "problem_word_lines": sections.get("重点问题词", []),
        "feedback_lines": sections.get("反馈", []),
    }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=. python -m unittest tests.test_speech_server -v`

Expected: PASS, `Ran 2 tests`.

- [ ] **Step 7: Commit**

```bash
git add server/__init__.py server/data_loader.py tests/test_speech_server.py
git commit -m "test: add speech server path and markdown parsing coverage"
```

### Task 2: Add Azure Alignment and Color Classification

**Files:**
- Modify: `server/data_loader.py`
- Modify: `tests/test_speech_server.py`
- Test: `tests/test_speech_server.py`

- [ ] **Step 1: Write the failing tests for word alignment and severity colors**

```python
from server.data_loader import (
    align_standard_text_with_azure,
    classify_word_color,
)


class SpeechServerAlignmentTests(unittest.TestCase):
    def test_classify_word_color_maps_scores_and_error_types(self) -> None:
        self.assertEqual("red", classify_word_color({"error_type": "Omission", "score": 0}))
        self.assertEqual("red", classify_word_color({"error_type": "Mispronunciation", "score": 20}))
        self.assertEqual("yellow", classify_word_color({"error_type": "Mispronunciation", "score": 58}))
        self.assertEqual("green", classify_word_color({"error_type": "None", "score": 92}))

    def test_align_standard_text_with_azure_preserves_lines_and_attaches_words(self) -> None:
        standard_text = (
            "The Friendly Farm, the Friendly Farm,\n"
            "Gracie! What are you eating?\n"
            "Is that Jim's picture of the wildlife park?"
        )
        azure_words = [
            {"word": "The", "error_type": "None", "score": 94.0},
            {"word": "Friendly", "error_type": "None", "score": 91.0},
            {"word": "Farm", "error_type": "None", "score": 70.0},
            {"word": "Gracie", "error_type": "None", "score": 94.0},
            {"word": "Is", "error_type": "Omission", "score": 0},
            {"word": "Jim's", "error_type": "Mispronunciation", "score": 46.0},
            {"word": "wildlife", "error_type": "Mispronunciation", "score": 13.0},
        ]
        lines = align_standard_text_with_azure(standard_text, azure_words)
        self.assertEqual(3, len(lines))
        self.assertEqual("The Friendly Farm, the Friendly Farm,", lines[0]["text"])
        self.assertEqual("red", lines[2]["tokens"][0]["color"])
        self.assertEqual("yellow", lines[2]["tokens"][2]["color"])
        self.assertEqual("red", lines[2]["tokens"][5]["color"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=. python -m unittest tests.test_speech_server -v`

Expected: FAIL with missing functions from `server.data_loader`.

- [ ] **Step 3: Implement the minimal color and alignment helpers**

```python
import re


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
        for raw in re.findall(r"[A-Za-z0-9']+|[^A-Za-z0-9'\s]+|\s+", line):
            if raw.isspace():
                tokens.append({"text": raw, "kind": "space"})
                continue
            if not re.match(r"[A-Za-z0-9']+$", raw):
                tokens.append({"text": raw, "kind": "punct"})
                continue
            aligned = None
            normalized_raw = _normalize_token(raw)
            while azure_index < len(azure_words):
                candidate = azure_words[azure_index]
                azure_index += 1
                if _normalize_token(str(candidate.get("word", ""))) == normalized_raw:
                    aligned = candidate
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
```

- [ ] **Step 4: Run the tests to verify the alignment behavior**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=. python -m unittest tests.test_speech_server -v`

Expected: PASS, `Ran 4 tests`.

- [ ] **Step 5: Commit**

```bash
git add server/data_loader.py tests/test_speech_server.py
git commit -m "feat: add speech review word alignment"
```

### Task 3: Add File Loading and Friendly Chinese Detail Text

**Files:**
- Modify: `server/data_loader.py`
- Modify: `tests/test_speech_server.py`
- Test: `tests/test_speech_server.py`

- [ ] **Step 1: Write the failing tests for full page data loading**

```python
from server.data_loader import load_speech_review_page_data


class SpeechServerLoaderTests(unittest.TestCase):
    def test_load_speech_review_page_data_reads_all_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir) / "evaluations" / "2026-04-14"
            base.mkdir(parents=True)
            (base / "Read_PB58.standard.txt").write_text(
                "The Friendly Farm,\nGracie! What are you eating?\n",
                encoding="utf-8",
            )
            (base / "Read_PB58.azure.json").write_text(
                json.dumps(
                    {
                        "reference_text": "The Friendly Farm,\nGracie! What are you eating?\n",
                        "recognized_text": "The Friendly farm. Gracie. What are you eating?",
                        "scores": {
                            "pronunciation": 71.6,
                            "accuracy": 70.0,
                            "fluency": 77.0,
                            "completeness": 71.0,
                        },
                        "words": [
                            {"word": "The", "error_type": "None", "score": 94.0},
                            {"word": "Friendly", "error_type": "None", "score": 91.0},
                            {"word": "Farm", "error_type": "None", "score": 70.0},
                            {"word": "Gracie", "error_type": "None", "score": 94.0},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (base / "Read_PB58.feedback.cn.md").write_text(
                "# 评测报告：Read_PB58\n\n"
                "## 匹配 Unit\n5\n\n"
                "## 匹配 Track\n5.05\n\n"
                "## 评分\n发音：71.6/100\n\n"
                "## 反馈\n你这次一直坚持读完了。\n",
                encoding="utf-8",
            )
            (base / "Read_PB58.feedback.md").write_text("# noop\n", encoding="utf-8")

            data = load_speech_review_page_data(Path(tmp_dir) / "evaluations", "2026-04-14", "Read_PB58")

        self.assertEqual("Read_PB58", data["name"])
        self.assertEqual("2026-04-14", data["date"])
        self.assertEqual("5", data["matched_unit"])
        self.assertEqual(["5.05"], data["matched_tracks"])
        self.assertEqual(["发音：71.6/100"], data["score_lines_cn"])
        self.assertEqual(["你这次一直坚持读完了。"], data["feedback_lines_cn"])
        self.assertEqual(2, len(data["standard_lines"]))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=. python -m unittest tests.test_speech_server -v`

Expected: FAIL with missing `load_speech_review_page_data`.

- [ ] **Step 3: Implement data loading and friendly detail text**

```python
import json


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


def load_speech_review_page_data(evaluations_root: Path, date: str, name: str) -> dict[str, object]:
    paths = build_evaluation_paths(evaluations_root, date, name)
    standard_text = paths["standard"].read_text(encoding="utf-8")
    azure_data = json.loads(paths["azure"].read_text(encoding="utf-8"))
    feedback_cn = parse_feedback_cn_markdown(paths["feedback_cn"].read_text(encoding="utf-8"))
    aligned_lines = align_standard_text_with_azure(standard_text, azure_data.get("words", []))
    for line in aligned_lines:
        for token in line["tokens"]:
            if token.get("kind") == "word" and isinstance(token.get("detail"), dict):
                token["detail_text_cn"] = build_word_detail_cn(token["detail"])
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
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=. python -m unittest tests.test_speech_server -v`

Expected: PASS, `Ran 5 tests`.

- [ ] **Step 5: Commit**

```bash
git add server/data_loader.py tests/test_speech_server.py
git commit -m "feat: load speech review page data"
```

### Task 4: Add HTML Rendering and Responsive Page Layout

**Files:**
- Create: `server/render.py`
- Modify: `tests/test_speech_server.py`
- Test: `tests/test_speech_server.py`

- [ ] **Step 1: Write the failing tests for HTML rendering**

```python
from server.render import render_speech_review_page, render_not_found_page


class SpeechServerRenderTests(unittest.TestCase):
    def test_render_speech_review_page_contains_sections(self) -> None:
        html = render_speech_review_page(
            {
                "name": "Read_PB58",
                "date": "2026-04-14",
                "matched_unit": "5",
                "matched_tracks": ["5.05"],
                "scores": {
                    "pronunciation": 71.6,
                    "accuracy": 70.0,
                    "fluency": 77.0,
                    "completeness": 71.0,
                },
                "score_lines_cn": ["发音：71.6/100"],
                "problem_word_lines_cn": ["Is：这个英文单词漏读了（分数：0）"],
                "feedback_lines_cn": ["你这次一直坚持读完了。"],
                "standard_lines": [
                    {
                        "text": "Is that Jim's picture of the wildlife park?",
                        "tokens": [
                            {"text": "Is", "kind": "word", "color": "red", "detail_text_cn": "这个词这次漏读了。当前分数：0"},
                            {"text": " ", "kind": "space"},
                            {"text": "that", "kind": "word", "color": "neutral", "detail_text_cn": ""},
                        ],
                    }
                ],
            }
        )
        self.assertIn("speech-page", html)
        self.assertIn("Read_PB58", html)
        self.assertIn("word-chip red", html)
        self.assertIn("你这次一直坚持读完了。", html)
        self.assertIn("viewport", html)

    def test_render_not_found_page_contains_message(self) -> None:
        html = render_not_found_page("Read_PB58", ["Read_PB58.standard.txt"])
        self.assertIn("Read_PB58", html)
        self.assertIn("Read_PB58.standard.txt", html)
        self.assertIn("未找到", html)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=. python -m unittest tests.test_speech_server -v`

Expected: FAIL with missing `server.render`.

- [ ] **Step 3: Implement the renderer with responsive HTML**

```python
# server/render.py
from __future__ import annotations

from html import escape


def render_speech_review_page(data: dict[str, object]) -> str:
    score_cards = "".join(
        f'<div class="score-card"><div class="score-label">{label}</div><div class="score-value">{value}/100</div></div>'
        for label, value in [
            ("Pronunciation", data["scores"].get("pronunciation", "N/A")),
            ("Accuracy", data["scores"].get("accuracy", "N/A")),
            ("Fluency", data["scores"].get("fluency", "N/A")),
            ("Completeness", data["scores"].get("completeness", "N/A")),
        ]
    )

    line_blocks = []
    for line in data["standard_lines"]:
        token_html = []
        for token in line["tokens"]:
            kind = token.get("kind")
            text = escape(token.get("text", ""))
            if kind == "word":
                color = token.get("color", "neutral")
                detail = escape(token.get("detail_text_cn", ""))
                token_html.append(
                    f'<button class="word-chip {color}" data-detail="{detail}" onclick="showWordDetail(this)">{text}</button>'
                )
            else:
                token_html.append(text)
        line_blocks.append(f'<div class="reading-line">{"".join(token_html)}</div>')

    feedback_blocks = "".join(f"<p>{escape(line)}</p>" for line in data["feedback_lines_cn"])
    score_lines = "".join(f"<p>{escape(line)}</p>" for line in data["score_lines_cn"])

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(data["name"])}</title>
  <style>
    :root {{
      --bg: #f5f1ea;
      --card: rgba(255,255,255,0.82);
      --ink: #1f2937;
      --muted: #6b7280;
      --green: #d8f2dc;
      --yellow: #fff2bf;
      --red: #ffd8d2;
      --shadow: 0 18px 60px rgba(55, 41, 24, 0.10);
    }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: radial-gradient(circle at top, #fdf9f2 0%, #f0ebe3 70%);
      color: var(--ink);
    }}
    .speech-page {{
      max-width: 960px;
      margin: 0 auto;
      padding: 24px 16px 64px;
    }}
    .hero, .card {{
      background: var(--card);
      backdrop-filter: blur(10px);
      border-radius: 28px;
      box-shadow: var(--shadow);
      padding: 20px;
      margin-bottom: 20px;
    }}
    .score-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .score-card {{
      border-radius: 18px;
      padding: 14px;
      background: rgba(255,255,255,0.75);
    }}
    .reading-line {{
      line-height: 1.9;
      font-size: clamp(20px, 2.5vw, 28px);
      margin: 0 0 8px;
      word-break: break-word;
    }}
    .word-chip {{
      border: none;
      border-radius: 12px;
      padding: 2px 4px;
      font: inherit;
      color: inherit;
      background: transparent;
    }}
    .word-chip.green {{ background: var(--green); }}
    .word-chip.yellow {{ background: var(--yellow); }}
    .word-chip.red {{ background: var(--red); }}
    .word-chip.neutral {{ background: transparent; }}
    .detail-popover {{
      position: fixed;
      left: 16px;
      right: 16px;
      bottom: 16px;
      display: none;
      background: rgba(28, 28, 30, 0.94);
      color: white;
      border-radius: 18px;
      padding: 16px;
      box-shadow: var(--shadow);
    }}
    .detail-popover.visible {{ display: block; }}
    @media (min-width: 768px) {{
      .detail-popover {{
        max-width: 360px;
        left: auto;
        right: 24px;
        bottom: 24px;
      }}
    }}
  </style>
</head>
<body>
  <main class="speech-page">
    <section class="hero">
      <p>{escape(data["date"])} · Unit {escape(str(data["matched_unit"]))} · Track {" / ".join(data["matched_tracks"])}</p>
      <h1>{escape(data["name"])}</h1>
      <div class="score-grid">{score_cards}</div>
    </section>
    <section class="card">
      <h2>标准文本</h2>
      {''.join(line_blocks)}
    </section>
    <section class="card">
      <h2>中文反馈</h2>
      {score_lines}
      {feedback_blocks}
    </section>
    <section class="card">
      <p>绿色：比较稳定</p>
      <p>黄色：还可以更清楚</p>
      <p>红色：这次要重点练习</p>
    </section>
  </main>
  <div id="detail-popover" class="detail-popover"></div>
  <script>
    function showWordDetail(button) {{
      const popover = document.getElementById('detail-popover');
      const detail = button.getAttribute('data-detail');
      if (!detail) return;
      popover.textContent = detail;
      popover.classList.add('visible');
    }}
    document.addEventListener('click', (event) => {{
      if (!event.target.classList.contains('word-chip')) {{
        document.getElementById('detail-popover').classList.remove('visible');
      }}
    }});
  </script>
</body>
</html>"""


def render_not_found_page(name: str, missing_files: list[str]) -> str:
    items = "".join(f"<li>{escape(item)}</li>" for item in missing_files)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>未找到</title></head>
<body><main><h1>未找到 {escape(name)}</h1><ul>{items}</ul></main></body>
</html>"""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=. python -m unittest tests.test_speech_server -v`

Expected: PASS, `Ran 7 tests`.

- [ ] **Step 5: Commit**

```bash
git add server/render.py tests/test_speech_server.py
git commit -m "feat: render speech review page"
```

### Task 5: Add HTTP Routing and Configurable Port

**Files:**
- Create: `server/http_server.py`
- Modify: `.env`
- Modify: `.gitignore`
- Modify: `tests/test_speech_server.py`
- Test: `tests/test_speech_server.py`

- [ ] **Step 1: Write the failing tests for route parsing**

```python
from server.http_server import parse_speech_path


class SpeechServerRouteTests(unittest.TestCase):
    def test_parse_speech_path_extracts_date_and_name(self) -> None:
        self.assertEqual(
            ("2026-04-14", "Read_PB58"),
            parse_speech_path("/speech/2026-04-14/Read_PB58"),
        )

    def test_parse_speech_path_rejects_invalid_routes(self) -> None:
        self.assertIsNone(parse_speech_path("/"))
        self.assertIsNone(parse_speech_path("/speech/2026-04-14"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=. python -m unittest tests.test_speech_server -v`

Expected: FAIL with missing `server.http_server`.

- [ ] **Step 3: Add `.env` config and minimal route parser**

```dotenv
SERVER_PORT=6001
```

```python
# server/http_server.py
from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from server.data_loader import load_speech_review_page_data
from server.render import render_not_found_page, render_speech_review_page

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATIONS_ROOT = REPO_ROOT / "evaluations"


def parse_speech_path(path: str) -> tuple[str, str] | None:
    parsed = urlparse(path)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 3 or parts[0] != "speech":
        return None
    return parts[1], parts[2]
```

- [ ] **Step 4: Complete the HTTP handler**

```python
class SpeechReviewHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        resolved = parse_speech_path(self.path)
        if resolved is None:
            self._send_html(404, render_not_found_page("speech", ["有效路径形如 /speech/2026-04-14/Read_PB58"]))
            return

        date, name = resolved
        try:
            page_data = load_speech_review_page_data(EVALUATIONS_ROOT, date, name)
        except FileNotFoundError as exc:
            self._send_html(404, render_not_found_page(name, [str(exc)]))
            return
        except Exception as exc:
            self._send_html(500, render_not_found_page(name, [str(exc)]))
            return

        self._send_html(200, render_speech_review_page(page_data))

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_html(self, status: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def run() -> None:
    port = int(os.environ.get("SERVER_PORT", "6001"))
    server = ThreadingHTTPServer(("0.0.0.0", port), SpeechReviewHandler)
    print(f"Speech review server running on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
```

- [ ] **Step 5: Ignore generated browser state if needed**

```gitignore
.superpowers/
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=. python -m unittest tests.test_speech_server -v`

Expected: PASS, `Ran 9 tests`.

- [ ] **Step 7: Commit**

```bash
git add .env .gitignore server/http_server.py tests/test_speech_server.py
git commit -m "feat: add speech review http server"
```

### Task 6: Rename Evaluation Files to Underscores

**Files:**
- Modify: `evaluations/2026-04-14/*`

- [ ] **Step 1: List the files that still contain spaces**

Run: `find evaluations/2026-04-14 -maxdepth 1 -type f | sed -n '/ /p'`

Expected: output includes `Read PB58.standard.txt`-style names.

- [ ] **Step 2: Rename the files in place**

```bash
python - <<'PY'
from pathlib import Path

base = Path("evaluations/2026-04-14")
for path in sorted(base.iterdir()):
    if path.is_file() and " " in path.name:
        path.rename(path.with_name(path.name.replace(" ", "_")))
PY
```

- [ ] **Step 3: Verify renamed files exist**

Run: `find evaluations/2026-04-14 -maxdepth 1 -type f | sort`

Expected: underscore names only, no spaces.

- [ ] **Step 4: Commit**

```bash
git add evaluations/2026-04-14
git commit -m "chore: rename evaluation files with underscores"
```

### Task 7: Verify End-to-End Rendering

**Files:**
- Modify: `server/data_loader.py` if needed
- Modify: `server/render.py` if needed
- Test: `tests/test_speech_server.py`

- [ ] **Step 1: Run the full test suite**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=. python -m unittest tests.test_speech_server tests.test_pipeline_helpers tests.test_audioscripts_parser -v`

Expected: PASS, zero failures.

- [ ] **Step 2: Start the server locally**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=. python -m server.http_server`

Expected: prints `Speech review server running on http://127.0.0.1:6001`

- [ ] **Step 3: Open the sample route and inspect it manually**

URL: `http://127.0.0.1:6001/speech/2026-04-14/Read_PB58`

Manual checks:

- standard text line breaks match `.standard.txt`
- colored words render correctly
- tapping a word shows a Chinese friendly detail
- score cards are visible and readable
- Chinese feedback is below the text
- layout is readable in browser mobile and tablet responsive modes

- [ ] **Step 4: If manual verification needs a tweak, make the minimal change and rerun tests**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=. python -m unittest tests.test_speech_server -v`

Expected: PASS after any small adjustment.

- [ ] **Step 5: Commit**

```bash
git add server tests .env .gitignore evaluations/2026-04-14
git commit -m "feat: add speech review server UI"
```

## Self-Review

Spec coverage check:

- underscore filenames: covered in Task 6
- server directory and configurable port: covered in Task 5
- `/speech/<date>/<name>` routing: covered in Task 5
- standard text with line breaks: covered in Tasks 2 and 4
- Azure score coloring: covered in Task 2
- Chinese friendly popovers: covered in Task 3 and Task 4
- feedback.cn summary and feedback rendering: covered in Task 1, Task 3, and Task 4
- modern responsive UI: covered in Task 4 and Task 7

Placeholder scan:

- removed generic “handle edge cases” language and replaced with exact test/code steps
- all code steps include concrete file content or concrete commands

Type consistency:

- `load_speech_review_page_data()` returns keys consumed by `render_speech_review_page()`
- route parser signature and names are consistent across test and server tasks
- alignment token structure uses `text`, `kind`, `color`, `detail_text_cn` consistently

