"""
MoonSpeak Assessment Pipeline

流程：
1. 音频 (.m4a) → ffmpeg 转换为 WAV
2. Whisper 转录获取文字
3. LLM 纠偏/推理标准原文，保存为 .txt
4. Azure 评分，保存结果为 .md
5. LLM 翻译结果为中文，保存为 .cn.md
"""

import os
import sys
import subprocess
import json
from dotenv import load_dotenv

# Load .env file
load_dotenv()


def convert_to_wav(audio_path: str) -> str:
    """Convert audio to WAV format."""
    if audio_path.lower().endswith('.wav'):
        return audio_path
    wav_path = audio_path.rsplit('.', 1)[0] + '.wav'
    subprocess.run([
        'ffmpeg', '-y', '-i', audio_path,
        '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le',
        wav_path
    ], capture_output=True)
    return wav_path


def whisper_transcribe(wav_path: str) -> str:
    """Transcribe audio using whisper-cli."""
    model = os.environ.get("WHISPER_MODEL", "ggml-large-v3-turbo")
    model_path = os.path.expanduser(f"~/.cache/whisper.cpp/{model}.bin")

    result = subprocess.run([
        'whisper-cli',
        '-m', model_path,
        '-l', 'en',
        '-t', '4',
        '--no-timestamps',
        wav_path
    ], capture_output=True, text=True)

    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def llm_infer_reference(whisper_text: str, audio_name: str = "") -> str:
    """Use LLM to infer and correct the standard reference text."""
    import requests

    API_KEY = os.environ.get("GLM_API_KEY")
    if not API_KEY:
        return whisper_text  # fallback

    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""A child recorded an English reading exercise. The audio was transcribed by Whisper STT.
The transcription may contain errors due to mishearing, noise, or children's pronunciation.

Whisper transcription: "{whisper_text}"
Audio filename hint: "{audio_name}"

Your task:
1. Infer the most likely ORIGINAL text the child was supposed to read
2. This appears to be from Oxford Reading Tree or similar children's English learning materials
3. Fix obvious transcription errors (wrong words, missing words, etc.)
4. Keep the corrected text in English

Respond ONLY with the corrected original text, nothing else."""

    data = {
        "model": "glm-4-flash",
        "messages": [
            {"role": "system", "content": "You are a helpful English learning assistant for children."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 500,
        "temperature": 0.3
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        result = response.json()
        if "choices" in result:
            return result["choices"][0]["message"]["content"].strip()
    except:
        pass
    return whisper_text


def azure_score(wav_path: str, reference_text: str) -> dict:
    """Score pronunciation using Azure Speech SDK."""
    import azure.cognitiveservices.speech as speechsdk

    speech_config = speechsdk.SpeechConfig(
        subscription=os.environ.get("AZURE_SPEECH_KEY"),
        region=os.environ.get("AZURE_SPEECH_REGION")
    )
    speech_config.speech_recognition_language = "en-US"

    audio_config = speechsdk.AudioConfig(filename=wav_path)
    recognizer = speechsdk.SpeechRecognizer(
        speech_config,
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

    if result.reason != speechsdk.ResultReason.RecognizedSpeech:
        return {
            "error": f"Recognition failed: {result.reason}",
            "recognized_text": "",
            "reference_text": reference_text,
            "scores": {}
        }

    pron_result = speechsdk.PronunciationAssessmentResult(result)

    return {
        "recognized_text": result.text,
        "reference_text": reference_text,
        "scores": {
            "pronunciation": round(pron_result.pronunciation_score, 1),
            "accuracy": round(pron_result.accuracy_score, 1),
            "fluency": round(pron_result.fluency_score, 1),
            "completeness": round(pron_result.completeness_score, 1),
        }
    }


def llm_generate_feedback_en(scores: dict, recognized_text: str, reference_text: str) -> str:
    """Generate English feedback for the child."""
    import requests

    API_KEY = os.environ.get("GLM_API_KEY")
    if not API_KEY:
        return "Great job reading!"

    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    pron_score = scores.get("pronunciation", 0)

    prompt = f"""A child just read English aloud. Provide encouraging feedback.

Reference text (what they should have read): "{reference_text}"
What they actually said: "{recognized_text}"
Pronunciation Score: {pron_score}/100

Requirements:
- Be encouraging and positive (for a young child learning English)
- Mention what they did well
- Gently suggest 1-2 things to improve
- Keep it short (2-3 sentences)
- Use simple English words
- Add an encouraging emoji at the end

Format: Just the feedback text, no labels."""

    try:
        response = requests.post(url, headers=headers, json={
            "model": "glm-4-flash",
            "messages": [
                {"role": "system", "content": "You are a warm, encouraging English teacher for young children."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 300,
            "temperature": 0.7
        }, timeout=30)
        result = response.json()
        if "choices" in result:
            return result["choices"][0]["message"]["content"].strip()
    except:
        pass
    return f"Good job! Your pronunciation score is {pron_score}/100. Keep practicing!"


def llm_translate_to_chinese(feedback_en: str, scores: dict) -> str:
    """Translate feedback to Chinese."""
    import requests

    API_KEY = os.environ.get("GLM_API_KEY")
    if not API_KEY:
        return feedback_en

    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    pron_score = scores.get("pronunciation", 0)
    accuracy = scores.get("accuracy", 0)
    fluency = scores.get("fluency", 0)
    completeness = scores.get("completeness", 0)

    prompt = f"""Translate the following English feedback for a child's English pronunciation practice into Chinese.
Make it natural and encouraging for a child.

English feedback:
"{feedback_en}"

Additional scores context:
- 发音分数: {pron_score}/100
- 准确度: {accuracy}/100
- 流利度: {fluency}/100
- 完整度: {completeness}/100

Requirements:
- 翻译成中文
- 保持鼓励性、积极的态度
- 适合儿童理解
- 简短，2-3句话
- 可以适当添加表情符号

Respond ONLY with the Chinese translation, nothing else."""

    try:
        response = requests.post(url, headers=headers, json={
            "model": "glm-4-flash",
            "messages": [
                {"role": "system", "content": "You are a helpful translator for children's educational content."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 500,
            "temperature": 0.3
        }, timeout=30)
        result = response.json()
        if "choices" in result:
            return result["choices"][0]["message"]["content"].strip()
    except:
        pass
    return feedback_en


def assess_audio(audio_path: str, output_dir: str = None) -> dict:
    """
    Full assessment pipeline for one audio file.

    Generates:
    - {base_name}.txt   (corrected reference text)
    - {base_name}.md    (assessment results in English)
    - {base_name}.cn.md (assessment results in Chinese)
    """
    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    output_dir = output_dir or os.path.dirname(audio_path)

    print(f"\n📝 Processing: {base_name}")

    # Step 1: Convert to WAV
    print("  🔄 Converting to WAV...")
    wav_path = convert_to_wav(audio_path)

    # Step 2: Whisper transcription
    print("  🎤 Whisper transcription...")
    whisper_text = whisper_transcribe(wav_path)
    print(f"      Transcribed: {whisper_text[:60]}...")

    # Step 3: LLM infer/correct reference text
    print("  🧠 Inferring reference text...")
    reference_text = llm_infer_reference(whisper_text, base_name)
    print(f"      Reference: {reference_text[:60]}...")

    # Save reference text
    ref_file = os.path.join(output_dir, f"{base_name}.txt")
    with open(ref_file, 'w', encoding='utf-8') as f:
        f.write(reference_text)
    print(f"  💾 Saved reference: {base_name}.txt")

    # Step 4: Azure scoring
    print("  ⭐ Azure scoring...")
    scores = azure_score(wav_path, reference_text)

    if "error" in scores:
        print(f"      Error: {scores['error']}")
    else:
        print(f"      Pronunciation: {scores['scores']['pronunciation']}/100")
        print(f"      Accuracy: {scores['scores']['accuracy']}/100")
        print(f"      Fluency: {scores['scores']['fluency']}/100")

    # Step 5: Generate English feedback
    print("  💬 Generating feedback...")
    feedback_en = llm_generate_feedback_en(
        scores.get('scores', {}),
        scores.get('recognized_text', ''),
        reference_text
    )
    print(f"      Feedback: {feedback_en[:60]}...")

    # Save English results
    result_md = f"""# Assessment Report: {base_name}

## Reference Text
{reference_text}

## Recognized Text
{scores.get('recognized_text', 'N/A')}

## Scores

| Metric | Score |
|--------|-------|
| Pronunciation | {scores.get('scores', {}).get('pronunciation', 'N/A')}/100 |
| Accuracy | {scores.get('scores', {}).get('accuracy', 'N/A')}/100 |
| Fluency | {scores.get('scores', {}).get('fluency', 'N/A')}/100 |
| Completeness | {scores.get('scores', {}).get('completeness', 'N/A')}/100 |

## Feedback
{feedback_en}
"""
    md_file = os.path.join(output_dir, f"{base_name}.md")
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(result_md)
    print(f"  💾 Saved results: {base_name}.md")

    # Step 6: Translate to Chinese
    print("  🌏 Translating to Chinese...")
    feedback_cn = llm_translate_to_chinese(feedback_en, scores.get('scores', {}))

    result_cn_md = f"""# 评测报告：{base_name}

## 参考原文
{reference_text}

## 识别文本
{scores.get('recognized_text', 'N/A')}

## 评分

| 指标 | 分数 |
|------|------|
| 发音 | {scores.get('scores', {}).get('pronunciation', 'N/A')}/100 |
| 准确度 | {scores.get('scores', {}).get('accuracy', 'N/A')}/100 |
| 流利度 | {scores.get('scores', {}).get('fluency', 'N/A')}/100 |
| 完整度 | {scores.get('scores', {}).get('completeness', 'N/A')}/100 |

## 反馈
{feedback_cn}
"""
    cn_md_file = os.path.join(output_dir, f"{base_name}.cn.md")
    with open(cn_md_file, 'w', encoding='utf-8') as f:
        f.write(result_cn_md)
    print(f"  💾 Saved Chinese: {base_name}.cn.md")

    return {
        "audio": os.path.basename(audio_path),
        "reference_text": reference_text,
        "recognized_text": scores.get('recognized_text', ''),
        "scores": scores.get('scores', {}),
        "feedback_en": feedback_en,
        "feedback_cn": feedback_cn,
        "files": {
            "reference": f"{base_name}.txt",
            "results": f"{base_name}.md",
            "results_cn": f"{base_name}.cn.md"
        }
    }


def assess_directory(audio_dir: str) -> list:
    """Process all audio files in a directory."""
    results = []
    for f in os.listdir(audio_dir):
        if f.lower().endswith(('.m4a', '.wav', '.mp3', '.aac', '.m4b')):
            audio_path = os.path.join(audio_dir, f)
            try:
                result = assess_audio(audio_path, audio_dir)
                results.append(result)
            except Exception as e:
                print(f"  ❌ Error processing {f}: {e}")
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m moonspeak.pipeline <audio_file_or_directory>")
        sys.exit(1)

    path = sys.argv[1]
    if os.path.isdir(path):
        results = assess_directory(path)
        print(f"\n✅ Processed {len(results)} files")
    else:
        result = assess_audio(path)
        print(f"\n✅ Assessment complete: {result['files']}")
