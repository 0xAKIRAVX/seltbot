"""Help & status: .help, .modules, .commands, .status, .start, .version."""
import logging
import os
import time

from .. import __version__, jalali
from ..core import COMMANDS, MODULES, PROTECTED_MODULES, command

log = logging.getLogger("seltbot.help")


@command("start", "helpmod", "", "شروع/راهنمای سریع", "Start & quick help", bot_ok=True)
async def start_cmd(app, ev, arg):
    fa = """🤖 **SeltBot v2** — سلف‌بات شخصیِ خودت

 سریع‌ترین راه: همین‌جا (یا توی **Saved Messages**) بنویس `.help`
 ساعت زنده کنار اسمت فعاله ✅

چند تا دستور پرکاربرد:
• `.afk دارم می‌رم بیرون` → جواب خودکار به پیام‌ها
• `.remind 30m شیر بخر` → یادآور
• `.save متن هرچی` → نوت (فراخوانی: #متن)
• `.weather تهران` • `.tr hello` • `.calc 2+2`
• `.status` → وضعیت کامل بات
"""
    en = """🤖 **SeltBot v2** — your personal self-bot

Type `.help` here (or in **Saved Messages**).
Live clock next to your name is ON ✅

Quick commands: `.afk reason` • `.remind 30m buy milk` •
`.save note text` • `.weather Tehran` • `.status`
"""
    await ev.reply(fa if app.fa else en)


@command("help", "helpmod", "[ماژول]", "راهنمای دستورات", "Full help", bot_ok=True)
async def help_cmd(app, ev, arg):
    name = arg.strip().lower()
    if name and name not in MODULES:
        await ev.reply(app.t("module_unknown"))
        return
    if name:
        info = MODULES[name]
        cmds = [c for c in COMMANDS.values() if c.module == name and not c.hidden]
        # dedupe by name (aliases map to same Cmd object)
        seen, uniq = set(), []
        for c in cmds:
            if c.name not in seen:
                seen.add(c.name)
                uniq.append(c)
        lines = [f"📦 **{info.title_fa}** (`{name}`)", ""]
        for c in uniq:
            d = c.d_fa if app.fa else c.d_en
            u = f" `{c.usage}`" if c.usage else ""
            lines.append(f"• `.{c.name}`{u} — {d}")
        await ev.reply("\n".join(lines)[:3900])
        return
    off = app.s("modules_off", []) or []
    lines = ["🤖 **ماژول‌های SeltBot** — `.help <اسم>` برای جزئیات", ""]
    for n, info in MODULES.items():
        state = "⛔" if n in off else "✅"
        lines.append(f"{state} `{n}` — {info.title_fa}")
    lines += ["", "💡 دستورات رو توی هر چتی از اکانت خودت بفرست (مثل Saved Messages)."
              " بات مدیریت هم همین دستورات رو با / اجرا می‌کنه."]
    await ev.reply("\n".join(lines)[:3900])


@command("modules", "helpmod", "", "لیست ماژول‌ها", "List modules", bot_ok=True)
async def modules_cmd(app, ev, arg):
    off = app.s("modules_off", []) or []
    await ev.reply("📦 ماژول‌ها:\n" + "\n".join(
        f"{'⛔' if n in off else '✅'} `{n}` — {i.title_fa}"
        for n, i in MODULES.items()))


@command("commands", "helpmod", "", "لیست همهٔ دستورات", "All commands", bot_ok=True)
async def commands_cmd(app, ev, arg):
    seen, uniq = set(), []
    for c in COMMANDS.values():
        if c.name not in seen and not c.hidden:
            seen.add(c.name)
            uniq.append(c)
    await ev.reply("⌨️ دستورات:\n" + " ".join(f"`.{c.name}`" for c in sorted(uniq, key=lambda x: x.module + x.name)))


@command("version", "helpmod", "", "نسخه", "Version", bot_ok=True)
async def version_cmd(app, ev, arg):
    await ev.reply(f"🤖 SeltBot v{__version__} — Telethon userbot")


@command("status", "helpmod", "", "وضعیت کامل", "Full status", bot_ok=True)
async def status_cmd(app, ev, arg):
    g = app.gov.status_line()
    off = app.s("modules_off", []) or []
    afk = app.db.setting("afk") or {}
    n_notes = len(app.db.notes_list() or [])
    n_tasks = len(app.db.tasks_all() or [])
    host = f"GitHub Actions run {app.run_id}" if app.run_id else "local"
    lines = [
        "📊 **وضعیت SeltBot**",
        f"• ⏱ آپ‌تایم شیفت: {app.uptime_str()} | باقی‌مانده: {app.deadline_in_str()}",
        f"• 🖥 هاست: {host}",
        f"• 👤 اکانت: {app.me.first_name if app.me else '?'} (`{app.owner_id}`)",
        f"• 🕐 ساعت: {'✅ روشن' if app.s('clock_on', True) else '⛔ خاموش'}"
        f" هر {app.s('clock_interval', 60)}s | آخرین: {g.get('last_name_write') or '—'}s پیش",
        f"• 🛡 ضدبن: backoff ×{g['backoff']} | strikes {g['strikes_1h']}"
        f" | بودجه {g['budget_used']}/{g['budget_cap']}",
        f"• 💤 AFK: {'فعال از ' + jalali.fmt_dur(time.time() - afk.get('since', time.time()), fa=True) if afk.get('active') else 'غیرفعال'}",
        f"• 🤖 پاسخ خودکار: {'روشن' if app.s('autoreply_on', False) else 'خاموش'}",
        f"• 📦 ماژول‌های خاموش: {', '.join(off) if off else '—'}",
        f"• 💾 دیتابیس: {app.db.size() // 1024}KB | نوت: {n_notes} | کارها: {n_tasks}",
        f"• 🌐 زبان: {app.lang} | تایم‌زون: {app.s('tz', 'Asia/Tehran')}",
    ]
    await ev.reply("\n".join(lines))
