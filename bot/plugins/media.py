"""Media tools: download, rename (re-upload with new name), upload, mediainfo,
profile photo management + rotation."""
import asyncio
import base64
import logging
import os
import time

from telethon.tl import functions, types

from ..core import command

log = logging.getLogger("seltbot.media")

_rotate_task = None


async def start(app):
    global _rotate_task
    # cancel a previous incarnation first — run() re-calls start()
    # after reconnects; without this the loop runs TWICE (double
    # profile writes → flood/ban risk)
    if _rotate_task and not _rotate_task.done():
        _rotate_task.cancel()
    _rotate_task = asyncio.ensure_future(_rotate_loop(app))


async def stop(app):
    if _rotate_task:
        _rotate_task.cancel()


async def _rotate_loop(app):
    while not app.stopping:
        try:
            await asyncio.sleep(600)
            if app.stopping or not app.s("photos_rotate_on", False):
                continue
            every = max(21600, int(app.s("photos_rotate_every_h", 12)) * 3600)
            if not app.limiter.allow(("photo_rotate", 0), every):
                continue
            photos = app.db.photos_all()
            if len(photos) < 2:
                continue
            idx = int(app.s("photos_rotate_idx", 0) or 0) % len(photos)
            row = app.db.photo_get(photos[idx]["id"])
            app.sets("photos_rotate_idx", (idx + 1) % len(photos))
            if not row:
                continue
            data = base64.b64decode(row["data"])
            path = os.path.join(app.data_dir, "downloads", "profile_rot.jpg")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            await app.client(functions.photos.UploadProfilePhotoRequest(
                file=await app.client.upload_file(path)))
            log.info("rotated profile photo → %s", row["name"])
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("photo rotate")


def _dl_dir(app):
    d = os.path.join(app.data_dir, "downloads")
    os.makedirs(d, exist_ok=True)
    return d


@command("download", "media", "[اسم]", "دانلود مدیای ریپلای‌شده", "Download media")
async def download_cmd(app, ev, arg):
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    if reply is None or not reply.media:
        await ev.reply("❌ روی عکس/ویدیو/فایل ریپلای کن.")
        return
    try:
        name = arg.strip() or (reply.file.name if reply.file and reply.file.name else None) \
            or f"file_{int(time.time())}"
        if not os.path.splitext(name)[1] and reply.file and reply.file.ext:
            name += reply.file.ext
        path = os.path.join(_dl_dir(app), os.path.basename(name))
        result = await reply.download_media(file=path)
        size = os.path.getsize(result) if result else 0
        await ev.reply(f"📥 ذخیره شد: `{os.path.basename(str(result))}`"
                       f" ({size // 1024} KB)\n⚠️ روی هاست اجرا، فایل‌ها موقتی‌ان — با .upload دوباره قابل ارسال‌ان.")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}: {str(e)[:150]}")


@command("rename", "media", "<اسم.پسوند>", "دانلود + ارسال با اسم جدید", "Re-upload renamed")
async def rename_cmd(app, ev, arg):
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    if reply is None or not reply.media:
        await ev.reply("❌ روی فایل ریپلای کن + اسم جدید بده: `.rename report.pdf`")
        return
    new = arg.strip() or (reply.file.name if reply.file else None)
    if not new:
        await ev.reply("❌ اسم جدید رو بده: `.rename myfile.pdf`")
        return
    try:
        data = await reply.download_media(file=bytes)
        path = os.path.join(_dl_dir(app), os.path.basename(new))
        with open(path, "wb") as f:
            f.write(data)
        await app.client.send_file(ev.chat_id, path, force_document=True,
                                   caption=f"📎 {os.path.basename(path)}")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}: {str(e)[:150]}")


@command("upload", "media", "<اسم>", "ارسال فایل ذخیره‌شده", "Upload saved file")
async def upload_cmd(app, ev, arg):
    name = arg.strip()
    if not name:
        files = sorted(os.listdir(_dl_dir(app)))[:30]
        await ev.reply("📂 فایل‌های موجود:\n" + ("\n".join("• " + f for f in files)
                                                if files else "— خالی —"))
        return
    path = os.path.join(_dl_dir(app), os.path.basename(name))
    if not os.path.exists(path):
        await ev.reply(app.t("not_found"))
        return
    try:
        await app.client.send_file(ev.chat_id, path)
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}")


@command("mediainfo", "media", "[ریپلای]", "اطلاعات مدیا", "Media info")
async def mediainfo_cmd(app, ev, arg):
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    if reply is None or not reply.media:
        await ev.reply("❌ روی مدیا ریپلای کن.")
        return
    f = reply.file
    if f is None:
        await ev.reply("⛔ مدیای قابل‌تحلیلی نیست.")
        return
    lines = [
        f"📎 نوع: {reply.media.__class__.__name__.replace('MessageMedia', '')}",
        f"• اسم: {f.name or '—'}",
        f"• حجم: {f.size // 1024} KB" if f.size else "• حجم: —",
        f"• MIME: {f.mime_type or '—'}",
        f"• ابعاد: {f.dimensions[0]}×{f.dimensions[1]}" if f.dimensions else "",
        f"• مدت: {f.duration:.0f}s" if getattr(f, "duration", None) else "",
    ]
    await ev.reply("\n".join(l for l in lines if l))


@command("setphoto", "media", "[ریپلای]", "ست‌کردن عکس پروفایل از ریپلای",
         "Set profile photo from reply")
async def setphoto_cmd(app, ev, arg):
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    if reply is None or not reply.media:
        await ev.reply("❌ روی عکس ریپلای کن.")
        return
    if not app.limiter.allow("setphoto", 1800):
        left = app.limiter.seconds_left("setphoto", 1800) // 60
        await ev.reply(f"⏳ برای امنیت اکانت، هر ۳۰ دقیقه یک‌بار می‌شه عکس عوض کرد "
                       f"({left} دقیقه مونده).")
        return
    try:
        data = await reply.download_media(file=bytes)
        path = os.path.join(_dl_dir(app), "profile_tmp.jpg")
        with open(path, "wb") as fh:
            fh.write(data)
        await app.client(functions.photos.UploadProfilePhotoRequest(
            file=await app.client.upload_file(path)))
        await ev.reply("📸 عکس پروفایل عوض شد.")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}: {str(e)[:150]}")


@command("photos", "media", "add|list|del|rotate", "مدیریت عکس‌های پروفایل",
         "Profile photos manager")
async def photos_cmd(app, ev, arg):
    global _rotate_idx
    parts = arg.split(None, 1)
    sub = (parts[0].lower() if parts else "list")
    rest = parts[1].strip() if len(parts) > 1 else ""
    if sub == "add":
        reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
        if reply is None or not reply.media:
            await ev.reply("❌ روی عکس ریپلای کن + اسم بده: `.photos add beytok`")
            return
        try:
            data = await reply.download_media(file=bytes)
        except Exception:
            data = None
        if not data or len(data) > 400 * 1024:
            await ev.reply("⚠️ عکس باید ≤۴۰۰KB باشه.")
            return
        app.db.photo_add(rest or f"photo_{int(time.time())}", base64.b64encode(data).decode())
        await ev.reply(f"🖼 عکس ذخیره شد ({len(app.db.photos_all())} تا داری).")
    elif sub == "del":
        try:
            pid = int(rest)
        except ValueError:
            await ev.reply(app.t("bad_arg"))
            return
        await ev.reply(app.t("deleted") if app.db.photo_del(pid) else app.t("not_found"))
    elif sub == "rotate":
        if rest in ("on", "روشن"):
            app.sets("photos_rotate_on", True)
            await ev.reply(f"🔁 چرخش عکس هر {app.s('photos_rotate_every_h', 12)} ساعت روشن شد.")
        elif rest in ("off", "خاموش"):
            app.sets("photos_rotate_on", False)
            await ev.reply("⏹ چرخش عکس خاموش شد.")
        elif rest.isdigit():
            app.sets("photos_rotate_every_h", max(6, int(rest)))
            await ev.reply(f"✅ چرخش هر {max(6, int(rest))} ساعت.")
        else:
            await ev.reply("❌ `.photos rotate on|off|<ساعت>` (حداقل ۶ ساعت)")
    else:
        rows = app.db.photos_all()
        await ev.reply("🖼 عکس‌های ذخیره‌شده:\n" + ("\n".join(
            f"• #{r['id']} {r['name']}" for r in rows) if rows else app.t("empty"))
            + f"\nچرخش: {'روشن' if app.s('photos_rotate_on', False) else 'خاموش'}")
