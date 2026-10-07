"""Watcher — real "who is looking at you" notifications (stalker-lite).

⚠️ Honest scope (read this!): Telegram has NO profile-view tracking — by
design, for privacy. There is no API and no update event for "someone opened
my profile"; any bot claiming that is faking it. What DOES exist as real
MTProto events — and what this module notifies — is the closest real thing:

  1. ⌨️ someone TYPING to you in private chat   (raw UpdateUserTyping)
  2. 👁 someone READING your private messages    (raw UpdateReadHistoryOutbox)
  3. 🟢 a watched user coming ONLINE             (raw UpdateUserStatus)

(Story viewers — the only true "who viewed" — require Premium stories,
which this account doesn't have.)

All notifications are sent through the MANAGER BOT: this module performs
ZERO writes and ZERO extra API reads from your account — it only observes
updates Telegram already pushes. Zero added ban risk.

Commands:
  .watch            status
  .watch on|off     master switch (default ON)
  .watch add @user  add user to online-watch list (or reply to their msg)
  .watch del @user  remove from list
  .watch list       show watched users
"""
import asyncio
import logging
import time

from telethon import events
from telethon.tl import types
from telethon.tl.types import PeerUser

from ..core import command

log = logging.getLogger("seltbot.watcher")

# throttle windows (seconds) per (kind, user_id)
THROTTLE = {"typing": 300, "read": 60, "online": 900}
_last = {}          # (kind, uid) → ts
_names = {}         # uid → display name cache


def _throttled(kind, uid, now=None):
    """True if this (kind,user) was already notified inside its window."""
    now = now or time.time()
    key = (kind, uid)
    t = _last.get(key)
    if t is not None and now - t < THROTTLE.get(kind, 300):
        return True
    _last[key] = now
    return False


def _peer_uid(peer):
    """User id for PM peers; None for groups/channels (noise filter)."""
    return peer.user_id if isinstance(peer, PeerUser) else None


def _watched(app):
    try:
        return list(app.s("watch_users", []) or [])
    except Exception:
        return []


def _watch_ids(app):
    return {int(u.get("id")) for u in _watched(app) if u.get("id")}


async def _name(app, uid):
    if uid in _names:
        return _names[uid]
    n = app.db.setting(f"chat_title_{uid}")
    if not n:
        try:
            ent = await app.client.get_entity(int(uid))
            n = (getattr(ent, "first_name", None) or "") + " " + \
                (getattr(ent, "last_name", None) or "")
            n = n.strip() or (getattr(ent, "username", None) or f"#{uid}")
        except Exception:
            n = f"#{uid}"
    _names[uid] = str(n)[:48]
    return _names[uid]


async def _notify(app, text):
    """Manager-bot push (never writes from the account)."""
    try:
        await app.manager_send(app.owner_id, text, parse_mode=None)
    except Exception:
        log.exception("watch notify")


async def _on_raw(app, update):
    if app.stopping:
        return
    try:
        if not app.s("watch_on", True):
            return
        me_id = app.me.id if app.me else None

        if isinstance(update, types.UpdateUserTyping):
            uid = int(update.user_id)
            if uid == me_id or _throttled("typing", uid):
                return
            n = await _name(app, uid)
            await _notify(app, f"⌨️ {n} داره بهت پیام خصوصی می‌نویسه…")
            return

        if isinstance(update, types.UpdateReadHistoryOutbox):
            uid = _peer_uid(update.peer)
            if uid is None or uid == me_id or _throttled("read", uid):
                return
            n = await _name(app, uid)
            await _notify(app, f"👁 {n} پیام خصوصی‌ت رو خوند ✓")
            return

        if isinstance(update, types.UpdateUserStatus):
            uid = int(update.user_id)
            if uid == me_id or uid not in _watch_ids(app):
                return
            if not isinstance(update.status, types.UserStatusOnline):
                return  # only online transitions (less noise)
            if _throttled("online", uid):
                return
            n = await _name(app, uid)
            await _notify(app, f"🟢 {n} آنلاین شد")
            return
    except Exception:
        log.exception("watch on_raw")


async def start(app):
    """Register raw-update handlers on the live client."""
    if not app.client:
        return

    async def _raw(update):
        await _on_raw(app, update)

    app.client.add_event_handler(
        _raw,
        events.Raw(types=[
            types.UpdateUserTyping,
            types.UpdateReadHistoryOutbox,
            types.UpdateUserStatus,
        ]))
    log.info("watcher armed (typing/read/online)")


async def stop(app):
    _last.clear()


# ---------------------------------------------------------------- commands
def _status_lines(app):
    users = _watched(app)
    ids = ", ".join(u.get("name", f"#{u.get('id')}") for u in users[:15]) or "—"
    return [
        "👁 **دیده‌شدن و فعالیت (stalker-lite)**",
        "━━━━━━━━━━━━━━━━━━",
        f"• وضعیت: {'✅ فعال' if app.s('watch_on', True) else '⛔ غیرفعال'}",
        f"• افراد تحت نظر (آنلاین‌شدن): {len(users)}",
        f"• لیست: {ids}",
        "",
        "ℹ️ تلگرام «دیدن پروفایل» رو به هیچ رباتی نمی‌ده (حریم خصوصی) —",
        "پس این ماژول نزدیک‌ترین سیگنال‌های واقعی رو بهت می‌ده:",
        "⌨️ تایپ‌کردن برات · 👁 خوندن پیام خصوصی‌ت · 🟢 آنلاین‌شدن لیست تحت نظر",
    ]


async def _resolve(app, ev, token):
    """token = @username | numeric id | '' (use reply sender)."""
    if not token:
        r = await ev.get_reply_message() if getattr(ev, "message", None) else None
        if r and r.sender_id:
            return int(r.sender_id), None
        return None, "ریپلای روی پیامِ فرد بزن یا آیدی بده."
    token = token.strip()
    if token.isdigit():
        return int(token), None
    if token.startswith("@"):
        try:
            ent = await app.client.get_entity(token)
            return int(ent.id), None
        except Exception as e:
            return None, f"پیدا نشد: {e}"
    return None, "فرمت: @username یا عدد آیدی"


@command("watch", "watcher", "[on|off|add|del|list]", "اعلان دیدن و فعالیت",
         "Who-is-watching-you alerts", bot_ok=True)
async def watch_cmd(app, ev, arg):
    a = (arg or "").strip()
    low = a.lower()

    if low in ("", "status"):
        await ev.reply("\n".join(_status_lines(app)))
        return
    if low == "on":
        app.sets("watch_on", True)
        await ev.reply("✅ اعلان‌های دیده‌شدن/فعالیت روشن شد.")
        return
    if low == "off":
        app.sets("watch_on", False)
        await ev.reply("⛔ اعلان‌های دیده‌شدن/فعالیت خاموش شد.")
        return
    if low == "list":
        await ev.reply("\n".join(_status_lines(app)))
        return
    if low.startswith("add"):
        uid, err = await _resolve(app, ev, a[3:].strip())
        if err:
            await ev.reply("❌ " + err)
            return
        users = _watched(app)
        if any(int(u.get("id")) == uid for u in users):
            await ev.reply("ℹ️ این فرد از قبل تو لیسته.")
            return
        n = await _name(app, uid)
        users.append({"id": uid, "name": n})
        app.sets("watch_users", users)
        await ev.reply(f"✅ {n} به لیست تحت نظر اضافه شد — آنلاین‌شدنش رو خبر می‌دم.")
        return
    if low.startswith("del"):
        uid, err = await _resolve(app, ev, a[3:].strip())
        if err:
            # allow del by name too
            users = _watched(app)
            nm = a[3:].strip().lower()
            users = [u for u in users if str(u.get("name", "")).lower() != nm]
            app.sets("watch_users", users)
            await ev.reply("✅ حذف شد (اگه تو لیست بود).")
            return
        users = [u for u in _watched(app) if int(u.get("id")) != uid]
        app.sets("watch_users", users)
        await ev.reply("✅ از لیست تحت نظر حذف شد.")
        return
    await ev.reply("❌ `.watch on|off|add @user|del @user|list`")
