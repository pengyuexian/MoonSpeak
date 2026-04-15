from __future__ import annotations

from html import escape


def render_speech_review_page(data: dict[str, object]) -> str:
    scores = data["scores"]
    score_cards = "".join(
        f'<div class="score-card"><div class="score-label">{label}</div><div class="score-value">{value}/100</div></div>'
        for label, value in [
            ("Pronunciation", scores.get("pronunciation", "N/A")),
            ("Accuracy", scores.get("accuracy", "N/A")),
            ("Fluency", scores.get("fluency", "N/A")),
            ("Completeness", scores.get("completeness", "N/A")),
        ]
    )

    line_blocks: list[str] = []
    for line in data["standard_lines"]:
        token_html: list[str] = []
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
