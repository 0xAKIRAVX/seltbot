"""Auto-reply: keyword / per-user / catch-all rules with random texts,
delay, working hours, cooldowns."""
import asyncio
import json
import logging
import random
import time

from ..core import command, incoming_hook

log = logging.getLogger("seltbot.autoreply")


def _in_hours(app, spec):
    """'9-18' → True if current hour within range."""
    try:
        a, b = spec.split("-")
        a, b = int(a.strip()), int(b.strip())
        h = app.now().hour
        return a <= h < b if a <= b else (h >= a or h < b)
    except Exception:
        return True


@incoming_hook()
async def autoreply_incoming(app, event):
    if app.module_off("autoreply") or not app.s("autoreply_on", False):
        return False
    if not event.is_private and not app.s("autoreply_groups", False):
        return False
    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False) or getattr(sender, "broadcast", False):
        return False
    sid = getattr(sender, "id", 0)
    if not sid or app.is_blocked(sid) or app.authorized(sid):
        return False
    text = (event.message.raw_text or "").lower()
    hours = app.s("autoreply_hours", "") or ""
    offhours_text = None
    if hours and not _in_hours(app, hours):
        offhours_text = app.s("autoreply_offhours", "") or ""
        if not offhours_text:
            return False
    rules = app.db.reply_rules()
    if not rules and not offhours_text:
        return False
    matched = None
    for r in rules:
        if r["kind"] == "user":
            m = r["match"].lstrip("@").lower()
            un = (getattr(sender, "username", None) or "").lower()
            if str(sid) == r["match"] or (un and un == m):
                matched = r
                break
    if matched is None:
        for r in rules:
            if r["kind"] == "kw" and r["match"] and r["match"] in text:
                matched = r
                break
    if matched is None:
        for r in rules:
            if r["kind"] == "any":
                matched = r
                break
    if matched is None and not offhours_text:
        return False
    cd = int(app.s("autoreply_cooldown", 900))
    if time.time() - app.db.seen(sid, "ar") < cd:
        return False
    app.db.touch_seen(sid, "ar")
    try:
        texts = json.loads(matched["texts"]) if matched else []
    except Exception:
        texts = []
    body = random.choice(texts) if texts else ""
    if offhours_text:
        body = offhours_text
    if not body:
        return False
    delay = float(app.s("autoreply_delay", 3) or 3)
    await asyncio.sleep(max(0.5, random.uniform(delay * 0.6, delay * 1.4)))
    try:
        m = await event.reply(body[:3500])
        app.mark_bot_sent(m.id)
        if matched:
            app.db.reply_hit(matched["id"])
    except Exception:
        log.exception("autoreply failed")
    return True


@command("autoreply", "autoreply", "[on/off/status]",
         "پاسخ خودکار به پیام‌های خصوصی", "Auto-reply system", bot_ok=True)
async def autoreply_cmd(app, ev, arg):
    sub = (arg.split()[0].lower() if arg.split() else "status")
    if sub == "on":
        app.sets("autoreply_on", True)
        await ev.reply("🤖 پاسخ خودکار روشن شد.")
    elif sub == "off":
        app.sets("autoreply_on", False)
        await ev.reply("🤖 پاسخ خودکار خاموش شد.")
    else:
        rules = app.db.reply_rules()
        on = app.s("autoreply_on", False)
        hours = app.s("autoreply_hours", "") or "—"
        lines = [
            "🤖 **پاسخ خودکار**",
            f"• وضعیت: {'✅ روشن' if on else '⛔ خاموش'} • قوانین: {len(rules)}",
            f"• تأخیر پاسخ: {app.s('autoreply_delay', 3)}s | کول‌داون: {app.s('autoreply_cooldown', 900)}s",
            f"• ساعات کاری: {hours}",
        ]
        await ev.reply("\n".join(lines))


@command("addreply", "autoreply", "<کلمه|@کاربر|*> <متن|متن2>",
         "افزودن قانون پاسخ", "Add auto-reply rule", bot_ok=True)
async def addreply_cmd(app, ev, arg):
    parts = arg.split(None, 1)
    if len(parts) < 2:
        await ev.reply("❌ مثال:\n`.addreply سلام سلام! چطوری؟`\n"
                       "`.addreply @user الان نمی‌تونم`\n`.addreply * بیننده نیستم | برگشتم`")
        return
    match, body = parts[0].strip(), parts[1].strip()
    texts = [t.strip() for t in body.split("|") if t.strip()]
    if not texts:
        await ev.reply(app.t("bad_arg"))
        return
    if match == "*":
        kind, match = "any", "*"
    elif match.startswith("@"):
        kind = "user"
    else:
        kind = "kw"
    app.db.reply_rule_add(kind, match, texts)
    await ev.reply(f"✅ قانون {kind} اضافه شد برای «{match}»"
                   f" با {len(texts)} متن (تصادفی انتخاب می‌شه).")


@command("replies", "autoreply", "", "لیست قوانین پاسخ", "List reply rules", bot_ok=True)
async def replies_cmd(app, ev, arg):
    rows = app.db.reply_rules()
    if not rows:
        await ev.reply(app.t("empty"))
        return
    lines = []
    for r in rows:
        try:
            n = len(json.loads(r["texts"]))
        except Exception:
            n = 0
        lines.append(f"• #{r['id']} [{r['kind']}] «{r['match']}» ({n} متن، {r['hits']} بار)")
    await ev.reply("🤖 قوانین پاسخ:\n" + "\n".join(lines[:40]))


@command("delreply", "autoreply", "<id>", "حذف قانون پاسخ", "Delete reply rule", bot_ok=True)
async def delreply_cmd(app, ev, arg):
    try:
        rid = int(arg.strip())
    except ValueError:
        await ev.reply(app.t("bad_arg"))
        return
    await ev.reply(app.t("deleted") if app.db.reply_rule_del(rid) else app.t("not_found"))


@command("clearreplies", "autoreply", "", "پاک‌کردن همهٔ قوانین", "Clear all rules", bot_ok=True)
async def clearreplies_cmd(app, ev, arg):
    app.db.reply_rules_clear()
    await ev.reply("🗑 همهٔ قوانین پاسخ پاک شد.")
