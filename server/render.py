from __future__ import annotations

from html import escape


def render_speech_review_page(data: dict[str, object]) -> str:
    scores = data["scores"]
    score_specs = [
        ("score-card-pronunciation", "发音", scores.get("pronunciation", "N/A")),
        ("score-card-accuracy", "准确度", scores.get("accuracy", "N/A")),
        ("score-card-fluency", "流利度", scores.get("fluency", "N/A")),
        ("score-card-completeness", "完整度", scores.get("completeness", "N/A")),
    ]
    score_cards = "".join(
        f'<div class="score-card {card_class}"><div class="score-card-label">{label}</div><div class="score-card-value">{value}</div></div>'
        for card_class, label, value in score_specs
    )

    feedback_blocks = "".join(f"<p>{escape(line)}</p>" for line in data["feedback_lines"])
    feedback_disclaimer = (
        '<p class="feedback-disclaimer">'
        "AI 生成的反馈可能不完全准确，请结合录音和实际朗读情况一起判断。"
        "</p>"
    )

    user_url = data.get("audio_url_user")
    user_btn_html = (
        f'<button class="audio-btn user-btn" data-type="user" data-url="{user_url}" onclick="playAudio(this, \'{user_url}\')">'
        '<span class="icon"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></span>'
        '<span class="label">播放跟读</span></button>'
        if user_url else ""
    )

    track_section_blocks: list[str] = []
    for section in data["track_sections"]:
        line_blocks: list[str] = []
        for line in section["lines"]:
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

        track_url = section.get("audio_url_track")
        track_btn_html = (
            f'<button class="audio-btn track-btn" data-type="original" data-url="{track_url}" onclick="playAudio(this, \'{track_url}\')">'
            '<span class="icon"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></span>'
            '<span class="label">播放原声</span></button>'
            if track_url else ""
        )
        header = escape(section["track_num"]) if section.get("track_num") else ""
        track_section_blocks.append(
            f'<section class="track-block"><h3>{header}</h3>{"".join(line_blocks)}<div class="audio-controls track-audio">{track_btn_html}</div></section>'
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(data["name"])}</title>
  <style>
    :root {{
      --bg: #fcfcf9;
      --card-bg: #ffffff;
      --ink: #2d3436;
      --muted: #636e72;
      --accent-1: #ffeaa7; /* 发音 - 柔黄色 */
      --accent-2: #81ecec; /* 准确度 - 柔青色 */
      --accent-3: #74b9ff; /* 流利度 - 柔蓝色 */
      --accent-4: #fab1a0; /* 完整度 - 柔橙色 */
      --shadow: 0 8px 30px rgba(0, 0, 0, 0.04);
    }}
    body {{
      margin: 0;
      font-family: "Rounded Mplus 1c", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      background-color: var(--bg);
      color: var(--ink);
    }}
    .speech-page {{
      max-width: 800px;
      margin: 0 auto;
      padding: 20px 12px;
    }}
    .hero, .card {{
      background: var(--card-bg);
      border-radius: 24px;
      box-shadow: var(--shadow);
      padding: 24px;
      margin-bottom: 20px;
      border: 1px solid rgba(0,0,0,0.02);
    }}
    .hero p {{
      font-size: 14px;
      color: var(--muted);
      margin-top: 0;
      margin-bottom: 8px;
    }}
    .hero h1 {{
      font-size: 26px;
      margin: 0 0 20px 0;
      font-weight: 800;
      color: #1a1a1a;
    }}
    .score-grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
    }}
    .score-card {{
      background: #fafafa;
      border-radius: 18px;
      padding: 14px 8px;
      text-align: center;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      border: 2px solid transparent;
      transition: all 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    }}
    .score-card:hover {{
      transform: translateY(-3px);
      box-shadow: 0 6px 16px rgba(0,0,0,0.06);
      background: #ffffff;
    }}
    .score-card-pronunciation {{ border-color: var(--accent-1); }}
    .score-card-accuracy {{ border-color: var(--accent-2); }}
    .score-card-fluency {{ border-color: var(--accent-3); }}
    .score-card-completeness {{ border-color: var(--accent-4); }}
    
    .score-card-label {{
      font-size: 13px;
      font-weight: 600;
      color: var(--muted);
    }}
    .score-card-value {{
      font-size: 22px;
      font-weight: 900;
      color: var(--ink);
      font-variant-numeric: tabular-nums;
    }}
    h2 {{
      font-size: 20px;
      margin-top: 0;
      margin-bottom: 20px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    h2::before {{
      content: "";
      display: inline-block;
      width: 4px;
      height: 20px;
      background: var(--accent-3);
      border-radius: 2px;
    }}
    .section-heading {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 20px;
    }}
    .section-heading h2 {{
      margin-bottom: 0;
    }}
    .section-heading-action {{
      flex-shrink: 0;
      display: flex;
      align-items: center;
    }}
    .reading-line {{
      line-height: 1.6;
      font-size: 26px;
      margin-bottom: 8px;
      word-break: break-word;
    }}
    .track-block {{
      padding: 14px 0 18px 0;
      border-bottom: 1px solid rgba(0,0,0,0.06);
    }}
    .track-block:last-of-type {{
      border-bottom: none;
      padding-bottom: 8px;
    }}
    .track-block h3 {{
      margin: 0 0 14px 0;
      font-size: 20px;
      color: var(--muted);
      font-weight: 700;
      letter-spacing: 0.02em;
      line-height: 1.2;
    }}
    .word-chip {{
      border: none;
      border-radius: 8px;
      padding: 2px 4px;
      font: inherit;
      color: inherit;
      cursor: pointer;
      transition: all 0.2s;
      background: transparent;
      font-weight: 500;
    }}
    .word-chip:hover {{ transform: scale(1.05); }}
    .word-chip.green {{ background: #e3f9e5; color: #1b5e20; }}
    .word-chip.yellow {{ background: #fff9db; color: #f59f00; }}
    .word-chip.red {{ background: #fff5f5; color: #e03131; }}
    
    .detail-popover {{
      position: fixed;
      left: 50%;
      transform: translateX(-50%);
      bottom: 24px;
      width: calc(100% - 40px);
      max-width: 420px;
      background: rgba(45, 52, 54, 0.95);
      backdrop-filter: blur(8px);
      color: white;
      padding: 18px;
      border-radius: 20px;
      display: none;
      box-shadow: 0 12px 30px rgba(0,0,0,0.25);
      z-index: 100;
      text-align: center;
      animation: slideUp 0.3s ease-out;
    }}
    @keyframes slideUp {{
      from {{ transform: translate(-50%, 20px); opacity: 0; }}
      to {{ transform: translate(-50%, 0); opacity: 1; }}
    }}
    .detail-popover.visible {{ display: block; }}
    .audio-controls {{
      margin-top: 24px;
      display: flex;
      gap: 12px;
      padding-top: 16px;
      border-top: 1px solid rgba(0,0,0,0.05);
    }}
    .track-audio {{
      margin-top: 14px;
      padding-top: 12px;
    }}
    .audio-btn {{
      position: relative;
      overflow: hidden;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 16px;
      border-radius: 999px;
      border: none;
      background: #f0f2f5;
      color: var(--ink);
      font-size: 15px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
      box-shadow: 0 4px 12px rgba(0,0,0,0.03);
    }}
    .audio-btn::before {{
      content: "";
      position: absolute;
      left: 0;
      top: 0;
      bottom: 0;
      width: var(--progress, 0%);
      background: rgba(0, 0, 0, 0.06);
      transition: width 0.1s linear;
      z-index: 0;
    }}
    .audio-btn span, .audio-btn svg {{
      position: relative;
      z-index: 1;
    }}
    .audio-btn:hover {{
      background: #e4e7eb;
      transform: translateY(-2px);
      box-shadow: 0 6px 16px rgba(0,0,0,0.08);
    }}
    .audio-btn:active {{
      transform: translateY(0);
    }}
    .audio-btn svg {{
      width: 20px;
      height: 20px;
      fill: currentColor;
    }}
    .audio-btn.track-btn {{
      background: #e3f2fd;
      color: #1976d2;
    }}
    .audio-btn.track-btn:hover {{ background: #bbdefb; }}
    .audio-btn.user-btn {{
      background: #e8f5e9;
      color: #2e7d32;
    }}
    .audio-btn.user-btn:hover {{ background: #c8e6c9; }}
    
    .audio-btn.playing {{
      box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    }}
    .feedback-disclaimer {{
      margin-top: 14px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
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
      <div class="section-heading">
        <h2>正文</h2>
        <div class="section-heading-action">{user_btn_html}</div>
      </div>
      {''.join(track_section_blocks)}
    </section>
    <section class="card">
      <h2>反馈</h2>
      {feedback_blocks}
      {feedback_disclaimer}
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

    const audioCache = new Map();
    let currentBtn = null;

    const ICONS = {{
      play: `<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`,
      pause: `<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>`
    }};

    function updateBtnState(btn, isPlaying) {{
      if (!btn) return;
      const type = btn.getAttribute("data-type");
      const labelText = type === "original" ? "播放原声" : "播放跟读";
      btn.querySelector(".label").textContent = isPlaying ? "暂停播放" : labelText;
      btn.querySelector(".icon").innerHTML = isPlaying ? ICONS.pause : ICONS.play;
      btn.classList.toggle("playing", isPlaying);
      if (!isPlaying && !audioCache.get(btn.getAttribute("data-url"))) {{
         btn.style.setProperty("--progress", "0%");
      }}
    }}

    function playAudio(btn, url) {{
      // 1. Stop identifying the previous button solely by global currentBtn if we want to pause it
      if (currentBtn && currentBtn !== btn) {{
        const prevUrl = currentBtn.getAttribute("data-url");
        const prevAudio = audioCache.get(prevUrl);
        if (prevAudio) {{
          prevAudio.pause();
          updateBtnState(currentBtn, false);
        }}
      }}

      // 2. Get or create audio for this URL
      let audio = audioCache.get(url);
      if (!audio) {{
        audio = new Audio(url);
        audio.ontimeupdate = () => {{
          if (audio.duration) {{
            const progress = (audio.currentTime / audio.duration) * 100;
            btn.style.setProperty("--progress", progress + "%");
          }}
        }};
        audio.onended = () => {{
          updateBtnState(btn, false);
          btn.style.setProperty("--progress", "0%");
          // We can either keep or clear from cache. 
          // Keeping it allows better memory management if we just reset its time.
          audio.currentTime = 0; 
        }};
        audio.onerror = () => {{
          alert("无法播放音频");
          updateBtnState(btn, false);
          audioCache.delete(url);
        }};
        audioCache.set(url, audio);
      }}

      // 3. Toggle state
      currentBtn = btn;
      if (audio.paused) {{
        audio.play();
        updateBtnState(btn, true);
      }} else {{
        audio.pause();
        updateBtnState(btn, false);
      }}
    }}
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
