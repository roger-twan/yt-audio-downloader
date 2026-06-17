# YouTube Audio Downloader

A small Dockerized Flask API that accepts YouTube URLs and downloads them with `yt-dlp`. By default it extracts audio to `/downloads`.

## Configure

Create your local Docker Compose file from the template:

```bash
cp docker-compose.template.yml docker-compose.yml
```

Then edit `docker-compose.yml` and replace:

```yaml
- /path/to/audio:/downloads
```

with your real audio folder.

Optional authentication:

```yaml
environment:
  API_TOKEN: your-secret-token
```

When `API_TOKEN` is set, all endpoints except `/health` require:

```text
Authorization: Bearer your-secret-token
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

If the container can reach YouTube directly, remove or comment out `YTDLP_PROXY` in `docker-compose.yml`.

When using ClashX, make sure it is running and that its HTTP or mixed proxy port is `7890`. If your ClashX port is different, update the proxy URLs in `docker-compose.yml`.

## Telegram Notifications

Telegram notifications are optional. Set these environment variables in `docker-compose.yml` to send a message after media is saved:

```yaml
TELEGRAM_BOT_TOKEN: "123456:your-bot-token"
TELEGRAM_CHAT_ID: "123456789"
```

If Telegram needs a proxy, set `TELEGRAM_PROXY`. When `TELEGRAM_PROXY` is omitted, the app reuses `YTDLP_PROXY` if it is set.

```yaml
TELEGRAM_PROXY: http://host.docker.internal:7890
```

Test Telegram from the running server:

```bash
curl -X POST http://localhost:7777/telegram/test
```

## Post-download Docker Command

You can trigger a command in another container after each successful download. For example, to run the same command as:

```bash
docker exec navidrome navidrome scan
```

uncomment the Docker socket volume and set:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock

environment:
  POST_DOWNLOAD_DOCKER_CONTAINER: navidrome
  POST_DOWNLOAD_DOCKER_COMMAND: navidrome scan
```

The Docker socket gives this service control over the host Docker daemon, so only enable it on a trusted host.
When this command is enabled, the Telegram notification is sent after the command finishes and includes the scan/sync result.

## Download Audio

```bash
curl -X POST http://localhost:7777/download \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

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
curl http://localhost:7777/jobs/abc123
```

List all jobs:

```bash
curl http://localhost:7777/jobs
```

## Request Options

```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "title": "Custom title",
  "audio_only": true,
  "audio_format": "mp3",
  "audio_quality": "5",
  "playlist": false
}
```

When `title` is set, it replaces the title part of the saved filename and the file metadata title.
The file metadata album is always set to `Audiobooks`.
The file metadata album artist is always set to `Audiobook`.

To download video instead of audio:

```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "audio_only": false,
  "format": "bestvideo+bestaudio/best",
  "merge_output_format": "mp4"
}
```

## Endpoints

- `GET /health`
- `POST /download`
- `GET /jobs`
- `GET /jobs/<job_id>`
- `POST /telegram/test`

Downloads are stored under:

```text
/downloads/<artist or uploader> - <title>.<format>
```
