import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from urllib import error as urlerror
from urllib import parse, request as urlrequest

from flask import Flask, jsonify, request
from yt_dlp import YoutubeDL


app = Flask(__name__)

DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/downloads")).resolve()
DEFAULT_AUDIO_FORMAT = os.getenv("DEFAULT_AUDIO_FORMAT", "mp3")
DEFAULT_AUDIO_QUALITY = os.getenv("DEFAULT_AUDIO_QUALITY", "0")
API_TOKEN = os.getenv("API_TOKEN")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))
YTDLP_PROXY = os.getenv("YTDLP_PROXY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY") or YTDLP_PROXY

executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
jobs: dict[str, dict[str, Any]] = {}
jobs_lock = Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_auth() -> tuple[dict[str, str], int] | None:
    if not API_TOKEN:
        return None

    expected = f"Bearer {API_TOKEN}"
    if request.headers.get("Authorization") == expected:
        return None

    return {"error": "Unauthorized"}, 401


def update_job(job_id: str, **changes: Any) -> None:
    with jobs_lock:
        job = jobs[job_id]
        job.update(changes)
        job["updated_at"] = utc_now()


def read_job(job_id: str) -> dict[str, Any] | None:
    with jobs_lock:
        job = jobs.get(job_id)
        return dict(job) if job else None


def sanitize_title(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', "-", value).strip(" .-")
    if not cleaned:
        return None

    return cleaned[:120]


def telegram_enabled() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def send_telegram_message(text: str) -> dict[str, Any]:
    if not telegram_enabled():
        return {"enabled": False}

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    body = parse.urlencode(
        {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")

    opener = urlrequest.build_opener()
    if TELEGRAM_PROXY:
        opener = urlrequest.build_opener(
            urlrequest.ProxyHandler(
                {
                    "http": TELEGRAM_PROXY,
                    "https": TELEGRAM_PROXY,
                }
            )
        )

    req = urlrequest.Request(api_url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with opener.open(req, timeout=15) as resp:
            return {"enabled": True, "status": resp.status}
    except urlerror.URLError as exc:
        return {"enabled": True, "error": str(exc)}


def progress_hook(job_id: str):
    def hook(event: dict[str, Any]) -> None:
        status = event.get("status")

        if status == "downloading":
            update_job(
                job_id,
                status="downloading",
                filename=event.get("filename"),
                downloaded_bytes=event.get("downloaded_bytes"),
                total_bytes=event.get("total_bytes") or event.get("total_bytes_estimate"),
                speed=event.get("speed"),
                eta=event.get("eta"),
                progress=event.get("_percent_str", "").strip(),
            )
        elif status == "finished":
            update_job(
                job_id,
                status="processing",
                filename=event.get("filename"),
                progress="100%",
            )

    return hook


def build_ydl_options(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    audio_only = bool(payload.get("audio_only", True))
    playlist = bool(payload.get("playlist", False))
    audio_format = str(payload.get("audio_format") or DEFAULT_AUDIO_FORMAT)
    audio_quality = str(payload.get("audio_quality") or DEFAULT_AUDIO_QUALITY)
    custom_title = sanitize_title(payload.get("title"))
    title_template = (
        custom_title.replace("%", "%%")
        if custom_title
        else "%(title).80B"
    )

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    options: dict[str, Any] = {
        "outtmpl": str(DOWNLOAD_DIR / f"%(artist,uploader)s - {title_template}.%(ext)s"),
        "noplaylist": not playlist,
        "restrictfilenames": False,
        "windowsfilenames": True,
        "ignoreerrors": False,
        "progress_hooks": [progress_hook(job_id)],
        "postprocessor_args": {
            "FFmpegMetadata": ["-metadata", "album=Audiobooks"],
        },
    }
    if custom_title:
        options["postprocessor_args"]["FFmpegMetadata"].extend(
            ["-metadata", f"title={custom_title}"]
        )

    proxy = payload.get("proxy") or YTDLP_PROXY
    if proxy:
        options["proxy"] = str(proxy)

    if audio_only:
        options.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": audio_format,
                        "preferredquality": audio_quality,
                    },
                    {"key": "FFmpegMetadata"},
                ],
            }
        )
    else:
        options.update(
            {
                "format": str(payload.get("format") or "bestvideo+bestaudio/best"),
                "merge_output_format": str(payload.get("merge_output_format") or "mp4"),
                "postprocessors": [{"key": "FFmpegMetadata"}],
            }
        )

    return options


def run_download(job_id: str, payload: dict[str, Any]) -> None:
    url = payload["url"]
    update_job(job_id, status="starting")

    try:
        custom_title = sanitize_title(payload.get("title"))
        options = build_ydl_options(job_id, payload)
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)

        if isinstance(info, dict):
            source_title = info.get("title")
            title = custom_title or source_title
            webpage_url = info.get("webpage_url") or url
        else:
            source_title = None
            title = custom_title
            webpage_url = url

        telegram_result = send_telegram_message(f"Audio saved: {title or webpage_url}")

        update_job(
            job_id,
            status="completed",
            title=title,
            source_title=source_title,
            url=webpage_url,
            download_dir=str(DOWNLOAD_DIR),
            telegram=telegram_result,
            completed_at=utc_now(),
            progress="100%",
        )
    except Exception as exc:
        update_job(job_id, status="failed", error=str(exc), completed_at=utc_now())


@app.before_request
def check_auth():
    if request.endpoint == "health":
        return None
    auth_error = require_auth()
    if auth_error:
        body, status = auth_error
        return jsonify(body), status
    return None


@app.get("/health")
def health():
    return jsonify({"ok": True, "download_dir": str(DOWNLOAD_DIR)})


@app.post("/download")
def download():
    payload = request.get_json(silent=True) or {}
    url = payload.get("url")

    if not isinstance(url, str) or not url.strip():
        return jsonify({"error": "JSON body must include a non-empty 'url' string."}), 400

    job_id = uuid.uuid4().hex
    now = utc_now()

    with jobs_lock:
        jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "url": url,
            "created_at": now,
            "updated_at": now,
            "audio_only": bool(payload.get("audio_only", True)),
            "title": sanitize_title(payload.get("title")),
        }

    executor.submit(run_download, job_id, {**payload, "url": url.strip()})

    return (
        jsonify(
            {
                "job_id": job_id,
                "status": "queued",
                "status_url": f"/jobs/{job_id}",
            }
        ),
        202,
    )


@app.get("/jobs")
def list_jobs():
    with jobs_lock:
        ordered_jobs = sorted(jobs.values(), key=lambda job: job["created_at"], reverse=True)
        return jsonify({"jobs": ordered_jobs})


@app.get("/jobs/<job_id>")
def get_job(job_id: str):
    job = read_job(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)


@app.post("/telegram/test")
def telegram_test():
    result = send_telegram_message("YouTube Audio Downloader Telegram notifications are working.")
    status = 200 if result.get("enabled") and not result.get("error") else 400
    return jsonify(result), status


if __name__ == "__main__":
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=8080)
