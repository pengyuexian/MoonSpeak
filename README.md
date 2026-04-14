# MoonSpeak 🌙

> AI-Powered English Pronunciation Coach for Kids

MoonSpeak is an open-source project created by [月弦 (Moon)](https://github.com/pengyuexian), designed to help children practice and improve their English pronunciation through AI-powered feedback.

## Features

- 🎙️ **Voice Input** — Kids record their reading/pronunciation exercises
- 📝 **Speech-to-Text** — Whisper-powered accurate transcription
- 🎯 **Pronunciation Assessment** — Azure AI delivers precise pronunciation scoring
- 💬 **AI Feedback** — Combined grammar + pronunciation analysis
- 📱 **iMessage Ready** — Integrates with Apple Messages for seamless workflow

## How It Works

```
Record Audio → Whisper Transcribes → Azure Scores Pronunciation → AI Provides Feedback
```

## Quick Start

```bash
# Clone the repo
git clone https://github.com/pengyuexian/MoonSpeak.git
cd MoonSpeak

# Create conda environment
conda env create -f environment.yml

# Activate environment
conda activate moonspeak

# Configure Azure credentials
export AZURE_SPEECH_KEY=your_key_here
export AZURE_SPEECH_REGION=eastus

# Run assessment
python -m moonspeak assess path/to/audio.m4a "The text to compare against"
```

## Project Structure

```
MoonSpeak/
├── src/
│   └── moonspeak/           # Main package
├── tests/                   # Unit tests
├── docs/                   # Documentation
├── environment.yml         # Conda environment
├── setup.py               # Package setup
└── README.md
```

## For Parents

MoonSpeak helps kids who are learning English by:
- Making pronunciation practice more engaging
- Providing instant, constructive feedback
- Encouraging regular practice through familiar tools (iMessage)

## License

MIT License — Created with ❤️ by 月弦

## Author

**月弦 (Moon)** — [pengyuexian](https://github.com/pengyuexian)

---

*Made with love for little learners everywhere* 🌙✨
