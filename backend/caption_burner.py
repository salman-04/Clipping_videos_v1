"""
Optional: burn word-by-word captions into MP4.
Only used when user enables the toggle in the UI.
"""
import subprocess
from pathlib import Path

from config import CAPTION_STYLE


def render_with_burned_captions(video_path, clip_start, clip_end,
                                output_path, word_segments, hook_text=""):
    """Try to burn captions. Returns False on any failure (app falls back to clean cut)."""
    try:
        ass_path = output_path.with_suffix(".ass")
        _build_simple_ass(word_segments, clip_start, clip_end, ass_path)

        duration = clip_end - clip_start
        ass_rel = ass_path.name  # relative — cwd is backend folder

        filter_complex = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=30:2,setsar=1[bg];"
            "[0:v]scale=1080:-2:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2:format=auto,format=yuv420p[comp];"
            f"[comp]ass={ass_rel}[out]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{clip_start:.2f}", "-t", f"{duration:.2f}",
            "-i", str(video_path),
            "-filter_complex", filter_complex,
            "-map", "[out]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print("BURN FFMPEG ERR:", r.stderr[-400:], flush=True)
            return False
        return True
    except Exception as e:
        print(f"BURN ERROR: {e}", flush=True)
        return False


def _build_simple_ass(words, start, end, out_path: Path):
    """Minimal ASS: 3 words per block, no karaoke sweep (simpler, reliable)."""
    style = CAPTION_STYLE
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {style['play_res_x']}",
        f"PlayResY: {style['play_res_y']}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{style['font_name']},{style['font_size']},"
        f"{style['primary_color']},{style['highlight_color']},"
        f"{style['outline_color']},&H00000000,-1,0,0,0,100,100,0,0,1,"
        f"{style['outline_width']},0,2,20,20,{style['margin_v']},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    clip_words = [w for w in words if w["end"] >= start and w["start"] <= end]
    i = 0
    while i < len(clip_words):
        chunk = clip_words[i:i + style["words_per_line"]]
        cs = max(0, chunk[0]["start"] - start)
        ce = min(end - start, chunk[-1]["end"] - start)
        text = " ".join(w["word"] for w in chunk)
        lines.append(f"Dialogue: 0,{_ass_ts(cs)},{_ass_ts(ce)},Default,,0,0,0,,{text}")
        i += style["words_per_line"]

    out_path.write_text("\n".join(lines), encoding="utf-8")


def _ass_ts(s: float) -> str:
    if s < 0: s = 0
    h = int(s // 3600); m = int((s % 3600) // 60); sec = s % 60
    cs = int(round((sec - int(sec)) * 100))
    if cs >= 100: cs = 0; sec += 1
    return f"{h}:{m:02d}:{int(sec):02d}.{cs:02d}"