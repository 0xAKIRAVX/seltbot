"""Message tools: delete, purge, edit, pin, forward, copy, react, info, id, json."""
import asyncio
import json as jsonlib
import logging

from telethon import errors
from telethon.tl import functions, types

from .. import jalali
from ..core import command

log = logging.getLogger("seltbot.msgtools")


@command("del", "msgtools", "[ریپلای]", "حذف پیام", "Delete message")
async def del_cmd(app, ev, arg):
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    target = reply or (getattr(ev, "message", None))
    if target is None:
        await ev.reply("❌ ریپلای کن روی پیامی که باید حذف بشه.")
        return
    try:
        await target.delete()
    except errors.RPCError as e:
        await ev.reply(f"⛔ نتونستم حذف کنم: {type(e).__name__}")
        return
    await ev.reply("🗑 حذف شد.")


@command("purge", "msgtools", "[تعداد]", "پاک‌کردن پیام‌های خودت از ریپلای تا اینجا",
         "Purge own messages")
async def purge_cmd(app, ev, arg):
    if getattr(ev, "message", None) is None:
        await ev.reply("⛔ فقط از اکانت خودت.")
        return
    reply = await ev.get_reply_message()
    if reply is None:
        await ev.reply("❌ روی اولین پیامِ بازه ریپلای کن (فقط پیام‌های خودت رو پاک می‌کنم).")
        return
    try:
        n = min(int(jalali.to_en_digits(arg.strip() or "100")), 200)
    except ValueError:
        n = 100
    from_id = reply.id
    msgs = await app.client.get_messages(ev.chat_id, limit=n,
                                         min_id=from_id - 1, reverse=False)
    own = [m for m in msgs if m.out]
    count = 0
    for m in own:
        try:
            await m.delete()
            count += 1
            await asyncio.sleep(0.4)
        except Exception:
            pass
    await ev.reply(f"🧹 {count} پیامِ خودت پاک شد (از {from_id} به بعد).")


@command("edit", "msgtools", "<متن جدید>", "ویرایش پیام خودت", "Edit own message")
async def edit_cmd(app, ev, arg):
    if getattr(ev, "message", None) is None:
        await ev.reply("⛔ فقط از اکانت خودت.")
        return
    reply = await ev.get_reply_message()
    target = reply if (reply and reply.out) else ev.message
    try:
        await target.edit(arg.strip() or "‌")
        await ev.reply("✏️ ویرایش شد." if target is reply else "✏️ همین پیام ویرایش شد.")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}: {str(e)[:150]}")


@command("pin", "msgtools", "[ریپلای]", "پین کردن پیام", "Pin message")
async def pin_cmd(app, ev, arg):
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    if reply is None:
        await ev.reply("❌ ریپلای لازمه.")
        return
    try:
        await app.client(functions.messages.UpdatePinnedMessageRequest(
            peer=await ev.get_input_chat(), message_id=reply.id, unpin=False))
        await ev.reply("📌 پین شد.")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}")


@command("unpin", "msgtools", "[ریپلای]", "آنپین", "Unpin message")
async def unpin_cmd(app, ev, arg):
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    if reply is None:
        await ev.reply("❌ ریپلای لازمه.")
        return
    try:
        await app.client(functions.messages.UpdatePinnedMessageRequest(
            peer=await ev.get_input_chat(), message_id=reply.id, unpin=True))
        await ev.reply("📌 آنپین شد.")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}")


@command("forward", "msgtools", "<چت>", "فروارد پیام ریپلای‌شده", "Forward message")
async def forward_cmd(app, ev, arg):
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    if reply is None or not arg.strip():
        await ev.reply("❌ ریپلای کن + مقصد بده: `.forward saved` یا `.forward @user` یا `.forward -100xxx`")
        return
    dest = arg.strip().lower()
    if dest in ("saved", "me", "self"):
        dest = "me"
    try:
        await reply.forward_to(dest)
        await ev.reply("➡️ فروارد شد.")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}: {str(e)[:150]}")


@command("copy", "msgtools", "[ریپلای]", "کپی پیام به پیام‌های ذخیره‌شده", "Copy to Saved")
async def copy_cmd(app, ev, arg):
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    if reply is None:
        await ev.reply("❌ ریپلای لازمه.")
        return
    try:
        if reply.media:
            await app.client.send_file("me", reply.media, caption=reply.raw_text or "")
        else:
            await app.send("me", reply.raw_text or "")
        await ev.reply("📋 به Saved Messages کپی شد.")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}")


@command("react", "msgtools", "<اموجی>", "ری‌اکشن به پیام", "React to message")
async def react_cmd(app, ev, arg):
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    if reply is None:
        await ev.reply("❌ ریپلای لازمه.")
        return
    emoji = arg.strip() or "👍"
    try:
        await app.client(functions.messages.SendReactionRequest(
            peer=await ev.get_input_chat(), msg_id=reply.id,
            reaction=[types.ReactionEmoji(emoticon=emoji)]))
        await ev.reply(f" {emoji} ری‌اکشن رفت.")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}")


@command("id", "msgtools", "", "شناسهٔ چت/پیام/کاربر", "Get IDs")
async def id_cmd(app, ev, arg):
    lines = [f"🆔 چت: `{ev.chat_id}`"]
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    if reply:
        sender = await reply.get_sender() if reply.sender_id else None
        lines.append(f"• پیام: `{reply.id}`")
        if reply.sender_id:
            lines.append(f"• فرستنده: `{reply.sender_id}`"
                         + (f" (@{sender.username})" if sender and getattr(sender, "username", None) else ""))
    await ev.reply("\n".join(lines))


@command("info", "msgtools", "[ریپلای|@user]", "اطلاعات کاربر/چت", "User/chat info")
async def info_cmd(app, ev, arg):
    target = None
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    if reply and reply.sender_id:
        target = await reply.get_sender()
    elif arg.strip():
        try:
            target = await app.client.get_entity(arg.strip())
        except Exception:
            target = None
    if target is not None and getattr(target, "first_name", None) is not None:
        full = ""
        try:
            u = await app.client(functions.users.GetFullUserRequest(id=target.id))
            full = getattr(u.full_user, "about", "") or ""
        except Exception:
            pass
        lines = [
            f"👤 **{target.first_name or ''} {target.last_name or ''}**".strip(),
            f"• آیدی: `{target.id}`",
            f"• یوزرنیم: @{target.username}" if getattr(target, "username", None) else "• یوزرنیم: —",
            f"• بیو: {full[:70]}" if full else "",
            f"• پریمیوم: {'✅' if getattr(target, 'premium', False) else '—'}",
        ]
        await ev.reply("\n".join(l for l in lines if l))
        return
    chat = await ev.get_chat()
    if chat is None:
        await ev.reply("❌ چیزی پیدا نشد.")
        return
    kind = "چت خصوصی" if getattr(chat, "is_private", False) else \
        ("گروه" if getattr(chat, "is_group", False) else
         ("سوپرگروه" if getattr(chat, "is_channel", False) and getattr(chat, "megagroup", False)
          else "کانال"))
    members = ""
    try:
        if getattr(chat, "is_group", False) or getattr(chat, "megagroup", False):
            res = await app.client(functions.messages.GetFullChatRequest(chat_id=chat.id))
            members = str(res.full_chat.participants_count)
    except Exception:
        try:
            res = await app.client(functions.channels.GetChannelsRequest(
                [await app.client.get_input_entity(chat.id)]))
            members = str(res.chats[0].participants_count) if res.chats else ""
        except Exception:
            pass
    lines = [f"💬 **{getattr(chat, 'title', None) or getattr(chat, 'first_name', '?')}**",
             f"• نوع: {kind}", f"• آیدی: `{chat.id}`"]
    if members:
        lines.append(f"• اعضا: {members}")
    if getattr(chat, "username", None):
        lines.append(f"• یوزرنیم: @{chat.username}")
    await ev.reply("\n".join(lines))


@command("msgjson", "msgtools", "[ریپلای]", "JSON خام پیام (در Saved)", "Raw message JSON")
async def msgjson_cmd(app, ev, arg):
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    if reply is None:
        await ev.reply("❌ ریپلای لازمه.")
        return
    try:
        d = reply.to_dict()
        js = jsonlib.dumps(d, ensure_ascii=False, indent=1, default=str)[:3500]
        await app.send_saved("🔧 JSON پیام:\n```json\n" + js + "\n```")
        await ev.reply("📤 به Saved Messages فرستاده شد.")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}")


@command("common", "msgtools", "[ریپلای]", "گروه‌های مشترک با کاربر", "Common groups")
async def common_cmd(app, ev, arg):
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    if reply is None or not reply.sender_id:
        await ev.reply("❌ روی پیام کاربر ریپلای کن.")
        return
    try:
        res = await app.client(functions.messages.GetCommonChatsRequest(
            user_id=reply.sender_id, max_id=0, limit=50))
        names = [getattr(c, "title", "?") for c in res.chats]
        await ev.reply("👥 گروه‌های مشترک:\n" + ("\n".join("• " + n for n in names[:30])
                                                if names else "—"))
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}")


@command("offline", "msgtools", "", "آنلاین‌نمایی خاموش", "Appear offline")
async def offline_cmd(app, ev, arg):
    try:
        await app.client(functions.account.UpdateStatusRequest(offline=True))
        await ev.reply("🌙 حالت آفلاین فعال شد.")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}")


@command("online", "msgtools", "", "آنلاین‌نمایی روشن", "Appear online")
async def online_cmd(app, ev, arg):
    try:
        await app.client(functions.account.UpdateStatusRequest(offline=False))
        await ev.reply("☀️ آنلاین شدی.")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}")
