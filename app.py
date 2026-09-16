import glob
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid

from flask import Flask, jsonify, request, send_file, abort, Response

import webview
import yt_dlp

MAX_DURATION_SECONDS = 3 * 60
MAX_FILE_SIZE_BYTES = 300 * 1024 * 1024  # backstop for sites that hide duration metadata

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def resolve_ffmpeg_location():
    # Prefer a system ffmpeg on PATH; otherwise fall back to imageio-ffmpeg,
    # which downloads a static binary for the current OS/arch on first use
    # and caches it, so no manual ffmpeg install is required.
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


def make_progress_hook(job_id, expected_files):
    # A video+audio download is two separate files, and yt-dlp fires a
    # 'finished' event after EACH one, not just the last. Naively mapping
    # each file's own 0-100% onto the job's progress bar makes it visibly
    # jump backwards when the second file starts. Knowing the real file
    # count upfront (from the probe below) lets us weight each file's
    # contribution correctly, and we never let the reported percentage
    # decrease either way.
    state = {"completed_files": 0, "max_pct": 0}

    def hook(d):
        status = d.get("status")

        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes") or 0
            file_pct = (downloaded * 100 / total) if total else 0
            # Reserve the last 5% for the ffmpeg merge/convert step.
            overall = (state["completed_files"] * 100 + file_pct) / expected_files * 0.95
            pct = max(state["max_pct"], int(overall))
            state["max_pct"] = pct
            set_job(job_id, status="downloading", progress=pct)
        elif status == "finished":
            state["completed_files"] = min(state["completed_files"] + 1, expected_files)
            overall = state["completed_files"] * 100 / expected_files * 0.95
            pct = max(state["max_pct"], int(overall))
            state["max_pct"] = pct
            if state["completed_files"] >= expected_files:
                set_job(job_id, status="converting", progress=max(pct, 95))
            else:
                set_job(job_id, status="downloading", progress=pct)

    return hook


def build_format_opts(media_format, quality):
    opts = {}
    if media_format == "mp3":
        opts["format"] = "bestaudio/best"
        bitrate = quality if quality in AUDIO_BITRATES else "192"
        opts["postprocessors"] = [
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
        opts["format"] = fmt
        opts["merge_output_format"] = "mp4"
    return opts


def probe(url, media_format, quality):
    """Resolve duration + the exact formats that will be downloaded, without
    downloading anything yet."""
    probe_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "skip_download": True,
    }
    probe_opts.update(build_format_opts(media_format, quality))
    probe_opts.pop("postprocessors", None)
    if FFMPEG_LOCATION:
        probe_opts["ffmpeg_location"] = FFMPEG_LOCATION

    with yt_dlp.YoutubeDL(probe_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    requested = info.get("requested_formats")
    file_count = len(requested) if requested else 1
    return info.get("duration"), file_count


def read_file_duration(path):
    """Best-effort real duration of a downloaded file, used when the source
    site doesn't expose duration in its metadata (Instagram commonly
    doesn't). Returns None if it can't be determined."""
    try:
        import mutagen

        info = mutagen.File(path)
        return info.info.length if info else None
    except Exception:  # noqa: BLE001
        return None


def too_long_error():
    limit_min = MAX_DURATION_SECONDS // 60
    return f"This app only converts clips up to {limit_min} minutes long."


def run_job(job_id, url, media_format, quality):
    set_job(job_id, status="checking", progress=0)

    try:
        duration, file_count = probe(url, media_format, quality)
    except Exception as exc:  # noqa: BLE001
        set_job(job_id, status="error", error=f"Could not read that link: {exc}")
        return

    # Some sites (notably Instagram) don't expose duration up front. Rather
    # than blocking those links outright, we let the download proceed and
    # verify the real file afterwards (see below).
    if duration is not None and duration > MAX_DURATION_SECONDS:
        set_job(job_id, status="error", error=too_long_error())
        return

    set_job(job_id, status="downloading", progress=0)
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "progress_hooks": [make_progress_hook(job_id, file_count)],
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "socket_timeout": 30,
    }
    ydl_opts.update(build_format_opts(media_format, quality))
    if FFMPEG_LOCATION:
        ydl_opts["ffmpeg_location"] = FFMPEG_LOCATION

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "media")

        matches = glob.glob(os.path.join(DOWNLOAD_DIR, f"{job_id}.*"))
        if not matches:
            raise RuntimeError("Conversion finished but no output file was found")
        final_path = matches[0]
        ext = os.path.splitext(final_path)[1]

        if duration is None:
            actual_duration = read_file_duration(final_path)
            too_big = os.path.getsize(final_path) > MAX_FILE_SIZE_BYTES
            if (actual_duration and actual_duration > MAX_DURATION_SECONDS) or too_big:
                os.remove(final_path)
                set_job(job_id, status="error", error=too_long_error())
                return

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


def suggested_filename(job):
    title = re.sub(r"[^\w\-. ]", "_", job.get("title", "media")).strip() or "media"
    ext = job.get("ext", os.path.splitext(job.get("file_path", ""))[1])
    return f"{title}{ext}"


@app.route("/api/download/<job_id>")
def download(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        abort(404)

    file_path = job["file_path"]
    if not os.path.isfile(file_path):
        abort(404)

    response = send_file(file_path, as_attachment=True, download_name=suggested_filename(job))
    return response


class Api:
    """Exposed to the frontend as window.pywebview.api — lets the page ask
    the OS for a native Save As dialog instead of relying on the browser
    engine's own (invisible, inconsistent) download handling."""

    def save_file(self, job_id):
        with JOBS_LOCK:
            job = JOBS.get(job_id)
        if not job or job.get("status") != "done":
            return {"ok": False, "error": "That file isn't ready yet."}

        file_path = job["file_path"]
        if not os.path.isfile(file_path):
            return {"ok": False, "error": "That file is no longer available."}

        window = webview.windows[0]
        result = window.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=os.path.join(os.path.expanduser("~"), "Downloads"),
            save_filename=suggested_filename(job),
        )
        if not result:
            return {"ok": False, "cancelled": True}

        dest = result if isinstance(result, str) else result[0]
        try:
            shutil.copyfile(file_path, dest)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

        return {"ok": True, "path": dest}

    def reveal_file(self, path):
        try:
            if sys.platform == "win32":
                subprocess.run(["explorer", "/select,", path])
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", path])
            else:
                subprocess.run(["xdg-open", os.path.dirname(path)])
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}


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


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(port, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def main():
    threading.Thread(target=cleanup_loop, daemon=True).start()

    port = find_free_port()

    server_thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    server_thread.start()
    wait_for_server(port)

    webview.create_window(
        "Media Converter",
        f"http://127.0.0.1:{port}",
        width=480,
        height=700,
        resizable=True,
        min_size=(420, 620),
        js_api=Api(),
    )
    webview.start()


if __name__ == "__main__":
    main()
