# MoonSpeak 🌙

> AI-Powered English Pronunciation Coach for Kids

MoonSpeak is an open-source project created by [月弦 (Moon)](https://github.com/pengyuexian), designed to help children practice and improve their English pronunciation through AI-powered feedback.

## Features

- 🎙️ **Voice Input** — Kids record their reading via iMessage
- 🎯 **Pronunciation Assessment** — Azure Speech SDK delivers precise scoring
- 🧠 **AI Reference Inference** — GLM-4 intelligently infers reference text
- 💬 **Kid-Friendly Feedback** — Encouraging, actionable feedback
- ☁️ **Cloud-Native** — Uses Azure Speech + GLM API

## How It Works

```
Audio (.m4a) → Azure Transcription → Whisper Transcription
                                              ↓
                                    AI Infers Reference Text
                                              ↓
                              Azure Pronunciation Scoring + Feedback
```

## Quick Start

```bash
# Clone the repo
git clone https://github.com/pengyuexian/MoonSpeak.git
cd MoonSpeak

# Create conda environment
conda env create -f environment.yml
conda activate moonspeak

# Configure credentials in .env
AZURE_SPEECH_KEY=your_key
AZURE_SPEECH_REGION=westus
GLM_API_KEY=your_glm_key

# Run pipeline
python -c "
import sys; sys.path.insert(0, 'src')
from moonspeak.pipeline import assess_audio
result = assess_audio('path/to/audio.m4a')
print(result['feedback'])
"
```

## Project Structure

```
MoonSpeak/
├── .env                    # API keys (git-ignored)
├── .gitignore
├── src/
│   └── moonspeak/
│       ├── __init__.py
│       ├── pipeline.py      # Main assessment pipeline
│       ├── assessor.py      # Azure pronunciation scoring
│       └── transcriber.py  # Whisper transcription
├── books/                  # Oxford Reading Tree materials (git-ignored)
├── evaluations/            # Daily evaluation results
│   └── YYYY-MM-DD/
│       ├── audio/          # Student's audio files
│       └── report.md       # Evaluation report
├── environment.yml
├── setup.py
└── README.md
```

## Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
# Azure Speech Services
AZURE_SPEECH_KEY=your_azure_key
AZURE_SPEECH_REGION=westus

# GLM API (智谱)
GLM_API_KEY=your_glm_key
```

## License

MIT License — Created with ❤️ by 月弦

## Author

**月弦 (Moon)** — [pengyuexian](https://github.com/pengyuexian)

---

*Made with love for little learners everywhere* 🌙✨
