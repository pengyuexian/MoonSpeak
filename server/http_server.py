from __future__ import annotations

import os
import mimetypes
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


class SpeechReviewHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path
        if path.startswith("/audio/"):
            self._handle_audio(path)
            return

        resolved = parse_speech_path(path)
        if resolved is None:
            self._send_html(
                404,
                render_not_found_page(
                    "speech",
                    ["有效路径形如 /speech/2026-04-14/Read_PB58"],
                ),
            )
            return

        date, name = resolved
        try:
            page_data = load_speech_review_page_data(EVALUATIONS_ROOT, date, name)
        except FileNotFoundError as exc:
            self._send_html(404, render_not_found_page(name, [str(exc)]))
            return
        except Exception as exc:  # pragma: no cover
            self._send_html(500, render_not_found_page(name, [str(exc)]))
            return

        self._send_html(200, render_speech_review_page(page_data))

    def _handle_audio(self, path: str) -> None:
        parts = [p for p in path.split("/") if p]
        # /audio/user/<date>/<filename>
        # /audio/track/<book_level>/<filename>
        file_path = None
        if len(parts) >= 4 and parts[1] == "user":
            date, filename = parts[2], parts[3]
            file_path = EVALUATIONS_ROOT / date / filename
        elif len(parts) >= 4 and parts[1] == "track":
            book_level, track_filename = parts[2], parts[3]
            file_path = REPO_ROOT / "books" / "Power_Up" / book_level / "Tracks" / track_filename
        
        if file_path and file_path.exists():
            mime_type, _ = mimetypes.guess_type(str(file_path))
            if not mime_type:
                mime_type = "application/octet-stream"
            
            try:
                content = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except Exception as e:
                self.send_error(500, f"Error reading audio: {e}")
        else:
            self.send_error(404, "Audio file not found")

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
