"""Entry point: for every new video found by check_channels.py, download the
tail clip, extract frames, OCR the scoreboard, and append to results.json.
Marks each video as processed only after it's fully handled, so a crash
partway through just means it gets retried tomorrow instead of being lost.
"""
import datetime
import json
import sys
from pathlib import Path

from extract_results import extract_from_frames
from utils import PROCESSED_FILE, RESULTS_FILE, load_json, save_json
from video_pipeline import cleanup, download_tail_clip, extract_frames

NEW_VIDEOS_FILE = Path(__file__).resolve().parent.parent / "new_videos.json"


def main():
    if not NEW_VIDEOS_FILE.exists():
        print("No new_videos.json found -- run check_channels.py first.")
        return

    with open(NEW_VIDEOS_FILE, "r", encoding="utf-8") as f:
        new_videos = json.load(f)

    if not new_videos:
        print("No new videos to process.")
        return

    processed = load_json(PROCESSED_FILE)
    results = load_json(RESULTS_FILE)

    for video in new_videos:
        video_id = video["video_id"]
        print(f"Processing {video_id} -- {video['title']}")

        try:
            window = video["clip_window"]
            clip_path = download_tail_clip(
                video_id, window["start_seconds_from_end"], window["end_seconds_from_end"]
            )
            frames = extract_frames(clip_path, fps=1.0)
            if not frames:
                raise RuntimeError("no frames extracted")

            extraction = extract_from_frames(frames, video["scoreboard_crop"])

            results["results"].append(
                {
                    "video_id": video_id,
                    "channel": video["channel_name"],
                    "title": video["title"],
                    "url": video["url"],
                    "published_at": video["published_at"],
                    "processed_at": datetime.datetime.utcnow().isoformat() + "Z",
                    "map_name": extraction["map_name"],
                    "participants": extraction["participants"],
                    "extraction_method": extraction["extraction_method"],
                }
            )

            if extraction["extraction_method"] == "manual_review_needed":
                print(f"  [!] Could not auto-extract results for {video_id}; flagged for manual review.")
            else:
                print(f"  OK via {extraction['extraction_method']}")

        except Exception as exc:  # noqa: BLE001 -- keep processing remaining videos
            print(f"  [error] failed to process {video_id}: {exc}", file=sys.stderr)
            continue  # do NOT mark as processed -- retry next run

        finally:
            cleanup(video_id)

        processed["video_ids"].append(video_id)

    save_json(PROCESSED_FILE, processed)
    save_json(RESULTS_FILE, results)
    NEW_VIDEOS_FILE.unlink(missing_ok=True)
    print("Done.")


if __name__ == "__main__":
    main()
