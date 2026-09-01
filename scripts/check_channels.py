"""Step 1: find videos uploaded since the last run.

Prints a JSON list of new-video dicts (one per line isn't needed, just a
single JSON array) to stdout, and also writes it to new_videos.json so the
next pipeline step can pick it up. Does NOT mark anything as processed --
that only happens after a video is successfully handled, so a failure
partway through doesn't silently lose a video.
"""
import json
import sys
from pathlib import Path

from utils import CHANNELS_FILE, PROCESSED_FILE, fetch_recent_uploads, load_json

OUT_FILE = Path(__file__).resolve().parent.parent / "new_videos.json"


def title_matches(title: str, keywords):
    if not keywords:
        return True
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)


def main():
    config = load_json(CHANNELS_FILE)
    processed = load_json(PROCESSED_FILE)
    processed_ids = set(processed.get("video_ids", []))

    new_videos = []

    for channel in config.get("channels", []):
        if not channel.get("enabled", True):
            continue

        try:
            uploads = fetch_recent_uploads(channel["channel_id"])
        except Exception as exc:  # noqa: BLE001 - log and keep going per channel
            print(f"[warn] failed to fetch uploads for {channel['name']}: {exc}", file=sys.stderr)
            continue

        for video in uploads:
            if video["video_id"] in processed_ids:
                continue
            if not title_matches(video["title"], channel.get("title_keywords")):
                continue

            video["channel_name"] = channel["name"]
            video["scoreboard_crop"] = channel["scoreboard_crop"]
            video["clip_seconds_from_end"] = channel.get("clip_seconds_from_end", 25)
            video["url"] = f"https://www.youtube.com/watch?v={video['video_id']}"
            new_videos.append(video)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(new_videos, f, indent=2)

    print(f"Found {len(new_videos)} new video(s).")
    for v in new_videos:
        print(f"  - [{v['channel_name']}] {v['title']} ({v['video_id']})")


if __name__ == "__main__":
    main()
