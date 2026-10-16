# AI Clip Studio

Turn long videos (podcasts, interviews, streams) into viral-ready short clips for TikTok / Instagram Reels / YouTube Shorts.

## Features

- **Find viral clips** — audio energy + heuristics + optional LLM analysis
- **Captions only** — generate SRT for a specific time range
- **Both** — full pipeline with metadata
- **6 render styles** — blur background, zoom crop, safe zone, square center, split, blur+zoom
- **SRT sidecar files** — ready for CapCut
- **Hook text files** — copy-paste ready
- **Pin clips** — survive "Clean Old Data"
- **Learning database** — track clip performance

## Requirements

- Windows 10/11
- Python 3.12
- FFmpeg (must be on PATH)
- 16 GB RAM recommended

## Install

1. Install Python 3.12: https://www.python.org/downloads/
2. Install FFmpeg:
   ```powershell
   winget install Gyan.FFmpeg
   ```
3. Clone this repo:
   ```powershell
   git clone https://github.com/salman-04/Clipping_videos_v1
   cd Clipping_videos_v1
   ```
4. Install Python packages:
   ```powershell
   cd backend
   pip install -r requirements.txt
   ```
5. Set up API keys (optional — only needed for "Smart" detection mode):
   ```powershell
   copy .env.example .env
   # Open .env in Notepad and paste your Groq key
   ```
   Get a free Groq key at https://console.groq.com/keys

## Run

```powershell
cd backend
python app.py
```

Open http://localhost:5000

## Usage

### Find Clips (default)
1. Paste a YouTube URL or upload a video
2. Pick detection: **Fast** (no API) or **Smart** (uses LLM)
3. Pick render style
4. Click Start

### Captions Only
1. Paste YouTube URL or upload
2. Mode → **Captions Only**
3. Paste time ranges like:
   ```
   00:02:00-00:03:00
   00:07:21-00:08:59
   ```
4. Click Start → get SRT + MP4 per range

## Output

Clips go to `data/output/<video_name>/`:
- `<clip>.mp4` — vertical 9:16 video
- `<clip>.srt` — captions for CapCut
- `<clip>.txt` — title + hook + reason metadata
- `clips.json` — all metadata for the video

Pinned clips go to `data/output/_pinned/`.

## License

MIT