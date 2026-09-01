# Golf Round Results

Automatically watches YouTube channels for new golf-game videos, reads the
end-of-round scoreboard off the video, and publishes results to a static
site — all on GitHub's free tier (Actions + Pages).

## How it works

1. **GitHub Actions runs daily** (`.github/workflows/check-videos.yml`,
   `workflow_dispatch` also lets you trigger it manually from the Actions tab).
2. `scripts/check_channels.py` asks the YouTube Data API for each channel's
   latest uploads and diffs against `data/processed.json`.
3. `scripts/main.py` downloads only the **last N seconds** of each new video
   (via `yt-dlp --download-sections`), pulls a few frames with `ffmpeg`, crops
   to the scoreboard region, and OCRs it with **Tesseract** (free, local).
4. If Tesseract's result looks too sparse to trust, and `GEMINI_API_KEY` is
   set, it falls back to Gemini's free-tier vision API for that one frame.
   If both fail, the video is recorded with `extraction_method:
   "manual_review_needed"` so you can fix it by hand instead of it silently
   producing wrong data.
5. Results are appended to `data/results.json`, committed back to the repo.
6. `site/` is a static page (no build step) that reads `data/results.json`
   and renders the leaderboard. Serve it with GitHub Pages.

## One-time setup

### 1. Get a YouTube Data API key (free)
- Go to the [Google Cloud Console](https://console.cloud.google.com/), create
  a project, enable **YouTube Data API v3**, create an API key.
- The free daily quota (10,000 units) is enough for many channels checked
  daily — this pipeline uses `playlistItems.list`, which only costs 1 unit
  per call.

### 2. (Optional) Get a Gemini API key (free tier)
- From [Google AI Studio](https://aistudio.google.com/) — used only as a
  fallback when Tesseract can't read a frame.

### 3. Add repo secrets
In your GitHub repo: **Settings → Secrets and variables → Actions**, add:
- `YOUTUBE_API_KEY` (required)
- `GEMINI_API_KEY` (optional, enables the fallback)

### 4. Configure channels
Edit `data/channels.json`:
- `channel_id`: starts with `UC…`. Easiest way to find it: open the
  channel's page, view source, search for `"channelId"`.
- `enabled`: set `true` once configured.
- `title_keywords`: skip videos whose title doesn't match (leave empty to
  process everything on the channel).
- `scoreboard_crop`: the box around the scoreboard, as **fractions of frame
  width/height** (0–1), e.g. `{"x": 0.15, "y": 0.1, "w": 0.7, "h": 0.55}`.
  See below for how to figure this out.
- `clip_seconds_from_end`: how many seconds of the video's tail to download.
  Should comfortably cover when the scoreboard appears after the round ends.

### 5. Find the right crop region per channel
Grab a sample end-game frame locally to eyeball the coordinates:
```bash
yt-dlp --download-sections "*-30-0" -f "mp4[height<=720]" -o clip.mp4 "VIDEO_URL"
ffmpeg -i clip.mp4 -vf fps=1 frame_%03d.jpg
```
Open a frame that shows the scoreboard, note the box around it as a fraction
of the image width/height, and put those numbers in `scoreboard_crop`.

### 6. Enable GitHub Pages
**Settings → Pages → Source: deploy from branch → root**. Your site will be
at `https://<you>.github.io/<repo>/site/index.html`.

### 7. Run it
Push to GitHub, then trigger the workflow manually once (Actions tab →
"Check channels for new golf videos" → Run workflow) to confirm everything
works before waiting for the daily schedule.

## Tuning the scoreboard parser

`scripts/extract_results.py`'s `parse_scoreboard_text()` is a generic
placeholder — it guesses at map names and "Name  Score" lines. Once you see
real OCR output from your channels, you'll likely want to tighten this regex
to match your game's actual scoreboard format. Videos that don't parse
cleanly still get recorded (flagged `manual_review_needed`) so you never
lose track of them — you can patch `data/results.json` by hand for those.

## Notes on downloading YouTube videos

This uses `yt-dlp`, a standard open-source tool, to download just the tail
clip needed for OCR (nothing is redistributed or re-uploaded). Automated
downloading sits in a gray area of YouTube's Terms of Service even for tools
like this — fine for a personal/fan project like this one, but worth keeping
in mind if this ever grows beyond that.
