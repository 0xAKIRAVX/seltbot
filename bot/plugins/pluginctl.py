"""Module control: list plugins, restart shift, update code, health self-check."""
import logging
import os

from ..core import MODULES, PROTECTED_MODULES, command

log = logging.getLogger("seltbot.pluginctl")


@command("plugins", "pluginctl", "", "لیست پلاگین‌ها", "List plugins", bot_ok=True)
async def plugins_cmd(app, ev, arg):
    off = app.s("modules_off", []) or []
    lines = ["🧩 پلاگین‌ها:"]
    for n, i in MODULES.items():
        state = "⛔" if n in off else "✅"
        prot = " 🔒" if n in PROTECTED_MODULES else ""
        lines.append(f"{state} `{n}` — {i.title_fa}{prot}")
    lines.append("\n💡 کد پلاگین‌ها توی `bot/plugins/` هست — فایل جدید = ماژول جدید.")
    await ev.reply("\n".join(lines)[:3500])


@command("restart", "pluginctl", "", "ری‌استارت تمیز شیفت", "Clean restart", bot_ok=True)
async def restart_cmd(app, ev, arg):
    await ev.reply("🔄 شیفت ری‌استارت می‌شه — ۱-۲ دقیقه برمی‌گردم.")
    app.stop_reason = "restart"
    import asyncio
    asyncio.get_event_loop().call_later(2, lambda: asyncio.ensure_future(app.graceful("restart")))


@command("update", "pluginctl", "", "آپدیت کد + ری‌استارت", "Update & restart", bot_ok=True)
async def update_cmd(app, ev, arg):
    await ev.reply("🔄 کد جدید از گیت هاب میاد و شیفت ری‌استارت می‌شه.")
    app.stop_reason = "restart"
    import asyncio
    asyncio.get_event_loop().call_later(2, lambda: asyncio.ensure_future(app.graceful("update-restart")))


@command("health", "pluginctl", "", "سلامت خودکار", "Health self-check", bot_ok=True)
async def health_cmd(app, ev, arg):
    checks = []
    checks.append(("اتصال تلگرام", "✅" if app.client and app.client.is_connected() else "⛔"))
    checks.append(("بات مدیریت", "✅" if app.manager_token else "— تنظیم نشده"))
    exp = app.db.setting("clock_expected", {}) or {}
    checks.append(("ساعت", "✅ فعال" if app.s("clock_on", True) else "⛔ خاموش"))
    try:
        import aiohttp  # noqa
        checks.append(("HTTP session", "✅"))
    except Exception:
        checks.append(("HTTP session", "⛔"))
    free = os.statvfs(".").f_bavail * os.statvfs(".").f_frsize // (1024 * 1024) \
        if hasattr(os, "statvfs") else "?"
    checks.append(("فضای دیسک", f"✅ {free}MB"))
    await ev.reply("🩺 سلامت:\n" + "\n".join(f"• {k}: {v}" for k, v in checks))
