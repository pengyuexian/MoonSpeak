import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from moonspeak.pipeline import NoReliableMatchError
from moonspeak.run_assessment import (
    build_report_url,
    build_run_result,
    main,
    normalize_staged_filename,
    stage_audio_file,
)


class RunAssessmentTests(unittest.TestCase):
    def test_normalize_staged_filename_replaces_spaces_with_underscores(self) -> None:
        self.assertEqual("Read_PB58.m4a", normalize_staged_filename("Read PB58.m4a"))

    def test_stage_audio_file_places_audio_in_today_directory_and_adds_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "Read PB58.m4a"
            source.write_bytes(b"audio")
            evaluations_root = Path(tmp_dir) / "evaluations"

            first = stage_audio_file(source, evaluations_root, "2026-04-15")
            second = stage_audio_file(source, evaluations_root, "2026-04-15")
            self.assertEqual("Read_PB58.m4a", first.name)
            self.assertEqual("Read_PB58_1.m4a", second.name)
            self.assertEqual("2026-04-15", first.parent.name)
            self.assertEqual(b"audio", first.read_bytes())
            self.assertEqual(b"audio", second.read_bytes())

    def test_build_report_url_appends_speech_route(self) -> None:
        self.assertEqual(
            "http://127.0.0.1:6001/speech/2026-04-15/Read_PB58",
            build_report_url("http://127.0.0.1:6001", "2026-04-15", "Read_PB58"),
        )

    def test_build_run_result_uses_feedback_artifact(self) -> None:
        result = build_run_result(
            server_base="http://127.0.0.1:6001",
            date="2026-04-15",
            staged_audio_path=Path("/repo/evaluations/2026-04-15/Read_PB58.m4a"),
            pipeline_result={"files": {"results": "Read_PB58.feedback.md"}},
        )

        self.assertEqual("/repo/evaluations/2026-04-15/Read_PB58.feedback.md", result["report_path"])
        self.assertEqual(
            "http://127.0.0.1:6001/speech/2026-04-15/Read_PB58",
            result["report_url"],
        )
        self.assertTrue(result["success"])

    @patch("moonspeak.run_assessment.assess_audio")
    def test_main_prints_success_json(self, assess_audio_mock) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "Read PB58.m4a"
            source.write_bytes(b"audio")
            staged_dir = Path(tmp_dir) / "evaluations" / "2026-04-15"

            def fake_assess_audio(audio_path: str, output_dir: str, scripts_dir: str | None = None) -> dict:
                report_path = Path(output_dir) / "Read_PB58.feedback.md"
                report_path.write_text("# report\n", encoding="utf-8")
                return {"files": {"results": report_path.name}}

            assess_audio_mock.side_effect = fake_assess_audio
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [str(source)],
                    evaluations_root=Path(tmp_dir) / "evaluations",
                    date="2026-04-15",
                    server_base="http://127.0.0.1:6001",
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(0, exit_code)
        self.assertTrue(payload["success"])
        self.assertEqual(
            "http://127.0.0.1:6001/speech/2026-04-15/Read_PB58",
            payload["report_url"],
        )
        self.assertEqual(str(staged_dir / "Read_PB58.feedback.md"), payload["report_path"])
        self.assertNotIn("error_type", payload)

    @patch("moonspeak.run_assessment.assess_audio")
    def test_main_keeps_pipeline_logs_out_of_stdout_json(self, assess_audio_mock) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "Read PB58.m4a"
            source.write_bytes(b"audio")

            def fake_assess_audio(audio_path: str, output_dir: str, scripts_dir: str | None = None) -> dict:
                print("pipeline log line")
                report_path = Path(output_dir) / "Read_PB58.feedback.md"
                report_path.write_text("# report\n", encoding="utf-8")
                return {"files": {"results": report_path.name}}

            assess_audio_mock.side_effect = fake_assess_audio
            stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                exit_code = main(
                    [str(source)],
                    evaluations_root=Path(tmp_dir) / "evaluations",
                    date="2026-04-15",
                    server_base="http://127.0.0.1:6001",
                )

        payload = json.loads(stdout_buffer.getvalue())
        self.assertEqual(0, exit_code)
        self.assertTrue(payload["success"])
        self.assertIn("pipeline log line", stderr_buffer.getvalue())

    @patch("moonspeak.run_assessment.assess_audio")
    def test_main_prints_failure_json_when_pipeline_raises(self, assess_audio_mock) -> None:
        assess_audio_mock.side_effect = RuntimeError("boom")
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "Read PB58.m4a"
            source.write_bytes(b"audio")
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [str(source)],
                    evaluations_root=Path(tmp_dir) / "evaluations",
                    date="2026-04-15",
                    server_base="http://127.0.0.1:6001",
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(payload["success"])
        self.assertEqual("runtime_failure", payload["error_type"])
        self.assertIn("boom", payload["error"])

    @patch("moonspeak.run_assessment.assess_audio")
    def test_main_prints_no_reliable_match_failure_type(self, assess_audio_mock) -> None:
        assess_audio_mock.side_effect = NoReliableMatchError("No reliable textbook match found")
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "random.m4a"
            source.write_bytes(b"audio")
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [str(source)],
                    evaluations_root=Path(tmp_dir) / "evaluations",
                    date="2026-04-15",
                    server_base="http://127.0.0.1:6001",
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(payload["success"])
        self.assertEqual("no_reliable_match", payload["error_type"])
        self.assertIn("No reliable textbook match found", payload["error"])


class RunAssessmentScriptTests(unittest.TestCase):
    def test_shell_wrapper_uses_moonspeak_env_and_runner_module(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_assessment.sh"

        self.assertTrue(script_path.exists())
        content = script_path.read_text(encoding="utf-8")
        self.assertIn("conda run --no-capture-output -n moonspeak", content)
        self.assertIn("python -m moonspeak.run_assessment", content)

        mode = script_path.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR)

    def test_shell_wrapper_extracts_url_from_json_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fake_conda = Path(tmp_dir) / "conda"
            fake_conda.write_text(
                "#!/usr/bin/env bash\n"
                "shift\n"
                "shift\n"
                "shift\n"
                "shift\n"
                "shift\n"
                "shift\n"
                "shift\n"
                "printf '%s\\n' '{\"success\": true, \"report_url\": \"http://127.0.0.1:6001/speech/2026-04-15/Read_PB60\"}'\n",
                encoding="utf-8",
            )
            fake_conda.chmod(0o755)

            env = {**os.environ, "PATH": f"{tmp_dir}:{os.environ['PATH']}"}
            result = subprocess.run(
                ["bash", "scripts/run_assessment.sh", "/tmp/fake.m4a"],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )

        self.assertEqual(0, result.returncode)
        self.assertEqual("http://127.0.0.1:6001/speech/2026-04-15/Read_PB60", result.stdout.strip())

    def test_shell_wrapper_prints_typed_failure_message_from_json_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fake_conda = Path(tmp_dir) / "conda"
            fake_conda.write_text(
                "#!/usr/bin/env bash\n"
                "shift\n"
                "shift\n"
                "shift\n"
                "shift\n"
                "shift\n"
                "shift\n"
                "shift\n"
                "printf '%s\\n' '{\"success\": false, \"error_type\": \"no_reliable_match\", \"error\": \"No reliable textbook match found\"}'\n",
                encoding="utf-8",
            )
            fake_conda.chmod(0o755)

            env = {**os.environ, "PATH": f"{tmp_dir}:{os.environ['PATH']}"}
            result = subprocess.run(
                ["bash", "scripts/run_assessment.sh", "/tmp/fake.m4a"],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("no_reliable_match: No reliable textbook match found", result.stdout.strip())


class RunAssessmentSkillTests(unittest.TestCase):
    def test_repo_skill_documents_complete_assessment_flow(self) -> None:
        skill_path = Path(__file__).resolve().parents[1] / "skills" / "complete-audio-assessment" / "SKILL.md"

        self.assertTrue(skill_path.exists())
        content = skill_path.read_text(encoding="utf-8")
        self.assertIn("SERVER", content)
        self.assertIn("server/start.sh", content)
        self.assertIn("scripts/run_assessment.sh", content)


class WatchIMsgScriptTests(unittest.TestCase):
    def test_watch_script_uses_env_config_without_private_defaults(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "watch-imsg.sh"

        self.assertTrue(script_path.exists())
        content = script_path.read_text(encoding="utf-8")
        self.assertIn('IMSG_CHAT_ID:-', content)
        self.assertIn('IMSG_SENDER:-', content)
        self.assertIn('TELEGRAM_TARGET:-', content)
        self.assertIn("IMSG_SUCCESS_TEXT", content)
        self.assertIn("TELEGRAM_FAILURE_TEXT", content)
        self.assertNotIn("moonstringpeng@icloud.com", content)
        self.assertNotIn("5581280352", content)
        self.assertNotIn("女儿", content)


if __name__ == "__main__":
    unittest.main()
