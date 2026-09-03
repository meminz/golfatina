"""Downloads the tail end of a video and extracts candidate frames."""
import os
import shutil
import subprocess
from pathlib import Path

WORK_DIR = Path(__file__).resolve().parent.parent / "work"
COOKIES_FILE = os.environ.get("YTDLP_COOKIES_FILE")


def _cookie_args():
    if COOKIES_FILE and Path(COOKIES_FILE).exists():
        return ["--cookies", COOKIES_FILE]
    return []


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout


def download_tail_clip(video_id: str, start_seconds_from_end: int, end_seconds_from_end: int) -> Path:
    """Downloads only a WINDOW near the end of the video -- video-only (no
    audio track needed, we only extract still frames). Tries yt-dlp's
    two-sided negative section syntax first; falls back to downloading the
    wider tail and trimming locally with ffmpeg if that fails.
    """
    if end_seconds_from_end >= start_seconds_from_end:
        raise ValueError("end_seconds_from_end must be smaller than start_seconds_from_end")

    video_dir = WORK_DIR / video_id
    video_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://www.youtube.com/watch?v={video_id}"

    video_format = (
        "bestvideo[height<=1080][ext=mp4]/"
        "bestvideo[height<=1080]/"
        "best[height<=1080]"
    )
    window_section = f"*-{start_seconds_from_end}--{end_seconds_from_end}"
    out_template = str(video_dir / "clip.%(ext)s")

    def _find_clip() -> Path:
        matches = list(video_dir.glob("clip.*"))
        if not matches:
            raise RuntimeError("yt-dlp reported success but no clip file was found")
        return matches[0]

    try:
        _run(
            [
                "yt-dlp",
                *_cookie_args(),
                "--download-sections", window_section,
                "-f", video_format,
                "-o", out_template,
                "--force-keyframes-at-cuts",
                "--quiet",
                "--no-warnings",
                url,
            ]
        )
        return _find_clip()
    except RuntimeError as exc:
        print(f"[warn] windowed download failed ({exc}); falling back to tail download + ffmpeg trim")

    tail_section = f"*-{start_seconds_from_end}-0"
    _run(
        [
            "yt-dlp",
            *_cookie_args(),
            "--download-sections", tail_section,
            "-f", video_format,
            "-o", out_template,
            "--force-keyframes-at-cuts",
            "--quiet",
            "--no-warnings",
            url,
        ]
    )
    wide_path = _find_clip()
    trimmed_path = video_dir / f"trimmed{wide_path.suffix}"
    window_duration = start_seconds_from_end - end_seconds_from_end

    _run(
        [
            "ffmpeg",
            "-y",
            "-i", str(wide_path),
            "-ss", "0",
            "-t", str(window_duration),
            "-c", "copy",
            str(trimmed_path),
            "-loglevel", "error",
        ]
    )
    wide_path.unlink(missing_ok=True)
    return trimmed_path


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
