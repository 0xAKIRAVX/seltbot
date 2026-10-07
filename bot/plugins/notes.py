"""Notes: save text/small-media notes, expand with #key, search, delete."""
import base64
import logging
import os

from ..core import command, outgoing_hook

log = logging.getLogger("seltbot.notes")

MAX_MEDIA = 256 * 1024  # notes with media ≤256KB (stored in encrypted state)


@outgoing_hook()
async def notes_expand(app, event):
    if app.module_off("notes"):
        return False
    msg = event.message
    text = (msg.raw_text or "").strip()
    if not (text.startswith("#") and " " not in text and 1 < len(text) <= 49):
        return False
    key = text[1:]
    row = app.db.note_get(key)
    if not row:
        return False
    try:
        if row["media"]:
            data = base64.b64decode(row["media"])
            path = os.path.join(app.data_dir, "downloads", row["media_name"] or "note.bin")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            await app.client.send_file(event.chat_id, path,
                                       caption=row["text"] or None)
            await msg.delete()
        else:
            await msg.edit(row["text"] or "‌")
    except Exception:
        log.exception("note expand failed")
    return True


@command("save", "notes", "<کلید> <متن> یا ریپلای", "ذخیرهٔ نوت",
         "Save a note")
async def save_cmd(app, ev, arg):
    parts = arg.split(None, 1)
    if not parts:
        await ev.reply("❌ مثال: `.save لینک‌ها https://t.me/...` یا ریپلای + `.save عکس`")
        return
    key = parts[0].strip()
    if len(key) > 48 or " " in key:
        await ev.reply("❌ کلید بدون فاصله و کوتاه باشه (مثلاً `لینک‌ها`).")
        return
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    media_b64, media_name, text = None, None, (parts[1].strip() if len(parts) > 1 else "")
    if reply is not None:
        if reply.media:
            try:
                data = await reply.download_media(file=bytes)
            except Exception:
                data = None
            if data:
                if len(data) > MAX_MEDIA:
                    await ev.reply("⚠️ فایل بزرگ‌تر از ۲۵۶KBه — نوت مدیا نمی‌شه.")
                    return
                media_b64 = base64.b64encode(data).decode()
                media_name = (getattr(reply, "file", None) and reply.file.name) or "note.bin"
        if not text:
            text = (reply.raw_text or "").strip()
    if not text and not media_b64:
        await ev.reply("❌ متنی برای ذخیره نیست.")
        return
    app.db.note_save(key, text, media_b64, media_name)
    await ev.reply(f"💾 نوت `{key}` ذخیره شد.{'. فایل: ' + media_name if media_name else ''}\n"
                   f"فراخوانی: بنویس `#{key}`")


@command("notes", "notes", "[جستجو]", "لیست/جستجوی نوت‌ها", "List/search notes",
         bot_ok=True)
async def notes_cmd(app, ev, arg):
    rows = app.db.notes_list(arg.strip() or None)
    if not rows:
        await ev.reply(app.t("empty"))
        return
    lines = []
    for r in rows[:40]:
        prev = (r["text"] or "").replace("\n", " ")[:38]
        icon = "📁 " if r["media"] else ""
        lines.append(f"• `#{r['key']}` — {icon}{prev}")
    await ev.reply("📋 نوت‌ها:\n" + "\n".join(lines))


@command("get", "notes", "<کلید>", "فراخوانی نوت", "Get a note", bot_ok=True)
async def get_cmd(app, ev, arg):
    key = arg.strip()
    if not key:
        await ev.reply(app.t("no_arg"))
        return
    row = app.db.note_get(key)
    if not row:
        await ev.reply(app.t("not_found"))
        return
    if row["media"]:
        import os
        data = base64.b64decode(row["media"])
        path = os.path.join(app.data_dir, "downloads", row["media_name"] or "note.bin")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        await app.client.send_file(ev.chat_id, path, caption=row["text"] or None,
                                   reply_to=getattr(ev, "message", None))
    else:
        await ev.reply(row["text"] or "‌")


@command("delnote", "notes", "<کلید>", "حذف نوت", "Delete a note", bot_ok=True)
async def delnote_cmd(app, ev, arg):
    if not arg.strip():
        await ev.reply(app.t("no_arg"))
        return
    await ev.reply(app.t("deleted") if app.db.note_del(arg.strip())
                   else app.t("not_found"))


@command("clearnotes", "notes", "", "پاک‌کردن همهٔ نوت‌ها", "Clear all notes", bot_ok=True)
async def clearnotes_cmd(app, ev, arg):
    app.db.notes_clear()
    await ev.reply("🗑 همهٔ نوت‌ها پاک شد.")
