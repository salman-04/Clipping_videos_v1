"""Core functions: download, extract, transcribe, cut, SRT."""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from config import (
    TEMP_DIR, OUTPUT_DIR,
    WHISPER_MODEL, WHISPER_LANGUAGE, WHISPER_BEAM_SIZE, WHISPER_CPU_THREADS,
)

__all__ = [
    "log", "sanitize", "check_ffmpeg", "download_youtube", "extract_audio",
    "transcribe_with_words", "cut_clean_clip", "build_srt_for_range",
    "get_duration", "format_timestamp", "parse_time_range",
]


def log(msg: str):
    print(msg, flush=True)


def sanitize(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip(" .")[:80]
    return name or "video"


def check_ffmpeg():
    import shutil
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH")
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe not found on PATH")


def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def get_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def parse_time_range(s: str):
    """
    Parse "2:00-3:00" or "00:02:00-00:03:00" or "2:00-3:00, 7:21-8:59"
    Returns list of (start_seconds, end_seconds).
    """
    ranges = []
    # Split by comma or newline
    parts = re.split(r"[,\n]+", s.strip())
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d{1,2}(?::\d{1,2}){1,2})\s*-\s*(\d{1,2}(?::\d{1,2}){1,2})$", part)
        if not m:
            continue
        a, b = m.group(1), m.group(2)
        ranges.append((_ts_to_sec(a), _ts_to_sec(b)))
    return ranges


def _ts_to_sec(ts: str) -> float:
    parts = [int(x) for x in ts.split(":")]
    if len(parts) == 2:      # M:SS
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:      # H:MM:SS
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0.0


def _cache_key(audio_path: Path) -> Path:
    h = hashlib.md5(str(audio_path).encode()).hexdigest()[:10]
    return TEMP_DIR / f"{sanitize(audio_path.stem)}_{h}_transcript.words.json"


def download_youtube(url: str) -> Path:
    import yt_dlp
    import uuid
    log(f"⬇️  Downloading: {url}")
    unique = uuid.uuid4().hex[:8]
    out_tmpl = str(TEMP_DIR / f"yt_{unique}_%(title)s.%(ext)s")

    ydl_opts = {
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": out_tmpl,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.extract_info(url, download=True)
        for f in TEMP_DIR.glob(f"yt_{unique}_*.mp4"):
            log(f"   ✅ {f.name}")
            return f
    raise FileNotFoundError("YouTube download failed")


def extract_audio(video_path: Path) -> Path:
    audio_path = TEMP_DIR / f"{sanitize(video_path.stem)}.wav"
    log(f"🔊 Extracting audio → {audio_path.name}")
    cmd = ["ffmpeg", "-y", "-i", str(video_path),
           "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
           str(audio_path)]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg audio extraction failed")
    return audio_path


def transcribe_with_words(audio_path: Path):
    """Returns (segments, word_segments). Cached."""
    from faster_whisper import WhisperModel

    cache_path = _cache_key(audio_path)
    if cache_path.exists():
        log(f"📦 Loading cached transcript")
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data["segments"], data["words"]

    os.environ["OMP_NUM_THREADS"] = str(WHISPER_CPU_THREADS)
    log(f"🧠 Loading Whisper '{WHISPER_MODEL}'...")
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8",
                         cpu_threads=WHISPER_CPU_THREADS, num_workers=2)

    log("🎧 Transcribing...")
    t0 = time.time()
    gen, info = model.transcribe(
        str(audio_path), language=WHISPER_LANGUAGE,
        beam_size=WHISPER_BEAM_SIZE, best_of=1, temperature=0.0,
        condition_on_previous_text=False, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 200},
        word_timestamps=True,
    )

    segments, words = [], []
    count = 0
    last_log = time.time()
    for s in gen:
        segments.append({"start": round(s.start, 2), "end": round(s.end, 2),
                         "text": s.text.strip()})
        if s.words:
            for w in s.words:
                words.append({"word": w.word.strip(),
                              "start": round(w.start, 2),
                              "end": round(w.end, 2)})
        count += 1
        if time.time() - last_log > 5:
            progress = s.start / max(info.duration, 1) * 100
            log(f"   ...{count} segments | {progress:.0f}%")
            last_log = time.time()

    log(f"   ✅ {len(segments)} segments, {len(words)} words in "
        f"{(time.time()-t0)/60:.1f} min")

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"segments": segments, "words": words}, f, ensure_ascii=False)

    return segments, words


def cut_clean_clip(video_path: Path, start: float, end: float,
                   output_path: Path) -> bool:
    """
    Clean cut with 9:16 vertical (blur bg). No captions burned.
    Re-encode for accurate seeking.
    """
    duration = end - start
    filter_complex = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=30:2,setsar=1[bg];"
        "[0:v]scale=1080:-2:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2:format=auto,format=yuv420p[v]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.2f}",
        "-t", f"{duration:.2f}",
        "-i", str(video_path),
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log(f"   FFMPEG ERR: {r.stderr[-400:]}")
        return False
    return True


def build_srt_for_range(segments: list, start: float, end: float,
                        out_path: Path, rebase: bool = True,
                        max_chars: int = 28):
    """
    Build SRT for a time range.
    - No overlap: each caption ends BEFORE the next starts.
    - Chunks by char count (safer than word count for on-screen width).
    - rebase=True means timestamps start at 0:00.
    """
    # Collect words with timestamps inside the range
    words = []
    for seg in segments:
        if seg["end"] < start or seg["start"] > end:
            continue
        seg_words = seg["text"].strip().split()
        if not seg_words:
            continue
        seg_start = max(seg["start"], start)
        seg_end = min(seg["end"], end)
        if seg_end <= seg_start:
            continue

        # Distribute words evenly across the segment duration
        dur = seg_end - seg_start
        per = dur / len(seg_words)
        for i, w in enumerate(seg_words):
            words.append({
                "word": w,
                "start": seg_start + i * per,
                "end": seg_start + (i + 1) * per,
            })

    if not words:
        out_path.write_text("", encoding="utf-8")
        return

    # Chunk into captions by character count
    chunks = []
    cur = []
    cur_len = 0
    for w in words:
        add_len = len(w["word"]) + (1 if cur else 0)
        if cur and (cur_len + add_len > max_chars or len(cur) >= 4):
            chunks.append(cur)
            cur = [w]
            cur_len = len(w["word"])
        else:
            cur.append(w)
            cur_len += add_len
    if cur:
        chunks.append(cur)

    offset = start if rebase else 0.0
    clip_len = end - start

    # Build entries with guaranteed gaps
    lines = []
    MIN_GAP = 0.05       # 50ms gap between captions
    MIN_DUR = 0.4        # 400ms min display time

    for i, chunk in enumerate(chunks):
        cs = max(0, chunk[0]["start"] - offset)
        ce = min(clip_len, chunk[-1]["end"] - offset)

        # Ensure minimum duration without breaking the next caption's start
        if ce - cs < MIN_DUR:
            ce = cs + MIN_DUR

        # If not last, cap end so next can start cleanly
        if i < len(chunks) - 1:
            next_start = max(0, chunks[i + 1][0]["start"] - offset)
            max_end = next_start - MIN_GAP
            if max_end < cs + MIN_DUR:
                # Not enough room — shrink start instead
                cs = max(0, next_start - MIN_DUR - MIN_GAP)
                max_end = next_start - MIN_GAP
            ce = min(ce, max_end)

        if ce <= cs:
            ce = cs + MIN_DUR

        text = " ".join(w["word"] for w in chunk)
        lines.append({"start": cs, "end": ce, "text": text})

    # Final pass — enforce monotonic non-overlapping timestamps
    for i in range(len(lines) - 1):
        if lines[i]["end"] > lines[i + 1]["start"]:
            lines[i]["end"] = max(lines[i]["start"] + MIN_DUR,
                                  lines[i + 1]["start"] - MIN_GAP)

    with open(out_path, "w", encoding="utf-8") as f:
        for i, line in enumerate(lines, 1):
            f.write(f"{i}\n{_srt_ts(line['start'])} --> "
                    f"{_srt_ts(line['end'])}\n{line['text']}\n\n")


def _srt_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    ms = int(round((s - int(s)) * 1000))
    if ms >= 1000:
        ms = 0
        s += 1
    return f"{h:02d}:{m:02d}:{int(s):02d},{ms:03d}"