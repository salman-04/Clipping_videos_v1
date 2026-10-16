"""
render_styles.py — 9:16 layouts.
Each function: (video_path, start, end, output_path) -> bool
"""
import subprocess
from pathlib import Path


def _run(cmd: list) -> bool:
    r = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        print("FFMPEG ERR:", r.stderr[-500:], flush=True)
        return False
    return True


def _base_cmd(video_path, start, end, output_path, filter_complex, map_label):
    return [
        "ffmpeg", "-y",
        "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}",
        "-i", str(video_path),
        "-filter_complex", filter_complex,
        "-map", map_label, "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ]


def style_blur_bg(video_path, start, end, output_path):
    fc = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=30:2,setsar=1[bg];"
        "[0:v]scale=1080:-2:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2:format=auto,format=yuv420p[v]"
    )
    return _run(_base_cmd(video_path, start, end, output_path, fc, "[v]"))


def style_zoom_crop(video_path, start, end, output_path, focus_x=0.5):
    fc = (
        f"[0:v]crop=ih*9/16:ih:iw*{focus_x}-(ih*9/16)/2:0,"
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,setsar=1,format=yuv420p[v]"
    )
    return _run(_base_cmd(video_path, start, end, output_path, fc, "[v]"))


def style_blur_zoom(video_path, start, end, output_path, zoom=1.15):
    fg_width = int(1080 * zoom)
    fc = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=30:2,setsar=1[bg];"
        f"[0:v]scale={fg_width}:-2:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2:format=auto,format=yuv420p[v]"
    )
    return _run(_base_cmd(video_path, start, end, output_path, fc, "[v]"))


def style_safe_zone(video_path, start, end, output_path):
    fc = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=40:3,setsar=1,eq=brightness=-0.15[bg];"
        "[0:v]scale=1080:-2:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2:format=auto,format=yuv420p[v]"
    )
    return _run(_base_cmd(video_path, start, end, output_path, fc, "[v]"))


def style_square_center(video_path, start, end, output_path):
    fc = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=30:2,setsar=1[bg];"
        "[0:v]scale=1080:1080:force_original_aspect_ratio=increase,"
        "crop=1080:1080[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2:format=auto,format=yuv420p[v]"
    )
    return _run(_base_cmd(video_path, start, end, output_path, fc, "[v]"))


def style_split_top_bottom(video_path, start, end, output_path):
    fc = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=30:2,setsar=1[bg];"
        "[0:v]scale=1080:-2:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H*0.15):format=auto,format=yuv420p[v]"
    )
    return _run(_base_cmd(video_path, start, end, output_path, fc, "[v]"))


STYLES = {
    "blur_bg": style_blur_bg,
    "zoom_crop": style_zoom_crop,
    "blur_zoom": style_blur_zoom,
    "safe_zone": style_safe_zone,
    "square_center": style_square_center,
    "split_top_bottom": style_split_top_bottom,
}


def render(video_path, start, end, output_path, style_name="blur_bg", **kwargs):
    fn = STYLES.get(style_name)
    if not fn:
        raise ValueError(f"Unknown style: {style_name}. Options: {list(STYLES)}")
    return fn(video_path, start, end, output_path, **kwargs)