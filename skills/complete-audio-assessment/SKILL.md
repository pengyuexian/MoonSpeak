---
name: complete-audio-assessment
description: Run the full MoonSpeak audio assessment flow for one audio file: stage it into today's evaluations directory, execute the pipeline, and return the generated speech review URL. Use when you want the end-to-end workflow from raw audio file to web report.
---

# Complete Audio Assessment

Run one audio file through the full project workflow and get a report URL back.

## Prerequisites

- The `moonspeak` conda environment exists.
- `.env` contains `SERVER`, for example:

```dotenv
SERVER=http://127.0.0.1:6001
```

- The local speech review server is already running before you start the assessment flow:

```bash
server/start.sh
```

This skill does not start the server for you. The server is a separate module.

## Run One File

Pass a local audio file to the wrapper script:

```bash
scripts/run_assessment.sh "/absolute/path/to/Read PB58.m4a"
```

What it does:

1. Copies the source audio into `evaluations/<YYYY-MM-DD>/`
2. Replaces spaces in the filename with underscores
3. Adds `_1`, `_2`, ... if today's folder already contains the same filename
4. Runs the existing MoonSpeak pipeline on the staged file
5. Prints the final speech review URL to stdout

## Expected Duration

- Typical single-file run: about 1-3 minutes
- Slower files: about 3-5 minutes
- Actual time depends on audio length, Whisper runtime, Azure scoring, and external API/network latency
- Azure pronunciation scoring now has an automatic timeout fallback at about 2 minutes

If Azure scoring hangs or is too slow, the pipeline stops waiting and falls back instead of hanging forever. The run still finishes automatically and still writes the normal output files, but the Azure scoring section may contain fallback error data instead of a full score payload.

## Output

Successful stdout output is the report URL:

```text
http://127.0.0.1:6001/speech/2026-04-15/Read_PB58
```

Generated files are saved next to the staged audio file in the same dated `evaluations/` folder. Typical outputs for `Read_PB58.m4a` are:

```text
Read_PB58.standard.txt
Read_PB58.azure.json
Read_PB58.feedback.md
Read_PB58.feedback.cn.md
```

## Common Failures

- `SERVER is not configured in .env`
  Add `SERVER=http://127.0.0.1:6001`

- `Audio file not found`
  Pass a valid local file path

- URL opens but page is unavailable
  Start the server first with `server/start.sh`

- Pipeline errors during Whisper/Azure/LLM steps
  Check `.env` API settings and local runtime dependencies
