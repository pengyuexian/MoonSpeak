import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from moonspeak.pipeline import (
    _align_assessment_words,
    _build_scores_from_aligned_words,
    _estimate_minimum_word_count,
    _expand_reference_span,
    _feedback_covers_problem_words,
    _run_with_timeout,
    _standard_is_substantially_shorter_than_transcript,
    azure_score,
    standard_matches_canonical_lines,
    build_standard_content_prompt,
    build_feedback_fallback_en,
    build_feedback_fallback_cn,
    build_feedback_prompt_cn,
    build_translation_prompt,
    _feedback_has_contradictions,
    _feedback_mentions_translated_alias,
    assess_audio,
    generate_standard_content,
    llm_generate_feedback_en,
    llm_generate_feedback_cn,
    narrow_reference_text,
    prepare_reference_text_for_llm,
    should_retry_standard_generation,
    clean_reference_text,
    build_output_paths,
    choose_report_tracks,
    extract_problem_words,
    find_best_match,
    load_audioscripts,
    normalize_book_path,
    render_problem_words_section_cn,
    render_problem_words_section_en,
    render_feedback_report_cn,
    render_feedback_report_en,
)


def _slow_identity(value: str) -> str:
    time.sleep(0.2)
    return value


class PipelineHelperTests(unittest.TestCase):
    def test_normalize_book_path_resolves_current_book(self) -> None:
        base = Path("/repo/books")
        self.assertEqual(
            base / "Power_Up" / "2",
            normalize_book_path("Power_Up/2", books_root=base),
        )

    def test_load_audioscripts_parses_unit_and_track_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            scripts_dir = Path(tmp_dir)
            (scripts_dir / "Unit_03-Party_time.md").write_text(
                "# Unit 3: Party time!\n\n"
                "## Track 3.01\n\n"
                "Jim: Hello there.  \n"
                "Jenny: Hi!  \n\n"
                "## Track 3.02\n\n"
                "A song line  \n",
                encoding="utf-8",
            )

            tracks = load_audioscripts(str(scripts_dir))

        self.assertIn("3.01", tracks)
        self.assertEqual(3, tracks["3.01"]["unit"])
        self.assertEqual("Track 3.01", tracks["3.01"]["track_header"])
        self.assertEqual("Jim: Hello there.\nJenny: Hi!", tracks["3.01"]["text"])

    def test_clean_reference_text_collapses_markdown_hard_breaks(self) -> None:
        raw = "Harry: Hello there.  \nJenny: Hi.\n\n[Frame 1]\n"
        self.assertEqual(
            "Harry: Hello there.\nJenny: Hi.\n\n[Frame 1]",
            clean_reference_text(raw),
        )

    def test_build_output_paths_uses_new_suffixes(self) -> None:
        paths = build_output_paths("/tmp", "Read PB58")
        self.assertEqual("/tmp/Read PB58.standard.txt", paths["reference"])
        self.assertEqual("/tmp/Read PB58.azure.json", paths["azure"])
        self.assertEqual("/tmp/Read PB58.feedback.md", paths["results"])
        self.assertNotIn("results_cn", paths)

    def test_render_feedback_reports_hide_source_and_whisper(self) -> None:
        matched_tracks = ["5.05", "5.06"]
        report_en = render_feedback_report_en(
            base_name="Read PB58",
            matched_level="2",
            matched_unit=5,
            matched_tracks=matched_tracks,
            standard_text="Hello.\nWorld.",
            scores={"pronunciation": 80, "accuracy": 70, "fluency": 90, "completeness": 60},
            problem_words=[{"word": "wildlife", "error_type": "Mispronunciation", "score": 22.0}],
            feedback_en="You did well. Read the small words too.",
        )
        self.assertIn("## Matched Level\n2", report_en)
        self.assertIn("## Matched Track\n5.05\n5.06", report_en)
        self.assertIn("Pronunciation: 80/100", report_en)
        self.assertIn("wildlife", report_en)
        self.assertNotIn("## Source File", report_en)
        self.assertNotIn("## Whisper Text", report_en)
        self.assertNotIn("## Azure 识别文本", report_en)
        self.assertNotIn("| Metric |", report_en)
        self.assertIn("Read PB58", report_en)

        report_cn = render_feedback_report_cn(
            base_name="Read PB58",
            matched_level="2",
            matched_unit=5,
            matched_tracks=matched_tracks,
            standard_text="Hello.\nWorld.",
            scores={"pronunciation": 80, "accuracy": 70, "fluency": 90, "completeness": 60},
            problem_words=[{"word": "wildlife", "error_type": "Mispronunciation", "score": 22.0}],
            feedback_cn="你读得不错。小词也要读出来。",
        )
        self.assertIn("## 匹配 Level\n2", report_cn)
        self.assertIn("## 匹配 Track\n5.05\n5.06", report_cn)
        self.assertIn("发音：80/100", report_cn)
        self.assertIn("wildlife", report_cn)
        self.assertNotIn("## 源文件", report_cn)
        self.assertNotIn("## Whisper 转写", report_cn)
        self.assertNotIn("## Azure 识别文本", report_cn)
        self.assertNotIn("| 指标 |", report_cn)

    def test_choose_report_tracks_filters_cross_unit_noise(self) -> None:
        matches = [
            {"unit": 5, "track_num": "5.05", "score": 0.54},
            {"unit": 5, "track_num": "5.06", "score": 0.31},
            {"unit": 5, "track_num": "5.08", "score": 0.18},
            {"unit": 0, "track_num": "0.05", "score": 0.14},
        ]
        self.assertEqual(["5.05", "5.06"], choose_report_tracks(matches))

    def test_choose_report_tracks_prefers_single_best_track_when_tail_closes(self) -> None:
        matches = [
            {
                "unit": 5,
                "track_num": "5.05",
                "score": 0.71,
                "text": "\n".join(
                    [
                        "Harry: Gracie! What are you eating?",
                        "Cameron: Is that Jim's picture of the wildlife park?",
                        "Henrietta: What? Not again! Stop it! Be quiet, everyone!",
                        "Rocky: Mum's the angriest animal in the barn!",
                        "Shelly, Harry & Gracie: Sorry, Henrietta!",
                    ]
                ),
            },
            {
                "unit": 5,
                "track_num": "5.06",
                "score": 0.42,
                "text": "4 Gracie: And Rocky's the naughtiest animal in\n8 Gracie: And you're the worst singer!",
            },
        ]
        transcript = (
            "Gracie what are you eating that Jim's picture of the wildlife park "
            "what not again stop it be quiet everyone mum's the angriest animal in the barn sorry harriet"
        )

        self.assertEqual(["5.05"], choose_report_tracks(matches, transcript))

    def test_estimate_minimum_word_count_uses_audio_duration(self) -> None:
        self.assertEqual(105, _estimate_minimum_word_count(124.0))
        self.assertEqual(73, _estimate_minimum_word_count(87.0))

    def test_expand_reference_span_uses_only_lines_with_evidence(self) -> None:
        reference_text = "\n".join(
            [
                "The Friendly Farm, the Friendly Farm,",
                "Fun and games on the Friendly Farm,",
                "With the animals in the barn,",
                "Fun and games on the Friendly Farm.",
                "[Frame 1]",
                "Harry: Gracie! What are you eating?",
                "Cameron: Is that Jim's picture of the wildlife park?",
                "Gracie: I'm not eating it! I'm bringing it to show you.",
                "[Frame 2]",
                "Rocky: What's that?",
                "Harry: Look! It's Jim's picture of a bear and a kangaroo ... oh, and a parrot!",
                "Cameron: The bear's the biggest, but the kangaroo's got the longest tail.",
                "[Frame 3]",
                "Harry: What? Is its tail longer than mine?",
                "Cameron: Yes, I think so, Harry.",
                "Rocky: Hmm, so, which is the best animal?",
            ]
        )
        transcript = (
            "The Friendly farm. Gracie. What are you eating? "
            "That Jim's picture of the wildlife park. "
            "I'm not eating it. I'm bringing it to show you. "
            "What's that? It's Jim's picture of a bear and a kangaroo. "
            "Oh, and a parrot. The bear's the biggest."
        )

        expanded = _expand_reference_span([("5.05", reference_text)], transcript, minimum_word_count=95)

        self.assertIn("## 5.05", expanded)
        self.assertIn("The Friendly Farm", expanded)
        self.assertNotIn("The Friendly Farm, the Friendly Farm,", expanded)
        self.assertNotIn("Fun and games on the Friendly Farm,", expanded)
        self.assertIn("The bear's the biggest, but the kangaroo's got the longest tail.", expanded)
        self.assertNotIn("What? Is its tail longer than mine?", expanded)
        self.assertNotIn("Yes, I think so, Harry.", expanded)
        self.assertNotIn("Harry:", expanded)
        self.assertNotIn("[Frame 1]", expanded)

    def test_expand_reference_span_keeps_single_evidenced_intro_line_before_dialogue_cluster(self) -> None:
        reference_text = "\n".join(
            [
                "The Friendly Farm, the Friendly Farm,",
                "Fun and games on the Friendly Farm,",
                "With the animals in the barn,",
                "Fun and games on the Friendly Farm.",
                "Harry: Gracie! What are you eating?",
                "Cameron: Is that Jim's picture of the wildlife park?",
            ]
        )
        transcript = "The friendly farm. Gracie, what are you eating? Is that Jim's picture of the wildlife park?"

        expanded = _expand_reference_span([("5.05", reference_text)], transcript, minimum_word_count=0)

        self.assertIn("## 5.05", expanded)
        self.assertIn("The Friendly Farm", expanded)
        self.assertNotIn("The Friendly Farm, the Friendly Farm,", expanded)
        self.assertNotIn("Fun and games on the Friendly Farm,", expanded)
        self.assertIn("Gracie! What are you eating?", expanded)

    def test_expand_reference_span_bridges_single_low_confidence_line_inside_strong_cluster(self) -> None:
        reference_text = "\n".join(
            [
                "Harry: Gracie! What are you eating?",
                "Cameron: Is that Jim's picture of the wildlife park?",
                "Gracie: I'm not eating it! I'm bringing it to show you.",
            ]
        )
        transcript = (
            "Gracie what are you eating? Is that dream's picture of the wild park? "
            "I'm not eating it. I'm bringing it to show you."
        )

        expanded = _expand_reference_span([("5.05", reference_text)], transcript, minimum_word_count=0)

        self.assertIn("Is that Jim's picture of the wildlife park?", expanded)

    def test_expand_reference_span_keeps_short_fuzzy_tail_line(self) -> None:
        reference_text = "\n".join(
            [
                "Henrietta: What? Not again! Stop it! Be quiet, everyone!",
                "Rocky: Mum's the angriest animal in the barn!",
                "Shelly, Harry & Gracie: Sorry, Henrietta!",
            ]
        )
        transcript = (
            "What not again stop it be quiet everyone mum's the angriest animal in the barn sorry harriet"
        )

        expanded = _expand_reference_span([("5.05", reference_text)], transcript, minimum_word_count=0)

        self.assertIn("Sorry, Henrietta!", expanded)

    def test_expand_reference_span_skips_duplicate_later_track_without_new_evidence(self) -> None:
        track_sections = [
            (
                "5.05",
                "\n".join(
                    [
                        "Harry: Gracie! What are you eating?",
                        "Cameron: Is that Jim's picture of the wildlife park?",
                        "Gracie: I'm not eating it! I'm bringing it to show you.",
                        "Rocky: What's that?",
                    ]
                ),
            ),
            (
                "5.06",
                "\n".join(
                    [
                        "6 Gracie: I'm not eating it! I'm bringing it to show you.",
                        "7 Rocky: Mum's the angriest animal in the barn!",
                        "8 Gracie: And you're the worst singer!",
                    ]
                ),
            ),
        ]
        transcript = (
            "Gracie, what are you eating? Is that Jim's picture of the wildlife park? "
            "I'm not eating it. I'm bringing it to show you. What's that?"
        )

        expanded = _expand_reference_span(track_sections, transcript, minimum_word_count=95)

        self.assertNotIn("## 5.06", expanded)
        self.assertNotIn("6 Gracie:", expanded)
        self.assertNotIn("Mum's the angriest animal in the barn!", expanded)

    def test_generate_standard_content_keeps_multi_track_headers_only_for_tracks_with_new_evidence(self) -> None:
        track_sections = [
            (
                "5.05",
                "\n".join(
                    [
                        "Harry: Gracie! What are you eating?",
                        "Cameron: Is that Jim's picture of the wildlife park?",
                    ]
                ),
            ),
            (
                "5.06",
                "\n".join(
                    [
                        "Rocky: Mum's the angriest animal in the barn!",
                        "Gracie: And you're the worst singer!",
                    ]
                ),
            ),
        ]
        whisper_text = (
            "Gracie what are you eating? Is that Jim's picture of the wildlife park? "
            "Mum's the angriest animal in the barn."
        )

        result = generate_standard_content(
            track_sections[0][1],
            whisper_text,
            "Track 5.05",
            5,
            track_sections=track_sections,
        )

        self.assertIn("## 5.05", result)
        self.assertIn("## 5.06", result)
        self.assertIn("Mum's the angriest animal in the barn!", result)
        self.assertNotIn("Rocky:", result)
        self.assertNotIn("Harry:", result)

    def test_generate_standard_content_suppresses_later_track_partials_already_covered(self) -> None:
        track_sections = [
            (
                "5.05",
                "\n".join(
                    [
                        "Shelly: And Gracie's the angriest!",
                        "Gracie: And you're the worst singer! ... And Rocky's the naughtiest animal in this barn!",
                    ]
                ),
            ),
            (
                "5.06",
                "\n".join(
                    [
                        "4 Gracie: And Rocky's the naughtiest animal in",
                        "8 Gracie: And you're the worst singer!",
                    ]
                ),
            ),
        ]
        whisper_text = (
            "And Gracie's the angriest. And you're the worst singer. "
            "And Rocky's the naughtiest animal in this barn."
        )

        result = generate_standard_content(
            track_sections[0][1],
            whisper_text,
            "Track 5.05",
            5,
            track_sections=track_sections,
        )

        self.assertNotIn("## 5.06", result)
        self.assertNotIn("And Rocky's the naughtiest animal in\n", result)

    def test_expand_reference_span_prefers_strongest_contiguous_cluster_within_track(self) -> None:
        reference_text = "\n".join(
            [
                "Rocky: I'm Rocky-Doodle-Doo and ... here's our song for today: Moving like wild animals!",
                "This is our wildlife park. We've got our masks.",
                "And we're all moving like wild animals.",
                "He's running, running, running like a lion.",
                "She's climbing, climbing, climbing like a bear.",
                "He's jumping, jumping, jumping like a kangaroo.",
                "She's hiding, hiding, hiding. Can you see the kitten there?",
                "The parrot's getting food.",
                "It's likes to fly.",
                "He's jumping, jumping, jumping like a rabbit.",
                "She's very slow. She's moving like a snail.",
            ]
        )
        transcript = (
            "This is our wild park. We've got our masks and we're all moving like wild animals. "
            "He's running, running, running like a lion. She's climbing, climbing, climbing like a bear. "
            "He's jumping, jumping, jumping like a kangaroo. She's hiding, hiding, hiding."
        )

        expanded = _expand_reference_span([("5.09", reference_text)], transcript, minimum_word_count=73)

        self.assertIn("She's hiding, hiding, hiding. Can you see the kitten there?", expanded)
        self.assertNotIn("He's jumping, jumping, jumping like a rabbit.", expanded)
        self.assertNotIn("She's very slow. She's moving like a snail.", expanded)

    def test_expand_reference_span_keeps_multiple_strong_clusters_in_same_track(self) -> None:
        reference_text = "\n".join(
            [
                "Rocky: I'm Rocky-Doodle-Doo and ... here's our song for today: Moving like wild animals!",
                "This is our wildlife park. We've got our masks.",
                "And we're all moving like wild animals.",
                "He's running, running, running like a lion.",
                "She's climbing, climbing, climbing like a bear.",
                "He's jumping, jumping, jumping like a kangaroo.",
                "She's hiding, hiding, hiding. Can you see the kitten there?",
                "The parrot's getting food.",
                "It's likes to fly.",
                "He's jumping, jumping, jumping like a rabbit.",
                "She's flying, flying, flying like a bat.",
                "She's very slow. She's moving like a snail.",
                "He's walking like a penguin. Can you do that?",
            ]
        )
        transcript = (
            "This is our wild park. We've got our masks and we're all moving like wild animals. "
            "He's running, running, running like a lion. She's climbing, climbing, climbing like a bear. "
            "He's jumping, jumping, jumping like a kangaroo. Can you see the kitten there? "
            "She's jumping, jumping, jumping like a rabbit. She's flying, flying, flying like a bat. "
            "She's very slow. She's moving like a snail. She's walking like a penguin."
        )

        expanded = _expand_reference_span([("5.09", reference_text)], transcript, minimum_word_count=73)

        self.assertIn("She's hiding, hiding, hiding. Can you see the kitten there?", expanded)
        self.assertIn("He's jumping, jumping, jumping like a rabbit.", expanded)
        self.assertIn("She's flying, flying, flying like a bat.", expanded)
        self.assertIn("She's very slow. She's moving like a snail.", expanded)

    def test_standard_shortness_guard_only_retries_for_truly_short_reference(self) -> None:
        transcript = (
            "The friendly farm Gracie what are you eating is that Jim's picture of the wildlife park "
            "I'm not eating it I'm bringing it to show you what's that look it's Jim's picture of a bear "
            "and a kangaroo oh and a parrot the bear's the biggest but the kangaroo got the longest tail"
        )
        self.assertFalse(
            _standard_is_substantially_shorter_than_transcript(
                "\n".join(
                    [
                        "The Friendly Farm, the Friendly Farm,",
                        "Gracie! What are you eating?",
                        "Is that Jim's picture of the wildlife park?",
                        "I'm not eating it! I'm bringing it to show you.",
                        "What's that?",
                        "Look! It's Jim's picture of a bear and a kangaroo ... oh, and a parrot!",
                        "The bear's the biggest, but the kangaroo's got the longest tail.",
                    ]
                ),
                transcript,
            )
        )

    def test_align_assessment_words_marks_insertions_and_omissions(self) -> None:
        aligned = _align_assessment_words(
            "The Friendly Farm",
            [
                {"word": "The", "error_type": "None", "score": 90},
                {"word": "Friendly", "error_type": "None", "score": 88},
                {"word": "barn", "error_type": "None", "score": 84},
            ],
        )

        self.assertEqual(
            [
                {"word": "The", "error_type": "None", "score": 90},
                {"word": "Friendly", "error_type": "None", "score": 88},
                {"word": "Farm", "error_type": "Omission", "score": 0},
                {"word": "barn", "error_type": "Insertion", "score": 84},
            ],
            aligned,
        )

    def test_align_assessment_words_prefers_earliest_match_for_repeated_phrase(self) -> None:
        aligned = _align_assessment_words(
            "The Friendly Farm the Friendly Farm Gracie",
            [
                {"word": "The", "error_type": "None", "score": 94},
                {"word": "Friendly", "error_type": "None", "score": 91},
                {"word": "Farm", "error_type": "None", "score": 73},
                {"word": "Gracie", "error_type": "None", "score": 94},
            ],
        )

        self.assertEqual(
            [
                ("The", "None"),
                ("Friendly", "None"),
                ("Farm", "None"),
                ("the", "Omission"),
                ("Friendly", "Omission"),
                ("Farm", "Omission"),
                ("Gracie", "None"),
            ],
            [(word["word"], word["error_type"]) for word in aligned],
        )

    def test_build_scores_from_aligned_words_aggregates_continuous_results(self) -> None:
        result = _build_scores_from_aligned_words(
            "The Friendly Farm",
            "The Friendly Farm",
            [
                {"word": "The", "error_type": "None", "score": 90},
                {"word": "Friendly", "error_type": "Mispronunciation", "score": 55},
                {"word": "Farm", "error_type": "Omission", "score": 0},
            ],
            [80, 70],
            [],
        )

        self.assertEqual({"pronunciation": 57.3, "accuracy": 48.3, "fluency": 75.0, "completeness": 66.7}, result["scores"])

    def test_run_with_timeout_returns_value_before_deadline(self) -> None:
        result = _run_with_timeout(str.upper, ("wildlife",), timeout_sec=1.0)
        self.assertEqual("WILDLIFE", result)

    def test_run_with_timeout_raises_timeout_error(self) -> None:
        with self.assertRaises(TimeoutError):
            _run_with_timeout(_slow_identity, ("wildlife",), timeout_sec=0.05)

    @patch("moonspeak.pipeline._run_with_timeout", side_effect=TimeoutError("timed out"))
    def test_azure_score_returns_error_payload_on_timeout(self, run_with_timeout_mock) -> None:
        result = azure_score("/tmp/demo.wav", "Hello there.")

        self.assertEqual("Azure pronunciation scoring timed out after 120s", result["error"])
        self.assertEqual("", result["recognized_text"])
        self.assertEqual("Hello there.", result["reference_text"])
        self.assertEqual({}, result["scores"])
        self.assertEqual([], result["words"])

    def test_find_best_match_prefers_track_with_better_phrase_order(self) -> None:
        tracks = {
            "5.01": {
                "unit": 5,
                "filename": "Unit_05-Test.md",
                "track_header": "Track 5.01",
                "text": "bear kangaroo parrot",
                "words": {"bear", "kangaroo", "parrot"},
            },
            "5.02": {
                "unit": 5,
                "filename": "Unit_05-Test.md",
                "track_header": "Track 5.02",
                "text": "bear parrot kangaroo",
                "words": {"bear", "kangaroo", "parrot"},
            },
        }

        matches = find_best_match("bear kangaroo parrot", tracks, top_n=2)

        self.assertEqual("5.01", matches[0]["track_num"])
        self.assertGreater(matches[0]["score"], matches[1]["score"])

    def test_find_best_match_normalizes_curly_apostrophes(self) -> None:
        tracks = {
            "5.05": {
                "unit": 5,
                "filename": "Unit_05-Test.md",
                "track_header": "Track 5.05",
                "text": "Is that Jim's picture of the wildlife park?",
                "words": {"is", "that", "jim's", "picture", "of", "the", "wildlife", "park"},
            },
            "5.06": {
                "unit": 5,
                "filename": "Unit_05-Test.md",
                "track_header": "Track 5.06",
                "text": "Is that Kim's picture of the city park?",
                "words": {"is", "that", "kim's", "picture", "of", "the", "city", "park"},
            },
        }

        matches = find_best_match("Is that Jim’s picture of the wildlife park", tracks, top_n=2)

        self.assertEqual("5.05", matches[0]["track_num"])
        self.assertGreater(matches[0]["score"], matches[1]["score"])

    def test_extract_problem_words_prioritizes_low_scores(self) -> None:
        scores = {
            "words": [
                {"word": "And", "error_type": "Omission", "score": 0},
                {"word": "And", "error_type": "Omission", "score": 0},
                {"word": "wildlife", "error_type": "Mispronunciation", "score": 22.0},
                {"word": "bringing", "error_type": "Mispronunciation", "score": 57.0},
                {"word": "jim's", "error_type": "Mispronunciation", "score": 50.0},
                {"word": "that", "error_type": "Mispronunciation", "score": 18.0},
                {"word": "Be", "error_type": "Omission", "score": 0},
                {"word": "Harry", "error_type": "Omission", "score": 10.0},
                {"word": "the", "error_type": None, "score": 95.0},
            ]
        }
        self.assertEqual(
            [
                {"word": "And", "error_type": "Omission", "score": 0},
                {"word": "wildlife", "error_type": "Mispronunciation", "score": 22.0},
                {"word": "jim's", "error_type": "Mispronunciation", "score": 50.0},
                {"word": "bringing", "error_type": "Mispronunciation", "score": 57.0},
            ],
            extract_problem_words(scores),
        )

    def test_standard_content_prompt_requires_llm_to_preserve_reference_line_breaks(self) -> None:
        _, prompt = build_standard_content_prompt(
            "Harry: Hello there.\nJenny: Hi!",
            "hello there hi",
            "Track 3.01",
            3,
        )
        self.assertIn("Use the canonical book text wording as the source of truth", prompt)
        self.assertIn("Keep ONLY the part that was actually read", prompt)
        self.assertIn("Use the line breaks from the canonical book text", prompt)
        self.assertIn("Do not merge multiple canonical lines into one paragraph", prompt)

    def test_problem_word_sections_are_child_friendly(self) -> None:
        problem_words = [
            {"word": "wildlife", "error_type": "Mispronunciation", "score": 13.0},
            {"word": "Is", "error_type": "Omission", "score": 0},
            {"word": "it", "error_type": "Insertion", "score": 91.0},
        ]
        en = render_problem_words_section_en(problem_words)
        cn = render_problem_words_section_cn(problem_words)
        self.assertIn("- wildlife: pronunciation was unclear", en)
        self.assertIn("- Is: this word was skipped", en)
        self.assertIn("- it: this extra word was added", en)
        self.assertIn("- wildlife：这个英文单词发得不清楚", cn)
        self.assertIn("- Is：这个英文单词漏读了", cn)
        self.assertIn("- it：这里多读了这个英文单词", cn)

    def test_translation_prompt_keeps_problem_words_in_english(self) -> None:
        feedback_en = (
            'You missed "And" at the beginning. '
            'Please say "wildlife", "jim\'s", and "bringing" more clearly.'
        )
        prompt = build_translation_prompt(feedback_en)
        self.assertIn("Keep every English problem word exactly as English", prompt)
        self.assertIn('Do NOT translate words like "And", "wildlife", "jim\'s", or "bringing"', prompt)

    def test_feedback_fallbacks_keep_problem_words_visible(self) -> None:
        problem_words = [
            {"word": "And", "error_type": "Omission", "score": 0},
            {"word": "wildlife", "error_type": "Mispronunciation", "score": 13.0},
            {"word": "jim's", "error_type": "Mispronunciation", "score": 50.0},
            {"word": "bringing", "error_type": "Mispronunciation", "score": 57.0},
        ]
        feedback_en = build_feedback_fallback_en(problem_words)
        feedback_cn = build_feedback_fallback_cn(problem_words)
        self.assertIn('"And"', feedback_en)
        self.assertIn('"wildlife"', feedback_en)
        self.assertIn('"jim\'s"', feedback_en)
        self.assertIn('"bringing"', feedback_en)
        self.assertIn("And", feedback_cn)
        self.assertIn("wildlife", feedback_cn)
        self.assertIn("jim's", feedback_cn)
        self.assertIn("bringing", feedback_cn)

    def test_feedback_contradiction_detector_rejects_praising_problem_words(self) -> None:
        problem_words = [
            {"word": "wildlife", "error_type": "Mispronunciation", "score": 13.0},
            {"word": "jim's", "error_type": "Mispronunciation", "score": 51.0},
        ]
        bad_feedback = 'You said "wildlife" really well. You also read "jim\'s" clearly.'
        self.assertTrue(_feedback_has_contradictions(bad_feedback, problem_words))

    def test_feedback_covers_problem_words_requires_token_boundary(self) -> None:
        self.assertFalse(
            _feedback_covers_problem_words(
                '你要继续练习 "sit" 这个词。',
                [{"word": "it", "error_type": "Mispronunciation", "score": 20}],
            )
        )

    def test_feedback_mentions_translated_alias_rejects_ascii_quoted_alias_form(self) -> None:
        self.assertTrue(
            _feedback_mentions_translated_alias(
                '单词 "it" 就是 "它"，下次要再练习。',
                [{"word": "it", "error_type": "Mispronunciation", "score": 20}],
            )
        )

    def test_feedback_mentions_translated_alias_rejects_chinese_quoted_english_with_alias_explanation(self) -> None:
        self.assertTrue(
            _feedback_mentions_translated_alias(
                '单词“it”的意思是“它”，下次要再练习。',
                [{"word": "it", "error_type": "Mispronunciation", "score": 20}],
            )
        )

    def test_feedback_mentions_translated_alias_rejects_unquoted_english_alias_explanation(self) -> None:
        self.assertTrue(
            _feedback_mentions_translated_alias(
                "it 的意思是它，下次要再练习。",
                [{"word": "it", "error_type": "Mispronunciation", "score": 20}],
            )
        )
        self.assertTrue(
            _feedback_mentions_translated_alias(
                "单词 it 就是它，下次要再练习。",
                [{"word": "it", "error_type": "Mispronunciation", "score": 20}],
            )
        )

    def test_feedback_mentions_translated_alias_rejects_parenthetical_alias_form(self) -> None:
        self.assertTrue(
            _feedback_mentions_translated_alias(
                '“它”（"it"）下次要再练习。',
                [{"word": "it", "error_type": "Mispronunciation", "score": 20}],
            )
        )

    def test_feedback_contradiction_detector_rejects_corner_quoted_praise(self) -> None:
        self.assertTrue(
            _feedback_has_contradictions(
                '你把「it」读得很好，不过这个词还要继续练习。',
                [{"word": "it", "error_type": "Mispronunciation", "score": 20}],
            )
        )

    def test_feedback_contradiction_detector_rejects_unquoted_praise(self) -> None:
        self.assertTrue(
            _feedback_has_contradictions(
                "wildlife 读得很好，不过这个词还要继续练习。",
                [{"word": "wildlife", "error_type": "Mispronunciation", "score": 20}],
            )
        )

    def test_feedback_contradiction_detector_rejects_unquoted_english_praise_forms(self) -> None:
        problem_words = [{"word": "wildlife", "error_type": "Mispronunciation", "score": 20}]
        self.assertTrue(_feedback_has_contradictions("You pronounced wildlife well.", problem_words))
        self.assertTrue(_feedback_has_contradictions("You read wildlife clearly.", problem_words))
        self.assertTrue(_feedback_has_contradictions("wildlife was good.", problem_words))
        self.assertTrue(_feedback_has_contradictions("wildlife was clear.", problem_words))

    def test_build_feedback_prompt_cn_requires_quoted_english_words_to_stay_in_english(self) -> None:
        prompt = build_feedback_prompt_cn(
            scores={"pronunciation": 70, "fluency": 72},
            recognized_text="it is big",
            reference_text='Read "it" clearly.',
            problem_words=[{"word": "it", "error_type": "Mispronunciation", "score": 20}],
        )

        self.assertIn('如果引用英文词，必须保持英文原样，例如 "it"', prompt)
        self.assertIn('不要把这些英文词翻译成中文', prompt)
        self.assertIn('- "it" (Mispronunciation, score 20)', prompt)

    @patch("moonspeak.pipeline.llm_chat_glm", side_effect=RuntimeError("glm disabled"))
    @patch("moonspeak.pipeline.llm_chat")
    def test_llm_generate_feedback_cn_returns_valid_llm_feedback(self, llm_chat_mock, _llm_chat_glm_mock) -> None:
        llm_chat_mock.return_value = (
            '你这次读得很认真，也一直坚持读完，做得不错。'
            '单词 "wildlife" 和 "bringing" 还需要继续练习，读的时候可以再慢一点，把每个部分读清楚。'
            '下次也要把 "And" 这个词读出来，这样句子会更完整。'
        )

        result = llm_generate_feedback_cn(
            scores={"fluency": 60},
            recognized_text="and wildlife bringing",
            reference_text='Read "And", "wildlife", and "bringing" clearly.',
            problem_words=[
                {"word": "And", "error_type": "Omission", "score": 0},
                {"word": "wildlife", "error_type": "Mispronunciation", "score": 20},
                {"word": "bringing", "error_type": "Mispronunciation", "score": 40},
            ],
        )

        self.assertEqual(result, llm_chat_mock.return_value)
        self.assertIn('"And"', result)
        self.assertIn('"wildlife"', result)
        self.assertIn('"bringing"', result)
        self.assertEqual(llm_chat_mock.call_count, 1)

    @patch("moonspeak.pipeline.llm_chat_glm", side_effect=RuntimeError("glm disabled"))
    @patch("moonspeak.pipeline.llm_chat")
    def test_llm_generate_feedback_en_accepts_valid_english_response(self, llm_chat_mock, _llm_chat_glm_mock) -> None:
        llm_chat_mock.return_value = (
            'You kept going all the way to the end, and that showed good focus. '
            'Please practice "wildlife" more carefully next time so each sound is clearer. '
            'Keep your steady pace and try that word again tomorrow.'
        )

        result = llm_generate_feedback_en(
            scores={
                "pronunciation": 72,
                "words": [{"word": "wildlife", "error_type": "Mispronunciation", "score": 20}],
            },
            recognized_text="wildlife",
            reference_text='Read "wildlife" clearly.',
        )

        self.assertEqual(result, llm_chat_mock.return_value)

    @patch("moonspeak.pipeline.llm_chat_glm", side_effect=RuntimeError("glm disabled"))
    @patch("moonspeak.pipeline.llm_chat", return_value='你把“它”读错了，需要再练习。')
    def test_llm_generate_feedback_cn_falls_back_when_word_is_translated(self, _llm_chat_mock, _llm_chat_glm_mock) -> None:
        result = llm_generate_feedback_cn(
            scores={"fluency": 60},
            recognized_text="it is big",
            reference_text='Read "it" clearly.',
            problem_words=[{"word": "it", "error_type": "Mispronunciation", "score": 20}],
        )

        self.assertIn('"it"', result)
        self.assertNotIn("“它”", result)
        self.assertEqual(result, build_feedback_fallback_cn([{"word": "it", "error_type": "Mispronunciation", "score": 20}], {"fluency": 60}))

    @patch("moonspeak.pipeline.llm_chat_glm", side_effect=RuntimeError("glm disabled"))
    @patch(
        "moonspeak.pipeline.llm_chat",
        return_value='You did a good job finishing the reading. Practice "wildlife" more carefully next time.',
    )
    def test_llm_generate_feedback_cn_falls_back_when_output_is_not_chinese(self, _llm_chat_mock, _llm_chat_glm_mock) -> None:
        problem_words = [{"word": "wildlife", "error_type": "Mispronunciation", "score": 20}]

        result = llm_generate_feedback_cn(
            scores={"fluency": 60},
            recognized_text="wildlife",
            reference_text='Read "wildlife" clearly.',
            problem_words=problem_words,
        )

        self.assertEqual(result, build_feedback_fallback_cn(problem_words, {"fluency": 60}))

    @patch("moonspeak.pipeline.llm_chat_glm", side_effect=RuntimeError("glm disabled"))
    @patch(
        "moonspeak.pipeline.llm_chat",
        return_value='你这次读得很认真。单词“它”也就是 "it" 还需要继续练习，下次要更清楚一点。',
    )
    def test_llm_generate_feedback_cn_falls_back_when_translated_alias_mentions_english_token(self, _llm_chat_mock, _llm_chat_glm_mock) -> None:
        problem_words = [{"word": "it", "error_type": "Mispronunciation", "score": 20}]

        result = llm_generate_feedback_cn(
            scores={"fluency": 60},
            recognized_text="it is big",
            reference_text='Read "it" clearly.',
            problem_words=problem_words,
        )

        self.assertEqual(result, build_feedback_fallback_cn(problem_words, {"fluency": 60}))

    @patch("moonspeak.pipeline.llm_chat_glm", side_effect=RuntimeError("glm disabled"))
    @patch(
        "moonspeak.pipeline.llm_chat",
        return_value='你这次读得很认真。单词“它”也就是 “it” 还需要继续练习，下次要更清楚一点。',
    )
    def test_llm_generate_feedback_cn_falls_back_when_translated_alias_uses_chinese_quotes(self, _llm_chat_mock, _llm_chat_glm_mock) -> None:
        problem_words = [{"word": "it", "error_type": "Mispronunciation", "score": 20}]

        result = llm_generate_feedback_cn(
            scores={"fluency": 60},
            recognized_text="it is big",
            reference_text='Read "it" clearly.',
            problem_words=problem_words,
        )

        self.assertEqual(result, build_feedback_fallback_cn(problem_words, {"fluency": 60}))

    @patch("moonspeak.pipeline.llm_chat_glm", side_effect=RuntimeError("glm disabled"))
    @patch("moonspeak.pipeline.llm_chat", return_value='你这次把 "wildlife" 读得很清楚，真的很好。继续加油，把它读得更清楚一点。')
    def test_llm_generate_feedback_cn_falls_back_when_feedback_is_contradictory(self, _llm_chat_mock, _llm_chat_glm_mock) -> None:
        problem_words = [{"word": "wildlife", "error_type": "Mispronunciation", "score": 13.0}]

        result = llm_generate_feedback_cn(
            scores={"fluency": 60},
            recognized_text="wildlife",
            reference_text='Read "wildlife" clearly.',
            problem_words=problem_words,
        )

        self.assertEqual(result, build_feedback_fallback_cn(problem_words, {"fluency": 60}))

    @patch("moonspeak.pipeline.llm_chat_glm", side_effect=RuntimeError("glm disabled"))
    @patch("moonspeak.pipeline.llm_chat", return_value='你把“wildlife”读得很好，但这个词还需要继续练习，下次可以再慢一点。')
    def test_llm_generate_feedback_cn_falls_back_when_chinese_quotes_have_contradictory_praise(self, _llm_chat_mock, _llm_chat_glm_mock) -> None:
        problem_words = [{"word": "wildlife", "error_type": "Mispronunciation", "score": 13.0}]

        result = llm_generate_feedback_cn(
            scores={"fluency": 60},
            recognized_text="wildlife",
            reference_text='Read "wildlife" clearly.',
            problem_words=problem_words,
        )

        self.assertEqual(result, build_feedback_fallback_cn(problem_words, {"fluency": 60}))

    @patch("moonspeak.pipeline.llm_chat_glm", side_effect=RuntimeError("glm disabled"))
    @patch("moonspeak.pipeline.llm_chat", return_value='你把 "wildlife" 读得很好，但这个词还需要继续练习，下次可以再慢一点。')
    def test_llm_generate_feedback_cn_falls_back_when_same_sentence_has_contradictory_praise(self, _llm_chat_mock, _llm_chat_glm_mock) -> None:
        problem_words = [{"word": "wildlife", "error_type": "Mispronunciation", "score": 13.0}]

        result = llm_generate_feedback_cn(
            scores={"fluency": 60},
            recognized_text="wildlife",
            reference_text='Read "wildlife" clearly.',
            problem_words=problem_words,
        )

        self.assertEqual(result, build_feedback_fallback_cn(problem_words, {"fluency": 60}))

    @patch("moonspeak.pipeline.render_feedback_report_cn", return_value="# report")
    @patch("moonspeak.pipeline.llm_generate_feedback_cn", return_value="反馈")
    @patch("moonspeak.pipeline.extract_problem_words", return_value=[])
    @patch("moonspeak.pipeline._standard_is_substantially_shorter_than_transcript", return_value=True)
    @patch("moonspeak.pipeline.should_retry_standard_generation", return_value=True)
    @patch(
        "moonspeak.pipeline.azure_score",
        side_effect=[
            {
                "recognized_text": "first recognized",
                "scores": {"pronunciation": 20.0, "completeness": 10.0, "accuracy": 30.0},
                "words": [],
            },
            {
                "recognized_text": "retry recognized",
                "scores": {"pronunciation": 75.0, "completeness": 80.0, "accuracy": 70.0},
                "words": [],
            },
        ],
    )
    @patch("moonspeak.pipeline.generate_standard_content", side_effect=["## 5.05\nOld line", "## 5.05\nNew line"])
    @patch("moonspeak.pipeline.find_best_match")
    @patch("moonspeak.pipeline.load_audioscripts")
    @patch("moonspeak.pipeline.whisper_transcribe", return_value="whispered text")
    @patch("moonspeak.pipeline.convert_to_wav", return_value="/tmp/sample.wav")
    def test_assess_audio_passes_retry_updated_reference_text_to_feedback_generation(
        self,
        _convert_to_wav_mock,
        _whisper_transcribe_mock,
        load_audioscripts_mock,
        find_best_match_mock,
        generate_standard_content_mock,
        _azure_score_mock,
        _should_retry_mock,
        _shorter_mock,
        _extract_problem_words_mock,
        llm_generate_feedback_cn_mock,
        _render_feedback_report_cn_mock,
    ) -> None:
        load_audioscripts_mock.return_value = {"5.05": {"text": "Canonical line"}}
        find_best_match_mock.return_value = [
            {
                "unit": 5,
                "track_num": "5.05",
                "track_header": "Track 5.05",
                "text": "Canonical line",
                "score": 0.9,
            }
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            assess_audio("/tmp/sample.m4a", output_dir=tmp_dir, scripts_dir="/tmp/scripts")

        self.assertEqual(generate_standard_content_mock.call_count, 2)
        self.assertEqual("New line", llm_generate_feedback_cn_mock.call_args.kwargs["reference_text"])

    def test_narrow_reference_text_limits_canonical_to_supported_span(self) -> None:
        reference_text = "\n".join(
            [
                "The Friendly Farm, the Friendly Farm,",
                "Fun and games on the Friendly Farm,",
                "With the animals in the barn,",
                "Fun and games on the Friendly Farm.",
                "Harry: Gracie! What are you eating?",
                "Cameron: Is that Jim's picture of the wildlife park?",
                "Gracie: I'm not eating it! I'm bringing it to show you.",
                "Rocky: What's that?",
                "Harry: Look! It's Jim's picture of a bear and a kangaroo ... oh, and a parrot!",
                "Cameron: The bear's the biggest, but the kangaroo's got the longest tail.",
                "Harry: What? Is its tail longer than mine?",
                "Cameron: Yes, I think so, Harry.",
                "Rocky: Hmm, so, which is the best animal?",
            ]
        )
        transcript = (
            "The Friendly farm. Gracie. What are you eating? "
            "That Jim's picture of the wildlife park. "
            "I'm not eating it. I'm bringing it to show you. "
            "What's that? It's Jim's picture of a bear and a kangaroo. "
            "Oh, and a parrot. The bear's the biggest."
        )
        narrowed = narrow_reference_text(reference_text, transcript)
        self.assertIn("The Friendly Farm, the Friendly Farm,", narrowed)
        self.assertNotIn("Fun and games on the Friendly Farm,", narrowed)
        self.assertNotIn("With the animals in the barn,", narrowed)
        self.assertIn("Cameron: The bear's the biggest, but the kangaroo's got the longest tail.", narrowed)
        self.assertNotIn("Harry: What? Is its tail longer than mine?", narrowed)
        self.assertNotIn("Rocky: Hmm, so, which is the best animal?", narrowed)

    def test_should_retry_standard_generation_when_completeness_is_polluted_by_omissions(self) -> None:
        score_result = {
            "recognized_text": "The Friendly farm. Gracie! What are you eating?",
            "scores": {"completeness": 25.0},
            "words": [
                {"word": "And", "error_type": "Omission", "score": 0},
                {"word": "wildlife", "error_type": "Mispronunciation", "score": 13.0},
                {"word": "Be", "error_type": "Omission", "score": 0},
                {"word": "Farm", "error_type": "Omission", "score": 0},
            ],
        }
        self.assertTrue(should_retry_standard_generation(score_result))

    def test_extract_problem_words_skips_capitalized_title_omissions(self) -> None:
        scores = {
            "words": [
                {"word": "Farm", "error_type": "Omission", "score": 0},
                {"word": "wildlife", "error_type": "Mispronunciation", "score": 13.0},
                {"word": "jim's", "error_type": "Mispronunciation", "score": 51.0},
                {"word": "bringing", "error_type": "Mispronunciation", "score": 58.0},
            ]
        }
        self.assertEqual(
            [
                {"word": "wildlife", "error_type": "Mispronunciation", "score": 13.0},
                {"word": "jim's", "error_type": "Mispronunciation", "score": 51.0},
                {"word": "bringing", "error_type": "Mispronunciation", "score": 58.0},
            ],
            extract_problem_words(scores),
        )

    def test_prepare_reference_text_for_llm_strips_frames_and_speaker_labels(self) -> None:
        reference_text = "\n".join(
            [
                "[Frame 1]",
                "Harry: Gracie! What are you eating?",
                "Cameron: Is that Jim's picture of the wildlife park?",
                "Shelly, Harry & Gracie: Sorry, Henrietta!",
            ]
        )
        prepared = prepare_reference_text_for_llm(reference_text)
        self.assertNotIn("[Frame 1]", prepared)
        self.assertNotIn("Harry:", prepared)
        self.assertNotIn("Cameron:", prepared)
        self.assertNotIn("Shelly, Harry & Gracie:", prepared)
        self.assertIn("Gracie! What are you eating?", prepared)
        self.assertIn("Is that Jim's picture of the wildlife park?", prepared)
        self.assertIn("Sorry, Henrietta!", prepared)

    def test_standard_matches_canonical_lines_rejects_changed_wording(self) -> None:
        prepared_reference = "\n".join(
            [
                "The Friendly Farm, the Friendly Farm,",
                "Gracie! What are you eating?",
                "Is that Jim's picture of the wildlife park?",
                "I'm not eating it! I'm bringing it to show you.",
                "What's that?",
                "Look! It's Jim's picture of a bear and a kangaroo ... oh, and a parrot!",
                "The bear's the biggest, but the kangaroo's got the longest tail.",
            ]
        )
        valid_standard = "\n".join(
            [
                "The Friendly Farm, the Friendly Farm,",
                "Gracie! What are you eating?",
                "Is that Jim's picture of the wildlife park?",
                "I'm not eating it! I'm bringing it to show you.",
                "What's that?",
                "Look! It's Jim's picture of a bear and a kangaroo ... oh, and a parrot!",
                "The bear's the biggest.",
            ]
        )
        invalid_standard = "\n".join(
            [
                "The Friendly Farm, the Friendly Farm,",
                "Gracie! What are you eating?",
                "That Jim's picture of the wildlife park?",
                "I'm not eating it! I'm bringing it to show you.",
            ]
        )
        self.assertTrue(standard_matches_canonical_lines(valid_standard, prepared_reference))
        self.assertFalse(standard_matches_canonical_lines(invalid_standard, prepared_reference))

    def test_standard_matches_canonical_lines_rejects_truncated_nonfinal_line(self) -> None:
        prepared_reference = "\n".join(
            [
                "The Friendly Farm, the Friendly Farm,",
                "Gracie! What are you eating?",
                "Is that Jim's picture of the wildlife park?",
            ]
        )
        invalid_standard = "\n".join(
            [
                "The Friendly Farm,",
                "Gracie! What are you eating?",
                "Is that Jim's picture of the wildlife park?",
            ]
        )
        self.assertFalse(standard_matches_canonical_lines(invalid_standard, prepared_reference))


if __name__ == "__main__":
    unittest.main()
