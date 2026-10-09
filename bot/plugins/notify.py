"""Notifications: mention alerts + keyword alerts → Saved Messages."""
import logging
import time

from ..core import as_int, command, incoming_hook

log = logging.getLogger("seltbot.notify")


@incoming_hook()
async def notify_incoming(app, event):
    if app.module_off("notify"):
        return False
    alerts = app.db.alerts_all()
    mentions_on = app.s("notify_mentions", False)
    if not alerts and not mentions_on:
        return False
    msg = event.message
    sender = await event.get_sender()
    sid = getattr(sender, "id", 0) or 0
    if sid and (app.authorized(sid) or app.is_blocked(sid)):
        return False
    if sid and getattr(sender, "bot", False):
        return False
    text = (msg.raw_text or "")
    low = text.lower()
    hit = next((a for a in alerts if a["value"] and a["value"] in low), None)
    mentioned = False
    if mentions_on and sid:
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
    if not hit and not mentioned:
        return False
    if not app.limiter.allow(("notify", event.chat_id),
                             as_int(app.s("notify_throttle", 600), 600, 30, 86400)):
        return False
    try:
        chat = await event.get_chat()
        where = (getattr(chat, "title", None) or getattr(chat, "first_name", None)
                 or str(event.chat_id))
        who = app.user_link(sender, plain=True) if sender else "کانال/ناشناس"
        why = f"کلمهٔ «{hit['value']}»" if hit else "منشن کرد"
        await app.send_saved(f"🔔 {who} در «{where}» → {why}")
        await msg.forward_to("me")
    except Exception:
        log.exception("notify delivery failed")
    return False


@command("notify", "notify", "mentions on|off", "اعلان منشن‌ها", "Mention alerts",
         bot_ok=True)
async def notify_cmd(app, ev, arg):
    sub = arg.strip().lower()
    if sub.endswith("on") or sub in ("روشن", "on"):
        app.sets("notify_mentions", True)
        await ev.reply("🔔 هر کی منشن‌ت کنه، تو Saved Messages خبر می‌گیری.")
    elif sub.endswith("off") or sub in ("خاموش", "off"):
        app.sets("notify_mentions", False)
        await ev.reply("🔕 اعلان منشن خاموش شد.")
    else:
        await ev.reply(f"منشن‌ها: {'روشن' if app.s('notify_mentions', False) else 'خاموش'}"
                       "\n`.notify on` / `.notify off`")


@command("alert", "notify", "add <کلمه> | list | del <id>", "هشدار کلمه‌کلیدی",
         "Keyword alerts", bot_ok=True)
async def alert_cmd(app, ev, arg):
    parts = arg.split(None, 1)
    sub = parts[0].lower() if parts else "list"
    rest = parts[1].strip() if len(parts) > 1 else ""
    if sub == "add":
        if not rest:
            await ev.reply("❌ `.alert add فوریت`")
            return
        app.db.alert_add("kw", rest.split()[0])
        await ev.reply(f"🔔 اگر کسی «{rest.split()[0]}» بنویسه، خبر می‌گیری.")
    elif sub == "del":
        try:
            aid = int(rest)
        except ValueError:
            await ev.reply(app.t("bad_arg"))
            return
        await ev.reply(app.t("deleted") if app.db.alert_del(aid) else app.t("not_found"))
    else:
        rows = app.db.alerts_all()
        await ev.reply("🔔 هشدارها:\n" + ("\n".join(
            f"• #{r['id']} «{r['value']}»" for r in rows) if rows else app.t("empty")))
