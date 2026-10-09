"""AFK system: auto-reply with duration, reason, per-user cooldown, auto-return.

v2.4: redesigned reply message (clean structure + humanized durations) and
added `.afktext` so the owner can fully customize the template.
"""
import asyncio
import datetime
import logging
import random
import re
import time

from .. import jalali
from ..core import command, incoming_hook, outgoing_hook

log = logging.getLogger("seltbot.afk")

AFK_TOKENS_HELP = (
    "🧩 توکن‌های قالب پیام AFK:\n"
    "`{name}` → اسمِ همون کسی که پیام داده\n"
    "`{dur}` → مدت غیبت — خودکار «همین الان» / «۵ دقیقه» / «۲ ساعت و ۱۷ دقیقه»\n"
    "`{time}` → ساعت رفتن (مثل ۱۴:۰۲)\n"
    "`{reason}` → دلیل AFK (اگه گفته باشی؛ اگه نداده باشی این خط خودش حذف می‌شه)\n\n"
    "قالب پیش‌فرض:\n"
    "💤 {name} جان، فعلاً مشغول هستم\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "⏱ مدت غیبت: {dur}\n"
    "🕐 ساعت رفتن: {time}\n"
    "📝 دلیل: {reason}\n\n"
    "📬 پیامت پیش خودم می‌مونه؛ به محض برگشتن جواب می‌دم ✨\n\n"
    "برگردوندن پیش‌فرض: `.afktext reset`"
)


def _state(app):
    return app.db.setting("afk") or {"active": False, "since": 0, "reason": "", "hits": 0}


def _set(app, st):
    app.db.set_setting("afk", st)


def _dur_display(app, dur_s):
    """Humanized: 'همین الان' for fresh AFK instead of the silly '۳ ثانیه'."""
    if dur_s < 90:
        return "همین الان" if app.fa else "just now"
    return jalali.fmt_dur(dur_s, fa=app.fa)


def _build_afk_text(app, name, dur_s, since_ts, reason):
    """Render the AFK auto-reply: default (structured, pretty) or custom
    template from .afktext with {name}/{dur}/{time}/{reason} tokens."""
    since_ts = since_ts or time.time()
    try:
        hm = datetime.datetime.fromtimestamp(since_ts, app.tzinfo).strftime("%H:%M")
    except Exception:
        hm = datetime.datetime.now(app.tzinfo).strftime("%H:%M")
    if app.fa:
        hm = jalali.fa_digits(hm)
    dur = _dur_display(app, dur_s)
    reason = (reason or "").strip()

    tpl = str(app.s("afk_text", "") or "")
    if tpl:
        if not reason:
            # drop lines that only carried the reason token
            tpl = "\n".join(ln for ln in tpl.split("\n") if "{reason}" not in ln)
        out = (tpl.replace("{name}", str(name))
                  .replace("{dur}", dur)
                  .replace("{time}", hm)
                  .replace("{reason}", reason))
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out.strip()

    # default template — v2.5.2: «فعلاً مشغول هستم» (owner: «پیش نیستم»
    # بی‌معنیه)، «مدت غیبت» / «ساعت رفتن» (spelling-checked labels),
    # greeting → divider → info rows → warm closing. Short clean lines in
    # both official Telegram and forks.
    if app.fa:
        lines = [
            f"💤 {name} جان، فعلاً مشغول هستم",
            "━━━━━━━━━━━━━━━━━━",
        ]
        if dur_s < 90:
            lines.append("⏱ تازه رفتم")
        else:
            lines.append(f"⏱ مدت غیبت: {dur}")
        lines.append(f"🕐 ساعت رفتن: {hm}")
        if reason:
            lines.append(f"📝 دلیل: {reason}")
        lines += [
            "",
            "📬 پیامت پیش خودم می‌مونه؛ به محض برگشتن جواب می‌دم ✨",
        ]
        return "\n".join(lines)
    lines = [
        f"💤 {name}, I'm busy at the moment",
        "━━━━━━━━━━━━━━━━━━",
        ("⏱ Just left" if dur_s < 90 else f"⏱ Away for {dur}"),
        f"🕐 Left at {hm}",
    ]
    if reason:
        lines.append(f"📝 {reason}")
    lines += [
        "",
        "📬 Your message is safe with me — I'll reply as soon as I'm back ✨",
    ]
    return "\n".join(lines)


@command("afk", "afk", "[دلیل]", "فعال‌کردن AFK", "Enable AFK mode", bot_ok=True)
async def afk_cmd(app, ev, arg):
    st = _state(app)
    st.update({"active": True, "since": time.time(),
               "reason": arg.strip(), "hits": st.get("hits", 0)})
    _set(app, st)
    if app.fa:
        msg = "💤 AFK روشن شد." + (f"\n📝 دلیل: {arg.strip()}" if arg.strip() else "")
        msg += "\nبه هر کی پیام بده، خودم با مدت و ساعت رفتنم جواب می‌دم."
        msg += "\n🎨 برای شخصی‌سازی قالب پیام: `.afktext`"
    else:
        msg = "💤 AFK enabled." + (f"\n📝 {arg.strip()}" if arg.strip() else "")
    await ev.reply(msg)


@command("unafk", "afk", "", "خاموش‌کردن AFK", "Disable AFK", bot_ok=True)
async def unafk_cmd(app, ev, arg):
    st = _state(app)
    if not st.get("active"):
        # v2.7.2: the outgoing hook already processed the auto-return seconds
        # ago (any message from the owner deactivates AFK) — stay silent
        # instead of contradicting the “خوش برگشتی” note that just went out.
        if time.time() - float(st.get("last_return") or 0) < 60:
            return
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


@command("afktext", "afk", "<قالب>", "قالب پیام AFK (شخصی‌سازی)",
         "Custom AFK reply template", bot_ok=True)
async def afktext_cmd(app, ev, arg):
    a = arg.strip()
    if not a:
        cur = str(app.s("afk_text", "") or "")
        head = ("قالب فعلی (پیش‌فرضِ مرتب):") if not cur else ("قالب فعلی:\n`" + cur + "`")
        await ev.reply(head + "\n\n" + AFK_TOKENS_HELP if not cur else head + "\n\n" + AFK_TOKENS_HELP)
        return
    if a.lower() in ("reset", "ریست", "پیش‌فرض", "default"):
        app.dels("afk_text")
        await ev.reply("✅ قالب پیام AFK به پیش‌فرضِ مرتب برگشت.")
        return
    app.sets("afk_text", a)
    sample = _build_afk_text(app, "علی", 305, time.time() - 305,
                             "فعلاً در دسترس نیستم")
    await ev.reply("✅ قالب ذخیره شد. نمونه (به‌جای «علی»، اسمِ همون کسی می‌شینه که پیام داده):\n\n"
                   + sample + "\n\n" + AFK_TOKENS_HELP)


async def _return(app, ev, st):
    dur = jalali.fmt_dur(time.time() - st.get("since", time.time()), fa=app.fa)
    hits = st.get("hits", 0)
    # v2.7.2: last_return lets `.unafk` know the outgoing hook already
    # greeted moments ago (any owner message auto-returns AFK) — before,
    # unafk then ALSO replied “AFK که فعال نیست” — contradictory double reply.
    _set(app, {"active": False, "since": 0, "reason": "", "hits": 0,
               "last_return": time.time()})
    text = (f"👋 خوش برگشتی! AFK بود: {dur} • {hits} جواب خودکار فرستادم."
            if app.fa else f"👋 Welcome back! AFK {dur} • {hits} auto-replies.")
    # v2.7.2: ev=None means the auto-return was triggered by the owner simply
    # TYPING somewhere — the greeting goes to Saved Messages ONLY. Replying
    # into that chat leaked “خوش برگشتی” into groups in front of everyone.
    if ev is not None:
        await ev.reply(text)
    else:
        try:
            await app.send_saved("💤 " + text)
        except Exception:
            log.exception("afk return note failed")


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
    since = st.get("since", time.time())
    dur_s = time.time() - since
    reason = (st.get("reason") or "").strip()
    # v2.5.2: the greeting carries the REAL sender's name (clickable mention
    # when possible). Names containing markdown-breaking chars ([ ] ( )) would
    # corrupt the mention link → fall back to the plain name.
    first = str(getattr(sender, "first_name", None)
                or getattr(sender, "username", None)
                or getattr(sender, "id", "?"))
    if any(c in first for c in "[]()\\"):
        name = app.user_link(sender, plain=True)
    else:
        name = app.user_link(sender, plain=False)
    txt = _build_afk_text(app, name, dur_s, since, reason)
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
        # v2.7.2: pass ev=None — the owner may be typing in a GROUP; the
        # “welcome back” note must land in Saved Messages, never in that chat.
        await _return(app, None, st)
    except Exception:
        log.exception("afk auto-return failed")
    return False
