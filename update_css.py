import re

with open("server/render.py", "r") as f:
    content = f.read()

# Replacement 1: .score-grid
old_grid = """    .score-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin-top: 20px;
    }"""
new_grid = """    .score-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      margin-top: 16px;
    }"""
content = content.replace(old_grid, new_grid)

# Replacement 2: .score-card
old_card = """    .score-card {
      position: relative;
      overflow: hidden;
      min-height: 140px;
      border-radius: 24px;
      padding: 18px;
      background: linear-gradient(160deg, rgba(255,255,255,0.96), rgba(255,255,255,0.74));
      border: 1px solid rgba(255,255,255,0.9);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.95);
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }"""
new_card = """    .score-card {
      position: relative;
      overflow: hidden;
      min-height: 80px;
      border-radius: 16px;
      padding: 16px;
      background: #ffffff;
      border: 1px solid rgba(0, 0, 0, 0.05);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }"""
content = content.replace(old_card, new_card)

# Replacement 3: .score-card::after
old_after = """    .score-card::after {
      content: "";
      position: absolute;
      width: 96px;
      height: 96px;
      border-radius: 999px;
      right: -18px;
      top: -18px;
      opacity: 0.7;
    }"""
new_after = """    .score-card::after {
      content: "";
      position: absolute;
      width: 72px;
      height: 72px;
      border-radius: 999px;
      right: -20px;
      top: -20px;
      opacity: 0.7;
    }"""
content = content.replace(old_after, new_after)

# Replacement 4: .score-card-label
old_label = """    .score-card-label {
      position: relative;
      z-index: 1;
      font-size: 14px;
      letter-spacing: 0.08em;
      color: var(--muted);
    }"""
new_label = """    .score-card-label {
      position: relative;
      z-index: 1;
      font-size: 13px;
      font-weight: 500;
      letter-spacing: 0.04em;
      color: var(--muted);
      margin-bottom: 8px;
    }"""
content = content.replace(old_label, new_label)

# Replacement 5: .score-card-value
old_value = """    .score-card-value {
      position: relative;
      z-index: 1;
      font-size: clamp(28px, 4.5vw, 42px);
      line-height: 1;
      font-weight: 700;
      color: #172033;
    }"""
new_value = """    .score-card-value {
      position: relative;
      z-index: 1;
      font-size: clamp(20px, 3.5vw, 28px);
      line-height: 1;
      font-weight: 700;
      color: #172033;
    }"""
content = content.replace(old_value, new_value)

with open("server/render.py", "w") as f:
    f.write(content)

print("done")
