"""Group & channel tools: kick/ban/mute/unmute/admins/members/leave/join.

نکته: اکشن‌های مدیریتی فقط جایی کار می‌کنن که اکانت تو ادمین باشه
(خطای دقیق تلگرام رو همون‌جا می‌بینی). .join و .leave محدودیت نرخی دارن (ضدبن).
"""
import asyncio
import datetime
import logging

from telethon import errors
from telethon.tl import functions, types

from .. import jalali
from ..core import command

log = logging.getLogger("seltbot.admintools")


async def _target_user(app, ev, arg):
    """ریپلای → فرستنده؛ یا @username / آیدی عددی."""
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    if reply and reply.sender_id:
        return await reply.get_sender()
    q = arg.strip()
    if not q:
        return None
    try:
        return await app.client.get_entity(q if q.startswith("@") or q.isdigit()
                                           else "@" + q)
    except Exception:
        return None


async def _chat_of(app, ev):
    return await ev.get_input_chat() if hasattr(ev, "get_input_chat") else None


def _admin_err(e):
    name = type(e).__name__
    if "Admin" in name or "CHAT_ADMIN_REQUIRED" in str(e):
        return "⛔ برای این کار باید ادمین باشی."
    if "UserNotParticipating" in name:
        return "⛔ این کاربر عضو چت نیست."
    if "Bot" in name and "kick" in name.lower():
        return "⛔ نمی‌شه بات‌ها رو اخراج کرد."
    return f"⛔ {name}"


@command("kick", "admintools", "[ریپلای|@کاربر]", "اخراج از گروه", "Kick user")
async def kick_cmd(app, ev, arg):
    if getattr(ev, "is_bot_ev", False):
        await ev.reply("⛔ فقط از اکانت خودت توی همون چت.")
        return
    user = await _target_user(app, ev, arg)
    if user is None:
        await ev.reply("❌ ریپلای کن روی پیام کاربر یا: `.kick @username`")
        return
    if user.id == app.owner_id:
        await ev.reply("خودتی که هستی 🙂")
        return
    try:
        await app.client.kick_participant(ev.chat_id, user)
        await ev.reply(f"👢 {app.user_link(user)} اخراج شد.")
    except Exception as e:
        await ev.reply(_admin_err(e))


@command("ban", "admintools", "[ریپلای|@کاربر]", "بن کاربر در چت", "Ban user")
async def ban_cmd(app, ev, arg):
    if getattr(ev, "is_bot_ev", False):
        await ev.reply("⛔ فقط از اکانت خودت توی همون چت.")
        return
    user = await _target_user(app, ev, arg)
    if user is None:
        await ev.reply("❌ ریپلای کن یا: `.ban @username`")
        return
    if user.id == app.owner_id:
        await ev.reply("خودتی که هستی 🙂")
        return
    try:
        await app.client.edit_permissions(ev.chat_id, user, view_messages=False)
        await ev.reply(f"🔨 {app.user_link(user)} بن شد.")
    except Exception as e:
        await ev.reply(_admin_err(e))


@command("mute", "admintools", "[مدت] [ریپلای]", "میوت موقت", "Mute user")
async def mute_cmd(app, ev, arg):
    if getattr(ev, "is_bot_ev", False):
        await ev.reply("⛔ فقط از اکانت خودت توی همون چت.")
        return
    dur = jalali.parse_duration(arg.split()[0]) if arg.split() else None
    user_arg = " ".join(arg.split()[1:]) if dur else arg
    user = await _target_user(app, ev, user_arg)
    if user is None:
        await ev.reply("❌ مثال: `.mute 30m` (ریپلای روی کاربر) یا `.mute 2h @user`")
        return
    if user.id == app.owner_id:
        await ev.reply("خودتو که نمی‌شه میوت کرد 🙂")
        return
    try:
        await app.client.edit_permissions(
            ev.chat_id, user, send_messages=False,
            until=datetime.datetime.now() + datetime.timedelta(seconds=dur or 1800))
        await ev.reply(f"🔇 {app.user_link(user)} برای "
                       f"{jalali.fmt_dur(dur or 1800, fa=True)} میوت شد.")
    except Exception as e:
        await ev.reply(_admin_err(e))


@command("unmute", "admintools", "[ریپلای|@کاربر]", "آن‌میوت", "Unmute user")
async def unmute_cmd(app, ev, arg):
    if getattr(ev, "is_bot_ev", False):
        await ev.reply("⛔ فقط از اکانت خودت توی همون چت.")
        return
    user = await _target_user(app, ev, arg)
    if user is None:
        await ev.reply("❌ ریپلای کن یا: `.unmute @username`")
        return
    try:
        await app.client.edit_permissions(ev.chat_id, user, send_messages=True)
        await ev.reply(f"🔊 {app.user_link(user)} آزاد شد.")
    except Exception as e:
        await ev.reply(_admin_err(e))


@command("admins", "admintools", "", "لیست ادمین‌های چت", "List admins")
async def admins_cmd(app, ev, arg):
    if getattr(ev, "is_bot_ev", False):
        await ev.reply("⛔ فقط از اکانت خودت توی همون چت.")
        return
    try:
        parts = await app.client.get_participants(
            ev.chat_id, filter=types.ChannelParticipantsAdmins(), limit=50)
    except Exception as e:
        await ev.reply(_admin_err(e))
        return
    if not parts:
        await ev.reply("ℹ️ ادمینی نبود / چت معمولیه.")
        return
    lines = ["👮 ادمین‌ها:"]
    for u in parts[:40]:
        nm = (u.first_name or "") + (" " + u.last_name if getattr(u, "last_name", None) else "")
        extra = f" @{u.username}" if getattr(u, "username", None) else ""
        lines.append(f"• {nm} `{u.id}`{extra}")
    await ev.reply("\n".join(lines)[:3800])


@command("members", "admintools", "[تعداد]", "اعضای چت", "List members")
async def members_cmd(app, ev, arg):
    if getattr(ev, "is_bot_ev", False):
        await ev.reply("⛔ فقط از اکانت خودت توی همون چت.")
        return
    try:
        n = min(max(int(jalali.to_en_digits(arg.strip() or "20")), 1), 100)
    except ValueError:
        n = 20
    try:
        parts = await app.client.get_participants(ev.chat_id, limit=n)
    except Exception as e:
        await ev.reply(_admin_err(e))
        return
    if not parts:
        await ev.reply("ℹ️ عضوی دریافت نشد (چت معمولی/کانال ممکنه).")
        return
    lines = [f"👥 {len(parts)} عضو (از اول):"]
    for u in parts:
        nm = (u.first_name or "?") + (" " + u.last_name if getattr(u, "last_name", None) else "")
        lines.append(f"• {nm} `{u.id}`")
    await ev.reply("\n".join(lines)[:3800])


@command("leave", "admintools", "confirm", "ترک چت (با تأیید)", "Leave chat")
async def leave_cmd(app, ev, arg):
    if getattr(ev, "is_bot_ev", False):
        await ev.reply("⛔ فقط از اکانت خودت توی همون چت.")
        return
    if arg.strip().lower() not in ("confirm", "بله", "آره", "yes"):
        where = app.s(f"chat_title_{ev.chat_id}", None) or str(ev.chat_id)
        await ev.reply(f"⚠️ برای ترک «{where}» بنویس: `.leave confirm`\n"
                       "(قابل برگشت نیست مگه دوباره join بزنی)")
        return
    where = app.s(f"chat_title_{ev.chat_id}", None) or str(ev.chat_id)
    try:
        await app.client.delete_dialog(ev.chat_id)
        await app.send_saved(f"👋 چت «{where}» ترک شد.")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}")


@command("join", "admintools", "<لینک>", "عضویت در کانال/گروه", "Join via link")
async def join_cmd(app, ev, arg):
    if getattr(ev, "is_bot_ev", False):
        await ev.reply("⛔ فقط از اکانت خودت.")
        return
    link = arg.strip()
    if not link:
        await ev.reply("❌ `.join https://t.me/groupname` یا `.join https://t.me/+hash`")
        return
    if not app.limiter.allow("join_chat", 300):
        await ev.reply("⏳ عضویت‌های پشت‌سرهم خطرناکن — ۵ دقیقه فاصله بذار.")
        return
    link = link.replace("https://t.me/", "").replace("http://t.me/", "").strip("/")
    try:
        if link.startswith("+") or link.startswith("joinchat/"):
            h = link.lstrip("+").replace("joinchat/", "")
            await app.client(functions.messages.ImportChatInviteRequest(h))
        else:
            await app.client(functions.channels.JoinChannelRequest(
                await app.client.get_input_entity("@" + link.lstrip("@"))))
        await ev.reply(f"➕ عضو شدی: {link}")
    except errors.InviteHashExpiredError:
        await ev.reply("⛔ لینک منقضی شده.")
    except errors.UserAlreadyParticipantError:
        await ev.reply("ℹ️ از قبل عضوی.")
    except errors.FloodWaitError as e:
        await ev.reply(f"⏳ تلگرام گفت {e.seconds}s صبر کن — زیادی join زدی.")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}: {str(e)[:150]}")
