import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL

from config import (
    AUDIOBOOK_DOWNLOAD_DIR,
    BEETS_COMMAND,
    DEFAULT_AUDIO_FORMAT,
    DEFAULT_AUDIO_QUALITY,
    LRCGET_COMMAND,
    SONG_DOWNLOAD_DIR,
    SONG_INBOX_DIR,
    SONG_QUALITY,
    YTDLP_PROXY,
)
from jobs import read_job, update_job, utc_now
from telegram import send_telegram_message


def sanitize_subfolder(value: str | None) -> str | None:
    if not value:
        return None

    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "-", value).strip(" .-/")
    return cleaned or None


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


def build_ydl_options(job_id: str, payload: dict[str, Any], media_type: str) -> dict[str, Any]:
    playlist = bool(payload.get("playlist", False))
    subfolder = sanitize_subfolder(payload.get("subfolder"))

    if media_type == "song":
        target_dir = SONG_INBOX_DIR / subfolder if subfolder else SONG_INBOX_DIR
    else:
        target_dir = AUDIOBOOK_DOWNLOAD_DIR / subfolder if subfolder else AUDIOBOOK_DOWNLOAD_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    options: dict[str, Any] = {
        "outtmpl": str(target_dir / "%(artist,uploader|Unknown Artist).20B - %(title).80B.%(ext)s"),
        "noplaylist": not playlist,
        "restrictfilenames": False,
        "windowsfilenames": True,
        "ignoreerrors": False,
        "progress_hooks": [progress_hook(job_id)],
    }

    proxy = payload.get("proxy") or YTDLP_PROXY
    if proxy:
        options["proxy"] = str(proxy)

    if media_type == "song":
        song_quality = str(payload.get("song_quality") or SONG_QUALITY)
        options.update(audio_options(DEFAULT_AUDIO_FORMAT, song_quality))
    else:
        audio_format = str(payload.get("audio_format") or DEFAULT_AUDIO_FORMAT)
        audio_quality = str(payload.get("audio_quality") or DEFAULT_AUDIO_QUALITY)
        options.update(audio_options(audio_format, audio_quality))

    return options


def audio_options(audio_format: str, audio_quality: str) -> dict[str, Any]:
    return {
        "format": "bestaudio/best",
        "writethumbnail": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": audio_quality,
            },
            {"key": "FFmpegMetadata"},
            {"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
            {"key": "EmbedThumbnail"},
        ],
    }


def expected_audio_format(payload: dict[str, Any], media_type: str) -> str:
    if media_type == "song":
        return DEFAULT_AUDIO_FORMAT
    return str(payload.get("audio_format") or DEFAULT_AUDIO_FORMAT)


def collect_downloaded_files(info: Any, audio_format: str) -> list[str]:
    files: list[str] = []

    def add_candidate(value: Any) -> None:
        if not isinstance(value, str) or not value:
            return

        path = Path(value)
        if path.suffix and path.suffix.lstrip(".") != audio_format:
            path = path.with_suffix(f".{audio_format}")
        if path.exists():
            resolved = str(path.resolve())
            if resolved not in files:
                files.append(resolved)

    def walk(item: Any) -> None:
        if not isinstance(item, dict):
            return

        requested_downloads = item.get("requested_downloads")
        if isinstance(requested_downloads, list):
            for download in requested_downloads:
                if isinstance(download, dict):
                    add_candidate(download.get("filepath"))
                    add_candidate(download.get("filename"))

        add_candidate(item.get("filepath"))
        add_candidate(item.get("_filename"))
        add_candidate(item.get("filename"))

        entries = item.get("entries")
        if isinstance(entries, list):
            for entry in entries:
                walk(entry)

    walk(info)
    return files


def song_review_keyboard(job_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "Accept as-is", "callback_data": f"song:{job_id}:accept"},
                {"text": "Identify with Beets", "callback_data": f"song:{job_id}:beets"},
            ],
            [
                {"text": "Identify + Lyrics", "callback_data": f"song:{job_id}:beets_lyrics"},
                {"text": "Reject", "callback_data": f"song:{job_id}:reject"},
            ],
        ]
    }


def run_configured_command(template: str | None, path: Path, job_id: str) -> dict[str, Any]:
    if not template:
        return {"enabled": False}

    command = shlex.split(
        template.format(path=str(path), filename=path.name, stem=path.stem, job_id=job_id)
    )
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return {
        "enabled": True,
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
        "ok": result.returncode == 0,
    }


def move_song_to_library(path: Path) -> str:
    relative = path.relative_to(SONG_INBOX_DIR)
    destination = SONG_DOWNLOAD_DIR / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(destination))

    lrc_path = path.with_suffix(".lrc")
    if lrc_path.exists():
        shutil.move(str(lrc_path), str(destination.with_suffix(".lrc")))

    return str(destination)


def process_song_review(job_id: str, action: str) -> dict[str, Any]:
    job = read_job(job_id)
    if not job:
        return {"ok": False, "error": "Job not found."}
    if job.get("media_type") != "song":
        return {"ok": False, "error": "Job is not a song download."}

    files = [Path(value) for value in job.get("files", []) if isinstance(value, str)]
    existing_files = [path for path in files if path.exists()]
    if not existing_files:
        return {"ok": False, "error": "No downloaded files found in inbox."}

    if action == "reject":
        update_job(job_id, status="rejected", reviewed_at=utc_now())
        return {"ok": True, "status": "rejected"}

    if action in {"beets", "beets_lyrics"} and not BEETS_COMMAND:
        return {"ok": False, "error": "BEETS_COMMAND is not configured."}
    if action == "beets_lyrics" and not LRCGET_COMMAND:
        return {"ok": False, "error": "LRCGET_COMMAND is not configured."}

    update_job(job_id, status="postprocessing", review_action=action)

    beets_results = []
    lrcget_results = []
    moved_files = []
    try:
        for path in existing_files:
            if action in {"beets", "beets_lyrics"}:
                result = run_configured_command(BEETS_COMMAND, path, job_id)
                beets_results.append(result)
                if result.get("enabled") and not result.get("ok"):
                    raise RuntimeError(f"Beets failed for {path.name}: {result.get('stderr')}")

            if action == "beets_lyrics":
                result = run_configured_command(LRCGET_COMMAND, path, job_id)
                lrcget_results.append(result)
                if result.get("enabled") and not result.get("ok"):
                    raise RuntimeError(f"lrcget failed for {path.name}: {result.get('stderr')}")

            if path.exists():
                moved_files.append(move_song_to_library(path))

        update_job(
            job_id,
            status="completed",
            review_action=action,
            beets=beets_results,
            lrcget=lrcget_results,
            moved_files=moved_files,
            completed_at=utc_now(),
        )
        return {"ok": True, "status": "completed", "moved_files": moved_files}
    except Exception as exc:
        update_job(
            job_id,
            status="review_failed",
            review_action=action,
            beets=beets_results,
            lrcget=lrcget_results,
            error=str(exc),
            completed_at=utc_now(),
        )
        return {"ok": False, "error": str(exc)}


def run_download(job_id: str, payload: dict[str, Any], media_type: str) -> None:
    url = payload["url"]
    update_job(job_id, status="starting")

    try:
        options = build_ydl_options(job_id, payload, media_type)
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)

        if isinstance(info, dict):
            title = info.get("title")
            webpage_url = info.get("webpage_url") or url
        else:
            title = None
            webpage_url = url

        downloaded_files = collect_downloaded_files(info, expected_audio_format(payload, media_type))

        if media_type == "song":
            telegram_result = send_telegram_message(
                "\n".join(
                    [
                        "Song downloaded for review",
                        f"Title: {title or 'Unknown'}",
                        f"URL: {webpage_url}",
                        f"Files: {len(downloaded_files)}",
                        "",
                        "Choose what to do next.",
                    ]
                ),
                song_review_keyboard(job_id),
            )
            update_job(
                job_id,
                status="pending_review",
                title=title,
                url=webpage_url,
                files=downloaded_files,
                telegram=telegram_result,
                completed_at=utc_now(),
                progress="100%",
            )
            return

        telegram_result = send_telegram_message(f"{media_type.title()} saved: {title or webpage_url}")

        update_job(
            job_id,
            status="completed",
            title=title,
            url=webpage_url,
            files=downloaded_files,
            telegram=telegram_result,
            completed_at=utc_now(),
            progress="100%",
        )
    except Exception as exc:
        update_job(job_id, status="failed", error=str(exc), completed_at=utc_now())
