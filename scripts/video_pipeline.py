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


def download_tail_clip(video_id: str, seconds_from_end: int) -> Path:
    """Downloads only the last `seconds_from_end` seconds of the video using
    yt-dlp's --download-sections, so we never pull a full-length video.
    """
    video_dir = WORK_DIR / video_id
    video_dir.mkdir(parents=True, exist_ok=True)
    out_path = video_dir / "clip.mp4"

    url = f"https://www.youtube.com/watch?v={video_id}"
    # yt-dlp section syntax: "*START-END". A negative start counts back from
    # the end of the video, "0" as the end means "to the very end".
    section = f"*-{seconds_from_end}-0"

    _run(
        [
            "yt-dlp",
            "--download-sections", section,
            "-f", "mp4[height<=720]/mp4",
            "-o", str(out_path),
            "--force-keyframes-at-cuts",
            "--quiet",
            "--no-warnings",
            url,
        ]
    )
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
