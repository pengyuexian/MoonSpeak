# Speech Review Server Design

## Goal

Add a lightweight HTTP server under `server/` that serves a modern speech review page from generated evaluation files.

The page must:

- load from routes like `/speech/2026-04-14/Read_PB58`
- read files from `evaluations/2026-04-14/`
- render the standard text with original line breaks preserved
- color words using Azure word-level assessment results
- show friendly Chinese detail popovers for each tappable word
- show the Chinese score summary and feedback below the text
- look polished on phone, iPad, and desktop

Also rename evaluation files in `evaluations/2026-04-14/` so spaces become underscores.

## Scope

In scope:

- rename files under `evaluations/2026-04-14/`
- add configurable server port in `.env`
- implement a Python HTTP server under `server/`
- implement one HTML page for `/speech/<date>/<name>`
- map Azure word-level results onto standard text words
- render Chinese feedback content from `.feedback.cn.md`

Out of scope:

- authentication
- editing data in the browser
- multi-page app routing
- database storage
- JS framework or frontend build pipeline

## Current State

The project is a Python codebase with generated evaluation artifacts under `evaluations/<date>/`.

For a sample item, the server will consume:

- `<name>.standard.txt`
- `<name>.azure.json`
- `<name>.feedback.md`
- `<name>.feedback.cn.md`

There is no existing web stack in the repo, so adding a minimal standard-library-based server is the lowest-risk option.

## Recommended Approach

Use a lightweight Python server with server-side HTML rendering and a small amount of inline JavaScript and CSS.

Why this approach:

- no framework dependency or build step
- easy to run locally in the existing conda environment
- easiest path to keep logic close to current file-based pipeline outputs
- enough flexibility for a polished responsive page

Rejected alternatives:

1. Flask or FastAPI plus templates
Adds structure, but increases dependencies and setup for a single-page file-backed tool.

2. Frontend app plus API
Too heavy for the current use case and creates unnecessary build and deployment complexity.

## File Naming Changes

Rename all files directly under `evaluations/2026-04-14/` so spaces become underscores.

Examples:

- `Read PB58.standard.txt` -> `Read_PB58.standard.txt`
- `Read PB58.azure.json` -> `Read_PB58.azure.json`
- `Read PB58.feedback.cn.md` -> `Read_PB58.feedback.cn.md`

The route key will use the renamed base name:

- `/speech/2026-04-14/Read_PB58`

The server will not try to support both old and new naming long-term. It will read the underscore form.

## Server Layout

Add a new `server/` directory.

Planned files:

- `server/http_server.py`
  Main HTTP server entry point and route handling.
- `server/render.py`
  HTML rendering and page assembly helpers.
- `server/data_loader.py`
  Read evaluation files, parse feedback, and align Azure words to standard text.
- `server/__init__.py`

If implementation stays small, `render.py` and `data_loader.py` may be merged, but the design assumes separation between HTTP concerns and data/render logic.

## Configuration

Add to `.env`:

- `SERVER_PORT=6001`

Server startup will read `.env` using the same project conventions already used elsewhere.

## Route Contract

### `GET /speech/<date>/<name>`

Example:

- `/speech/2026-04-14/Read_PB58`

Resolution rules:

1. Find `evaluations/<date>/`
2. Resolve the base name `<name>`
3. Load:
   - `<name>.standard.txt`
   - `<name>.azure.json`
   - `<name>.feedback.cn.md`
   - optionally `<name>.feedback.md` if needed for fallback or debugging
4. Render one HTML page

Error handling:

- missing directory -> styled 404 page
- missing required files -> styled 404 page with missing file list
- malformed JSON -> styled error page with concise failure reason

## Data Model

The page needs four data blocks:

1. Metadata
   - date
   - base name
   - matched unit and track from feedback

2. Scores
   - pronunciation
   - accuracy
   - fluency
   - completeness

3. Standard text lines
   - exact line order from `.standard.txt`
   - word tokens aligned with Azure word results

4. Chinese feedback
   - scores section from `.feedback.cn.md`
   - feedback section from `.feedback.cn.md`

## Word Alignment Strategy

Azure word lists and standard text do not always match one-to-one. The page must not mislabel the text.

Strategy:

1. Tokenize standard text into visible words while preserving punctuation and line breaks.
2. Tokenize Azure `words` in order.
3. Align sequentially using normalized word comparison:
   - lowercase
   - normalize curly quotes
   - tolerate possessive quote variants
4. Only attach Azure data when a word match is sufficiently confident.
5. If a token cannot be aligned confidently, render it as neutral text instead of forcing a score.

This favors correctness over full coverage.

## Color Mapping

Use child-friendly traffic-light semantics with soft, modern colors.

- Green
  stable or high score word
- Yellow
  somewhat unclear word
- Red
  omitted or clearly weak word
- Neutral
  no confident Azure alignment

Recommended mapping:

- `Omission` -> red
- `Insertion` -> not shown inline because the word is not in standard text
- `Mispronunciation`
  - score < 35 -> red
  - score >= 35 and < 70 -> yellow
  - score >= 70 -> green
- `None`
  - score >= 85 -> green
  - score >= 70 and < 85 -> yellow
  - score < 70 -> yellow

## Word Detail Popovers

Each tappable colored word opens a friendly Chinese detail card.

Popover content will avoid raw technical labels such as `Mispronunciation`.

Examples:

- `这个词这次漏读了。`
- `这个词读得不太清楚，还需要多练几次。`
- `这个词还可以更稳定一点。`
- `这次分数：58`

Interaction:

- desktop: click word opens floating popover near word
- phone/iPad: tap word opens anchored card or bottom sheet style overlay depending on available width

One open popover at a time.

## Page Structure

Single-page layout with four sections.

### 1. Hero Header

Shows:

- title based on file name
- date
- matched unit and track

Also includes four score cards:

- Pronunciation
- Accuracy
- Fluency
- Completeness

### 2. Standard Text Card

Main reading block:

- preserves original line breaks exactly
- renders each line as a separate block row
- each aligned word becomes an inline chip-like highlight

### 3. Chinese Feedback Card

Shows the Chinese score summary and Chinese feedback from `.feedback.cn.md` in a natural layout rather than raw markdown.

Do not show:

- source file section
- whisper text section
- Azure raw text section

### 4. Legend / Helper Area

Short Chinese legend:

- 绿色：比较稳定
- 黄色：还可以更清楚
- 红色：这次要重点练习

## Visual Direction

Design target:

- modern
- clean
- warm
- reading-first
- suitable for kids and parents together

Visual system:

- soft warm neutral background instead of pure white
- large rounded content cards
- subtle shadows and light gradients
- refined typography
- low-saturation semantic colors for word highlights

Typography:

- interface and score labels: modern sans-serif
- reading text: highly readable serif or humanist face if available, otherwise a strong system fallback stack

Motion:

- small fade-in on load
- subtle hover/tap transitions on words
- smooth popover open/close

## Responsive Behavior

### Phone

- single-column layout
- tighter horizontal padding
- score cards in one or two columns depending on width
- larger line height in text
- word details may open as bottom-sheet-style panel if needed

### iPad

- single reading column remains centered
- score cards can use two columns
- popovers can stay floating

### Desktop

- centered reading column with generous margins
- score cards can span four columns
- hover and click affordances enabled

## Markdown Parsing for Chinese Feedback

The Chinese feedback file is markdown-like but structurally simple.

The renderer should parse:

- matched unit
- matched track
- scores
- problem words
- feedback body

The page should render the score and feedback parts only as user-facing content below the standard text.

Matched unit and track may also be reused in the header.

## Error Pages

Use the same visual language as the main page.

Need three cases:

- evaluation not found
- required file missing
- evaluation data malformed

Each error page should be readable and calm, not a raw traceback.

## Testing Strategy

Add tests for:

- renaming evaluation files to underscores
- route path to file resolution
- parsing `.feedback.cn.md`
- aligning Azure words to standard text
- color classification
- rendering page HTML containing expected sections
- 404 handling

Manual verification:

- open sample route in browser
- verify line breaks match `.standard.txt`
- verify tap/click detail behavior
- verify phone and tablet layouts using browser responsive mode

## Risks and Mitigations

### Risk: Azure words do not align perfectly

Mitigation:

- use ordered conservative alignment
- leave uncertain tokens neutral instead of wrong

### Risk: Markdown feedback format drifts

Mitigation:

- parse only the known headings used by the current pipeline
- fail gracefully with empty sections instead of crashing

### Risk: UI becomes hard to read on mobile

Mitigation:

- constrain reading width
- keep text large and spacing generous
- test specifically for phone and iPad breakpoints

## Implementation Plan Boundary

The next phase should implement:

1. file renaming for `evaluations/2026-04-14`
2. server scaffolding and env config
3. data loading and parsing
4. alignment and color classification
5. polished HTML/CSS/JS page
6. tests

