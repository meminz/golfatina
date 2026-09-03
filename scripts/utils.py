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


def fetch_all_uploads(channel_id: str, since=None, max_videos=None):
    """Paginates through a channel's ENTIRE uploads playlist (oldest videos
    require walking through pageToken pages -- the API has no 'jump to date'
    option). Use for backfilling; for the daily check, fetch_recent_uploads
    is cheaper since it only looks at the first page.

    since: an ISO date string (e.g. "2024-01-01") -- stop once we hit videos
           published before this date (uploads playlist is newest-first).
    max_videos: stop after collecting this many videos, regardless of date.
    """
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY environment variable is not set")

    playlist_id = uploads_playlist_id(channel_id)
    videos = []
    page_token = None

    while True:
        params = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,  # API max per page
            "key": YOUTUBE_API_KEY,
        }
        if page_token:
            params["pageToken"] = page_token

        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()

        stop = False
        for item in payload.get("items", []):
            snippet = item["snippet"]
            published_at = snippet["publishedAt"]

            if since and published_at < since:
                stop = True
                break

            videos.append(
                {
                    "video_id": item["contentDetails"]["videoId"],
                    "title": snippet["title"],
                    "published_at": published_at,
                    "channel_title": snippet["channelTitle"],
                }
            )

            if max_videos and len(videos) >= max_videos:
                stop = True
                break

        page_token = payload.get("nextPageToken")
        if stop or not page_token:
            break

    return videos


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
