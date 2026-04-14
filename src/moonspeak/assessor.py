"""
MoonSpeak Pronunciation Assessor

Uses Azure Speech SDK for pronunciation assessment.
"""

import os
import wave
import azure.cognitiveservices.speech as speechsdk


class PronunciationAssessor:
    """Assess pronunciation using Azure Speech SDK."""

    def __init__(self, subscription: str = None, region: str = "eastus"):
        """
        Initialize the assessor.

        Args:
            subscription: Azure Speech API key. If None, reads from AZURE_SPEECH_KEY env.
            region: Azure region. Defaults to 'eastus'.
        """
        self.subscription = subscription or os.environ.get("AZURE_SPEECH_KEY")
        self.region = region or os.environ.get("AZURE_SPEECH_REGION", "eastus")

        if not self.subscription:
            raise ValueError(
                "Azure Speech key not provided. "
                "Set AZURE_SPEECH_KEY env or pass subscription parameter."
            )

        self.speech_config = speechsdk.SpeechConfig(
            subscription=self.subscription,
            region=self.region
        )

    def assess(
        self,
        audio_path: str,
        reference_text: str,
        output_file: str = None
    ) -> dict:
        """
        Assess pronunciation of an audio file against reference text.

        Args:
            audio_path: Path to the audio file (.wav or .m4a).
            reference_text: The text the speaker should have said.
            output_file: Optional path to write results JSON.

        Returns:
            Dictionary with scores and word-level feedback.
        """
        audio_config = speechsdk.AudioConfig(filename=audio_path)
        recognizer = speechsdk.SpeechRecognizer(
            self.speech_config,
            audio_config=audio_config
        )

        pronunciation_config = speechsdk.PronunciationAssessmentConfig(
            reference_text=reference_text,
            grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
            granularity=speechsdk.PronunciationAssessmentGranularity.Word,
            enable_miscue=True
        )
        pronunciation_config.apply_to(recognizer)

        result = recognizer.recognize_once()

        if result.reason == speechsdk.ResultReason.NoMatch:
            return {"error": "No speech recognized", "details": result.no_match_details}

        pron_result = speechsdk.PronunciationAssessmentResult(result)

        scores = {
            "pronunciation_score": round(pron_result.pronunciation_score, 1),
            "accuracy_score": round(pron_result.accuracy_score, 1),
            "fluency_score": round(pron_result.fluency_score, 1),
            "completeness_score": round(pron_result.completeness_score, 1),
        }

        words = []
        if pron_result.words:
            for word_result in pron_result.words:
                words.append({
                    "word": word_result.word,
                    "error_type": word_result.error_type,
                    "score": round(word_result.score, 1) if hasattr(word_result, 'score') else None
                })

        assessment = {
            "scores": scores,
            "words": words,
            "recognized_text": result.text,
            "reference_text": reference_text
        }

        if output_file:
            import json
            with open(output_file, 'w') as f:
                json.dump(assessment, f, indent=2, ensure_ascii=False)

        return assessment


def format_feedback(assessment: dict) -> str:
    """
    Format assessment results into kid-friendly feedback.

    Args:
        assessment: Result from PronunciationAssessor.assess()

    Returns:
        Formatted string with encouragement and tips.
    """
    if "error" in assessment:
        return f"😅 {assessment['error']}"

    scores = assessment["scores"]
    pron_score = scores["pronunciation_score"]

    # Overall message
    if pron_score >= 90:
        feedback = f"🌟 Excellent! Your pronunciation score: {pron_score}/100!\n\n"
    elif pron_score >= 75:
        feedback = f"👍 Great job! Your pronunciation score: {pron_score}/100!\n\n"
    elif pron_score >= 60:
        feedback = f"💪 Good effort! Your pronunciation score: {pron_score}/100!\n\n"
    else:
        feedback = f"📚 Keep practicing! Your pronunciation score: {pron_score}/100!\n\n"

    # Word-level feedback
    problem_words = [w for w in assessment.get("words", []) if w.get("error_type")]
    if problem_words:
        feedback += "Words to work on:\n"
        for w in problem_words:
            feedback += f"  • {w['word']} — {w['error_type']}\n"
        feedback += "\nTry saying these words again slowly!\n"

    return feedback


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python -m moonspeak.assessor <audio_file> <reference_text>")
        sys.exit(1)

    assessor = PronunciationAssessor()
    result = assessor.assess(sys.argv[1], sys.argv[2])
    print(format_feedback(result))
