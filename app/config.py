import os
from pathlib import Path


AUDIOBOOK_DOWNLOAD_DIR = Path(os.getenv("AUDIOBOOK_DOWNLOAD_DIR", "/downloads")).resolve()
SONG_DOWNLOAD_DIR = Path(os.getenv("SONG_DOWNLOAD_DIR", "/songs")).resolve()
SONG_INBOX_DIR = Path(os.getenv("SONG_INBOX_DIR", "/songs-inbox")).resolve()

DEFAULT_AUDIO_FORMAT = os.getenv("AUDIO_FORMAT", "mp3")
DEFAULT_AUDIO_QUALITY = os.getenv("AUDIO_QUALITY", "0")
SONG_QUALITY = os.getenv("SONG_QUALITY", "0")

BEETS_COMMAND = os.getenv("BEETS_COMMAND")
LRCGET_COMMAND = os.getenv("LRCGET_COMMAND")

API_TOKEN = os.getenv("API_TOKEN")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))
YTDLP_PROXY = os.getenv("YTDLP_PROXY")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY") or YTDLP_PROXY


def ensure_directories() -> None:
    AUDIOBOOK_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    SONG_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    SONG_INBOX_DIR.mkdir(parents=True, exist_ok=True)
