<div align="center">

# clipyyy

**Free, open-source AI video clipper. Turn long videos and podcasts into viral short clips for TikTok, Instagram Reels and YouTube Shorts.**

An open-source, self-hosted alternative to OpusClip, Vizard and Klap. Runs on your machine with local Ollama AI, no per-request fees or cloud model quotas, and no watermark.

[![License: MIT](https://img.shields.io/badge/license-MIT-black.svg)](LICENSE)
[![Python 3.11–3.12](https://img.shields.io/badge/python-3.11%E2%80%933.12-black.svg)](pyproject.toml)
[![CI](https://github.com/T3-Venture-Labs-Limited/clipyyy/actions/workflows/ci.yml/badge.svg)](https://github.com/T3-Venture-Labs-Limited/clipyyy/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/docker-compose%20up-black.svg)](#quick-start)

[Quick start](#quick-start) · [Features](#features) · [CLI and AI agents](#cli-and-ai-agents) · [How it works](#how-it-works) · [FAQ](#faq)

![clipyyy web app: paste a YouTube link, choose clip count, format and caption style](docs/screenshot.png)

</div>

## What is clipyyy?

clipyyy is an open-source tool that cuts long-form video into short vertical clips automatically. Give it a YouTube link, a podcast episode, an interview or a talk. It transcribes the audio locally with Whisper, asks a large language model to find the moments that work on their own, reframes each one around the speaker for 9:16, and burns in animated word-by-word captions. You get ready-to-post MP4 files with a title, caption and hashtags for each clip.

It has a web app for people and a JSON command line for scripts and AI coding agents. Video, audio, transcripts and model inference stay on your computer. The app uses local Ollama models and makes no hosted LLM requests.

## Features

- **AI clip finder.** An LLM reads the whole transcript and ranks the strongest standalone moments by hook, value and clarity. Clips are snapped to sentence boundaries so nothing starts or ends mid-thought.
- **Local AI, no API quotas.** [Ollama](https://ollama.com) runs clip selection and campaign analysis on your computer. Use a vision-capable model such as `qwen2.5vl:3b` for campaign edits. Speed and quality depend on your hardware.
- **Local transcription.** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) with word-level timestamps, on CPU or GPU, in 90+ languages.
- **Automatic reframing.** Face tracking (MediaPipe) keeps the speaker centred when converting horizontal video to 9:16, 4:5 or 1:1.
- **Animated captions.** Word-by-word highlighted subtitles in three styles, rendered with ffmpeg.
- **Post-ready copy.** Every clip comes with a YouTube Shorts title, a social caption and hashtags.
- **Any source.** YouTube and the 1,000+ sites [yt-dlp](https://github.com/yt-dlp/yt-dlp) supports, or upload a local video file.
- **Batch processing.** Paste many links at once; runs are queued and resume where they stopped if something fails.
- **Optional B-roll.** Cuts in matching free stock footage from Pexels.
- **Optional auto-posting.** Publish or schedule clips to TikTok, Instagram, YouTube, Facebook and more through [Buffer](https://buffer.com).
- **No watermark or AI credits.** No per-request fees or daily model quotas; your computer's speed and memory are the practical limits. MIT licensed.

## Quick start

### Docker (easiest)

```bash
git clone https://github.com/T3-Venture-Labs-Limited/clipyyy
cd clipyyy
docker compose up -d
```

Open http://localhost:8000, make sure Ollama is running, choose an installed local model in Settings, paste a video link and click **Find clips**. For campaign editing, use a vision-capable model such as `qwen2.5vl:3b`. No hosted AI key or billing account is required. Clips, runs and settings are saved in `./data`.

### From source

Requires Python 3.11 or 3.12, Node 22+, [uv](https://docs.astral.sh/uv/), ffmpeg with libass (Linux distribution packages include it; on a Mac see [below](#macos)), and deno or node for YouTube downloads.

```bash
git clone https://github.com/T3-Venture-Labs-Limited/clipyyy
cd clipyyy
uv sync
npm --prefix frontend ci && npm --prefix frontend run build
uv run clipyyy serve
```

Open http://127.0.0.1:8000. Run `uv run clipyyy doctor` to check your setup.

### macOS

clipyyy runs on Apple Silicon Macs with macOS 14 (Sonoma) or newer, and on Intel Macs with macOS 13 (Ventura) or newer. Install the tools with [Homebrew](https://brew.sh), then follow the steps above:

```bash
brew install ffmpeg-full uv node deno
```

- **Use `ffmpeg-full`, not `ffmpeg`.** Homebrew's standard `ffmpeg` is built without libass, so it can't draw captions. `ffmpeg-full` can. If you already have Homebrew's `ffmpeg`, `ffmpeg-full` is installed beside it rather than replacing it; clipyyy finds it either way. `uv run clipyyy doctor` shows which ffmpeg is used, and `CLIPYYY_FFMPEG` points it at another one.
- **Transcription** runs on the processor, not the Mac's GPU. A smaller Whisper model under Settings is faster.
- **Intel Macs** get everything except face tracking: the face detector (MediaPipe) no longer supports them, so vertical clips are cropped from the centre.
- **Docker** works too, with Docker Desktop on both Apple Silicon and Intel.

## CLI and AI agents

Everything in the web app is also available from the command line. Every command accepts `--json`, so scripts and coding agents (Claude Code, Codex, Cursor and others) can use clipyyy directly.

```bash
# Install a local vision-capable model once (also handles text tasks)
ollama pull qwen2.5vl:3b
clipyyy config set llm_model qwen2.5vl:3b

# Find the 5 best clips under 45 seconds and save them to ./shorts
clipyyy clip "https://www.youtube.com/watch?v=..." --count 5 --max 45 --out ./shorts

# A local podcast recording, square format, with B-roll and extra guidance
clipyyy clip ~/podcast/episode-12.mp4 --aspect 1:1 --broll --instructions "Only the funniest moments"

clipyyy runs                            # list runs
clipyyy show <run-id> --json            # clips with captions, hashtags and file paths
clipyyy retry <run-id> --from select    # pick new clips without re-transcribing
clipyyy models                           # list locally installed Ollama models
clipyyy publish <clip-id> --channel <buffer-channel-id> --mode queue
```

Example `--json` output:

```json
{
  "run_id": "3f9c2a1b7d40",
  "status": "completed",
  "clips": [
    {
      "rank": 1,
      "title": "Why most startups price too low",
      "post_title": "The Pricing Mistake That Kills Startups",
      "caption": "Charging more filtered out the customers who were never going to stay.",
      "hashtags": ["#startups", "#pricing", "#founders"],
      "duration_seconds": 48.2,
      "score": 9.1,
      "file": "/home/you/shorts/clip-01-why-most-startups-price-too-low.mp4"
    }
  ]
}
```

For agents, [`skills/clipyyy/SKILL.md`](skills/clipyyy/SKILL.md) is a ready-made skill file, and [`AGENTS.md`](AGENTS.md) explains the codebase.

## How it works

| Step | What happens |
|---|---|
| 1. Download | yt-dlp fetches the video (up to 1080p), or a local file is used. |
| 2. Transcribe | faster-whisper produces word-level timestamps on your machine. |
| 3. Find clips | The LLM returns ranked clips with titles, captions, hashtags and B-roll ideas. Clips are checked against your length limits. |
| 4. Plan edits | Each clip is split into short shots; some are marked for B-roll. |
| 5. B-roll | Matching stock footage is downloaded from Pexels (optional). |
| 6. Reframe | Faces are tracked and the crop follows the main speaker. |
| 7. Render | ffmpeg cuts the clip, keeps the original audio and burns in captions. |

Every step saves its result, so a failed run resumes from the step that failed.

## clipyyy vs OpusClip, Vizard and Klap

| | clipyyy | Hosted clipping tools |
|---|---|---|
| Price | Free and open source (MIT); no per-request AI fees. Local hardware and electricity are yours | Monthly subscriptions or credits |
| Watermark | Never | Some free plans add one |
| Where videos are processed | On your computer | Uploaded to the vendor's servers |
| AI model | Local Ollama model running on your computer | Fixed by the vendor |
| Automation | JSON CLI and agent skill | Web app, some offer an API |
| Customisation | Edit the prompt, caption styles and code | Settings in their UI |

Hosted tools are more polished and need no setup. clipyyy is for people who want control, privacy, no limits, or to automate clipping with scripts and agents.

## Settings

Choose an installed local Ollama model in **Settings**. `llm_provider` is locked to local Ollama; legacy hosted-provider keys are ignored. Other optional integrations can still use their own keys.

| Setting | Environment variable | Used for |
|---|---|---|
| `llm_provider` | `CLIPYYY_LLM_PROVIDER` | Always `ollama` (local-only) |
| `llm_model` | `CLIPYYY_LLM_MODEL` | Local model, default `qwen2.5vl:3b` |
| `whisper_model` | `CLIPYYY_WHISPER_MODEL` | `tiny`, `base` (default, faster on CPU), `small`, `medium`, `large-v3`, `turbo` |
| `ytdlp_cookies_from_browser` | `CLIPYYY_COOKIES_FROM_BROWSER` | Using your browser's YouTube login if YouTube blocks downloads |
| `pexels_api_key` | `PEXELS_API_KEY` | B-roll |
| `buffer_api_key` | `BUFFER_API_KEY` | Auto-posting |
| `s3_*` | `CLIPYYY_S3_*` | Hosting clips so Buffer can fetch them |
| `default_instructions` | `CLIPYYY_DEFAULT_INSTRUCTIONS` | Guidance added to every run, such as your audience or a call to action |

Data is stored in `CLIPYYY_HOME` (default `~/.clipyyy`).

### Auto-posting with Buffer

Buffer accepts media only by public URL, so clipyyy first uploads the clip to your own S3-compatible bucket (Cloudflare R2, Backblaze B2, AWS S3 or MinIO), then creates the post as queued, scheduled, immediate or draft. Add your [Buffer API key](https://publish.buffer.com/settings/api) and bucket details under Settings.

## FAQ

**Is clipyyy free?**
Yes. clipyyy is free and open source under the MIT licence. AI inference runs locally through Ollama, so there are no per-request fees, credits or daily hosted-model quotas. Model downloads use disk space, and processing speed depends on your computer.

**What is the best free OpusClip alternative?**
clipyyy is a free, open-source OpusClip alternative that runs locally, has no watermark or AI credit limits, and includes both a web app and a CLI.

**Can it clip podcasts?**
Yes, video podcasts. Upload the recording or paste a YouTube or other link. Audio-only files are not supported yet because clips need a picture.

**Does it work on a Mac?**
Yes: Apple Silicon with macOS 14 or newer, and Intel with macOS 13 or newer. Install `ffmpeg-full` from Homebrew rather than `ffmpeg`; see [macOS](#macos).

**Does it need a GPU?**
No. Transcription runs on the CPU; an hour of video takes several minutes. A CUDA GPU makes it faster and is used automatically when available.

**Which languages are supported?**
Whisper transcribes 90+ languages and detects the language automatically. Titles and captions are written in the language of the video unless you ask otherwise.

**Which AI model should I use?**
Start with `qwen2.5vl:3b` for both text and campaign frame analysis. Smaller text-only models can be faster for ordinary clipping but cannot inspect campaign video frames.

**YouTube says "Sign in to confirm you're not a bot". What do I do?**
Wait and retry, or choose your browser under Settings → Downloads so yt-dlp can use your YouTube login.

**Can AI agents use it?**
Yes. Every CLI command returns JSON, and `skills/clipyyy/SKILL.md` teaches agents how to use it.

## Privacy and security

- Videos, audio, transcripts and AI inference stay on your machine when using the built-in local Ollama workflow.
- API keys are stored in the local SQLite database. Protect the data folder.
- The web app has no login and listens on localhost by default. Do not expose it to the internet without authentication in front of it.

## Development

```bash
uv sync
uv run pytest -q                  # tests (need ffmpeg)
uv run ruff check src tests
npm --prefix frontend run dev     # UI on :5173, proxies /api to :8000
uv run clipyyy serve              # API and worker on :8000
```

Contributions are welcome. See [AGENTS.md](AGENTS.md) for a map of the codebase.

## Credits

- Captions use [Archivo Black](https://github.com/Omnibus-Type/ArchivoBlack) (SIL Open Font License, included).
- Stock footage from [Pexels](https://www.pexels.com).
- Built on [yt-dlp](https://github.com/yt-dlp/yt-dlp), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [MediaPipe](https://github.com/google-ai-edge/mediapipe), [ffmpeg](https://ffmpeg.org) and [FastAPI](https://fastapi.tiangolo.com).

## License

[MIT](LICENSE)
