# Media Converter

A tiny desktop app: paste a link from YouTube, Twitter/X, TikTok, Instagram,
or any of the [hundreds of sites yt-dlp supports](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md),
pick MP4 or MP3, and get the converted file. Clips up to 3 minutes long.

- **It's an app, not a website.** Running it opens a native app window
  (via [pywebview](https://pywebview.flowrl.com/)) — no browser tab, no
  address bar, no terminal to watch. Just a window with a Convert button.
- **Runs entirely on your own machine.** Under the hood there's a small local
  server bound to `127.0.0.1`, invisible to the network, with no shared
  backend or telemetry anywhere. When you convert a link, your computer talks
  directly to the source platform.
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

An app window opens automatically — that's it.

## How it works

- Frontend is a single static page (`static/`) — no framework, no build step.
- Backend (`app.py`) is a small Flask app that only ever listens on
  `127.0.0.1`, on a random free port. On launch, `pywebview` opens a native
  window pointed at that local server, so the whole thing feels and behaves
  like a normal desktop app rather than something you browse to.
- Each conversion runs in a background thread: a quick metadata probe checks
  the clip's length (rejecting anything over 3 minutes before any bytes are
  downloaded), then the real download/conversion runs and reports progress
  that the window polls. The finished file is served from `downloads/`,
  which is cleaned up automatically after about an hour.
- All the actual extraction/conversion logic is [yt-dlp](https://github.com/yt-dlp/yt-dlp),
  which is what gives this broad site support for free.

## Legal

Only use this on content you have the right to download, and respect each
platform's terms of service and applicable copyright law. This project is a
generic front-end for yt-dlp; it doesn't circumvent DRM and only works on
publicly accessible media. The 3-minute limit is meant to keep this a tool
for short clips, not a way to pull down full videos.

## Contributing

Issues and PRs welcome. It's intentionally small — a single Flask file and a
static frontend — so it should be easy to read end to end before changing
anything.
