"""Backfill: pull OLDER videos (not just the newest ones) into new_videos.json
so main.py can process them, same as it does for daily new uploads.

Run this LOCALLY rather than via GitHub Actions -- see the note in README
about YouTube sometimes blocking yt-dlp from data-center IPs, which is far
more likely to bite you across a big backfill batch than a single daily video.

Usage:
    cd scripts
    python backfill.py --since 2024-01-01
    python backfill.py --channel "Example Golf Channel" --limit 20
"""
import argparse
import json
from pathlib import Path

from utils import CHANNELS_FILE, PROCESSED_FILE, fetch_all_uploads, load_json

OUT_FILE = Path(__file__).resolve().parent.parent / "new_videos.json"


def title_matches(title: str, keywords):
    if not keywords:
        return True
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", help="Only backfill this channel (matches 'name' in channels.json)")
    parser.add_argument("--since", help="Only include videos published on/after this date, e.g. 2024-01-01")
    parser.add_argument("--limit", type=int, help="Max videos to pull per channel")
    args = parser.parse_args()

    config = load_json(CHANNELS_FILE)
    processed = load_json(PROCESSED_FILE)
    processed_ids = set(processed.get("video_ids", []))

    # Merge with any already-queued videos rather than overwriting, in case
    # you run backfill more than once before running main.py.
    queued = []
    if OUT_FILE.exists():
        with open(OUT_FILE, "r", encoding="utf-8") as f:
            queued = json.load(f)
    queued_ids = {v["video_id"] for v in queued}

    since_iso = f"{args.since}T00:00:00Z" if args.since else None

    for channel in config.get("channels", []):
        if not channel.get("enabled", True):
            continue
        if args.channel and channel["name"] != args.channel:
            continue

        print(f"Fetching upload history for {channel['name']} ...")
        uploads = fetch_all_uploads(channel["channel_id"], since=since_iso, max_videos=args.limit)
        print(f"  found {len(uploads)} video(s) in range")

        added = 0
        for video in uploads:
            if video["video_id"] in processed_ids or video["video_id"] in queued_ids:
                continue
            if not title_matches(video["title"], channel.get("title_keywords")):
                continue

            video["channel_name"] = channel["name"]
            video["scoreboard_crop"] = channel["scoreboard_crop"]
            video["clip_window"] = channel.get(
                "clip_window", {"start_seconds_from_end": 27, "end_seconds_from_end": 20}
            )
            video["url"] = f"https://www.youtube.com/watch?v={video['video_id']}"

            queued.append(video)
            queued_ids.add(video["video_id"])
            added += 1

        print(f"  queued {added} new video(s)")

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(queued, f, indent=2)

    print(f"\n{len(queued)} video(s) total queued in new_videos.json.")
    print("Run `python main.py` to process them (this can take a while for a large batch).")


if __name__ == "__main__":
    main()
