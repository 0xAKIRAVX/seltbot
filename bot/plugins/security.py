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


@command("autochats", "security",
         "mode all|wl|bl | add [آیدی] | del [آیدی] | list",
         "سفید/سیاه‌لیست چت‌ها برای قابلیت‌های خودکار", "Chat allow/deny list",
         bot_ok=True)
async def autochats_cmd(app, ev, arg):
    """کجاها AFK/پاسخ خودکار/قوانین/آنتی‌اسپم فعال باشن.
    mode all = همه (پیش‌فرض) | wl = فقط لیست | bl = همه جز لیست.
    بدون آیدی → همین چتی که توش هستی."""
    parts = arg.split(None, 1)
    sub = (parts[0].lower() if parts else "list")
    rest = parts[1].strip() if len(parts) > 1 else ""
    mode = app.s("auto_chats_mode", "all") or "all"
    lst = app.s("auto_chats_list", []) or []
    if sub == "mode":
        v = {"all": "all", "wl": "whitelist", "whitelist": "whitelist",
             "bl": "blacklist", "blacklist": "blacklist"}.get(rest.lower())
        if not v:
            await ev.reply("❌ `.autochats mode all|wl|bl`\n"
                           "all = همهٔ چت‌ها | wl = فقط چت‌های لیست | bl = همه جز لیست")
            return
        app.sets("auto_chats_mode", v)
        name = {"all": "همهٔ چت‌ها", "whitelist": "فقط چت‌های لیست (سفید)",
                "blacklist": "همه جز لیست (سیاه)"}[v]
        await ev.reply(f"✅ قابلیت‌های خودکار در: {name}")
    elif sub == "add":
        cid = int(rest) if (rest.lstrip("-").isdigit() and rest) else ev.chat_id
        if cid in lst:
            await ev.reply("از قبل توی لیسته.")
            return
        lst.append(cid)
        app.sets("auto_chats_list", lst)
        where = app.s(f"chat_title_{cid}", None) or str(cid)
        await ev.reply(f"✅ «{where}» به لیست اضافه شد ({len(lst)} مورد).")
    elif sub == "del":
        cid = int(rest) if (rest.lstrip("-").isdigit() and rest) else ev.chat_id
        if cid not in lst:
            await ev.reply("توی لیست نبود.")
            return
        lst.remove(cid)
        app.sets("auto_chats_list", lst)
        await ev.reply(f"🗑 حذف شد ({len(lst)} مورد مونده).")
    else:
        mode_fa = {"all": "همهٔ چت‌ها", "whitelist": "فقط سفید‌لیست",
                   "blacklist": "همه جز سیاه‌لیست"}.get(mode, mode)
        rows = "\n".join(
            f"• `{c}` — {app.s(f'chat_title_{c}', None) or '—'}" for c in lst[:20]) or "—"
        await ev.reply(f"🧭 قابلیت‌های خودکار (AFK/پاسخ/قوانین/آنتی‌اسپم): {mode_fa}\n"
                       f"چت‌های لیست:\n{rows}")
