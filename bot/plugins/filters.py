"""Per-chat keyword filters (someone says X in chat → bot replies Y)."""
import logging
import time

from ..core import as_int, command, incoming_hook

log = logging.getLogger("seltbot.filters")


@incoming_hook()
async def filters_incoming(app, event):
    if app.module_off("filters"):
        return False
    rows = app.db.filters_list(event.chat_id)
    if not rows:
        return False
    sender = await event.get_sender()
    if sender is None:
        return False
    if getattr(sender, "bot", False) or app.authorized(getattr(sender, "id", 0)):
        return False
    text = (event.message.raw_text or "").lower()
    for r in rows:
        if r["pattern"] and r["pattern"] in text:
            if not app.limiter.allow(("filter", event.chat_id),
                                     as_int(app.s("filters_cooldown", 300), 300, 5, 86400)):
                return False
            try:
                m = await event.reply(r["reply"])
                app.mark_bot_sent(m.id)
                app.db.filter_hit(r["id"])
            except Exception:
                log.exception("filter reply failed")
            return True
    return False


@command("filter", "filters", "<کلمه> -> <پاسخ>", "فیلتر کلمه در این چت",
         "Add chat keyword filter")
async def filter_cmd(app, ev, arg):
    import re
    m = re.split(r"\s*(?:->|=>|→|::)\s*", arg.strip(), maxsplit=1)
    if len(m) != 2 or not m[0].strip() or not m[1].strip():
        await ev.reply("❌ مثال: `.filter سلام -> سلام علیکم بچه‌ها`")
        return
    word, reply = m[0].strip().lower(), m[1].strip()
    app.db.filter_add(ev.chat_id, word, reply)
    await ev.reply(f"✅ فیلتر اضافه شد: «{word}» → جواب می‌دم.")


@command("filters", "filters", "", "لیست فیلترهای این چت", "List filters for this chat")
async def filters_cmd(app, ev, arg):
    rows = app.db.filters_list(ev.chat_id)
    if not rows:
        rows_all = app.db.filters_list()
        await ev.reply(app.t("empty") if not rows_all
                       else "📋 این چت فیلتری نداره — فیلترهای چت‌های دیگه: "
                            + str(len(rows_all)))
        return
    await ev.reply("📋 فیلترهای این چت:\n" + "\n".join(
        f"• #{r['id']} «{r['pattern']}» ({r['hits']} بار)" for r in rows[:30]))


@command("stop", "filters", "<کلمه>", "حذف فیلتر", "Remove a filter")
async def stop_cmd(app, ev, arg):
    if not arg.strip():
        await ev.reply(app.t("no_arg"))
        return
    await ev.reply(app.t("deleted") if app.db.filter_del(ev.chat_id, arg.strip().lower())
                   else app.t("not_found"))


@command("stopfilters", "filters", "", "پاک‌کردن فیلترهای این چت", "Clear chat filters")
async def stopfilters_cmd(app, ev, arg):
    app.db.filters_clear(ev.chat_id)
    await ev.reply("🗑 فیلترهای این چت پاک شد.")
