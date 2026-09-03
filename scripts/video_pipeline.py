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

def _attempt_download(url, section, out_template, use_android_client, use_cookies):
    """One yt-dlp attempt. Android client spoofing bypasses the JS-challenge
    that specifically trips up the default web client on cloud/server IPs --
    try it cookie-free first, since supplying cookies makes yt-dlp fall back
    to the (blockable) authenticated web client instead."""
    cmd = ["yt-dlp"]
    if use_android_client:
        cmd += ["--extractor-args", "youtube:player_client=android"]
    elif use_cookies:
        cmd += _cookie_args()
    cmd += [
        "--download-sections", section,
        "-f", "bestvideo[height<=1080][ext=mp4]/bestvideo[height<=1080]/best[height<=1080]",
        "-o", out_template,
        "--force-keyframes-at-cuts",
        "--quiet",
        "--no-warnings",
        url,
    ]
    _run(cmd)


def download_tail_clip(video_id: str, start_seconds_from_end: int, end_seconds_from_end: int) -> Path:
    """Downloads only a WINDOW near the end of the video, video-only (no
    audio needed -- we only extract still frames). Tries, in order:
      1. Windowed download, Android client spoof (no cookies) -- avoids the
         JS-challenge that blocks the default web client on cloud IPs.
      2. Windowed download, cookies (if YTDLP_COOKIES_FILE is set).
      3. Wide tail download + local ffmpeg trim, cookies -- last resort.
    """
    if end_seconds_from_end >= start_seconds_from_end:
        raise ValueError("end_seconds_from_end must be smaller than start_seconds_from_end")

    video_dir = WORK_DIR / video_id
    video_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://www.youtube.com/watch?v={video_id}"
    window_section = f"*-{start_seconds_from_end}--{end_seconds_from_end}"
    out_template = str(video_dir / "clip.%(ext)s")

    def _find_clip() -> Path:
        matches = list(video_dir.glob("clip.*"))
        if not matches:
            raise RuntimeError("yt-dlp reported success but no clip file was found")
        return matches[0]

    # Attempt 1: windowed + Android client
    try:
        _attempt_download(url, window_section, out_template, use_android_client=True, use_cookies=False)
        return _find_clip()
    except RuntimeError as exc:
        print(f"[warn] Android-client windowed download failed ({exc}); trying cookies")

    # Attempt 2: windowed + cookies
    try:
        _attempt_download(url, window_section, out_template, use_android_client=False, use_cookies=True)
        return _find_clip()
    except RuntimeError as exc:
        print(f"[warn] cookie-based windowed download failed ({exc}); falling back to wide tail + trim")

    # Attempt 3: wide tail + local trim
    tail_section = f"*-{start_seconds_from_end}-0"
    wide_template = str(video_dir / "clip_wide.%(ext)s")
    _attempt_download(url, tail_section, wide_template, use_android_client=True, use_cookies=False)

    wide_matches = list(video_dir.glob("clip_wide.*"))
    if not wide_matches:
        raise RuntimeError("all download attempts failed")
    wide_path = wide_matches[0]

    trimmed_path = video_dir / f"trimmed{wide_path.suffix}"
    window_duration = start_seconds_from_end - end_seconds_from_end
    _run(
        [
            "ffmpeg", "-y",
            "-i", str(wide_path),
            "-ss", "0", "-t", str(window_duration),
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
