import json
import tempfile
import unittest
from pathlib import Path

from server.data_loader import (
    build_evaluation_paths,
    align_standard_text_with_azure,
    classify_word_color,
    parse_feedback_cn_markdown,
    load_speech_review_page_data,
)


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


class SpeechServerLoaderTests(unittest.TestCase):
    def test_load_speech_review_page_data_reads_all_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir) / "evaluations" / "2026-04-14"
            base.mkdir(parents=True)
            (base / "Read_PB58.standard.txt").write_text(
                "The Friendly Farm,\nGracie! What are you eating?\n",
                encoding="utf-8",
            )
            (base / "Read_PB58.azure.json").write_text(
                json.dumps(
                    {
                        "reference_text": "The Friendly Farm,\nGracie! What are you eating?\n",
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
        self.assertEqual(2, len(data["standard_lines"]))
        self.assertEqual(
            "这个词整体比较稳定。当前分数：94",
            data["standard_lines"][0]["tokens"][0]["detail_text_cn"],
        )
