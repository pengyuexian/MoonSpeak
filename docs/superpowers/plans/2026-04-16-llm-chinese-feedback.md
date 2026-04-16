# LLM Chinese Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the final feedback with LLM-generated Chinese guidance, collapse report output to a single `*.feedback.md`, and update the server page to read that file and show an AI disclaimer.

**Architecture:** Keep structured assessment facts in code and limit LLM usage to the final Chinese feedback paragraph. Validate the LLM output against extracted problem words and fallback to the existing Chinese template when it is missing required details or mistranslates quoted English words. Update all report consumers to use the single markdown artifact.

**Tech Stack:** Python, unittest, markdown report files, existing MiniMax/GLM LLM helpers, existing HTTP server renderer.

---

### Task 1: Switch report artifact paths to a single feedback file

**Files:**
- Modify: `src/moonspeak/pipeline.py`
- Modify: `server/data_loader.py`
- Modify: `tests/test_speech_server.py`
- Modify: `tests/test_run_assessment.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_speech_server.py
self.assertEqual(
    base / "2026-04-14" / "Read_PB58.feedback.md",
    paths["feedback"],
)
self.assertNotIn("feedback_cn", paths)
self.assertNotIn("feedback_en", paths)

# tests/test_run_assessment.py
pipeline_result={"files": {"results": "Read_PB58.feedback.md"}}
self.assertEqual("/repo/evaluations/2026-04-15/Read_PB58.feedback.md", result["report_path"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=.:src python -m unittest tests.test_speech_server tests.test_run_assessment -v`
Expected: FAIL because code still expects `feedback_cn` / `feedback_en` keys and `.feedback.cn.md` paths.

- [ ] **Step 3: Write minimal implementation**

```python
# server/data_loader.py
return {
    "standard": base_dir / f"{name}.standard.txt",
    "azure": base_dir / f"{name}.azure.json",
    "feedback": base_dir / f"{name}.feedback.md",
}

# src/moonspeak/pipeline.py
return {
    "reference": os.path.join(output_dir, f"{base_name}.standard.txt"),
    "azure": os.path.join(output_dir, f"{base_name}.azure.json"),
    "results": os.path.join(output_dir, f"{base_name}.feedback.md"),
}
```

- [ ] **Step 4: Update report consumers**

```python
# server/data_loader.py
feedback_md = parse_feedback_cn_markdown(paths["feedback"].read_text(encoding="utf-8"))

# tests/test_run_assessment.py expectations
Path(output_dir) / "Read_PB58.feedback.md"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=.:src python -m unittest tests.test_speech_server tests.test_run_assessment -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/moonspeak/pipeline.py server/data_loader.py tests/test_speech_server.py tests/test_run_assessment.py
git commit -m "Unify feedback report artifact"
```

### Task 2: Add LLM-first Chinese feedback generation with validation and fallback

**Files:**
- Modify: `src/moonspeak/pipeline.py`
- Modify: `tests/test_pipeline_helpers.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_llm_generate_feedback_cn_keeps_quoted_english_words(self):
    result = pipeline.llm_generate_feedback_cn(
        scores={"pronunciation": 70, "fluency": 72, "words": []},
        recognized_text="it is big",
        reference_text='Read "it" clearly.',
        problem_words=[{"word": "it", "error_type": "Mispronunciation", "score": 20}],
    )
    self.assertIn('"it"', result)


def test_llm_generate_feedback_cn_falls_back_when_word_is_translated(self):
    with patch("src.moonspeak.pipeline.llm_chat", return_value='你把“它”读错了，需要再练习。'):
        result = pipeline.llm_generate_feedback_cn(
            scores={"fluency": 60, "words": []},
            recognized_text="it is big",
            reference_text='Read "it" clearly.',
            problem_words=[{"word": "it", "error_type": "Mispronunciation", "score": 20}],
        )
    self.assertIn('"it"', result)
    self.assertNotIn('“它”', result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=.:src python -m unittest tests.test_pipeline_helpers -v`
Expected: FAIL because `llm_generate_feedback_cn` does not exist or does not validate quoted English words.

- [ ] **Step 3: Write minimal implementation**

```python
def build_feedback_prompt_cn(scores: dict, recognized_text: str, reference_text: str, problem_words: list[dict]) -> str:
    problem_summary = "\n".join(
        f'- "{item["word"]}" ({item["error_type"]}, score {item["score"]})'
        for item in problem_words
    ) or "- none"
    return f"""一个孩子刚完成英语朗读，请用中文写一段鼓励但有指导性的反馈。

参考原文：{reference_text}
识别结果：{recognized_text}
评分：{scores}
重点问题词：
{problem_summary}

要求：
- 只输出中文反馈正文
- 适合孩子和家长阅读
- 先肯定，再给具体练习建议
- 如果引用英文词，必须保持英文原样，例如 \"it\"
- 不要把这些英文词翻译成中文
- 不要说问题词读得很好
"""


def llm_generate_feedback_cn(scores: dict, recognized_text: str, reference_text: str, problem_words: list[dict]) -> str:
    prompt = build_feedback_prompt_cn(scores, recognized_text, reference_text, problem_words)
    for chat in (llm_chat, llm_chat_glm):
        try:
            result = chat("你是一位给儿童英语朗读提供反馈的老师。", prompt, temperature=0.2, max_tokens=700)
        except Exception:
            continue
        if (
            result
            and _feedback_looks_complete(result)
            and _feedback_covers_problem_words(result, problem_words)
            and _translation_keeps_english_words(result, _problem_word_list(problem_words))
            and not _feedback_has_contradictions(result, problem_words)
        ):
            return result.strip()
    return build_feedback_fallback_cn(problem_words, scores)
```

- [ ] **Step 4: Replace current feedback generation call site**

```python
problem_words = extract_problem_words(scores)
feedback_cn = llm_generate_feedback_cn(
    scores=scores.get("scores", {}),
    recognized_text=str(scores.get("recognized_text", "")),
    reference_text=scoring_reference_text,
    problem_words=problem_words,
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=.:src python -m unittest tests.test_pipeline_helpers -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/moonspeak/pipeline.py tests/test_pipeline_helpers.py
git commit -m "Use LLM-generated Chinese feedback with fallback"
```

### Task 3: Collapse report writing to a single Chinese markdown file

**Files:**
- Modify: `src/moonspeak/pipeline.py`
- Modify: `tests/test_pipeline_helpers.py`

- [ ] **Step 1: Write the failing test**

```python
def test_assess_audio_returns_single_feedback_report_file(self):
    result = pipeline.assess_audio("/tmp/Read_PB58.m4a", output_dir="/tmp/out", scripts_dir="/tmp/scripts")
    self.assertIn("results", result["files"])
    self.assertNotIn("results_cn", result["files"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=.:src python -m unittest tests.test_pipeline_helpers -v`
Expected: FAIL because return payload still includes `results_cn` and writes two files.

- [ ] **Step 3: Write minimal implementation**

```python
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
    ...,
    "feedback_cn": feedback_cn,
    "files": {
        "reference": os.path.basename(output_paths["reference"]),
        "results": os.path.basename(output_paths["results"]),
    },
}
```

- [ ] **Step 4: Delete obsolete English/translation call path from `assess_audio`**

```python
# remove feedback_en generation
# remove result_cn_md write
# keep render_feedback_report_en helper only if still referenced elsewhere; otherwise delete it
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=.:src python -m unittest tests.test_pipeline_helpers tests.test_run_assessment -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/moonspeak/pipeline.py tests/test_pipeline_helpers.py tests/test_run_assessment.py
git commit -m "Write single Chinese feedback report"
```

### Task 4: Update server loader and page disclaimer

**Files:**
- Modify: `server/data_loader.py`
- Modify: `server/render.py`
- Modify: `tests/test_speech_server.py`

- [ ] **Step 1: Write the failing tests**

```python
self.assertEqual(["你这次一直坚持读完了。"], data["feedback_lines"])
self.assertIn("AI 生成的反馈可能不完全准确，请结合录音和实际朗读情况一起判断。", html)
self.assertIn("feedback-note", html)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=.:src python -m unittest tests.test_speech_server -v`
Expected: FAIL because loader still exposes `feedback_lines_cn` and page has no disclaimer.

- [ ] **Step 3: Write minimal implementation**

```python
# server/data_loader.py
return {
    ...,
    "feedback_lines": feedback_md["feedback_lines"],
}

# server/render.py
feedback_blocks = "".join(f"<p>{escape(line)}</p>" for line in data["feedback_lines"])
...
<p class="feedback-note">AI 生成的反馈可能不完全准确，请结合录音和实际朗读情况一起判断。</p>
```

- [ ] **Step 4: Add note styling**

```css
.feedback-note {
  margin-top: 14px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--muted);
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=.:src python -m unittest tests.test_speech_server -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add server/data_loader.py server/render.py tests/test_speech_server.py
git commit -m "Update speech page to use single feedback file"
```

### Task 5: Full regression verification

**Files:**
- Modify: `tests/test_pipeline_helpers.py`
- Modify: `tests/test_run_assessment.py`
- Modify: `tests/test_speech_server.py`

- [ ] **Step 1: Run the full suite**

Run: `conda run --no-capture-output -n moonspeak env PYTHONPATH=.:src python -m unittest tests.test_speech_server tests.test_pipeline_helpers tests.test_audioscripts_parser tests.test_run_assessment -v`
Expected: PASS, 0 failures.

- [ ] **Step 2: Verify no code still depends on `feedback.cn.md`**

Run: `rg -n "feedback\.cn\.md|feedback_cn|results_cn" src server tests scripts`
Expected: no remaining runtime references, or only test names/comments that are intentionally updated.

- [ ] **Step 3: Commit final cleanup**

```bash
git add src/moonspeak/pipeline.py server/data_loader.py server/render.py tests/test_pipeline_helpers.py tests/test_run_assessment.py tests/test_speech_server.py
git commit -m "Finalize LLM Chinese feedback flow"
```
