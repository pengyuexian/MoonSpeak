from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from contextlib import redirect_stdout

from dotenv import load_dotenv

from moonspeak.pipeline import NoReliableMatchError, REPO_ROOT, assess_audio

load_dotenv()

EVALUATIONS_ROOT = REPO_ROOT / "evaluations"


def normalize_staged_filename(filename: str) -> str:
    return filename.replace(" ", "_")


def stage_audio_file(source_path: Path, evaluations_root: Path, date: str) -> Path:
    day_dir = evaluations_root / date
    day_dir.mkdir(parents=True, exist_ok=True)

    normalized_name = normalize_staged_filename(source_path.name)
    stem = Path(normalized_name).stem
    suffix = Path(normalized_name).suffix
    candidate = day_dir / normalized_name
    index = 1
    while candidate.exists():
        candidate = day_dir / f"{stem}_{index}{suffix}"
        index += 1

    shutil.copy2(source_path, candidate)
    return candidate


def build_report_url(server_base: str, date: str, name: str) -> str:
    return f"{server_base.rstrip('/')}/speech/{date}/{name}"


def build_run_result(
    server_base: str,
    date: str,
    staged_audio_path: Path,
    pipeline_result: dict,
) -> dict[str, object]:
    report_name = str(pipeline_result.get("files", {}).get("results", ""))
    report_path = staged_audio_path.with_name(report_name)
    base_name = staged_audio_path.stem
    return {
        "success": True,
        "report_path": str(report_path),
        "report_url": build_report_url(server_base, date, base_name),
    }


def _build_failure_result(error: str, *, error_type: str) -> dict[str, object]:
    return {"success": False, "error_type": error_type, "error": error}


def main(
    argv: list[str] | None = None,
    *,
    evaluations_root: Path = EVALUATIONS_ROOT,
    date: str | None = None,
    server_base: str | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Stage one audio file into today's evaluations directory and run assessment.")
    parser.add_argument("audio_file", help="Path to the input audio file")
    args = parser.parse_args(argv)

    source_path = Path(args.audio_file).expanduser().resolve()
    if not source_path.exists() or not source_path.is_file():
        print(
            json.dumps(
                _build_failure_result(f"Audio file not found: {source_path}", error_type="runtime_failure"),
                ensure_ascii=False,
            )
        )
        return 1

    run_date = date or datetime.now().strftime("%Y-%m-%d")
    server = (server_base or os.environ.get("SERVER", "")).strip()
    if not server:
        print(
            json.dumps(
                _build_failure_result("SERVER is not configured in .env", error_type="runtime_failure"),
                ensure_ascii=False,
            )
        )
        return 1

    try:
        staged_audio_path = stage_audio_file(source_path, evaluations_root, run_date)
        pipeline_stdout = io.StringIO()
        with redirect_stdout(pipeline_stdout):
            pipeline_result = assess_audio(str(staged_audio_path), str(staged_audio_path.parent))
        logs = pipeline_stdout.getvalue()
        if logs.strip():
            print(logs, file=sys.stderr, end="" if logs.endswith("\n") else "\n")
        report_result = build_run_result(server, run_date, staged_audio_path, pipeline_result)
        report_path = Path(str(report_result["report_path"]))
        if not report_path.exists():
            raise FileNotFoundError(f"Report file not found: {report_path}")
    except NoReliableMatchError as exc:
        print(json.dumps(_build_failure_result(str(exc), error_type="no_reliable_match"), ensure_ascii=False))
        return 1
    except Exception as exc:
        print(json.dumps(_build_failure_result(str(exc), error_type="runtime_failure"), ensure_ascii=False))
        return 1

    print(json.dumps(report_result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
