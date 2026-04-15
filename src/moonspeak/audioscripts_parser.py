from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


HEADER_CUTOFF = 95.0
FOOTER_CUTOFF = 780.0
ROW_TOLERANCE = 2.5
SPACE_WIDTH = 5.0
TITLE_TRACK_RE = re.compile(r"^Track\s+(\d+)\.01$")
TRACK_RE = re.compile(r"^Track\s+(\d+\.\d+)$")
TRACKS_RE = re.compile(r"^Tracks\s+(\d+\.\d+)\s+and\s+(\d+\.\d+)$")


@dataclass
class UnitContent:
    number: int
    title: str
    tracks: dict[str, str] = field(default_factory=dict)


@dataclass
class _LineSegment:
    text: str
    x_min: float
    x_max: float
    y_min: float


@dataclass
class _PageLines:
    left: list[str]
    right: list[str]


def _run_pdftotext_bbox(pdf_path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-bbox-layout", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _segment_text(line_element: ET.Element) -> str:
    pieces: list[str] = []
    previous_x_max: float | None = None

    for word in line_element.findall(".//{*}word"):
        text = (word.text or "").strip()
        if not text:
            continue

        x_min = float(word.attrib["xMin"])
        x_max = float(word.attrib["xMax"])
        if previous_x_max is not None and x_min > previous_x_max + 0.8:
            pieces.append(" ")
        pieces.append(text)
        previous_x_max = x_max

    return "".join(pieces)


def _render_column(segments: list[_LineSegment], column_left: float) -> list[str]:
    if not segments:
        return []

    rows: list[list[_LineSegment]] = []
    for segment in sorted(segments, key=lambda item: (item.y_min, item.x_min)):
        if not rows or abs(segment.y_min - rows[-1][0].y_min) > ROW_TOLERANCE:
            rows.append([segment])
        else:
            rows[-1].append(segment)

    rendered: list[str] = []
    for row in rows:
        row.sort(key=lambda item: item.x_min)
        parts: list[str] = []
        cursor = column_left
        for index, segment in enumerate(row):
            gap = segment.x_min - cursor
            if gap > 0:
                spaces = int(round(gap / SPACE_WIDTH))
                if index == 0:
                    parts.append(" " * spaces)
                else:
                    parts.append(" " * max(1, spaces))
            parts.append(segment.text)
            cursor = segment.x_max
        rendered.append("".join(parts).rstrip())
    return rendered


def _extract_page_lines(root: ET.Element) -> list[_PageLines]:
    pages: list[_PageLines] = []
    for page in root.findall(".//{*}page"):
        width = float(page.attrib["width"])
        midpoint = width / 2
        left_segments: list[_LineSegment] = []
        right_segments: list[_LineSegment] = []

        for line in page.findall(".//{*}line"):
            text = _segment_text(line)
            if not text:
                continue

            y_min = float(line.attrib["yMin"])
            if y_min < HEADER_CUTOFF or y_min > FOOTER_CUTOFF:
                continue

            x_min = float(line.attrib["xMin"])
            x_max = float(line.attrib["xMax"])
            segment = _LineSegment(text=text, x_min=x_min, x_max=x_max, y_min=y_min)
            if x_min < midpoint:
                left_segments.append(segment)
            else:
                right_segments.append(segment)

        left_edge = min((segment.x_min for segment in left_segments), default=0.0)
        right_edge = min((segment.x_min for segment in right_segments), default=midpoint)
        pages.append(
            _PageLines(
                left=_render_column(left_segments, left_edge),
                right=_render_column(right_segments, right_edge),
            )
        )
    return pages


def _page_unit_title(page: _PageLines, page_index: int) -> tuple[int, str] | None:
    top_lines = [line.strip() for line in page.left[:8] if line.strip()]
    if not top_lines:
        return None

    first_line = top_lines[0]
    match = re.match(r"^(\d+)\s+(.+)$", first_line)
    if match:
        unit_number = int(match.group(1))
        singular = f"Track {unit_number}.01"
        combined = f"Tracks {unit_number}.01 and {unit_number}.02"
        if singular in top_lines or combined in top_lines:
            return unit_number, match.group(2).strip()
        return None

    if page_index == 0 and not first_line.startswith("Track "):
        return 0, first_line
    return None


def _detect_unit_titles(pages: list[_PageLines]) -> dict[int, str]:
    titles: dict[int, str] = {}
    for page_index, page in enumerate(pages):
        title_info = _page_unit_title(page, page_index)
        if title_info is None:
            continue
        unit_number, title = title_info
        titles.setdefault(unit_number, title)
    return titles


def _normalize_track_body(lines: list[str]) -> str:
    cleaned: list[str] = []
    blank_pending = False

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            if cleaned and not blank_pending:
                cleaned.append("")
            blank_pending = True
            continue

        blank_pending = False
        cleaned.append(line)

    def should_merge(previous: str, current: str) -> bool:
        previous_stripped = previous.strip()
        current_stripped = current.strip()
        if not previous_stripped or not current_stripped:
            return False
        if previous_stripped.startswith("[Frame") or current_stripped.startswith("[Frame"):
            return False
        if TRACK_RE.match(current_stripped) or TRACKS_RE.match(current_stripped):
            return False

        previous_indent = len(previous) - len(previous.lstrip(" "))
        current_indent = len(current) - len(current.lstrip(" "))
        if current_indent > previous_indent:
            return True

        first = current_stripped[0]
        return first.islower() or first in {",", ".", ";", ":", ")", "]", "&"}

    reflowed: list[str] = []
    for line in cleaned:
        if line and reflowed and reflowed[-1] and should_merge(reflowed[-1], line):
            reflowed[-1] = f"{reflowed[-1].rstrip()} {line.strip()}"
        else:
            reflowed.append(line)

    cleaned = reflowed

    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()

    return "\n".join(cleaned)


def parse_audioscripts_pdf(pdf_path: str | Path) -> dict[int, UnitContent]:
    pdf_path = Path(pdf_path)
    root = ET.fromstring(_run_pdftotext_bbox(pdf_path))
    pages = _extract_page_lines(root)
    unit_titles = _detect_unit_titles(pages)

    units: dict[int, UnitContent] = {}
    current_track: str | None = None
    current_unit_number: int | None = None
    track_lines: list[str] = []

    def flush_track() -> None:
        nonlocal current_track, track_lines
        if current_track is None or current_unit_number is None:
            return
        units[current_unit_number].tracks[current_track] = _normalize_track_body(track_lines)
        current_track = None
        track_lines = []

    for page_index, page in enumerate(pages):
        page_title = _page_unit_title(page, page_index)
        for line in [*page.left, *page.right]:
            stripped = line.strip()
            if not stripped:
                track_lines.append("")
                continue

            track_match = TRACK_RE.match(stripped)
            combined_match = TRACKS_RE.match(stripped)
            if track_match or combined_match:
                flush_track()
                track_number = track_match.group(1) if track_match else combined_match.group(1)
                unit_number = int(track_number.split(".", 1)[0])
                title = unit_titles.get(unit_number, f"Unit {unit_number}")
                units.setdefault(unit_number, UnitContent(number=unit_number, title=title))
                current_unit_number = unit_number
                current_track = stripped
                track_lines = []
                continue

            if current_track is None:
                continue

            if page_title is not None and stripped == f"{page_title[0]} {page_title[1]}":
                flush_track()
                continue

            if TITLE_TRACK_RE.match(current_track) and stripped == units[current_unit_number].title:
                continue

            track_lines.append(line.rstrip())

    flush_track()
    return dict(sorted(units.items()))


def _safe_unit_filename(unit: UnitContent) -> str:
    title = re.sub(r"[^\w\s-]", "", unit.title, flags=re.UNICODE)
    title = re.sub(r"[-\s]+", "_", title).strip("_")
    return f"Unit_{unit.number:02d}-{title}.md"


def _format_markdown_body(body: str) -> list[str]:
    formatted: list[str] = []
    for line in body.splitlines():
        if not line.strip():
            formatted.append("")
            continue

        normalized = re.sub(r"^([^:\n]+:)\s+", r"\1 ", line)
        formatted.append(f"{normalized}  ")
    return formatted


def write_unit_markdown_files(units: dict[int, UnitContent], output_dir: str | Path) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []

    for unit_number in sorted(units):
        unit = units[unit_number]
        lines = [f"# Unit {unit.number}: {unit.title}", ""]
        for track_name, body in unit.tracks.items():
            lines.extend(
                [
                    f"## {track_name}",
                    "",
                ]
            )
            lines.extend(_format_markdown_body(body))
            lines.append("")

        content = "\n".join(lines).rstrip() + "\n"
        path = output_dir / _safe_unit_filename(unit)
        path.write_text(content, encoding="utf-8")
        written_paths.append(path)

    return written_paths
