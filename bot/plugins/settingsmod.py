"""Settings: view/set keys, language, timezone, prefix, module on/off."""
import logging

from ..core import MODULES, PROTECTED_MODULES, command

log = logging.getLogger("seltbot.settings")

EDITABLE = {
    "lang": "fa|en",
    "tz": "منطقهٔ زمانی (مثل Asia/Tehran)",
    "prefix": "پیشوند دستورات (مثل .)",
    "delcmd": "true/false حذف پیام دستور بعد از اجرا",
    "clock_interval": "فاصلهٔ آپدیت ساعت (ثانیه)",
    "clock_bio_interval": "فاصلهٔ آپدیت ساعت بیو",
    "clock_digits": "mono|ascii|fa",
    "clock_template": "قالب ساعت",
    "safety_daily_updates": "سقف روزانهٔ آپدیت پروفایل",
    "afk_cooldown": "فاصلهٔ تکرار جواب AFK به یک نفر (ثانیه)",
    "autoreply_on": "true/false",
    "autoreply_delay": "تأخیر پاسخ خودکار (ثانیه)",
    "autoreply_cooldown": "کول‌داون پاسخ خودکار (ثانیه)",
    "autoreply_hours": "ساعات کاری مثل 9-18",
    "autoreply_groups": "true/false پاسخ در گروه‌ها",
    "filters_cooldown": "کول‌داون فیلترها (ثانیه)",
    "notify_mentions": "true/false اعلان منشن‌ها",
    "ai_model": "اسم مدل AI",
    "ai_prompt": "شخصیت AI",
}


@command("settings", "settingsmod", "", "نمایش تنظیمات", "Show settings", bot_ok=True)
async def settings_cmd(app, ev, arg):
    lines = ["⚙️ **تنظیمات کلیدی**"]
    for k, hint in EDITABLE.items():
        v = app.s(k)
        lines.append(f"• `{k}` = `{v}` — {hint}")
    lines.append("\nبرای تغییر: `.set <کلید> <مقدار>`")
    await ev.reply("\n".join(lines)[:3800])


@command("set", "settingsmod", "<کلید> <مقدار>", "تغییر تنظیم", "Set a setting",
         bot_ok=True)
async def set_cmd(app, ev, arg):
    parts = arg.split(None, 1)
    if len(parts) < 2:
        await ev.reply("❌ `.set lang en` — کلیدهای موجود رو با .settings ببین.")
        return
    k, v = parts[0].strip(), parts[1].strip()
    if k not in EDITABLE:
        await ev.reply(f"⛔ کلید `{k}` قابل تنظیم نیست — .settings رو ببین.")
        return
    import json
    try:
        parsed = json.loads(v)
    except Exception:
        parsed = v
    app.sets(k, parsed)
    await ev.reply(f"✅ `{k}` = `{parsed}`")


@command("on", "settingsmod", "<ماژول>", "روشن‌کردن ماژول", "Enable module", bot_ok=True)
async def on_cmd(app, ev, arg):
    name = arg.strip().lower()
    if name not in MODULES:
        await ev.reply(app.t("module_unknown"))
        return
    off = app.s("modules_off", []) or []
    if name in off:
        off.remove(name)
        app.sets("modules_off", off)
    await app.start_module(name)
    await ev.reply(f"✅ ماژول `{name}` روشن شد.")


@command("off", "settingsmod", "<ماژول>", "خاموش‌کردن ماژول", "Disable module",
         bot_ok=True)
async def off_cmd(app, ev, arg):
    name = arg.strip().lower()
    if name not in MODULES:
        await ev.reply(app.t("module_unknown"))
        return
    if name in PROTECTED_MODULES:
        await ev.reply("⛔ این ماژول لازمه — خاموش نمی‌شه.")
        return
    off = app.s("modules_off", []) or []
    if name not in off:
        off.append(name)
        app.sets("modules_off", off)
    await app.stop_module(name)
    await ev.reply(f"⛔ ماژول `{name}` خاموش شد.")


@command("lang", "settingsmod", "fa|en", "تغییر زبان", "Set language", bot_ok=True)
async def lang_cmd(app, ev, arg):
    v = arg.strip().lower()
    if v not in ("fa", "en"):
        await ev.reply("❌ `.lang fa` یا `.lang en`")
        return
    app.sets("lang", v)
    await ev.reply("✅ زبان: فارسی" if v == "fa" else "✅ Language: English")


@command("reset", "settingsmod", "<کلید>", "ریست یک تنظیم به پیش‌فرض", "Reset a key",
         bot_ok=True)
async def reset_cmd(app, ev, arg):
    k = arg.strip()
    if not k:
        await ev.reply(app.t("no_arg"))
        return
    app.dels(k)
    await ev.reply(f"↩️ `{k}` ریست شد.")
