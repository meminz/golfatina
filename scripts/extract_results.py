"""Step 3: turn a candidate end-game frame into structured results.

Splits the scoreboard into three narrow sub-crops (map name, names column,
totals column) and OCRs each separately -- OCR-ing the whole multi-column
table at once causes Tesseract to scramble which number belongs to which
row/column. If the names/totals row counts don't line up, or a frame
produces nothing usable, falls back to Gemini's free-tier vision API
(requires GEMINI_API_KEY) for that one frame. If that's unavailable too,
the video is flagged manual_review_needed instead of guessing.
"""
import base64
import json
import os
import re
from pathlib import Path

import pytesseract
import requests
from PIL import Image, ImageOps

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.0-flash"

# The in-game scoreboard's internal layout is identical across all channels
# since it's the same game UI -- only scoreboard_crop (where the board sits
# in each streamer's frame) varies per channel, and lives in channels.json.
SCOREBOARD_LAYOUT = {
    "map_name": {"x": 0.28, "y": 0.115, "w": 0.44, "h": 0.05},
    "names":    {"x": 0.075, "y": 0.335, "w": 0.165, "h": 0.56},
    "totals":   {"x": 0.885, "y": 0.335, "w": 0.07, "h": 0.56},
}


def crop_to_scoreboard(image_path: Path, crop: dict) -> Image.Image:
    """Outer crop: isolates the whole scoreboard from the full video frame."""
    img = Image.open(image_path)
    w, h = img.size
    box = (
        int(crop["x"] * w),
        int(crop["y"] * h),
        int((crop["x"] + crop["w"]) * w),
        int((crop["y"] + crop["h"]) * h),
    )
    return img.crop(box)


def crop_subregion(image: Image.Image, region: dict) -> Image.Image:
    """Inner crop: isolates one column/line out of an already-cropped
    scoreboard image. `region` fractions are relative to `image`'s own
    width/height, NOT the full frame.
    """
    w, h = image.size
    box = (
        int(region["x"] * w),
        int(region["y"] * h),
        int((region["x"] + region["w"]) * w),
        int((region["y"] + region["h"]) * h),
    )
    return image.crop(box)


def _upscale(image: Image.Image, target_w: int = 800) -> Image.Image:
    if image.width < target_w:
        scale = target_w / image.width
        image = image.resize((int(image.width * scale), int(image.height * scale)), Image.LANCZOS)
    return image


def _clean_lines(text: str, min_letters: int = 3) -> list[str]:
    """Drops empty lines and stray artifacts. Requires a lowercase letter
    so all-caps junk lines (leftover borders OCR'd as garbage) get filtered
    out, since real usernames in this UI are mixed/lower case.
    """
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        has_lower = bool(re.search(r"[a-z]", line))
        letter_count = len(re.findall(r"[A-Za-z]", line))
        if has_lower and letter_count >= min_letters:
            lines.append(line)
    return lines


def ocr_map_name(image: Image.Image) -> str:
    text = pytesseract.image_to_string(_upscale(image), config="--psm 7")
    return text.strip()


def ocr_names(image: Image.Image) -> list[str]:
    text = pytesseract.image_to_string(_upscale(image), config="--psm 6")
    return _clean_lines(text)


def ocr_totals(image: Image.Image) -> list[str]:
    """Grayscale + threshold binarization measurably improves digit
    recognition on bold/stylized game fonts vs raw color input."""
    gray = ImageOps.grayscale(_upscale(image))
    bw = gray.point(lambda p: 255 if p > 150 else 0)
    text = pytesseract.image_to_string(
        bw, config="--psm 6 -c tessedit_char_whitelist=0123456789"
    )
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def ocr_gemini_fallback(image_path: Path) -> dict | None:
    """Sends the full (uncropped) frame to Gemini's free-tier API and asks
    for structured JSON directly. Used when Tesseract's column reads don't
    line up cleanly. Requires GEMINI_API_KEY; skipped otherwise.
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
        "Use each player's FINAL TOTAL score only, not per-hole scores. "
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
    """Tries each candidate frame (last frames first), OCRs the three
    sub-regions using the hardcoded SCOREBOARD_LAYOUT, and returns the first
    attempt where names/totals line up. Falls back to Gemini per-frame,
    then to manual_review_needed.
    """
    for frame_path in reversed(frame_paths):
        outer = crop_to_scoreboard(frame_path, crop)

        map_name = ocr_map_name(crop_subregion(outer, SCOREBOARD_LAYOUT["map_name"])) or None
        names = ocr_names(crop_subregion(outer, SCOREBOARD_LAYOUT["names"]))
        totals = ocr_totals(crop_subregion(outer, SCOREBOARD_LAYOUT["totals"]))

        if names and totals and len(names) == len(totals):
            return {
                "extraction_method": "tesseract",
                "frame": frame_path.name,
                "map_name": map_name,
                "participants": [{"name": n, "score": s} for n, s in zip(names, totals)],
            }

        gemini_result = ocr_gemini_fallback(frame_path)
        if gemini_result:
            return {
                "extraction_method": "gemini",
                "frame": frame_path.name,
                "map_name": gemini_result.get("map_name"),
                "participants": gemini_result.get("participants", []),
            }

    return {
        "extraction_method": "manual_review_needed",
        "frame": None,
        "map_name": None,
        "participants": [],
    }
