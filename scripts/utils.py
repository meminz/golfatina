"""Small shared helpers used by the other scripts."""
import json
import os
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CHANNELS_FILE = DATA_DIR / "channels.json"
PROCESSED_FILE = DATA_DIR / "processed.json"
RESULTS_FILE = DATA_DIR / "results.json"

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def uploads_playlist_id(channel_id: str) -> str:
    """A channel's 'uploads' playlist ID is always its channel ID with the
    leading UC swapped for UU. This avoids an extra API call/quota unit
    per channel just to look up the uploads playlist.
    """
    if not channel_id.startswith("UC"):
        raise ValueError(f"Unexpected channel_id format: {channel_id}")
    return "UU" + channel_id[2:]


def fetch_recent_uploads(channel_id: str, max_results: int = 10):
    """Return the most recent videos for a channel via playlistItems.list.
    Cheaper on quota than search.list (1 unit vs 100 units per call).
    """
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY environment variable is not set")

    playlist_id = uploads_playlist_id(channel_id)
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/playlistItems",
        params={
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": max_results,
            "key": YOUTUBE_API_KEY,
        },
        timeout=30,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])

    videos = []
    for item in items:
        snippet = item["snippet"]
        videos.append(
            {
                "video_id": item["contentDetails"]["videoId"],
                "title": snippet["title"],
                "published_at": snippet["publishedAt"],
                "channel_title": snippet["channelTitle"],
            }
        )
    return videos
