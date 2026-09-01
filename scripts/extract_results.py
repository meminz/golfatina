"""Step 3: turn a candidate end-game frame into structured results.

Primary path: crop to the channel's configured scoreboard region and run
Tesseract (free, local, no API). If that produces something too sparse to
be a real scoreboard, and a GEMINI_API_KEY secret is set, fall back to
Gemini's free-tier vision model for that one frame. If neither works, the
video is flagged for manual review instead of silently producing junk data.
"""
import base64
import json
import os
import re
from pathlib import Path

import pytesseract
import requests
from PIL import Image

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.0-flash"


def crop_to_scoreboard(image_path: Path, crop: dict) -> Image.Image:
    img = Image.open(image_path)
    w, h = img.size
    box = (
        int(crop["x"] * w),
        int(crop["y"] * h),
        int((crop["x"] + crop["w"]) * w),
        int((crop["y"] + crop["h"]) * h),
    )
    return img.crop(box)


def ocr_tesseract(image: Image.Image) -> str:
    # Upscaling small crops helps Tesseract a lot with stylized game fonts.
    if image.width < 1000:
        scale = 1000 / image.width
        image = image.resize((int(image.width * scale), int(image.height * scale)))
    return pytesseract.image_to_string(image)


def looks_like_scoreboard(text: str) -> bool:
    """Very rough sanity check: a real scoreboard capture should have a few
    lines of non-trivial text. Tune this per-game if you get false positives.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return len(lines) >= 3 and sum(len(ln) for ln in lines) > 20


def ocr_gemini_fallback(image_path: Path) -> dict | None:
    """Sends the *uncropped* frame to Gemini's free-tier API and asks it to
    return structured JSON directly. Only used when Tesseract's result looks
    too sparse to trust. Requires a GEMINI_API_KEY secret; skipped otherwise.
    """
    if not GEMINI_API_KEY:
        return None

    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = (
        "This is a screenshot from a golf video game, possibly showing an "
        "end-of-round scoreboard. If it IS a scoreboard, respond with ONLY "
        "raw JSON (no markdown fences) in this shape: "
        '{"is_scoreboard": true, "map_name": "...", '
        '"participants": [{"name": "...", "score": "..."}]}. '
        'If it is NOT a scoreboard, respond with ONLY {"is_scoreboard": false}.'
    )

    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        params={"key": GEMINI_API_KEY},
        json={
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                    ]
                }
            ]
        },
        timeout=30,
    )
    resp.raise_for_status()
    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    text = re.sub(r"^```json|```$", "", text.strip(), flags=re.MULTILINE).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not parsed.get("is_scoreboard"):
        return None
    return parsed


def extract_from_frames(frame_paths: list[Path], crop: dict) -> dict:
    """Tries each candidate frame (usually the last few seconds of the clip,
    newest first) and returns the first successful structured extraction.
    """
    for frame_path in reversed(frame_paths):  # last frames first
        cropped = crop_to_scoreboard(frame_path, crop)
        raw_text = ocr_tesseract(cropped)

        if looks_like_scoreboard(raw_text):
            return {
                "extraction_method": "tesseract",
                "raw_text": raw_text,
                "frame": frame_path.name,
                # Parsing raw_text into map/participants is game-specific --
                # see parse_scoreboard_text() below for the customization point.
                **parse_scoreboard_text(raw_text),
            }

        gemini_result = ocr_gemini_fallback(frame_path)
        if gemini_result:
            return {
                "extraction_method": "gemini",
                "raw_text": raw_text,
                "frame": frame_path.name,
                "map_name": gemini_result.get("map_name"),
                "participants": gemini_result.get("participants", []),
            }

    return {
        "extraction_method": "manual_review_needed",
        "raw_text": None,
        "frame": None,
        "map_name": None,
        "participants": [],
    }


def parse_scoreboard_text(raw_text: str) -> dict:
    """Best-effort, GAME-SPECIFIC parsing of raw OCR text into structured
    fields. This is the piece you'll want to tune once you see real OCR
    output from your channels -- current logic is a generic placeholder:
    - first line containing "map" or similar is treated as the map name
    - remaining lines matching "Name ... number" are treated as a
      participant + score pair
    """
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]

    map_name = None
    participants = []

    score_line = re.compile(r"^(?P<name>[A-Za-z0-9_\-\. ]{2,20}?)\s+(?P<score>-?\d{1,3})$")

    for line in lines:
        if map_name is None and re.search(r"\bmap\b|\bcourse\b|\bhole\b", line, re.IGNORECASE):
            map_name = line
            continue

        match = score_line.match(line)
        if match:
            participants.append(
                {"name": match.group("name").strip(), "score": match.group("score")}
            )

    return {"map_name": map_name, "participants": participants}
