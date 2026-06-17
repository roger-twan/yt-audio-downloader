import uuid
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request

from config import (
    API_TOKEN,
    AUDIOBOOK_DOWNLOAD_DIR,
    MAX_WORKERS,
    SONG_DOWNLOAD_DIR,
    SONG_INBOX_DIR,
    ensure_directories,
)
from jobs import create_job, list_jobs as list_all_jobs, read_job
from media import process_song_review, run_download
from telegram import answer_telegram_callback, edit_telegram_message, send_telegram_message


app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)


def require_auth() -> tuple[dict[str, str], int] | None:
    if not API_TOKEN:
        return None

    expected = f"Bearer {API_TOKEN}"
    if request.headers.get("Authorization") == expected:
        return None

    return {"error": "Unauthorized"}, 401


@app.before_request
def check_auth():
    if request.endpoint in {"health", "telegram_callback"}:
        return None
    auth_error = require_auth()
    if auth_error:
        body, status = auth_error
        return jsonify(body), status
    return None


@app.get("/health")
def health():
    return jsonify(
        {
            "ok": True,
            "audiobook_download_dir": str(AUDIOBOOK_DOWNLOAD_DIR),
            "song_download_dir": str(SONG_DOWNLOAD_DIR),
            "song_inbox_dir": str(SONG_INBOX_DIR),
        }
    )


def enqueue_download(media_type: str):
    payload = request.get_json(silent=True) or {}
    url = payload.get("url")

    if not isinstance(url, str) or not url.strip():
        return jsonify({"error": "JSON body must include a non-empty 'url' string."}), 400

    job_id = uuid.uuid4().hex
    create_job(job_id, url=url, media_type=media_type)
    executor.submit(run_download, job_id, {**payload, "url": url.strip()}, media_type)

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


@app.post("/download/audiobook")
def download_audiobook():
    return enqueue_download("audiobook")


@app.post("/download/song")
def download_song():
    return enqueue_download("song")


@app.get("/jobs")
def list_jobs():
    return jsonify({"jobs": list_all_jobs()})


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


@app.post("/telegram/callback/<token>")
def telegram_callback(token: str):
    if not API_TOKEN or token != API_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    callback_query = payload.get("callback_query")
    if not isinstance(callback_query, dict):
        return jsonify({"ok": True, "ignored": True})

    callback_data = str(callback_query.get("data") or "")
    parts = callback_data.split(":")
    if len(parts) != 3 or parts[0] != "song":
        return jsonify({"ok": True, "ignored": True})

    _, job_id, action = parts
    if action not in {"accept", "beets", "beets_lyrics", "reject"}:
        return jsonify({"ok": True, "ignored": True})

    callback_query_id = str(callback_query.get("id") or "")
    message = callback_query.get("message") if isinstance(callback_query.get("message"), dict) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}

    result = process_song_review(job_id, action)
    if callback_query_id:
        answer_telegram_callback(callback_query_id, "Done" if result.get("ok") else "Failed")

    chat_id = chat.get("id")
    message_id = message.get("message_id")
    if chat_id and message_id:
        status_text = "completed" if result.get("ok") else f"failed: {result.get('error')}"
        edit_telegram_message(str(chat_id), int(message_id), f"Song review {action}: {status_text}")

    return jsonify(result), 200 if result.get("ok") else 400


if __name__ == "__main__":
    ensure_directories()
    app.run(host="0.0.0.0", port=8080)
