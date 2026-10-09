"""IF-THEN automation rules + anti-spam shield.

قوانین «اگر ... آنگاه ...» — هر اتفاقی در چت‌ها افتاد، خودکار واکنش نشون بده.

مثال‌ها:
  .rule add kw:سلام -> reply:سلام علیکم
  .rule add re:^\\?+ -> reply:سوالت رو واضح‌تر بپرس
  .rule add from:123456789 -> reply:سلام! الان نمی‌تونم جواب بدم
  .rule add media:link -> del
  .rule add media:sticker -> react:❤️
  .rule add kw:فوری -> alert:کسی کلمهٔ فوری رو گفت
  .rule add kw:قرارداد -> note:قرارداد
  .rule add chat:-100123456 -> reply:این چت فقط اطلاع‌رسانیه

تریگرها (اگر):  kw کلمه | re رجکس | from کاربر | chat چت | media نوع مدیا
اکشن‌ها (آنگاه): reply متن | del حذف | react ایموجی | alert هشدار | fwd فروارد | note نوت

نخستین قاعدهٔ همسان اجرا می‌شه (first-match). سقف ساعتی داره (ضدبن).
آنتی‌اسپم: .antispam on — هرکس در ۱۰ ثانیه بیشتر از حد مجاز پیام بده، پیام‌هاش حذف می‌شه (اگه ادمین باشی) + هشدار می‌گیری.
"""
import asyncio
import logging
import re
import time
from collections import deque

from telethon.tl import functions, types

from ..core import command, incoming_hook

log = logging.getLogger("seltbot.rules")

TRIGS = ("kw", "re", "from", "chat", "media")
ACTS = ("reply", "del", "react", "alert", "fwd", "note")
MEDIA_KINDS = ("any", "photo", "video", "gif", "sticker", "voice", "audio",
               "file", "link")

RULES_HELP = """🧩 **قوانین اگر-آنگاه**

ساختار:
`.rule add <تریگر>:<مقدار> -> <اکشن>:<مقدار>`

تریگرها:
• `kw:کلمه` — اگه کلمه‌ای در متن باشه
• `re:الگو` — رجکس روی متن
• `from:آیدی` — پیامِ کاربر خاص (آیدی عددی یا @یوزرنیم)
• `chat:آیدی` — فقط در چت خاص
• `media:نوع` — any/photo/video/gif/sticker/voice/audio/file/link

اکشن‌ها:
• `reply:متن` — جواب می‌ده
• `del` — پیام رو حذف می‌کنه (ادمین باشی)
• `react:👍` — ری‌اکشن می‌ذاره
• `alert:توضیح` — به Saved Messages هشدار می‌ده
• `fwd:saved` — فروارد به Saved (یا آیدی چت)
• `note:کلید` — متن پیام رو نوت می‌کنه

نمونه‌ها:
`.rule add kw:سلام -> reply:سلام علیکم`
`.rule add media:link -> del`
`.rule add kw:فوری -> alert:کلمهٔ فوری!`"""


def parse_rule(spec):
    """'kw:سلام -> reply:متن' → ('kw','سلام','reply','متن') یا None."""
    if "->" not in spec:
        return None
    left, right = spec.split("->", 1)

    def side(s, kinds, bare_ok=()):
        s = s.strip()
        for k in kinds:
            if s.lower().startswith(k + ":"):
                v = s[len(k) + 1:].strip()
                return (k, v) if v or k in ("media",) else None
        if s.lower() in bare_ok:
            return (s.lower(), "")
        return None

    trig = side(left, TRIGS)
    act = side(right, ACTS, bare_ok=("del",))
    if not trig or not act:
        return None
    if trig[0] == "media" and trig[1].lower() not in MEDIA_KINDS:
        return None
    if act[0] in ("reply", "react", "alert", "note") and not act[1]:
        return None
    if act[0] == "fwd" and not act[1]:
        act = ("fwd", "saved")
    return (trig[0], trig[1], act[0], act[1])


# ---------------- آنتی‌اسپم ----------------
_track = {}      # (chat, uid) -> deque[ts]
_jailed = {}     # (chat, uid) -> until ts
_last_alert = {}  # (chat, uid) -> ts


@incoming_hook()
async def antispam_incoming(app, event):
    if app.module_off("rules") or not app.s("antispam_on", False):
        return False
    chat_id = event.chat_id or 0
    if not chat_id or not app.auto_chat_ok(chat_id):
        return False
    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False) or getattr(sender, "broadcast", False):
        return False
    sid = getattr(sender, "id", 0)
    if not sid or app.authorized(sid) or app.is_blocked(sid):
        return False
    key = (chat_id, sid)
    now = time.time()
    dq = _track.setdefault(key, deque())
    dq.append(now)
    while dq and now - dq[0] > 10:
        dq.popleft()
    burst = max(3, int(app.s("antispam_burst", 8)))
    if len(dq) > burst:
        _jailed[key] = now + 120
    if not (_jailed.get(key, 0) > now):
        return False
    # در بازهٔ اسپم → پیام رو حذف کن (اگ حق داشته باشیم) + یک‌بار خبر بده
    try:
        await event.message.delete()
    except Exception:
        pass
    if time.time() - _last_alert.get(key, 0) > 3600:
        _last_alert[key] = time.time()
        try:
            where = app.s(f"chat_title_{chat_id}", None) or str(chat_id)
            who = app.user_link(sender, plain=True)
            await app.send_saved(
                f"🚨 آنتی‌اسپم: {who} در «{where}» بیشتر از {burst} پیام در ۱۰ ثانیه "
                f"فرستاد — ۲ دقیقه پیام‌هاش حذف می‌شه (اگ ادمین باشی).")
        except Exception:
            log.exception("antispam alert")
    return True


# ---------------- موتور قوانین ----------------
_hour_counter = {"hour": 0, "n": 0}


def _hour_used(app):
    h = int(time.time() // 3600)
    if _hour_counter["hour"] != h:
        _hour_counter.update(hour=h, n=0)
    _hour_counter["n"] += 1
    return _hour_counter["n"] <= max(3, int(app.s("rules_max_per_hour", 25)))


def _media_match(kind, msg, low):
    if kind == "link":
        return ("http://" in low) or ("https://" in low) or ("t.me/" in low)
    has = bool(msg.media or msg.photo)
    if kind == "any":
        return has or ("http://" in low) or ("https://" in low)
    if not has:
        return False
    return {
        "photo": bool(msg.photo),
        "video": bool(getattr(msg, "video", None)),
        "gif": bool(getattr(msg, "gif", None)),
        "sticker": bool(getattr(msg, "sticker", None)),
        "voice": bool(getattr(msg, "voice", None)),
        "audio": bool(getattr(msg, "audio", None)),
        "file": bool(getattr(msg, "document", None)) and not bool(getattr(msg, "audio", None)),
    }.get(kind, False)


def _bare_chat_id(x):
    """v2.7.2: normalize any chat-id style to the bare positive id.
    Telethon reports supergroups/channels as -100XXXXXXXXXX and basic groups
    as -XXXXX; users paste ids copied from `.id` (same style) or from Bot-API
    docs (also -100…). The old match compared `str(chat_id)` against
    `value.lstrip('-')` — the minus was stripped from ONE side only, so a
    `chat:-1001234` rule NEVER matched. Bare ids compare correctly for all
    styles."""
    try:
        n = abs(int(str(x).strip()))
    except (TypeError, ValueError):
        return None
    if n > 1000000000000:          # -100XXXXXXXXXX prefix
        n -= 1000000000000
    return n


def _trig_match(app, r, text, low, sender, event, msg):
    t, v = r["trig"], r["tval"]
    if t == "kw":
        return v.lower() in low
    if t == "re":
        try:
            return re.search(v, text) is not None
        except re.error:
            return False
    if t == "from":
        v = v.lstrip("@").lower()
        sid = str(getattr(sender, "id", "") or "")
        un = (getattr(sender, "username", None) or "").lower()
        return (sid and sid == v) or (un and un == v)
    if t == "chat":
        a, b = _bare_chat_id(event.chat_id), _bare_chat_id(v)
        if a is not None and b is not None:
            return a == b
        return str(event.chat_id or "") == v
    if t == "media":
        return _media_match(v.lower(), msg, low)
    return False


async def _do_action(app, event, r, sender, msg):
    a, v = r["act"], r["aval"]
    rid = r["id"]
    try:
        if a == "reply":
            if not app.limiter.allow(("rule_reply", event.chat_id), 30):
                return
            m = await event.reply(v[:3500])
            app.mark_bot_sent(m.id)
        elif a == "del":
            await msg.delete()
        elif a == "react":
            if not app.limiter.allow(("rule_react", event.chat_id), 30):
                return
            await app.client(functions.messages.SendReactionRequest(
                peer=await event.get_input_chat(), msg_id=msg.id,
                reaction=[types.ReactionEmoji(emoticon=v or "👍")]))
        elif a == "alert":
            where = app.s(f"chat_title_{event.chat_id}", None) or str(event.chat_id)
            who = app.user_link(sender, plain=True) if sender else "?"
            await app.send_saved(f"🔔 قاعدهٔ #{rid}: {who} در «{where}»"
                                 + (f" — {v}" if v else ""))
            try:
                await msg.forward_to("me")
            except Exception:
                pass
        elif a == "fwd":
            dest = v if v not in ("saved", "me", "self") else "me"
            await msg.forward_to(dest)
        elif a == "note":
            key = v.split()[0][:48] if v.split() else f"rule{rid}"
            text = (msg.raw_text or "").strip()
            app.db.note_save(key, text[:3000] if text else "(مدیا)")
    except Exception:
        log.exception("rule action failed")


@incoming_hook()
async def rules_incoming(app, event):
    if app.module_off("rules") or not app.s("rules_on", False):
        return False
    chat_id = event.chat_id or 0
    if not chat_id or not app.auto_chat_ok(chat_id):
        return False
    rows = app.db.rules_all()
    if not rows:
        return False
    sender = await event.get_sender()
    if sender is None or getattr(sender, "broadcast", False):
        return False
    sid = getattr(sender, "id", 0)
    if sid and (app.authorized(sid) or app.is_blocked(sid)):
        return False
    if getattr(sender, "bot", False):
        return False
    msg = event.message
    text = (msg.raw_text or "")
    low = text.lower()
    for r in rows:
        if not r["enabled"]:
            continue
        try:
            hit = _trig_match(app, r, text, low, sender, event, msg)
        except Exception:
            log.exception("rule match error #%s", r["id"])
            continue
        if hit:
            app.db.rule_hit(r["id"])
            if _hour_used(app):
                await _do_action(app, event, r, sender, msg)
            return True   # نخستین قاعدهٔ همسان
    return False


# ---------------- دستورات ----------------
@command("rule", "rules", "add <اگر> -> <آنگاه> | del N | on/off N",
         "قوانین اگر-آنگاه", "IF-THEN automation rules")
async def rule_cmd(app, ev, arg):
    parts = arg.split(None, 1)
    sub = (parts[0].lower() if parts else "help")
    rest = parts[1].strip() if len(parts) > 1 else ""
    if sub in ("help", "راهنما", ""):
        await ev.reply(RULES_HELP)
        return
    if sub == "add":
        parsed = parse_rule(rest)
        if not parsed:
            await ev.reply("❌ قالب درست نیست. مثال:\n"
                           "`.rule add kw:سلام -> reply:سلام علیکم`\n"
                           "راهنمای کامل: `.rule help`")
            return
        trig, tval, act, aval = parsed
        if not app.s("rules_on", False):
            app.sets("rules_on", True)
        rid = app.db.rule_add(trig, tval, act, aval)
        app.db.commit()
        await ev.reply(f"✅ قانون #{rid} ذخیره شد:\n"
                       f"اگر `{trig}:{tval}` ← آنگاه `{act}:{aval}`\n"
                       "(موتور قوانین روشن شد)")
    elif sub == "del":
        try:
            rid = int(rest)
        except ValueError:
            await ev.reply(app.t("bad_arg"))
            return
        await ev.reply(app.t("deleted") if app.db.rule_del(rid) else app.t("not_found"))
        app.db.commit()
    elif sub in ("on", "off"):
        if rest.isdigit():
            okk = app.db.rule_toggle(int(rest), sub == "on")
            await ev.reply(f"قانون #{rest} " + ("روشن" if sub == "on" else "خاموش")
                           + " شد." if okk else app.t("not_found"))
        else:
            app.sets("rules_on", sub == "on")
            await ev.reply("🧩 موتور قوانین " + ("روشن" if sub == "on" else "خاموش")
                           + " شد.")
    else:
        await ev.reply("❌ زیرفرمان: add | del | on | off | help")


@command("rules", "rules", "", "لیست قوانین اگر-آنگاه", "List IF-THEN rules",
         bot_ok=True)
async def rules_cmd(app, ev, arg):
    rows = app.db.rules_all()
    if not rows:
        await ev.reply("🧩 قانونی ثبت نشده. مثال:\n`.rule add kw:سلام -> reply:سلام علیکم`"
                       "\nراهنما: `.rule help`")
        return
    on = app.s("rules_on", False)
    lines = [f"🧩 **قوانین** (موتور: {'✅ روشن' if on else '⛔ خاموش'})"]
    for r in rows[:40]:
        state = "" if r["enabled"] else " ⏸"
        lines.append(f"• #{r['id']} `{r['trig']}:{r['tval']}` → "
                     f"`{r['act']}:{r['aval']}` ({r['hits']} بار){state}")
    await ev.reply("\n".join(lines)[:3800])


@command("clearrules", "rules", "", "پاک‌کردن همهٔ قوانین", "Clear all rules",
         bot_ok=True)
async def clearrules_cmd(app, ev, arg):
    app.db.rules_clear()
    app.db.commit()
    await ev.reply("🗑 همهٔ قوانین پاک شد.")


@command("antispam", "rules", "on|off|<حد>", "آنتی‌اسپم چت‌ها", "Anti-spam shield",
         bot_ok=True)
async def antispam_cmd(app, ev, arg):
    v = arg.strip().lower()
    if v in ("on", "روشن"):
        app.sets("antispam_on", True)
        await ev.reply(f"🛡 آنتی‌اسپم روشن شد — بیشتر از {app.s('antispam_burst', 8)} "
                       "پیام در ۱۰ ثانیه = حذف + هشدار.")
    elif v in ("off", "خاموش"):
        app.sets("antispam_on", False)
        await ev.reply("🛡 آنتی‌اسپم خاموش شد.")
    elif v.isdigit():
        n = max(3, int(v))
        app.sets("antispam_burst", n)
        await ev.reply(f"✅ حد اسپم: {n} پیام در ۱۰ ثانیه.")
    else:
        await ev.reply(f"🛡 آنتی‌اسپم: {'روشن' if app.s('antispam_on', False) else 'خاموش'}"
                       f" | حد: {app.s('antispam_burst', 8)}/10s\n"
                       "`.antispam on` / `.antispam off` / `.antispam 12`")
