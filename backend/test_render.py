"""
Test render styles on a single clip range.
Usage: python test_render.py <video_path> <start> <end>
Example: python test_render.py video.mp4 120 165
"""
import sys
from pathlib import Path
from render_styles import STYLES, render

def main():
    if len(sys.argv) < 4:
        print("Usage: python test_render.py <video> <start_sec> <end_sec>")
        print("Example: python test_render.py podcast.mp4 120 165")
        sys.exit(1)

    video = Path(sys.argv[1])
    start = float(sys.argv[2])
    end = float(sys.argv[3])

    if not video.exists():
        print(f"❌ Not found: {video}")
        sys.exit(1)

    out_dir = Path("style_tests")
    out_dir.mkdir(exist_ok=True)

    print(f"🎬 Video: {video.name}")
    print(f"⏱️  Range: {start}s → {end}s ({end-start:.0f}s)")
    print(f"📁 Output: {out_dir.absolute()}\n")

    for name in STYLES:
        out = out_dir / f"{name}.mp4"
        print(f"→ Rendering '{name}'...")
        ok = render(video, start, end, out, style_name=name)
        print(f"   {'✅' if ok else '❌'} {out.name}\n")

    print("Done. Open the style_tests folder to preview.")


if __name__ == "__main__":
    main()