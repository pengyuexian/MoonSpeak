import json
import stat
import tempfile
import unittest
from pathlib import Path

from server.data_loader import (
    align_standard_text_with_azure,
    build_evaluation_paths,
    build_word_detail_cn,
    classify_word_color,
    load_speech_review_page_data,
    parse_feedback_cn_markdown,
)
from server.http_server import parse_speech_path
from server.render import render_not_found_page, render_speech_review_page


class SpeechServerDataTests(unittest.TestCase):
    def test_build_evaluation_paths_uses_underscore_names(self) -> None:
        base = Path("/repo/evaluations")
        paths = build_evaluation_paths(base, "2026-04-14", "Read_PB58")
        self.assertEqual(
            base / "2026-04-14" / "Read_PB58.standard.txt",
            paths["standard"],
        )
        self.assertEqual(
            base / "2026-04-14" / "Read_PB58.azure.json",
            paths["azure"],
        )
        self.assertEqual(
            base / "2026-04-14" / "Read_PB58.feedback.cn.md",
            paths["feedback_cn"],
        )
        self.assertEqual(
            base / "2026-04-14" / "Read_PB58.feedback.md",
            paths["feedback_en"],
        )

    def test_parse_feedback_cn_markdown_extracts_summary_sections(self) -> None:
        markdown = (
            "# 评测报告：Read_PB58\n\n"
            "## 匹配 Unit\n5\n\n"
            "## 匹配 Track\n5.05\n\n"
            "## 评分\n"
            "发音：71.6/100\n"
            "准确度：70.0/100\n"
            "流利度：77.0/100\n"
            "完整度：71.0/100\n\n"
            "## 重点问题词\n"
            "- Is：这个英文单词漏读了（分数：0）\n\n"
            "## 反馈\n"
            "你这次一直坚持读完了。\n"
        )
        parsed = parse_feedback_cn_markdown(markdown)
        self.assertEqual("5", parsed["matched_unit"])
        self.assertEqual(["5.05"], parsed["matched_tracks"])
        self.assertEqual(
            [
                "发音：71.6/100",
                "准确度：70.0/100",
                "流利度：77.0/100",
                "完整度：71.0/100",
            ],
            parsed["score_lines"],
        )
        self.assertEqual(["Is：这个英文单词漏读了（分数：0）"], parsed["problem_word_lines"])
        self.assertEqual(["你这次一直坚持读完了。"], parsed["feedback_lines"])


class SpeechServerAlignmentTests(unittest.TestCase):
    def test_classify_word_color_maps_scores_and_error_types(self) -> None:
        self.assertEqual("red", classify_word_color({"error_type": "Omission", "score": 0}))
        self.assertEqual("red", classify_word_color({"error_type": "Mispronunciation", "score": 20}))
        self.assertEqual("yellow", classify_word_color({"error_type": "Mispronunciation", "score": 58}))
        self.assertEqual("green", classify_word_color({"error_type": "None", "score": 92}))

    def test_align_standard_text_with_azure_preserves_lines_and_attaches_words(self) -> None:
        standard_text = (
            "The Friendly Farm, the Friendly Farm,\n"
            "Gracie! What are you eating?\n"
            "Is that Jim's picture of the wildlife park?"
        )
        azure_words = [
            {"word": "The", "error_type": "None", "score": 94.0},
            {"word": "Friendly", "error_type": "None", "score": 91.0},
            {"word": "Farm", "error_type": "None", "score": 70.0},
            {"word": "Gracie", "error_type": "None", "score": 94.0},
            {"word": "Is", "error_type": "Omission", "score": 0},
            {"word": "Jim's", "error_type": "Mispronunciation", "score": 46.0},
            {"word": "wildlife", "error_type": "Mispronunciation", "score": 13.0},
        ]
        lines = align_standard_text_with_azure(standard_text, azure_words)
        self.assertEqual(3, len(lines))
        self.assertEqual("The Friendly Farm, the Friendly Farm,", lines[0]["text"])
        self.assertEqual("word", lines[0]["tokens"][0]["kind"])
        self.assertEqual("space", lines[0]["tokens"][1]["kind"])
        self.assertEqual("punct", lines[0]["tokens"][5]["kind"])
        self.assertEqual("space", lines[0]["tokens"][6]["kind"])
        self.assertEqual("punct", lines[1]["tokens"][1]["kind"])
        self.assertEqual("neutral", lines[1]["tokens"][3]["color"])
        self.assertEqual("", lines[1]["tokens"][3]["detail"])
        self.assertEqual("red", lines[2]["tokens"][0]["color"])
        self.assertEqual("yellow", lines[2]["tokens"][4]["color"])
        self.assertEqual("red", lines[2]["tokens"][12]["color"])

    def test_align_standard_text_with_curly_apostrophe_keeps_word_together(self) -> None:
        standard_text = "Jim’s picture"
        azure_words = [
            {"word": "Jim's", "error_type": "Mispronunciation", "score": 46.0},
            {"word": "picture", "error_type": "None", "score": 91.0},
        ]

        lines = align_standard_text_with_azure(standard_text, azure_words)

        self.assertEqual(1, len(lines))
        self.assertEqual("Jim’s picture", lines[0]["text"])
        self.assertEqual(3, len(lines[0]["tokens"]))
        self.assertEqual("Jim’s", lines[0]["tokens"][0]["text"])
        self.assertEqual("word", lines[0]["tokens"][0]["kind"])
        self.assertEqual("picture", lines[0]["tokens"][2]["text"])
        self.assertEqual("word", lines[0]["tokens"][2]["kind"])
        self.assertEqual("yellow", lines[0]["tokens"][0]["color"])
        self.assertEqual("green", lines[0]["tokens"][2]["color"])

    def test_build_word_detail_cn_formats_omission_and_mispronunciation_branches(self) -> None:
        self.assertEqual(
            "这个词这次漏读了。当前分数：0",
            build_word_detail_cn({"error_type": "Omission", "score": 0}),
        )
        self.assertEqual(
            "这个词读得不太清楚，还需要重点练习。当前分数：20",
            build_word_detail_cn({"error_type": "Mispronunciation", "score": 20}),
        )
        self.assertEqual(
            "这个词还不够稳定，可以再放慢一点读。当前分数：58",
            build_word_detail_cn({"error_type": "Mispronunciation", "score": 58}),
        )


class SpeechServerLoaderTests(unittest.TestCase):
    def test_load_speech_review_page_data_reads_all_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir) / "evaluations" / "2026-04-14"
            base.mkdir(parents=True)
            (base / "Read_PB58.standard.txt").write_text(
                "The Friendly Farm,\nGracie! What are you eating?\nGhost\n",
                encoding="utf-8",
            )
            (base / "Read_PB58.azure.json").write_text(
                json.dumps(
                    {
                        "reference_text": "The Friendly Farm,\nGracie! What are you eating?\nGhost\n",
                        "recognized_text": "The Friendly farm. Gracie. What are you eating?",
                        "scores": {
                            "pronunciation": 71.6,
                            "accuracy": 70.0,
                            "fluency": 77.0,
                            "completeness": 71.0,
                        },
                        "words": [
                            {"word": "The", "error_type": "None", "score": 94.0},
                            {"word": "Friendly", "error_type": "None", "score": 91.0},
                            {"word": "Farm", "error_type": "None", "score": 70.0},
                            {"word": "Gracie", "error_type": "None", "score": 94.0},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (base / "Read_PB58.feedback.cn.md").write_text(
                "# 评测报告：Read_PB58\n\n"
                "## 匹配 Unit\n5\n\n"
                "## 匹配 Track\n5.05\n\n"
                "## 评分\n发音：71.6/100\n\n"
                "## 反馈\n你这次一直坚持读完了。\n",
                encoding="utf-8",
            )
            (base / "Read_PB58.feedback.md").write_text("# noop\n", encoding="utf-8")

            data = load_speech_review_page_data(Path(tmp_dir) / "evaluations", "2026-04-14", "Read_PB58")

        self.assertEqual("Read_PB58", data["name"])
        self.assertEqual("2026-04-14", data["date"])
        self.assertEqual("5", data["matched_unit"])
        self.assertEqual(["5.05"], data["matched_tracks"])
        self.assertEqual(["发音：71.6/100"], data["score_lines_cn"])
        self.assertEqual(["你这次一直坚持读完了。"], data["feedback_lines_cn"])
        self.assertEqual(3, len(data["standard_lines"]))
        self.assertEqual(
            "这个词整体比较稳定。当前分数：94",
            data["standard_lines"][0]["tokens"][0]["detail_text_cn"],
        )
        self.assertEqual(
            "",
            data["standard_lines"][2]["tokens"][0]["detail_text_cn"],
        )


class SpeechServerRenderTests(unittest.TestCase):
    def test_render_speech_review_page_contains_sections(self) -> None:
        html = render_speech_review_page(
            {
                "name": "Read_PB58",
                "date": "2026-04-14",
                "matched_unit": "5",
                "matched_tracks": ["5.05"],
                "scores": {
                    "pronunciation": 71.6,
                    "accuracy": 70.0,
                    "fluency": 77.0,
                    "completeness": 71.0,
                },
                "score_lines_cn": ["发音：71.6/100"],
                "problem_word_lines_cn": ["Is：这个英文单词漏读了（分数：0）"],
                "feedback_lines_cn": ["你这次一直坚持读完了。"],
                "standard_lines": [
                    {
                        "text": "Is that Jim's picture of the wildlife park?",
                        "tokens": [
                            {
                                "text": "Is",
                                "kind": "word",
                                "color": "red",
                                "detail_text_cn": "这个词这次漏读了。当前分数：0",
                            },
                            {"text": " ", "kind": "space"},
                            {
                                "text": "that",
                                "kind": "word",
                                "color": "neutral",
                                "detail_text_cn": "",
                            },
                        ],
                    }
                ],
            }
        )
        self.assertIn("speech-page", html)
        self.assertIn("Read_PB58", html)
        self.assertIn("word-chip red", html)
        self.assertIn("你这次一直坚持读完了。", html)
        self.assertIn("viewport", html)
        self.assertIn("发音", html)
        self.assertIn("准确度", html)
        self.assertIn("流利度", html)
        self.assertIn("完整度", html)
        self.assertIn("score-card score-card-pronunciation", html)
        self.assertIn("score-card score-card-accuracy", html)
        self.assertIn("score-card score-card-fluency", html)
        self.assertIn("score-card score-card-completeness", html)
        self.assertIn("score-card-label", html)
        self.assertIn("score-card-value", html)
        self.assertIn("<h2>反馈</h2>", html)
        self.assertNotIn("<h2>中文反馈</h2>", html)
        self.assertNotIn("<p>发音：71.6/100</p>", html)
        self.assertNotIn("绿色：比较稳定", html)
        self.assertNotIn("黄色：还可以更清楚", html)
        self.assertNotIn("红色：这次要重点练习", html)

    def test_render_not_found_page_contains_message(self) -> None:
        html = render_not_found_page("Read_PB58", ["Read_PB58.standard.txt"])
        self.assertIn("Read_PB58", html)
        self.assertIn("Read_PB58.standard.txt", html)
        self.assertIn("未找到", html)


class SpeechServerRouteTests(unittest.TestCase):
    def test_parse_speech_path_extracts_date_and_name(self) -> None:
        self.assertEqual(
            ("2026-04-14", "Read_PB58"),
            parse_speech_path("/speech/2026-04-14/Read_PB58"),
        )

    def test_parse_speech_path_rejects_invalid_routes(self) -> None:
        self.assertIsNone(parse_speech_path("/"))
        self.assertIsNone(parse_speech_path("/speech/2026-04-14"))


class SpeechServerStartScriptTests(unittest.TestCase):
    def test_start_script_uses_moonspeak_conda_environment(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "server" / "start.sh"

        self.assertTrue(script_path.exists())

        content = script_path.read_text(encoding="utf-8")
        self.assertIn("conda run --no-capture-output -n moonspeak", content)
        self.assertIn("PYTHONPATH=.:src", content)
        self.assertIn("python -m server.http_server", content)

        mode = script_path.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR)
