"""
AI Clip Generator — Terminal Edition (interactive + command-line)
================================================================
Finds viral clips (10-90s) in long videos using Gemini.
Outputs 9:16 vertical MP4s + SRT captions for CapCut.

Usage:
    # Interactive mode
    python clipper.py

    # Command-line mode
    python clipper.py -i "video.mp4" --clips 10
    python clipper.py -u "https://youtu.be/..." --clips 15 --min-dur 30 --max-dur 60
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# Local imports — assumes clipper.py lives in the same folder as config.py, core.py
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    OUTPUT_DIR, MIN_CLIPS, MAX_CLIPS,
    MIN_CLIP_SECONDS, MAX_CLIP_SECONDS, DEFAULT_CLIPS,
)
from core import (
    log, sanitize, check_ffmpeg, download_youtube, extract_audio,
    transcribe, analyze_with_gemini, cut_vertical_clip, build_srt_for_clip,
    get_duration,
)


# -------------------------------------------------------------------------
# Main pipeline
# -------------------------------------------------------------------------
def run(video_source: str, is_url: bool,
        target_clips: int, min_dur: int, max_dur: int,
        skip_captions: bool):
    check_ffmpeg()

    # 1. Get the video
    if is_url:
        video_path = download_youtube(video_source)
    else:
        video_path = Path(video_source)
        if not video_path.exists():
            log(f"❌ File not found: {video_source}")
            sys.exit(1)

    video_name = sanitize(video_path.stem.strip()).rstrip(". ")
    if not video_name:
        video_name = "video"

    duration = get_duration(video_path)
    log(f"🎬 Video: {video_name}")
    log(f"⏱️  Duration: {duration:.0f}s ({duration/60:.1f} min)")

    out_dir = OUTPUT_DIR / video_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # 2. Extract audio
    audio_path = extract_audio(video_path)

    # 3. Transcribe
    segments = transcribe(audio_path)
    if not segments:
        log("❌ No speech detected. Aborting.")
        sys.exit(1)

    # 4. Analyze with Gemini
    log("")
    log(f"🎯 Looking for {target_clips} clips between {min_dur}-{max_dur}s...")
    clips = analyze_with_gemini(
        segments,
        min_dur,
        max_dur,
        MIN_CLIPS,
        min(target_clips, MAX_CLIPS),
    )
    if not clips:
        log("❌ Gemini found no clips. Try a longer video.")
        sys.exit(1)

    clips.sort(key=lambda c: c["score"], reverse=True)

    # Save metadata
    meta = {
        "video": str(video_path),
        "title": video_name,
        "duration_seconds": duration,
        "target_clips": target_clips,
        "min_duration": min_dur,
        "max_duration": max_dur,
        "clips": clips,
    }
    meta_path = out_dir / "clips.json"
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log(f"⚠️  Could not save metadata: {e}")
        meta_path = None

    # Show clips
    log("")
    log("=" * 68)
    log(f"📋 FOUND {len(clips)} CLIPS")
    log("=" * 68)
    for i, c in enumerate(clips[:15], 1):
        dur = c["end"] - c["start"]
        log(f"  {i:2d}. [{c['score']}/10] {dur:4.0f}s  {c['title']}")
    if len(clips) > 15:
        log(f"  ... and {len(clips) - 15} more (see clips.json)")

    # 5. Cut clips
    log("")
    log("=" * 68)
    log(f"✂️  CUTTING {len(clips)} CLIPS → {out_dir}")
    log("=" * 68)

    made = 0
    for i, c in enumerate(clips, 1):
        title = sanitize(c["title"])
        dur = int(c["end"] - c["start"])
        fname = f"{i:02d}_score{c['score']}_dur{dur}s_{title}.mp4"
        out_path = out_dir / fname

        log(f"[{i}/{len(clips)}] {fname}")

        ok = cut_vertical_clip(video_path, c["start"], c["end"], out_path)
        if not ok:
            log("   ❌ Failed to cut")
            continue

        if not skip_captions:
            srt_path = out_path.with_suffix(".srt")
            build_srt_for_clip(segments, c["start"], c["end"], srt_path, words_per_line=3)

        made += 1
        log(f"   ✅ OK ({dur}s)")

    # 6. Cleanup temp audio
    try:
        os.remove(audio_path)
    except Exception:
        pass

    # Summary
    log("")
    log("=" * 68)
    log(f"✅ DONE — {made}/{len(clips)} clips created")
    log(f"📁 Output: {out_dir}")
    if meta_path:
        log(f"📄 Metadata: {meta_path}")
    log("=" * 68)
    log("")
    log("📌 Next steps in CapCut:")
    log("   1. New project → import a clip (.mp4)")
    log("   2. Text → Import local subtitle → pick the matching .srt")
    log("   3. Style the caption (font, color, animation)")
    log("   4. Export and upload")
    log("")


# -------------------------------------------------------------------------
# Interactive mode
# -------------------------------------------------------------------------
def prompt_user():
    print("=" * 60)
    print(" 🎬 AI Clip Generator")
    print("=" * 60)
    print()

    print("Input type:")
    print("  1) Local video file")
    print("  2) YouTube URL")
    choice = input("Enter 1 or 2 [default 2]: ").strip() or "2"

    if choice == "1":
        source = input("Video file path (drag & drop): ").strip()
        source = re.sub(r"^&\s*", "", source).strip().strip("'").strip('"')
        is_url = False
    else:
        source = input("YouTube URL: ").strip().strip('"').strip("'")
        is_url = True

    print()
    n = input("How many clips do you want? [default 10]: ").strip()
    target_clips = int(n) if n.isdigit() else 10

    print()
    print("Clip duration range (seconds):")
    print("  1) Short    (10-30s)  — punchy, fast-paced")
    print("  2) Medium   (30-60s)  — balanced [default]")
    print("  3) Long     (60-90s)  — storytelling")
    print("  4) Custom")
    dur_choice = input("Enter 1-4 [default 2]: ").strip() or "2"

    if dur_choice == "1":
        min_dur, max_dur = 10, 30
    elif dur_choice == "2":
        min_dur, max_dur = 30, 60
    elif dur_choice == "3":
        min_dur, max_dur = 60, 90
    else:
        try:
            min_dur = int(input("  Min duration (seconds): ").strip())
            max_dur = int(input("  Max duration (seconds): ").strip())
        except ValueError:
            min_dur, max_dur = 30, 60
            print("  ⚠️  Invalid input, using defaults 30-60s")

    print()
    print("─" * 60)
    print("📋 Summary:")
    src_display = source[:60] + ("..." if len(source) > 60 else "")
    print(f"   Source:      {src_display}")
    print(f"   Target:      {target_clips} clips")
    print(f"   Duration:    {min_dur}-{max_dur}s")
    print("─" * 60)

    confirm = input("\nStart? (y/n) [default y]: ").strip().lower() or "y"
    if confirm != "y":
        print("Cancelled.")
        sys.exit(0)

    print()
    return source, is_url, target_clips, min_dur, max_dur


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="Generate viral 9:16 clips from long videos using Gemini."
    )
    p.add_argument("-i", "--input", help="Path to a local video file")
    p.add_argument("-u", "--url", help="YouTube URL")
    p.add_argument("--clips", type=int, default=None,
                   help=f"Target number of clips (default {DEFAULT_CLIPS})")
    p.add_argument("--min-dur", type=int, default=None,
                   help=f"Minimum clip duration in seconds (default {MIN_CLIP_SECONDS})")
    p.add_argument("--max-dur", type=int, default=None,
                   help=f"Maximum clip duration in seconds (default {MAX_CLIP_SECONDS})")
    p.add_argument("--no-captions", action="store_true",
                   help="Skip writing .srt sidecar files")
    a = p.parse_args()

    if a.input or a.url:
        target = a.clips if a.clips is not None else DEFAULT_CLIPS
        min_d = a.min_dur if a.min_dur is not None else MIN_CLIP_SECONDS
        max_d = a.max_dur if a.max_dur is not None else MAX_CLIP_SECONDS
        run(a.input or a.url, bool(a.url), target, min_d, max_d, a.no_captions)
    else:
        source, is_url, target, min_d, max_d = prompt_user()
        run(source, is_url, target, min_d, max_d, a.no_captions)


if __name__ == "__main__":
    t0 = time.time()
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user.")
        sys.exit(0)
    finally:
        log(f"⏱️  Total time: {time.time() - t0:.0f}s")