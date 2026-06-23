# AGENT_CONTEXT — tg-thumb-cleaner
_Last updated: 2026-06-22 | Session 8 (dry-run pass)_

## Repo
`azizthekiller123/tg-thumb-cleaner`
Railway auto-deploys on push to main (~2 min). Never edit Railway directly.

## What this bot does
Pyrogram userbot (pyrofork==2.3.45, imported as `pyrogram` — **NEVER change imports**).
Watches `SOURCE_CHANNEL` (@ClipmateZone_New — a **supergroup**, not a channel) for new
video/document posts. For each file:
1. Downloads thumbnail ONLY (~5–30 KB JPEG — not the full video, uses file_id reuse)
2. EasyOCR detects text watermarks (e.g. `@ClipmateEmpirer`)
3. OpenCV `inpaint` erases detected text regions from the thumbnail
4. `caption_cleaner` strips all @mentions/URLs/promo lines from caption
5. If caption becomes empty → `auto_caption.from_filename()` generates a clean title
6. Re-sends to `DEST_CHANNEL` with cleaned thumbnail + caption (no video re-upload)

## User context
- Multiple Telegram accounts available
- Source: @ClipmateZone_New (supergroup) — target watermark: `@ClipmateEmpirer`
- Stack: pyrofork + easyocr (CPU, ~100 MB model download on first run) + opencv-python-headless + Pillow

## File map
| File | Purpose |
|------|---------|
| `main.py` | Entry point — all commands + file handler + startup |
| `config.py` | Env var loader |
| `thumb_cleaner.py` | EasyOCR + cv2.inpaint pipeline (`remove_watermark`, `resize_thumb`) |
| `caption_cleaner.py` | Built-in strip patterns + dynamic custom patterns via `strip_patterns.py` |
| `auto_caption.py` | Parse filename → clean title (e.g. `Title (2026) \| S01 \| 1080p \| Hindi`) [S8] |
| `strip_patterns.py` | Runtime regex patterns → `strip_patterns.json` [S7] |
| `seen_db.py` | Deduplication → `seen.json` |
| `skipped_db.py` | In-memory track of last 50 duplicate-skipped files (resets on restart) [S8] |
| `requirements.txt` | `pyrofork==2.3.45`, `easyocr`, `opencv-python-headless`, `Pillow` |
| `Dockerfile` | CPU-only EasyOCR, Railway-compatible |

## Required env vars (Railway)
```
API_ID, API_HASH, SESSION_STRING
SOURCE_CHANNEL     — @username or numeric ID of source supergroup
DEST_CHANNEL       — destination channel ID
ADMINS             — comma-separated Telegram user IDs
```
Optional: `LOG_CHANNEL`, `DELAY`

## Critical architecture notes
- **MUST use `(filters.channel | filters.group)`** — ClipmateZone_New is a supergroup,
  `filters.channel` alone misses it
- **`_is_source()`** matches by numeric ID OR @username — not by `"-100{src}"` construction (that was a bug)
- **`send_video(video=file_id, thumb=cleaned)`** — no full video re-download, just file_id reuse
- **EasyOCR** downloads ~100 MB model on first run — first Railway deploy is slow
- **`_send()`** has `dest_override` param for multi-destination /bulk

## All commands
### Core
- `/status` — session stats (forwarded, thumb cleaned, failed, dedup count, skipped this session, custom patterns)
- `/preview` — reply to image → get cleaned version
- `/preview side` — reply to image → get Original + Cleaned side by side [S8]
- `/help` — full command list

### Deduplication
- `/dupstats` — dedup DB size
- `/resetdups confirm` — wipe seen.json
- `/listskipped` — last 20 files skipped as duplicates this session [S8]

### Bulk processing
- `/bulk <N>` — process last N messages from source (max 500)
- `/bulk <N> <dest_channel_id>` — override destination for this run [S8]
- `/stopbulk` — cancel mid-run

### Caption / pattern
- `/strippatterns list/add/remove/test` — runtime caption strip patterns [S7]

## Key API contracts
```python
# seen_db
seen_db.get_unique_id(message) → str | None
seen_db.is_seen(uid: str) → bool
seen_db.mark_seen(uid: str)
seen_db.count() → int
seen_db.reset()

# skipped_db (in-memory, resets on restart)
skipped_db.record(filename: str, uid: str)
skipped_db.list_recent() → list  # newest-first, max 50
skipped_db.session_count() → int

# auto_caption
auto_caption.from_filename(filename: str | None) → str | None
# Input:  "The.Chestnut.Man.2026.S02.480p.HDRip.Hindi.mkv"
# Output: "The Chestnut Man (2026) | S02 | 480p | Hindi"
# Returns None if filename is None/empty/unparseable

# strip_patterns
strip_patterns.load() → list[str]
strip_patterns.add(pattern: str) → str  # "" on success, error msg on fail
strip_patterns.remove(index: int) → str  # "" on success, error msg on fail
strip_patterns.count() → int

# _send (internal)
_send(client, message, caption, thumb, dest_override=None) → bool
```

## Bugs fixed across all sessions
| Session | Bug | Fix |
|---------|-----|-----|
| 1 | `_is_source()` used broken `-100{src}` construction | Rewrote |
| 2 | `filters.channel` missed supergroup | Added `\| filters.group` |
| 3 | Document thumbnails not handled | Added document thumb path |
| 4 | `NamedTemporaryFile` race condition | Replaced with `mkstemp` |
| 5 | Empty cleaned thumb not validated | Added size check |
| 8 | `bulk_dest` inside `try/except` block (syntax error) | Moved outside |
| 8 (dry-run) | `/status` didn't show `skipped_db.session_count()` | Fixed |

## What to build next (priority order)
1. **Quality routing** — 480p → channel A, 720p/1080p → channel B (multi-account = no rate concern)
2. **`/ignorechat`** — skip specific sources without removing them (same as forwarder)
3. **`/keywords`** — keyword filter (e.g. Hindi only, or block CAMRip)
4. **Milestone alerts** — notify LOG_CHANNEL every 100/500 files cleaned
5. **Per-language destination routing** — Hindi→channelA, Tamil→channelB
