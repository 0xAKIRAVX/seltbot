"""Bio manager: set bio, presets, rotating bio; also first/last name + username."""
import asyncio
import logging
import time

from telethon.tl import functions, types

from ..core import command

log = logging.getLogger("seltbot.bio")

_task = None


async def start(app):
    global _task
    # cancel a previous incarnation first — run() re-calls start()
    # after reconnects; without this the loop runs TWICE (double
    # profile writes → flood/ban risk)
    if _task and not _task.done():
        _task.cancel()
    _task = asyncio.ensure_future(_rotate_loop(app))


async def stop(app):
    if _task:
        _task.cancel()


async def _rotate_loop(app):
    while not app.stopping:
        try:
            await asyncio.sleep(300)
            if app.stopping or not app.s("biorotate_on", False):
                continue
            presets = app.s("bio_presets", []) or []
            if len(presets) < 2:
                continue
            idx = int(app.s("bio_rotate_idx", 0) or 0) % len(presets)
            app.sets("bio_rotate_idx", (idx + 1) % len(presets))
            await app.gov.apply("bio", presets[idx][:139], force=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("bio rotate")


@command("bio", "bio", "[متن]", "تنظیم/نمایش بیو", "Set/show bio", bot_ok=True)
async def bio_cmd(app, ev, arg):
    if not arg.strip():
        me = await app.client(functions.users.GetUsersRequest(id=[types.InputUserSelf()]))
        cur = (getattr(me[0], "about", "") or "") if me else ""
        await ev.reply(f"📝 بیوی فعلی: {cur or '—'}\n(متن جدید رو بفرست: `.bio متن`)")
        return
    ok, _, why = await app.gov.apply("bio", arg.strip()[:139], force=True)
    await ev.reply("📝 بیو عوض شد." if ok else f"⛔ {why}")


@command("biopresets", "bio", "add <متن> | list | del <n>", "بیوهای آماده",
         "Bio presets", bot_ok=True)
async def biopresets_cmd(app, ev, arg):
    parts = arg.split(None, 1)
    sub = parts[0].lower() if parts else "list"
    rest = parts[1].strip() if len(parts) > 1 else ""
    presets = app.s("bio_presets", []) or []
    if sub == "add":
        if not rest:
            await ev.reply("❌ `.biopresets add شب بخیر 🌙`")
            return
        presets.append(rest[:139])
        app.sets("bio_presets", presets)
        await ev.reply(f"✅ {len(presets)} بیو آماده داری.")
    elif sub == "del":
        try:
            i = int(rest) - 1
            removed = presets.pop(i)
            app.sets("bio_presets", presets)
            await ev.reply(app.t("deleted") + f": {removed[:40]}")
        except Exception:
            await ev.reply(app.t("bad_arg"))
    else:
        await ev.reply("📝 بیوهای آماده:\n" + ("\n".join(
            f"{i + 1}. {p}" for i, p in enumerate(presets)) if presets else app.t("empty")))


@command("biorotate", "bio", "<دقیقه|off>", "چرخش خودکار بیو", "Rotating bio",
         bot_ok=True)
async def biorotate_cmd(app, ev, arg):
    v = arg.strip().lower()
    if v in ("off", "خاموش"):
        app.sets("biorotate_on", False)
        await ev.reply("⏹ چرخش بیو خاموش شد.")
        return
    try:
        minutes = int(v)
    except ValueError:
        await ev.reply("❌ `.biorotate 240` (دقیقه — حداقل ۶۰) یا `.biorotate off`")
        return
    if minutes < 60:
        minutes = 60
        await ev.reply("⚠️ برای امنیت اکانت حداقل ۶۰ دقیقه — ست شد روی ۶۰.")
    app.sets("biorotate_on", True)
    app.sets("biorotate_every", minutes)
    await ev.reply(f"🔁 بیو هر {minutes} دقیقه بین بیوهای آماده می‌چرخه.")


@command("setname", "bio", "<اسم جدید>", "تغییر اسم اصلی", "Change first name")
async def setname_cmd(app, ev, arg):
    if not arg.strip():
        await ev.reply("❌ `.setname Mohammad` — اسم اولت رو عوض می‌کنه (ساعت روی اسم آخر می‌شینه).")
        return
    new = arg.strip()[:63]
    app.sets("clock_first_base", new)
    ok, _, why = await app.gov.apply("first_name", new, force=True)
    await ev.reply("✏️ اسم اول عوض شد." if ok else f"⛔ {why}")


@command("username", "bio", "<یوزرنیم>", "تغییر یوزرنیم", "Change username")
async def username_cmd(app, ev, arg):
    u = arg.strip().lstrip("@")
    if not u:
        me = app.me
        await ev.reply(f"👤 یوزرنیم فعلی: @{getattr(me, 'username', None) or '—'}"
                       "\nبرای تغییر: `.username newname` (تلگرام محدودیت تغییر داره — کم و با فاصله)")
        return
    try:
        await app.client(functions.account.UpdateUsernameRequest(username=u))
        await ev.reply(f"✅ یوزرنیم: @{u}")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}: {str(e)[:150]}")
