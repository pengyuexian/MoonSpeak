import unittest
from pathlib import Path

from server.data_loader import (
    build_evaluation_paths,
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
