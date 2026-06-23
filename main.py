"""
TG Thumbnail Watermark Cleaner — main.py
─────────────────────────────────────────
Watches SOURCE_CHANNEL for new video/document posts.
For each file:
  1. Downloads the thumbnail only (not the full video — file_id reuse)
  2. EasyOCR + OpenCV inpaint erases any text watermark from the thumbnail
  3. Strips @mentions / links / [tags] from captions
  4. Re-sends to DEST_CHANNEL with cleaned thumbnail + caption

Commands (DM the userbot, ADMINS only):
  /status   — session stats
  /preview  — send an image → get back watermark-removed version (test mode)
  /help     — command list
"""
import asyncio
import functools
import logging
import os
import tempfile

from pyrogram import Client, filters, idle
from pyrogram.types import Message
from pyrogram.errors import (
    FloodWait,
    SessionRevoked, AuthKeyUnregistered, UserDeactivated,
)

from config import (
    API_ID, API_HASH, SESSION_STRING,
    SOURCE_CHANNEL, DEST_CHANNEL, ADMINS, DELAY, LOG_CHANNEL,
)
from caption_cleaner import clean as clean_caption
import seen_db
import strip_patterns as sp_db
import auto_caption
import skipped_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("thumb_cleaner")

app = Client(
    "thumb_cleaner_session",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)

_stats = {"forwarded": 0, "failed": 0, "thumb_cleaned": 0, "thumb_skipped": 0}
_bulk_running = False
_stop_bulk    = False


def admin_only(func):
    @functools.wraps(func)
    async def wrapper(client, message: Message):
        if ADMINS and message.from_user and message.from_user.id not in ADMINS:
            await message.reply("⛔ Not authorized.")
            return
        await func(client, message)
    return wrapper


# FIX 1: Simplified _is_source — no broken "-100{src}" construction
def _is_source(message: Message) -> bool:
    """Check whether this message comes from SOURCE_CHANNEL."""
    chat_id  = message.chat.id
    username = (getattr(message.chat, "username", None) or "").strip().lower()
    src = SOURCE_CHANNEL.strip()
    # Match by numeric ID (e.g. "-1003417865047")
    if str(chat_id) == src:
        return True
    # Match by @username (e.g. "@ClipmateZone_New" or "ClipmateZone_New")
    src_username = src.lstrip("@").lower()
    if username and username == src_username:
        return True
    return False


# FIX 2: Use (filters.channel | filters.group) — ClipmateZone_New is a supergroup
@app.on_message((filters.channel | filters.group) & (filters.video | filters.document))
async def on_new_file(client: Client, message: Message):
    if not _is_source(message):
        return

    logger.info(f"📥 New file from source: msg_id={message.id}")

    # 0. Duplicate check
    uid = seen_db.get_unique_id(message)
    if uid and seen_db.is_seen(uid):
        fname = (
            (message.video and message.video.file_name) or
            (message.document and message.document.file_name) or
            "unknown"
        )
        skipped_db.record(fname, uid)
        logger.debug(f"⏭️ Duplicate skipped: {uid[:12]}…")
        return

    # 1. Clean caption + auto-caption fallback
    cleaned_caption = clean_caption(message.caption)
    if not cleaned_caption:
        fname = (
            (message.video and message.video.file_name) or
            (message.document and message.document.file_name)
        )
        cleaned_caption = auto_caption.from_filename(fname)

    # FIX 3: Handle document thumbnails too — not just videos
    thumb_path = None
    if _has_thumbs(message):
        try:
            thumb_path = await _get_clean_thumb(client, message)
        except Exception as e:
            logger.warning(f"Thumb processing failed: {e} — forwarding without custom thumb")
            _stats["thumb_skipped"] += 1

    # 3. Forward
    success = await _send(client, message, cleaned_caption, thumb_path)

    # Cleanup
    _cleanup(thumb_path)

    if success:
        _stats["forwarded"] += 1
        if thumb_path:
            _stats["thumb_cleaned"] += 1
        if uid:
            seen_db.mark_seen(uid)
        logger.info(f"✅ Forwarded msg_id={message.id} | total={_stats['forwarded']}")
    else:
        _stats["failed"] += 1
        logger.error(f"❌ Failed msg_id={message.id}")


def _has_thumbs(message: Message) -> bool:
    """True if this message has a thumbnail (video or document)."""
    if message.video and message.video.thumbs:
        return True
    if message.document and message.document.thumbs:
        return True
    return False


def _get_thumb_file_id(message: Message) -> str | None:
    """Get the file_id of the first available thumbnail."""
    if message.video and message.video.thumbs:
        return message.video.thumbs[0].file_id
    if message.document and message.document.thumbs:
        return message.document.thumbs[0].file_id
    return None


def _cleanup(*paths):
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass


# FIX 4 + 5: Use tempfile.mkstemp() and accept any media type's thumb
async def _get_clean_thumb(client: Client, message: Message) -> str | None:
    """Download thumbnail only (not full video), remove watermark, return cleaned path."""
    from thumb_cleaner import remove_watermark, resize_thumb

    thumb_fid = _get_thumb_file_id(message)
    if not thumb_fid:
        return None

    # mkstemp returns (fd, path) — close fd immediately, let pyrogram write the file
    fd_in, tmp_in = tempfile.mkstemp(suffix=".jpg")
    os.close(fd_in)
    fd_out, tmp_out = tempfile.mkstemp(suffix="_clean.jpg")
    os.close(fd_out)

    try:
        # Download just the thumbnail (5–30 KB JPEG, not the full video)
        downloaded = await client.download_media(thumb_fid, file_name=tmp_in)
        if not downloaded or not os.path.exists(tmp_in) or os.path.getsize(tmp_in) == 0:
            logger.warning("Thumb download returned empty file")
            return None

        remove_watermark(tmp_in, tmp_out)

        # Validate BEFORE resize — remove_watermark may not write tmp_out on failure
        if not os.path.exists(tmp_out) or os.path.getsize(tmp_out) == 0:
            logger.warning("Cleaned thumb is empty — skipping")
            return None

        resize_thumb(tmp_out)
        return tmp_out

    except Exception as e:
        logger.warning(f"Thumb download/process error: {e}")
        return None
    finally:
        _cleanup(tmp_in)


async def _send(
    client: Client,
    message: Message,
    caption: str | None,
    thumb: str | None,
    dest_override: str | None = None,
) -> bool:
    """Send to DEST_CHANNEL (or dest_override) using file_id."""
    dest = dest_override or DEST_CHANNEL
    for attempt in range(1, 4):
        try:
            if message.video:
                v = message.video
                await client.send_video(
                    dest,
                    video=v.file_id,
                    thumb=thumb,
                    caption=caption or "",
                    duration=v.duration or 0,
                    width=v.width or 0,
                    height=v.height or 0,
                    supports_streaming=True,
                )
            elif message.document:
                d = message.document
                await client.send_document(
                    dest,
                    document=d.file_id,
                    thumb=thumb,        # None if doc had no thumbs
                    caption=caption or "",
                    file_name=d.file_name,
                )

            await asyncio.sleep(DELAY)
            return True

        except FloodWait as e:
            wait = e.value + 10
            logger.warning(f"⏳ FloodWait {e.value}s → sleeping {wait}s (attempt {attempt})")
            await asyncio.sleep(wait)
        except Exception as e:
            logger.error(f"❌ Send error attempt {attempt}: {type(e).__name__}: {e}")
            await asyncio.sleep(5 * attempt)

    return False


# ── Session watchdog ───────────────────────────────────────────────────────
async def _session_watchdog():
    await asyncio.sleep(60)
    while True:
        await asyncio.sleep(300)
        try:
            await app.get_me()
        except (SessionRevoked, AuthKeyUnregistered, UserDeactivated) as e:
            alert = (
                f"⚠️ **Session Revoked!**\n\nError: `{type(e).__name__}`\n\n"
                f"Regenerate SESSION_STRING with session_gen.py and redeploy."
            )
            logger.critical(f"🔴 SESSION REVOKED: {e}")
            if LOG_CHANNEL:
                try: await app.send_message(LOG_CHANNEL, alert)
                except Exception: pass
            for uid in ADMINS:
                try: await app.send_message(uid, alert)
                except Exception: pass
            await asyncio.sleep(5)
            os._exit(1)
        except Exception:
            pass


# ── Commands ───────────────────────────────────────────────────────────────
@app.on_message(filters.command("status") & filters.private)
@admin_only
async def cmd_status(client: Client, message: Message):
    me = await client.get_me()
    await message.reply(
        f"**🖼️ Thumbnail Watermark Cleaner**\n\n"
        f"👤 Running as: `{me.first_name}` (@{me.username})\n"
        f"📡 Source: `{SOURCE_CHANNEL}`\n"
        f"📤 Destination: `{DEST_CHANNEL}`\n\n"
        f"**Session stats:**\n"
        f"✅ Forwarded: `{_stats['forwarded']}`\n"
        f"🖼️ Thumbnails cleaned: `{_stats['thumb_cleaned']}`\n"
        f"⏭️ Thumb skipped (no thumb/error): `{_stats['thumb_skipped']}`\n"
        f"❌ Failed: `{_stats['failed']}`\n"
        f"🔍 Dedup DB: `{seen_db.count():,}` unique files tracked\n"
        f"⏭️ Skipped (dupes) this session: `{skipped_db.session_count():,}`\n"
        f"🔧 Custom strip patterns: `{sp_db.count()}`",
        parse_mode="markdown"
    )


@app.on_message(filters.command("preview") & filters.private)
@admin_only
async def cmd_preview(client: Client, message: Message):
    args = message.text.split(None, 1)
    side_by_side = len(args) > 1 and "side" in args[1].lower()

    """
    /preview — test watermark removal.
    Send this command as a reply to any image, OR send an image with caption /preview.
    The bot applies the same removal pipeline and sends back the cleaned image.
    """
    from thumb_cleaner import remove_watermark, resize_thumb

    # Resolve the target photo
    target = message.reply_to_message if message.reply_to_message else message
    if not target.photo:
        await message.reply(
            "📸 Send an image with caption `/preview`, or reply to an image with `/preview`.\n\n"
            "I'll apply the watermark removal pipeline and send back the result.",
            parse_mode="markdown"
        )
        return

    status = await message.reply("⏳ Downloading and processing...")

    fd_in, tmp_in   = tempfile.mkstemp(suffix=".jpg")
    fd_out, tmp_out = tempfile.mkstemp(suffix="_clean.jpg")
    os.close(fd_in)
    os.close(fd_out)

    try:
        downloaded = await client.download_media(target.photo.file_id, file_name=tmp_in)
        if not downloaded or not os.path.exists(tmp_in):
            await status.edit("❌ Could not download the image.")
            return

        remove_watermark(tmp_in, tmp_out)
        resize_thumb(tmp_out)

        if not os.path.exists(tmp_out) or os.path.getsize(tmp_out) == 0:
            await status.edit("❌ Processing produced an empty file.")
            return

        await status.delete()
        if side_by_side:
            from pyrogram.types import InputMediaPhoto
            await client.send_media_group(
                message.chat.id,
                media=[
                    InputMediaPhoto(tmp_in, caption="📸 Original"),
                    InputMediaPhoto(tmp_out, caption="✅ Cleaned"),
                ],
            )
        else:
            await client.send_photo(
                message.chat.id,
                photo=tmp_out,
                caption="✅ Watermark removed — preview result",
            )

    except Exception as e:
        logger.error(f"/preview error: {e}")
        await status.edit(f"❌ Error: `{type(e).__name__}: {e}`", parse_mode="markdown")
    finally:
        _cleanup(tmp_in, tmp_out)





# ── /strippatterns ─────────────────────────────────────────────────────────
@app.on_message(filters.command("strippatterns") & filters.private)
@admin_only
async def cmd_strippatterns(client: Client, message: Message):
    """
    /strippatterns list              — show all custom patterns
    /strippatterns add <regex>       — add a new pattern (validated)
    /strippatterns remove <n>        — remove pattern by list number
    /strippatterns test <text>       — test what the cleaner does to a caption
    """
    import strip_patterns as sp

    args  = message.text.split(None, 2)
    sub   = args[1].strip().lower() if len(args) > 1 else "list"
    value = args[2].strip()         if len(args) > 2 else ""

    # ── list ──────────────────────────────────────────────────────────────
    if sub == "list":
        patterns = sp.load()
        if not patterns:
            await message.reply(
                "📋 **Custom strip patterns** — none set.\n\n"
                "Add one with:\n`/strippatterns add @YourPattern`",
                parse_mode="markdown"
            )
            return
        lines = "\n".join(f"`{i+1}.` `{p}`" for i, p in enumerate(patterns))
        await message.reply(
            f"📋 **Custom strip patterns** ({len(patterns)}):\n\n{lines}\n\n"
            f"Built-in patterns (always active): @mentions, t.me/ links, URLs, [tags]",
            parse_mode="markdown"
        )

    # ── add ───────────────────────────────────────────────────────────────
    elif sub == "add":
        if not value:
            await message.reply("Usage: `/strippatterns add <regex>`", parse_mode="markdown")
            return
        err = sp.add(value)
        if err:
            await message.reply(f"❌ {err}", parse_mode="markdown")
        else:
            await message.reply(
                f"✅ Pattern added: `{value}`\n"
                f"Takes effect immediately — no restart needed.",
                parse_mode="markdown"
            )

    # ── remove ────────────────────────────────────────────────────────────
    elif sub in ("remove", "del", "delete"):
        if not value.isdigit():
            await message.reply("Usage: `/strippatterns remove <number>`", parse_mode="markdown")
            return
        err = sp.remove(int(value))
        if err:
            await message.reply(f"❌ {err}", parse_mode="markdown")
        else:
            await message.reply(f"🗑️ Pattern #{value} removed.", parse_mode="markdown")

    # ── test ──────────────────────────────────────────────────────────────
    elif sub == "test":
        if not value:
            await message.reply("Usage: `/strippatterns test <caption text>`", parse_mode="markdown")
            return
        from caption_cleaner import clean
        result = clean(value)
        await message.reply(
            f"**Input:**\n`{value}`\n\n"
            f"**After cleaning:**\n`{result or '(empty — fully stripped)'}`",
            parse_mode="markdown"
        )

    else:
        await message.reply(
            "**Usage:**\n"
            "• `/strippatterns list` — show all patterns\n"
            "• `/strippatterns add <regex>` — add pattern\n"
            "• `/strippatterns remove <n>` — remove by number\n"
            "• `/strippatterns test <text>` — preview what gets stripped",
            parse_mode="markdown"
        )



# ── /listskipped ──────────────────────────────────────────────────────────────
@app.on_message(filters.command("listskipped") & filters.private)
@admin_only
async def cmd_listskipped(client: Client, message: Message):
    entries = skipped_db.list_recent()
    total   = skipped_db.session_count()
    if not entries:
        await message.reply("✅ No files skipped as duplicates this session.")
        return
    lines = []
    for e in entries[:20]:
        import datetime
        t = datetime.datetime.fromtimestamp(e["ts"]).strftime("%H:%M")
        lines.append(f"• `{e['filename'][:50]}` — {t}")
    await message.reply(
        f"**⏭️ Skipped as duplicates this session: {total}**\n"
        f"_(showing last {len(lines)})_\n\n" + "\n".join(lines),
        parse_mode="markdown"
    )



# ── /dupstats ──────────────────────────────────────────────────────────────
@app.on_message(filters.command("dupstats") & filters.private)
@admin_only
async def cmd_dupstats(client: Client, message: Message):
    n = seen_db.count()
    await message.reply(
        f"**🔍 Deduplication Stats**\n\n"
        f"📦 Unique files tracked: `{n:,}`\n"
        f"💾 Stored in: `seen.json`\n\n"
        f"Any file already in this list will be skipped by both\n"
        f"real-time forwarding and `/bulk`.\n"
        f"Use `/resetdups` to clear it.",
        parse_mode="markdown"
    )


# ── /resetdups ─────────────────────────────────────────────────────────────
@app.on_message(filters.command("resetdups") & filters.private)
@admin_only
async def cmd_resetdups(client: Client, message: Message):
    args = message.text.split(None, 1)
    n = seen_db.count()
    if len(args) < 2 or args[1].strip().lower() != "confirm":
        await message.reply(
            f"⚠️ This will clear `{n:,}` file IDs from `seen.json`.\n\n"
            f"After reset, all files will be treated as new — "
            f"`/bulk` will re-forward everything.\n\n"
            f"Send `/resetdups confirm` to proceed.",
            parse_mode="markdown"
        )
        return
    seen_db.reset()
    await message.reply(f"🗑️ Cleared `{n:,}` entries from `seen.json`.", parse_mode="markdown")


# ── /bulk ──────────────────────────────────────────────────────────────────
@app.on_message(filters.command("bulk") & filters.private)
@admin_only
async def cmd_bulk(client: Client, message: Message):
    """
    /bulk <N>              — process last N messages from source (max 500)
    /bulk all              — process all history (capped at 500)
    /bulk <N> <dest_id>    — override destination channel for this run
    Use /stopbulk to cancel mid-run.
    """
    global _bulk_running, _stop_bulk

    if _bulk_running:
        await message.reply("⚠️ A bulk job is already running. Use /stopbulk to cancel it first.")
        return

    # Parse: /bulk <N|all> [dest_channel_id]
    parts = message.text.split()
    raw   = parts[1].strip().lower() if len(parts) > 1 else ""
    bulk_dest: int | str = (
        int(parts[2].strip())
        if len(parts) > 2 and parts[2].strip().lstrip("-").isdigit()
        else DEST_CHANNEL
    )

    MAX_CAP = 500
    if raw == "all":
        limit = MAX_CAP
    else:
        try:
            limit = min(int(raw), MAX_CAP)
            if limit <= 0:
                raise ValueError
        except ValueError:
            await message.reply(
                "**Usage:**\n"
                "• `/bulk 50` — process last 50 messages\n"
                "• `/bulk all` — process all (max 500)\n"
                "• `/bulk 50 -100xxx` — override destination channel\n"
                "• `/stopbulk` — cancel mid-run",
                parse_mode="markdown"
            )
            return

    _bulk_running = True
    _stop_bulk    = False

    prog = await message.reply(
        f"🔄 Starting bulk job: scanning last **{limit}** messages from `{SOURCE_CHANNEL}`...\n"
        f"Use /stopbulk to cancel.",
        parse_mode="markdown"
    )

    scanned = forwarded = thumb_ok = failed = skipped = non_file = 0

    # Collect then reverse so we forward oldest-first (get_chat_history returns newest-first)
    all_msgs = []
    async for msg in client.get_chat_history(SOURCE_CHANNEL, limit=limit):
        all_msgs.append(msg)
    all_msgs.reverse()

    try:
        for msg in all_msgs:
            if _stop_bulk:
                break

            if not msg.video and not msg.document:
                scanned += 1
                non_file += 1
                continue

            scanned += 1

            # Duplicate check
            bulk_uid = seen_db.get_unique_id(msg)
            if bulk_uid and seen_db.is_seen(bulk_uid):
                skipped += 1
                continue

            # Progress update every 10 processed files
            if scanned % 10 == 0:
                try:
                    await prog.edit(
                        f"🔄 **Bulk progress** ({scanned}/{limit} scanned)\n"
                        f"✅ Forwarded: {forwarded} | 🖼️ Cleaned: {thumb_ok}\n"
                        f"❌ Failed: {failed} | 📄 Non-file: {non_file}\n"
                        f"Send /stopbulk to stop.",
                        parse_mode="markdown"
                    )
                except Exception:
                    pass

            # Clean caption + auto-caption fallback
            cleaned_caption = clean_caption(msg.caption)
            if not cleaned_caption:
                bfname = (msg.video and msg.video.file_name) or (msg.document and msg.document.file_name)
                cleaned_caption = auto_caption.from_filename(bfname)

            # Clean thumbnail
            thumb_path = None
            if _has_thumbs(msg):
                try:
                    thumb_path = await _get_clean_thumb(client, msg)
                    if thumb_path:
                        thumb_ok += 1
                except Exception as e:
                    logger.warning(f"Bulk thumb error msg={msg.id}: {e}")

            # Send to destination
            success = await _send(client, msg, cleaned_caption, thumb_path, dest_override=bulk_dest)
            _cleanup(thumb_path)

            if success:
                forwarded += 1
                _stats["forwarded"] += 1
                if thumb_path:
                    _stats["thumb_cleaned"] += 1
                if bulk_uid:
                    seen_db.mark_seen(bulk_uid)
            else:
                failed += 1
                _stats["failed"] += 1

            await asyncio.sleep(DELAY)

    except Exception as e:
        logger.error(f"Bulk job error: {e}")
        await prog.edit(f"❌ Bulk job crashed: `{type(e).__name__}: {e}`", parse_mode="markdown")
        _bulk_running = False
        return

    _bulk_running = False
    status = "🛑 Stopped early" if _stop_bulk else "✅ Complete"
    await prog.edit(
        f"**{status} — Bulk Job**\n\n"
        f"📋 Scanned: {scanned}\n"
        f"✅ Forwarded: {forwarded}\n"
        f"🖼️ Thumbnails cleaned: {thumb_ok}\n"
        f"❌ Failed: {failed}\n"
        f"⏭️ Duplicates skipped: {skipped}\n"
        f"📄 Non-file messages: {non_file}",
        parse_mode="markdown"
    )


# ── /stopbulk ──────────────────────────────────────────────────────────────
@app.on_message(filters.command("stopbulk") & filters.private)
@admin_only
async def cmd_stopbulk(client: Client, message: Message):
    global _stop_bulk
    if not _bulk_running:
        await message.reply("ℹ️ No bulk job is currently running.")
        return
    _stop_bulk = True
    await message.reply("🛑 Stop signal sent — will halt after the current message.")


@app.on_message(filters.command(["start", "help"]) & filters.private)
async def cmd_help(client: Client, message: Message):
    await message.reply(
        "**🖼️ TG Thumbnail Watermark Cleaner**\n\n"
        "Watches a source channel, removes watermark text from video thumbnails,\n"
        "strips @mentions from captions, forwards to your index channel.\n\n"
        "• Video sent by `file_id` — no full re-download needed\n"
        "• EasyOCR detects text → OpenCV inpaints (erases) it\n"
        "• CPU only, no GPU required\n\n"
        "**Commands:**\n"
        "• `/status` — session + cleaning stats\n"
        "• `/preview` — reply to an image to test watermark removal\n"
        "• `/bulk <N>` or `/bulk all` — catch up history from source channel\n"
        "• `/stopbulk` — cancel a running bulk job\n"
        "• `/dupstats` — show how many unique files are tracked\n"
        "• `/resetdups` — clear seen.json (re-forward everything)\n"
        "• `/strippatterns list/add/remove/test` — manage caption strip patterns\n",
        parse_mode="markdown"
    )


# ── Startup ────────────────────────────────────────────────────────────────
async def main():
    await app.start()
    me = await app.get_me()
    logger.info(f"🚀 Started as: {me.first_name} (@{me.username})")
    logger.info(f"📡 Watching: {SOURCE_CHANNEL} → {DEST_CHANNEL}")

    # Pre-load EasyOCR model so first forward is fast (first-time ~100 MB download)
    try:
        logger.info("⏳ Pre-loading EasyOCR model...")
        from thumb_cleaner import _get_reader
        _get_reader()
        logger.info("✅ EasyOCR model loaded and ready")
    except Exception as e:
        logger.warning(f"OCR pre-load skipped: {e} — will load on first use")

    asyncio.create_task(_session_watchdog())
    logger.info("🛡️ Session watchdog started (checks every 5 min)")

    if LOG_CHANNEL:
        try:
            await app.send_message(
                LOG_CHANNEL,
                f"✅ **Thumbnail Cleaner started**\n"
                f"As: `{me.first_name}`\n"
                f"Source: `{SOURCE_CHANNEL}` → `{DEST_CHANNEL}`"
            )
        except Exception:
            pass

    logger.info("⏳ Listening for new files...")
    await idle()
    await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
