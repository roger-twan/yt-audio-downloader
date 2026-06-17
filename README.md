# YouTube Audio Downloader

A small Dockerized Flask API that accepts YouTube URLs and downloads audio with `yt-dlp`.

It exposes separate endpoints for audiobooks and songs:

- `POST /download/audiobook` extracts audio with `AUDIO_FORMAT` and `AUDIO_QUALITY`, embeds metadata, and embeds the thumbnail as JPG cover art.
- `POST /download/song` extracts audio with the same `AUDIO_FORMAT`, uses `SONG_QUALITY`, embeds metadata, and embeds the thumbnail as JPG cover art.

## Configure

Create your local Compose file from the tracked template:

```bash
cp docker-compose_template.yml docker-compose.yml
```

`docker-compose.yml` is ignored by Git, so keep local paths, tokens, and chat IDs there. Edit it and replace the mounted folders with your real audio folders:

```yaml
volumes:
  - /path/to/audiobooks:/downloads/audiobooks
  - /path/to/songs-inbox:/downloads/songs-inbox
  - /path/to/songs:/downloads/songs
```

The main settings are:

```yaml
environment:
  AUDIOBOOK_DOWNLOAD_DIR: /downloads/audiobooks
  SONG_INBOX_DIR: /downloads/songs-inbox
  SONG_DOWNLOAD_DIR: /downloads/songs
  AUDIO_FORMAT: mp3
  AUDIO_QUALITY: "5"
  SONG_QUALITY: "0"
  API_TOKEN: change-me
```

Songs are downloaded to `SONG_INBOX_DIR` first. After Telegram review, accepted files are moved to `SONG_DOWNLOAD_DIR`.

When `API_TOKEN` is set, all endpoints except `/health` require:

```text
Authorization: Bearer change-me
```

## Run

```bash
docker compose up -d
```

The API listens on `http://localhost:7777`.

## ClashX Proxy

Using ClashX is optional. Keep `YTDLP_PROXY` in `docker-compose.yml` only when `yt-dlp` needs a proxy to reach YouTube:

```yaml
YTDLP_PROXY: http://host.docker.internal:7890
```

`YTDLP_PROXY` is passed directly to `yt-dlp`, the same as running `yt-dlp --proxy http://host.docker.internal:7890 ...`.

## Telegram Notifications

Telegram notifications are optional. Set these environment variables in `docker-compose.yml` to send a message after media is saved:

```yaml
TELEGRAM_BOT_TOKEN: "123456:your-bot-token"
TELEGRAM_CHAT_ID: "123456789"
```

If Telegram needs a proxy, set `TELEGRAM_PROXY`. When `TELEGRAM_PROXY` is omitted, the app reuses `YTDLP_PROXY` if it is set.

Test Telegram from the running server:

```bash
curl -X POST http://localhost:7777/telegram/test \
  -H "Authorization: Bearer change-me"
```

To use review buttons, expose the app through HTTPS and set the Telegram webhook to the callback URL:

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=https://your-domain.example/telegram/callback/change-me"
```

The last path segment must match `API_TOKEN`.

## Download Audiobook

```bash
curl -X POST http://localhost:7777/download/audiobook \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer change-me" \
  -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

## Download Song

```bash
curl -X POST http://localhost:7777/download/song \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer change-me" \
  -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

Songs do not move directly into the final library. The bot sends a Telegram message with these actions:

- `Accept as-is`: move the downloaded file from inbox to `SONG_DOWNLOAD_DIR`.
- `Identify with Beets`: run `BEETS_COMMAND`, then move the file.
- `Identify + Lyrics`: run `BEETS_COMMAND`, then `LRCGET_COMMAND`, then move the file and matching `.lrc` sidecar.
- `Reject`: keep the file in inbox and mark the job rejected.

Optional post-review commands can be configured in `docker-compose.yml`. Use `{path}` as the downloaded file path:

```yaml
BEETS_COMMAND: beet import -q {path}
LRCGET_COMMAND: lrcget {path}
```

For `Identify + Lyrics`, configure `BEETS_COMMAND` so the file at `{path}` is still available when the command exits, or make sure your Beets library path is the final song library. The app moves files that remain in inbox after post-processing.

Response:

```json
{
  "job_id": "abc123",
  "status": "queued",
  "status_url": "/jobs/abc123"
}
```

Check progress:

```bash
curl http://localhost:7777/jobs/abc123 \
  -H "Authorization: Bearer change-me"
```

List all jobs:

```bash
curl http://localhost:7777/jobs \
  -H "Authorization: Bearer change-me"
```

## Request Options

```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "audio_format": "mp3",
  "audio_quality": "5",
  "song_quality": "0",
  "playlist": false,
  "subfolder": "YouTube"
}
```

`audio_format` can override `AUDIO_FORMAT` per request. `audio_quality` applies to `/download/audiobook`. `song_quality` applies to `/download/song`.

## Endpoints

- `GET /health`
- `POST /download/audiobook`
- `POST /download/song`
- `GET /jobs`
- `GET /jobs/<job_id>`
- `POST /telegram/test`
- `POST /telegram/callback/<API_TOKEN>`

Downloads are stored under:

```text
/downloads/audiobooks/<artist or uploader> - <title>.<format>
/downloads/songs-inbox/<artist or uploader> - <title>.<format>
/downloads/songs/<artist or uploader> - <title>.<format>
```
