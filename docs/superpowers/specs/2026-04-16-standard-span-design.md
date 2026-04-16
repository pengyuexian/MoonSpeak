# Standard Span Selection Design

## Goal
Fix standard-text generation so it keeps lines the child actually read, supports multi-track matches, avoids adding unread opening chant/narration lines, strips role names and frame markers, and keeps scoring free of synthetic track separators.

## Design
The pipeline should stop treating the matched track as a single monolithic span. Instead it should select lines using reading evidence across all matched tracks, then build a display standard and a scoring standard from the same selected lines.

For each matched track, canonical text is split into lines. Evidence is computed per line from Whisper text and recognized text, ignoring frame tags and role-name prefixes. Only lines with strong evidence, or weak lines bridged between strong lines, are retained. This allows multi-track input and prevents unread chant/narration lines from being dragged in just because the track matched overall.

If more than one track is selected, the saved `standard.txt` uses `## Track X.XX` separators for readability. Before Azure scoring, those synthetic separators are stripped so scoring only sees spoken content.

## Constraints
- Keep canonical wording and line breaks.
- Remove `[Frame X]` lines unless actually spoken.
- Remove role-name prefixes by default.
- Allow multi-track output in `standard.txt`.
- Do not send `## Track` separator lines to Azure scoring.
