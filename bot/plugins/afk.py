"""AFK system: auto-reply with duration, reason, per-user cooldown, auto-return."""
import asyncio
import logging
import random
import time

from .. import jalali
from ..core import command, incoming_hook, outgoing_hook

log = logging.getLogger("seltbot.afk")


def _state(app):
    return app.db.setting("afk") or {"active": False, "since": 0, "reason": "", "hits": 0}


def _set(app, st):
    app.db.set_setting("afk", st)


@command("afk", "afk", "[دلیل]", "فعال‌کردن AFK", "Enable AFK mode", bot_ok=True)
async def afk_cmd(app, ev, arg):
    st = _state(app)
    st.update({"active": True, "since": time.time(),
               "reason": arg.strip(), "hits": st.get("hits", 0)})
    _set(app, st)
    if app.fa:
        msg = "💤 AFK روشن شد." + (f"\n📝 دلیل: {arg.strip()}" if arg.strip() else "")
        msg += "\nهر کی پیام بده خودم جواب می‌دم و مدت رو می‌گم."
    else:
        msg = "💤 AFK enabled." + (f"\n📝 {arg.strip()}" if arg.strip() else "")
    await ev.reply(msg)


@command("unafk", "afk", "", "خاموش‌کردن AFK", "Disable AFK", bot_ok=True)
async def unafk_cmd(app, ev, arg):
    st = _state(app)
    if not st.get("active"):
        await ev.reply("AFK که فعال نیست 🙂")
        return
    await _return(app, ev, st)


@command("afkstatus", "afk", "", "وضعیت AFK", "AFK status", bot_ok=True)
async def afkstatus_cmd(app, ev, arg):
    st = _state(app)
    if not st.get("active"):
        await ev.reply("💤 AFK غیرفعاله.")
        return
    dur = jalali.fmt_dur(time.time() - st.get("since", time.time()), fa=app.fa)
    await ev.reply(f"💤 AFK فعال — مدت: {dur} • جواب‌های خودکار: {st.get('hits', 0)}"
                   + (f"\n📝 {st.get('reason', '')}" if st.get("reason") else ""))


async def _return(app, ev, st):
    dur = jalali.fmt_dur(time.time() - st.get("since", time.time()), fa=app.fa)
    hits = st.get("hits", 0)
    _set(app, {"active": False, "since": 0, "reason": "", "hits": 0})
    await ev.reply(f"👋 خوش برگشتی! AFK بود: {dur} • {hits} جواب خودکار فرستادم."
                   if app.fa else f"👋 Welcome back! AFK {dur} • {hits} auto-replies.")


@incoming_hook()
async def afk_incoming(app, event):
    if app.module_off("afk"):
        return False
    st = _state(app)
    if not st.get("active"):
        return False
    msg = event.message
    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False) or getattr(sender, "broadcast", False):
        return False
    sid = getattr(sender, "id", 0)
    if not sid or app.is_blocked(sid) or app.authorized(sid):
        return False
    if app.db.setting("afk_ignore_groups", False) and not event.is_private:
        return False
    text = (msg.raw_text or "")
    mentioned = False
    if event.is_private:
        mentioned = True
    else:
        me_un = getattr(app.me, "username", None)
        if me_un and f"@{me_un}" in text:
            mentioned = True
        elif msg.is_reply:
            try:
                r = await msg.get_reply_message()
                if r and r.out:
                    mentioned = True
            except Exception:
                pass
    if not mentioned:
        return False
    cd = int(app.s("afk_cooldown", 1800))
    if time.time() - app.db.seen(sid, "afk") < cd:
        return False
    app.db.touch_seen(sid, "afk")
    st["hits"] = st.get("hits", 0) + 1
    _set(app, st)
    dur = jalali.fmt_dur(time.time() - st.get("since", time.time()), fa=app.fa)
    reason = st.get("reason") or ""
    name = app.user_link(sender, plain=False)
    if app.fa:
        txt = f"{name} جان، من الان AFK هستم 💤\n⏱ مدت: {dur}"
        if reason:
            txt += f"\n📝 {reason}"
        txt += "\nبه محض برگشتم جواب می‌دم ✌️"
    else:
        txt = f"{name}, I'm AFK right now 💤\n⏱ Away for: {dur}"
        if reason:
            txt += f"\n📝 {reason}"
        txt += "\nI'll get back to you soon."
    try:
        await asyncio.sleep(random.uniform(1.5, 4.0))
        m = await event.reply(txt)
        app.mark_bot_sent(m.id)
    except Exception:
        log.exception("afk reply failed")
    return True


@outgoing_hook()
async def afk_outgoing(app, event):
    if app.module_off("afk"):
        return False
    st = _state(app)
    if not st.get("active"):
        return False
    try:
        await _return(app, event, st)
    except Exception:
        log.exception("afk auto-return failed")
    return False
