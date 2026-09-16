import glob
import os
import re
import threading
import time
import uuid

from flask import Flask, jsonify, request, send_file, abort, Response

import yt_dlp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def resolve_ffmpeg_location():
    # Prefer a system ffmpeg on PATH; otherwise fall back to imageio-ffmpeg,
    # which downloads a static binary for the current OS/arch on first use
    # and caches it, so no manual ffmpeg install is required.
    import shutil

    if shutil.which("ffmpeg"):
        return None  # yt-dlp will find it on PATH itself

    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


FFMPEG_LOCATION = resolve_ffmpeg_location()

app = Flask(__name__, static_folder="static", static_url_path="/static")

JOBS = {}
JOBS_LOCK = threading.Lock()

URL_RE = re.compile(r"^https?://", re.IGNORECASE)

VIDEO_HEIGHT_LIMITS = {
    "best": None,
    "1080": 1080,
    "720": 720,
    "480": 480,
}

AUDIO_BITRATES = {"320", "192", "128"}


def set_job(job_id, **fields):
    with JOBS_LOCK:
        JOBS[job_id].update(fields)


def make_progress_hook(job_id):
    def hook(d):
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes") or 0
            pct = int(downloaded * 100 / total) if total else None
            set_job(
                job_id,
                status="downloading",
                progress=pct if pct is not None else JOBS.get(job_id, {}).get("progress", 0),
            )
        elif status == "finished":
            set_job(job_id, status="converting", progress=95)

    return hook


def run_job(job_id, url, media_format, quality):
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "progress_hooks": [make_progress_hook(job_id)],
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "socket_timeout": 30,
    }
    if FFMPEG_LOCATION:
        ydl_opts["ffmpeg_location"] = FFMPEG_LOCATION

    if media_format == "mp3":
        ydl_opts["format"] = "bestaudio/best"
        bitrate = quality if quality in AUDIO_BITRATES else "192"
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": bitrate,
            }
        ]
    else:
        height = VIDEO_HEIGHT_LIMITS.get(quality, None)
        if height:
            fmt = f"bv*[ext=mp4][height<={height}]+ba[ext=m4a]/b[height<={height}]/bv*+ba/b"
        else:
            fmt = "bv*[ext=mp4]+ba[ext=m4a]/b/bv*+ba/b"
        ydl_opts["format"] = fmt
        ydl_opts["merge_output_format"] = "mp4"

    try:
        set_job(job_id, status="downloading", progress=0)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "media")

        matches = glob.glob(os.path.join(DOWNLOAD_DIR, f"{job_id}.*"))
        if not matches:
            raise RuntimeError("Conversion finished but no output file was found")
        final_path = matches[0]
        ext = os.path.splitext(final_path)[1]

        set_job(
            job_id,
            status="done",
            progress=100,
            file_path=final_path,
            title=title,
            ext=ext,
        )
    except Exception as exc:  # noqa: BLE001
        set_job(job_id, status="error", error=str(exc))


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/convert", methods=["POST"])
def convert():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    media_format = data.get("format", "mp4")
    quality = str(data.get("quality", "best"))

    if not url or not URL_RE.match(url):
        return jsonify({"error": "Please provide a valid http(s) URL"}), 400
    if media_format not in ("mp4", "mp3"):
        return jsonify({"error": "format must be mp4 or mp3"}), 400

    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "queued", "progress": 0, "created": time.time()}

    thread = threading.Thread(target=run_job, args=(job_id, url, media_format, quality), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "unknown job"}), 404
    safe = {k: v for k, v in job.items() if k != "file_path"}
    return jsonify(safe)


@app.route("/api/download/<job_id>")
def download(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        abort(404)

    file_path = job["file_path"]
    if not os.path.isfile(file_path):
        abort(404)

    title = re.sub(r"[^\w\-. ]", "_", job.get("title", "media")).strip() or "media"
    ext = job.get("ext", os.path.splitext(file_path)[1])
    download_name = f"{title}{ext}"

    response = send_file(file_path, as_attachment=True, download_name=download_name)
    return response


def cleanup_loop():
    while True:
        time.sleep(600)
        cutoff = time.time() - 3600
        with JOBS_LOCK:
            stale_ids = [
                jid for jid, job in JOBS.items()
                if job.get("status") in ("done", "error") and job.get("created", cutoff) < cutoff
            ]
        for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
            try:
                if os.path.getmtime(f) < cutoff:
                    os.remove(f)
            except OSError:
                pass
        with JOBS_LOCK:
            for jid in stale_ids:
                JOBS.pop(jid, None)


if __name__ == "__main__":
    threading.Thread(target=cleanup_loop, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
