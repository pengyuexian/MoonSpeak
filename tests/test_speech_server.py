import unittest
from pathlib import Path

from server.data_loader import (
    build_evaluation_paths,
    align_standard_text_with_azure,
    classify_word_color,
    parse_feedback_cn_markdown,
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
        self.assertEqual("red", lines[2]["tokens"][0]["color"])
        self.assertEqual("yellow", lines[2]["tokens"][2]["color"])
        self.assertEqual("red", lines[2]["tokens"][5]["color"])
