# Media Converter

A tiny, self-hosted web app: paste a link from YouTube, Twitter/X, TikTok,
Instagram, or any of the [hundreds of sites yt-dlp supports](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md),
pick MP4 or MP3, and download the converted file.

- **Runs entirely on your own machine.** It's a local Flask server bound to
  `127.0.0.1` — nothing is exposed to the network, and there's no shared
  backend or telemetry. When you convert a link, your computer talks directly
  to the source platform; nothing passes through any server the author
  controls.
- **No build step, no bundling ffmpeg binaries into the repo.** ffmpeg is
  resolved automatically at runtime (system install if you have one,
  otherwise a cached static binary via `imageio-ffmpeg`).

## Requirements

- Python 3.9+

That's it — ffmpeg is handled automatically (see above).

## Run it

**Windows:** double-click [`run.bat`](run.bat), or:

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python app.py
```

**macOS / Linux:**

```bash
./run.sh
```

or manually:

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python app.py
```

Then open http://127.0.0.1:5000

## How it works

- Frontend is a single static page (`static/`) — no framework, no build step.
- Backend (`app.py`) is a small Flask app. Each conversion runs in a
  background thread and reports progress that the page polls; the
  finished file is served from `downloads/`, which is cleaned up
  automatically after about an hour.
- All the actual extraction/conversion logic is [yt-dlp](https://github.com/yt-dlp/yt-dlp),
  which is what gives this broad site support for free.

## Legal

Only use this on content you have the right to download, and respect each
platform's terms of service and applicable copyright law. This project is a
generic front-end for yt-dlp; it doesn't circumvent DRM and only works on
publicly accessible media.

## Contributing

Issues and PRs welcome. It's intentionally small — a single Flask file and a
static frontend — so it should be easy to read end to end before changing
anything.
