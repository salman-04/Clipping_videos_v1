"""
AI Clip Studio — Flask API
Three modes: find-clips | captions-only | both
"""
import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import logging
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# Fix CWD for relative paths (ariblk.ttf etc)
os.chdir(Path(__file__).parent)
sys.path.insert(0, str(Path(__file__).parent))

# Load .env
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ[_k.strip()] = _v.strip()

from config import (
    OUTPUT_DIR, TEMP_DIR, UPLOADS_DIR, PINNED_DIR, FRONTEND_DIR,
    DEFAULT_CLIPS, MIN_CLIP_SECONDS, MAX_CLIP_SECONDS,
)
import database as db
from llm_providers import call_llm_with_fallback, LLMError
from core import (
    log, sanitize, check_ffmpeg, download_youtube, extract_audio,
    transcribe_with_words, cut_clean_clip, build_srt_for_range,
    get_duration, format_timestamp, parse_time_range,
)
from audio_highlighter import detect_highlights, analyze_audio
from clip_scorer import fuse_scores
from render_styles import STYLES as RENDER_STYLES, render as render_style

# Find frontend folder — works both as script and as packaged .exe
def _find_frontend():
    candidates = [
        FRONTEND_DIR,
        Path(__file__).parent.parent / "frontend",
        Path(sys.executable).parent / "frontend" if getattr(sys, "frozen", False) else None,
        Path(sys.executable).parent / "_internal" / "frontend" if getattr(sys, "frozen", False) else None,
        Path(getattr(sys, "_MEIPASS", "")) / "frontend" if getattr(sys, "_MEIPASS", None) else None,
    ]
    for p in candidates:
        if p and p.exists() and (p / "index.html").exists():
            return p
    return FRONTEND_DIR  # fallback

_FRONTEND = _find_frontend()

app = Flask(__name__, static_folder=str(_FRONTEND), static_url_path="")
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024

JOBS = {}


# ── Routes ──────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(str(_FRONTEND), "index.html")


@app.route("/api/stats")
def api_stats():
    return jsonify(db.get_stats())


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"):
        return jsonify({"error": f"Unsupported: {ext}"}), 400
    base = sanitize(Path(f.filename).stem)[:60]
    safe_name = f"{base}_{uuid.uuid4().hex[:8]}{ext}"
    dest = UPLOADS_DIR / safe_name
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    f.save(str(dest))
    return jsonify({
        "path": str(dest),
        "filename": safe_name,
        "size_mb": round(dest.stat().st_size / (1024 * 1024), 1),
    })


@app.route("/api/jobs", methods=["POST"])
def api_create_job():
    data = request.get_json() or {}
    source = (data.get("source") or "").strip()
    is_url = bool(data.get("is_url", False))
    mode = data.get("mode", "find-clips")   # find-clips | captions-only | both
    detection = data.get("detection", "fast")  # fast | smart
    burn = bool(data.get("burn_captions", False))
    style = data.get("style", "blur_bg")   # render style key
    ranges_raw = data.get("ranges", "")     # for captions-only
    num_clips = int(data.get("num_clips", DEFAULT_CLIPS))
    min_dur = int(data.get("min_duration", MIN_CLIP_SECONDS))
    max_dur = int(data.get("max_duration", MAX_CLIP_SECONDS))
    api_keys = data.get("api_keys", {})

    if not source:
        return jsonify({"error": "source required"}), 400
        # If it's a local file, verify it exists before queueing
    if not is_url:
        src_path = Path(source)
        if not src_path.exists():
            return jsonify({
                "error": f"File not found: {source}. Upload it again or re-select."
            }), 400
    if mode == "captions-only" and not ranges_raw.strip():
        return jsonify({"error": "ranges required for captions-only mode"}), 400

    job_id = str(uuid.uuid4())[:8]
    JOBS[job_id] = {
        "status": "queued", "log": [], "clips": [],
        "error": None, "progress": 0, "stage": "queued",
    }

    threading.Thread(
        target=_run_job,
        args=(job_id, source, is_url, mode, detection, burn, style,
              ranges_raw, num_clips, min_dur, max_dur, api_keys),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id})


@app.route("/api/jobs/<job_id>")
def api_job_status(job_id):
    if job_id not in JOBS:
        return jsonify({"error": "not found"}), 404
    j = JOBS[job_id]
    return jsonify({
        "status": j["status"], "log": j["log"][-40:], "clips": j["clips"],
        "error": j["error"], "progress": j.get("progress", 0),
        "stage": j.get("stage", ""), "video_title": j.get("video_title", ""),
    })


@app.route("/api/clips/<job_id>/file/<filename>")
def api_serve_file(job_id, filename):
    if job_id not in JOBS:
        return jsonify({"error": "not found"}), 404
    d = JOBS[job_id].get("video_dir")
    if not d:
        return jsonify({"error": "not ready"}), 404
    return send_from_directory(d, filename, as_attachment=filename.endswith(".srt"))


@app.route("/api/pin", methods=["POST"])
def api_pin():
    data = request.get_json() or {}
    clip_id = data.get("clip_id")
    pin = bool(data.get("pin", True))
    job_id = data.get("job_id")
    filename = data.get("filename")

    if not clip_id or not job_id or not filename:
        return jsonify({"error": "missing params"}), 400

    db.set_pinned(int(clip_id), pin)

    if pin:
        # Copy the mp4, srt, txt to _pinned/
        src_dir = JOBS.get(job_id, {}).get("video_dir")
        if src_dir:
            src_dir = Path(src_dir)
            base = Path(filename).stem
            for ext in (".mp4", ".srt", ".txt"):
                src = src_dir / f"{base}{ext}"
                if src.exists():
                    # Prefix with video name so pinned files don't collide
                    vid = sanitize(src_dir.name)[:40]
                    dst = PINNED_DIR / f"{vid}__{base}{ext}"
                    shutil.copy2(src, dst)
        return jsonify({"ok": True, "message": f"Pinned to {PINNED_DIR.name}/"})
    else:
        return jsonify({"ok": True, "message": "Unpinned"})


@app.route("/api/clean", methods=["POST"])
def api_clean():
    """Delete output/* (except _pinned/), temp/*, uploads/*. Keep DB."""
    deleted = {"output": 0, "temp": 0, "uploads": 0}
    errors = []

    def _safe_rm(p: Path):
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            return True
        except Exception as e:
            errors.append(f"{p.name}: {e}")
            return False

    # output/ except _pinned
    for item in OUTPUT_DIR.iterdir():
        if item.name == "_pinned":
            continue
        if _safe_rm(item):
            deleted["output"] += 1

    # temp/
    for item in TEMP_DIR.iterdir():
        if _safe_rm(item):
            deleted["temp"] += 1

    # uploads/
    for item in UPLOADS_DIR.iterdir():
        if _safe_rm(item):
            deleted["uploads"] += 1

    return jsonify({"ok": True, "deleted": deleted, "errors": errors})


@app.route("/api/pinned")
def api_pinned():
    items = []
    if PINNED_DIR.exists():
        for f in sorted(PINNED_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.suffix == ".mp4":
                items.append({
                    "name": f.name,
                    "size": round(f.stat().st_size / (1024 * 1024), 1),
                })
    return jsonify(items)

import user_settings


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    """Return current settings (API keys masked)."""
    data = user_settings.load()
    masked = dict(data)
    masked["api_keys"] = {
        k: ("•" * 20 + v[-4:]) if v else ""
        for k, v in data.get("api_keys", {}).items()
    }
    return jsonify(masked)


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    """Save API key or Ollama model."""
    data = request.get_json() or {}

    if "provider" in data and "api_key" in data:
        user_settings.set_api_key(data["provider"], data["api_key"])

    if "ollama_model" in data:
        user_settings.set_ollama_model(data["ollama_model"])

    return jsonify({"ok": True})


@app.route("/api/ollama/models")
def api_ollama_models():
    """List models the user has installed in Ollama."""
    from llm_providers import list_ollama_models
    models = list_ollama_models()
    return jsonify({
        "installed": models,
        "current": user_settings.get_ollama_model(),
        "ollama_url": user_settings.load().get("ollama_url"),
    })


# ── Worker ──────────────────────────────────────────────────
def _log_to_job(job_id, msg):
    print(f"[{job_id}] {msg}", flush=True)
    if job_id in JOBS:
        JOBS[job_id]["log"].append(msg)


def _stage(job_id, stage, progress=None):
    if job_id in JOBS:
        JOBS[job_id]["stage"] = stage
        if progress is not None:
            JOBS[job_id]["progress"] = progress


def _run_job(job_id, source, is_url, mode, detection, burn, style,
             ranges_raw, num_clips, min_dur, max_dur, api_keys):
    try:
        check_ffmpeg()
        JOBS[job_id]["status"] = "running"
        _stage(job_id, "Preparing", 3)

        # 1. Get video
        if is_url:
            _stage(job_id, "Downloading", 5)
            video_path = download_youtube(source)
        else:
            video_path = Path(source)
            if not video_path.exists():
                raise RuntimeError(f"File not found: {source}")

        video_name = sanitize(video_path.stem.strip()).rstrip(". ") or "video"
        duration = get_duration(video_path)
        _log_to_job(job_id, f"🎬 {video_name} ({duration/60:.1f} min)")

        out_dir = OUTPUT_DIR / video_name
        out_dir.mkdir(parents=True, exist_ok=True)

        # 2. Audio
        _stage(job_id, "Extracting audio", 10)
        audio_path = extract_audio(video_path)

        # 3. Transcribe
        _stage(job_id, "Transcribing", 20)
        segments, words = transcribe_with_words(audio_path)
        _log_to_job(job_id, f"✅ {len(segments)} segments")

        clips_data = []

        # ── CAPTIONS-ONLY MODE ──
        if mode == "captions-only":
            ranges = parse_time_range(ranges_raw)
            if not ranges:
                raise RuntimeError("No valid ranges parsed. Use e.g. 2:00-3:00")

            _log_to_job(job_id, f"✂️  {len(ranges)} ranges to caption")

            for i, (rs, re_) in enumerate(ranges, 1):
                pct = 30 + int(i / len(ranges) * 60)
                _stage(job_id, f"Range {i}/{len(ranges)}", pct)
                tag = f"{_fmt(rs)}-{_fmt(re_)}".replace(":", "")
                fname = f"range_{i:02d}_{tag}.mp4"
                srt_name = f"range_{i:02d}_{tag}.srt"
                txt_name = f"range_{i:02d}_{tag}.txt"

                out_path = out_dir / fname
                _log_to_job(job_id, f"[{i}/{len(ranges)}] Cutting {fname}...")

                ok = render_style(video_path, rs, re_, out_path, style_name=style)
                if not ok:
                    continue

                build_srt_for_range(segments, rs, re_,
                                    out_dir / srt_name, rebase=True)

                # Write hook text (empty in captions-only)
                (out_dir / txt_name).write_text("", encoding="utf-8")

                clips_data.append({
                    "filename": fname,
                    "srt": srt_name,
                    "txt": txt_name,
                    "title": f"Range {_fmt(rs)}-{_fmt(re_)}",
                    "start": rs, "end": re_,
                    "duration": int(re_ - rs),
                    "hook": "", "reason": "User-specified range",
                    "score": 0,
                    "video_url": f"/api/clips/{job_id}/file/{fname}",
                    "srt_url": f"/api/clips/{job_id}/file/{srt_name}",
                    "txt_url": f"/api/clips/{job_id}/file/{txt_name}",
                    "clip_id": None,
                })

        # ── FIND-CLIPS or BOTH MODE ──
        else:
            # Audio energy always
            _stage(job_id, "Audio energy", 30)
            try:
                energy = analyze_audio(audio_path)
            except Exception as e:
                _log_to_job(job_id, f"⚠️  Audio analysis failed: {e}")
                energy = []

            # Detection
            if detection == "smart":
                _stage(job_id, "AI analysis", 40)
                _log_to_job(job_id, "🧠 Smart mode (LLM)")
                try:
                    clips = _detect_llm(segments, min_dur, max_dur,
                                        num_clips, api_keys, job_id)
                except LLMError as e:
                    _log_to_job(job_id, f"⚠️  LLM failed: {e}")
                    _log_to_job(job_id, "   Falling back to audio-only...")
                    clips = detect_highlights(audio_path, min_dur, max_dur, num_clips)
            else:
                _stage(job_id, "Audio detection", 40)
                _log_to_job(job_id, "⚡ Fast mode (no API)")
                clips = detect_highlights(audio_path, min_dur, max_dur, num_clips)

            # Fusion scoring
            if clips and energy:
                _stage(job_id, "Scoring", 55)
                clips = fuse_scores(clips, segments, energy,
                                    log_fn=lambda m: _log_to_job(job_id, m))

            clips = clips[:num_clips]
            if not clips:
                raise RuntimeError("No clips found")

            # DB job record
            job_db_id = db.create_job(
                video_title=video_name, video_source=source[:500],
                provider=detection, model="", clip_count=len(clips),
            )

            _stage(job_id, "Rendering", 60)
            for i, c in enumerate(clips, 1):
                pct = 60 + int(i / len(clips) * 38)
                _stage(job_id, f"Clip {i}/{len(clips)}", pct)

                title = sanitize(c["title"])[:40]
                dur = int(c["end"] - c["start"])
                score = c.get("final_score", c["score"])
                fname = f"{i:02d}_score{score}_dur{dur}s_{title}.mp4"
                srt_name = fname.replace(".mp4", ".srt")
                txt_name = fname.replace(".mp4", ".txt")

                out_path = out_dir / fname
                _log_to_job(job_id, f"[{i}/{len(clips)}] {fname}")

                # Optional burned captions
                ok = False
                if burn:
                    try:
                        from caption_burner import render_with_burned_captions
                        ok = render_with_burned_captions(
                            video_path, c["start"], c["end"], out_path,
                            words, hook_text=c.get("hook", ""),
                        )
                    except Exception as e:
                        _log_to_job(job_id, f"   ⚠️  Burn failed: {e}")
                        ok = False
                if not ok:
                    ok = render_style(video_path, c["start"], c["end"],
                                       out_path, style_name=style)

                if not ok:
                    continue

                build_srt_for_range(segments, c["start"], c["end"],
                                    out_dir / srt_name, rebase=True)

                # Hook text file
                # Auto-generate hook if missing (audio mode)
                if not c.get("hook"):
                    c["hook"] = _generate_hook_from_segments(
                        segments, c["start"], c["end"]
                    )
                # Auto-generate a title if it's just "Highlight at..."
                if not c.get("title") or c["title"].startswith("Highlight at"):
                    auto_hook = c.get("hook") or ""
                    if auto_hook:
                        words = auto_hook.split()[:5]
                        c["title"] = " ".join(words).rstrip(",.;:")
                    if not c.get("title"):
                        c["title"] = f"Clip {i}"

                hook_content = _build_hook_file(c)
                (out_dir / txt_name).write_text(hook_content, encoding="utf-8")

                clip_db_id = db.add_clip(
                    job_id=job_db_id, filename=fname, title=c["title"],
                    ai_score=int(score), start_time=c["start"], end_time=c["end"],
                    duration=dur, hook=c.get("hook", ""),
                    reason=c.get("reason", ""),
                )

                clips_data.append({
                    "filename": fname, "srt": srt_name, "txt": txt_name,
                    "title": c["title"], "start": c["start"], "end": c["end"],
                    "duration": dur, "score": score,
                    "hook": c.get("hook", ""), "reason": c.get("reason", ""),
                    "breakdown": c.get("score_breakdown"),
                    "video_url": f"/api/clips/{job_id}/file/{fname}",
                    "srt_url": f"/api/clips/{job_id}/file/{srt_name}",
                    "txt_url": f"/api/clips/{job_id}/file/{txt_name}",
                    "clip_id": clip_db_id,
                })

        # Write per-video metadata
        meta = {
            "video": video_name,
            "duration": duration,
            "mode": mode,
            "detection": detection,
            "clips": clips_data,
        }
        (out_dir / "clips.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Cleanup audio
        try:
            os.remove(audio_path)
        except Exception:
            pass

        JOBS[job_id]["clips"] = clips_data
        JOBS[job_id]["status"] = "completed"
        JOBS[job_id]["video_title"] = video_name
        JOBS[job_id]["video_dir"] = str(out_dir)
        _stage(job_id, "Completed", 100)
        _log_to_job(job_id, f"✅ DONE — {len(clips_data)} clips")

    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = str(e)
        _log_to_job(job_id, f"❌ {e}")


def _generate_hook_from_segments(segments: list, clip_start: float,
                                  clip_end: float) -> str:
    """Extract the first complete sentence in the clip as the hook text."""
    # Find segments inside clip
    inside = [s for s in segments if s["end"] >= clip_start and s["start"] <= clip_end]
    if not inside:
        return ""

    # Combine text from the first 3 segments (opening words)
    opening = " ".join(s["text"] for s in inside[:3]).strip()
    if not opening:
        return ""

    # Find the first sentence ending
    import re as _re
    m = _re.search(r"[.?!]", opening)
    if m:
        hook = opening[:m.end()].strip()
    else:
        # No punctuation — cut at ~8 words
        words = opening.split()
        hook = " ".join(words[:8]) + ("..." if len(words) > 8 else "")

    # Clean up
    hook = hook.strip()
    if len(hook) > 120:
        hook = hook[:117] + "..."

    return hook

def _detect_llm(segments, min_dur, max_dur, num_clips, api_keys, job_id):
    lines = [f"[{format_timestamp(s['start'])}] {s['text']}" for s in segments]
    transcript = "\n".join(lines)
    if len(transcript) > 100_000:
        transcript = transcript[:100_000] + "\n[TRUNCATED]"

    prompt = f"""You are a viral clip expert. Find up to {num_clips} clips, each {min_dur}-{max_dur}s.
Clips must not overlap. Start at natural sentence boundaries.
Prioritize: hot takes, emotional peaks, funny moments, quotable lines.

Return ONLY JSON array:
[{{"start": <float>, "end": <float>, "title": "<short>", "score": <1-10>, "hook": "<line>", "reason": "<why>"}}]

TRANSCRIPT:
{transcript}

JSON:"""

    clips = call_llm_with_fallback(
        prompt, api_keys,
        log_fn=lambda m: _log_to_job(job_id, m),
    )

    cleaned = []
    for c in clips:
        try:
            s = float(c["start"]); e = float(c["end"])
            if e - s < min_dur - 1: e = s + min_dur
            if e - s > max_dur + 1: e = s + max_dur
            cleaned.append({
                "start": round(s, 2), "end": round(e, 2),
                "title": str(c.get("title", "Untitled"))[:60],
                "score": int(c.get("score", 5)),
                "hook": str(c.get("hook", ""))[:200],
                "reason": str(c.get("reason", ""))[:300],
            })
        except Exception:
            continue
    return cleaned[:num_clips]


def _build_hook_file(c: dict) -> str:
    """Text file content for CapCut copy-paste."""
    lines = [
        f"TITLE: {c.get('title', '')}",
        "",
        f"HOOK: {c.get('hook', '')}",
        "",
        f"REASON: {c.get('reason', '')}",
        "",
        f"TIME: {_fmt(c['start'])} - {_fmt(c['end'])}",
        f"DURATION: {int(c['end'] - c['start'])}s",
        f"SCORE: {c.get('final_score', c.get('score', ''))}",
    ]
    return "\n".join(lines)


def _fmt(sec: float) -> str:
    h = int(sec // 3600); m = int((sec % 3600) // 60); s = int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

@app.route("/api/jobs/recent")
def api_recent_jobs():
    """Return last 10 completed jobs (in-memory)."""
    items = []
    for jid, job in list(JOBS.items())[-10:]:
        if job.get("status") == "completed":
            items.append({
                "job_id": jid,
                "video_title": job.get("video_title", ""),
                "clip_count": len(job.get("clips", [])),
            })
    return jsonify(items)


@app.route("/api/styles")
def api_styles():
    return jsonify(list(RENDER_STYLES.keys()))


if __name__ == "__main__":
    db.init_db()
    print("🎬 AI Clip Studio")
    print(f"📁 Output: {OUTPUT_DIR}")
    print(f"📌 Pinned: {PINNED_DIR}")
    print("🌐 Open http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)


