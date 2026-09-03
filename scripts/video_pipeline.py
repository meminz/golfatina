"""Step 2: for one video, grab only the last N seconds and split it into
candidate frames. Downloading just the tail (via yt-dlp's download-sections)
keeps this fast and avoids pulling entire videos just to look at the very end.
"""
import shutil
import subprocess
from pathlib import Path

WORK_DIR = Path(__file__).resolve().parent.parent / "work"


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout


def download_tail_clip(video_id: str, start_seconds_from_end: int, end_seconds_from_end: int) -> Path:
    """Downloads only a WINDOW near the end of the video -- from
    `start_seconds_from_end` seconds before the end, to `end_seconds_from_end`
    seconds before the end (e.g. 27 -> 20 means "the 7 seconds starting 27s
    before the end"). This is narrower than grabbing the whole tail, so it's
    faster and produces fewer frames to OCR.

    Tries yt-dlp's two-sided negative section syntax first (downloads only
    the window itself). If that fails for any reason -- section syntax can
    be finicky across yt-dlp versions -- falls back to downloading the wider
    tail (from start_seconds_from_end to the very end) and trimming to the
    exact window locally with ffmpeg, which is slower but bulletproof.
    """
    if end_seconds_from_end >= start_seconds_from_end:
        raise ValueError(
            "end_seconds_from_end must be smaller than start_seconds_from_end "
            "(the window's 'end' offset is closer to the end of the video)"
        )

    video_dir = WORK_DIR / video_id
    video_dir.mkdir(parents=True, exist_ok=True)
    out_path = video_dir / "clip.mp4"
    url = f"https://www.youtube.com/watch?v={video_id}"

    # yt-dlp section syntax: "*START-END". A "-" prefix on either side makes
    # that offset relative to the end of the video, e.g. "*-27--20" means
    # "from 27s before the end, to 20s before the end".
    window_section = f"*-{start_seconds_from_end}--{end_seconds_from_end}"

    try:
        _run(
            [
                "yt-dlp",
                "--download-sections", window_section,
                "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
                "--merge-output-format",
                "mp4",
                "-o", str(out_path),
                "--force-keyframes-at-cuts",
                "--quiet",
                "--no-warnings",
                url,
            ]
        )
        return out_path
    except RuntimeError as exc:
        print(f"[warn] windowed download failed ({exc}); falling back to tail download + ffmpeg trim")

    # Fallback: download the wider tail, then trim to the exact window.
    wide_path = video_dir / "clip_wide.mp4"
    tail_section = f"*-{start_seconds_from_end}-0"
    _run(
        [
            "yt-dlp",
            "--download-sections", tail_section,
            "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
            "--merge-output-format",
            "mp4",
            "-o", str(wide_path),
            "--force-keyframes-at-cuts",
            "--quiet",
            "--no-warnings",
            url,
        ]
    )

    window_duration = start_seconds_from_end - end_seconds_from_end
    _run(
        [
            "ffmpeg",
            "-y",
            "-i", str(wide_path),
            "-ss", "0",
            "-t", str(window_duration),
            "-c", "copy",
            str(out_path),
            "-loglevel", "error",
        ]
    )
    wide_path.unlink(missing_ok=True)
    return out_path


def extract_frames(clip_path: Path, fps: float = 1.0) -> list[Path]:
    """Splits the clip into JPEG frames at the given rate (default: 1/sec)."""
    frames_dir = clip_path.parent / "frames"
    frames_dir.mkdir(exist_ok=True)

    _run(
        [
            "ffmpeg",
            "-y",
            "-i", str(clip_path),
            "-vf", f"fps={fps}",
            "-qscale:v", "2",
            str(frames_dir / "frame_%03d.jpg"),
            "-loglevel", "error",
        ]
    )
    return sorted(frames_dir.glob("frame_*.jpg"))


def cleanup(video_id: str):
    video_dir = WORK_DIR / video_id
    if video_dir.exists():
        shutil.rmtree(video_dir)
