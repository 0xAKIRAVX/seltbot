"""Security: sudoers (allowed users), blocklist, authorization."""
import logging

from ..core import command

log = logging.getLogger("seltbot.security")


async def _resolve(app, s):
    s = s.strip()
    if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
        return int(s)
    if s.startswith("@"):
        try:
            ent = await app.client.get_entity(s)
            return ent.id
        except Exception:
            return None
    return None


@command("allow", "security", "<@user|id>", "دادن دستور به کاربر", "Add sudo user")
async def allow_cmd(app, ev, arg):
    if not arg.strip():
        await ev.reply("❌ `.allow @username` یا `.allow 12345678`")
        return
    uid = await _resolve(app, arg)
    if uid is None:
        await ev.reply(app.t("not_found") + " — یوزرنیم درست رو بده.")
        return
    if uid == app.owner_id:
        await ev.reply("این خودته 🙂")
        return
    app.db.sudo_add(uid)
    await ev.reply(f"✅ `{uid}` الان می‌تونه دستورات سلف‌بات رو اجرا کنه.")


@command("deny", "security", "<@user|id>", "گرفتن دسترسی", "Remove sudo user")
async def deny_cmd(app, ev, arg):
    if not arg.strip():
        await ev.reply(app.t("no_arg"))
        return
    uid = await _resolve(app, arg) if not arg.strip().isdigit() else int(arg.strip())
    if uid is None:
        await ev.reply(app.t("not_found"))
        return
    await ev.reply(app.t("removed") if app.db.sudo_del(uid) else app.t("not_found"))


@command("sudoers", "security", "", "لیست کاربران مجاز", "List sudo users", bot_ok=True)
async def sudoers_cmd(app, ev, arg):
    rows = app.db.sudoers()
    await ev.reply("👮 کاربران مجاز:\n" + ("\n".join(f"• `{u}`" for u in rows)
                                          if rows else "— فقط خودت —"))


@command("block", "security", "<@user|id>", "بلاک (بی‌خیال AFK/پاسخ خودکار)",
         "Block user from bot reactions")
async def block_cmd(app, ev, arg):
    if not arg.strip():
        await ev.reply(app.t("no_arg"))
        return
    uid = await _resolve(app, arg)
    if uid is None:
        await ev.reply(app.t("not_found"))
        return
    app.db.block_add(uid)
    await ev.reply(f"🚫 `{uid}` بلاک شد — دیگه جواب خودکار نمی‌گیره.")


@command("unblock", "security", "<@user|id>", "آن‌بلاک", "Unblock user")
async def unblock_cmd(app, ev, arg):
    if not arg.strip():
        await ev.reply(app.t("no_arg"))
        return
    uid = await _resolve(app, arg)
    if uid is None:
        await ev.reply(app.t("not_found"))
        return
    await ev.reply(app.t("removed") if app.db.block_del(uid) else app.t("not_found"))


@command("blocked", "security", "", "لیست بلاک‌شده‌ها", "List blocked users", bot_ok=True)
async def blocked_cmd(app, ev, arg):
    rows = app.db.blocked()
    await ev.reply("🚫 بلاک‌شده‌ها:\n" + ("\n".join(f"• `{u}`" for u in rows)
                                          if rows else "— خالی —"))
