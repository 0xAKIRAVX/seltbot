"""Settings: view/set keys, language, timezone, prefix, module on/off."""
import logging
import re

from ..core import MODULES, PROTECTED_MODULES, command

log = logging.getLogger("seltbot.settings")

# v2.8.0 — typed validation for .set. Before, ANY value was accepted: a typo
# like `.set clock_interval abc` stored a string, and the clock loop's
# int(...) then raised ValueError on EVERY tick → the clock silently died
# until someone dug into the logs. Same class of crash for the governor's
# daily budget, AFK/autoreply cooldowns, notify throttle, etc. Now each key
# carries a validator; junk is rejected with a Persian hint up front.
# (A second, defensive as_int() layer in core.py guards against values that
# were already stored junk — belt AND suspenders.)
_INT_KEYS = {
    "clock_interval": (15, 7200, "فاصلهٔ آپدیت ساعت (ثانیه) — بین ۱۵ و ۷۲۰۰"),
    "clock_bio_interval": (30, 86400, "فاصلهٔ آپدیت ساعت بیو — بین ۳۰ و ۸۶۴۰۰"),
    "safety_daily_updates": (100, 20000, "سقف روزانهٔ آپدیت پروفایل — بین ۱۰۰ و ۲۰۰۰۰"),
    "afk_cooldown": (10, 86400, "کول‌داون AFK (ثانیه) — بین ۱۰ و ۸۶۴۰۰"),
    "autoreply_cooldown": (10, 86400, "کول‌داون پاسخ خودکار (ثانیه) — بین ۱۰ و ۸۶۴۰۰"),
    "notify_throttle": (30, 86400, "فاصلهٔ اعلان‌های یک چت (ثانیه) — بین ۳۰ و ۸۶۴۰۰"),
    "filters_cooldown": (5, 86400, "کول‌داون فیلترها (ثانیه) — بین ۵ و ۸۶۴۰۰"),
    "rules_max_per_hour": (3, 1000, "سقف اجرای قوانین در ساعت — بین ۳ و ۱۰۰۰"),
    "antispam_burst": (3, 100, "حد اسپم — بین ۳ و ۱۰۰ پیام در ۱۰ ثانیه"),
}
_FLOAT_KEYS = {
    "autoreply_delay": (0.0, 300.0, "تأخیر پاسخ خودکار (ثانیه) — بین ۰ و ۳۰۰"),
}
_BOOL_KEYS = {"delcmd", "autoreply_on", "autoreply_groups", "notify_mentions"}
_DIGIT_KEYS_NOTE = "فونت ارقام — یکی از: bold/fa/mono/double/serif/full/ascii"


def validate_setting(app, k, v):
    """Return (ok, normalized_value, error_fa). v is the RAW string from .set."""
    from ..jalali import to_en_digits
    s = str(v).strip()
    if k in _INT_KEYS:
        lo, hi, hint = _INT_KEYS[k]
        try:
            n = int(to_en_digits(s))
        except ValueError:
            return False, None, f"⛔ `{k}` عدد می‌خواد — {hint}"
        if not (lo <= n <= hi):
            return False, None, f"⛔ `{k}` باید بین {lo} و {hi} باشه — {hint}"
        return True, n, None
    if k in _FLOAT_KEYS:
        lo, hi, hint = _FLOAT_KEYS[k]
        try:
            f = float(to_en_digits(s))
        except ValueError:
            return False, None, f"⛔ `{k}` عدد می‌خواد — {hint}"
        if not (lo <= f <= hi):
            return False, None, f"⛔ `{k}` باید بین {lo} و {hi} باشه — {hint}"
        return True, f, None
    if k in _BOOL_KEYS:
        t = s.lower()
        if t in ("true", "1", "on", "روشن", "yes"):
            return True, True, None
        if t in ("false", "0", "off", "خاموش", "no"):
            return True, False, None
        return False, None, f"⛔ `{k}` فقط true یا false می‌شه."
    if k == "lang":
        if s.lower() not in ("fa", "en"):
            return False, None, "⛔ `lang` فقط fa یا en می‌شه."
        return True, s.lower(), None
    if k == "tz":
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(s)
        except Exception:
            return False, None, "⛔ منطقهٔ زمانی نامعتبره — مثل Asia/Tehran"
        return True, s, None
    if k == "prefix":
        if not s or len(s) > 4 or " " in s:
            return False, None, "⛔ پیشوند باید ۱ تا ۴ حرف و بدون فاصله باشه (مثل . یا !)"
        return True, s, None
    if k == "clock_digits":
        if s.lower() not in ("bold", "fa", "mono", "double", "serif", "full", "ascii"):
            return False, None, f"⛔ {k}: {_DIGIT_KEYS_NOTE}"
        return True, s.lower(), None
    if k == "autoreply_hours":
        if s and not re.fullmatch(r"\d{1,2}\s*-\s*\d{1,2}", to_en_digits(s)):
            return False, None, "⛔ ساعات کاری اینجوری بده: 9-18"
        return True, s, None
    if k == "ai_url":
        if s and not s.lower().startswith(("http://", "https://")):
            return False, None, "⛔ آدرس AI باید با http:// یا https:// شروع بشه"
        return True, s, None
    # free-text keys (clock_template, clock_prefix/suffix, ai_key/model/prompt,
    # autoreply_offhours) — accepted as-is
    return True, s, None

EDITABLE = {
    "lang": "fa|en",
    "tz": "منطقهٔ زمانی (مثل Asia/Tehran)",
    "prefix": "پیشوند دستورات (مثل .)",
    "delcmd": "true/false حذف پیام دستور بعد از اجرا",
    "clock_interval": "فاصلهٔ آپدیت ساعت (ثانیه)",
    "clock_bio_interval": "فاصلهٔ آپدیت ساعت بیو",
    "clock_digits": "mono|ascii|fa",
    "clock_template": "قالب ساعت",
    "clock_prefix": "پیشوند ساعت (مثل 🕐)",
    "clock_suffix": "پسوند ساعت",
    "safety_daily_updates": "سقف روزانهٔ آپدیت پروفایل",
    "afk_cooldown": "فاصلهٔ تکرار جواب AFK به یک نفر (ثانیه)",
    "autoreply_on": "true/false",
    "autoreply_delay": "تأخیر پاسخ خودکار (ثانیه)",
    "autoreply_cooldown": "کول‌داون پاسخ خودکار (ثانیه)",
    "autoreply_hours": "ساعات کاری مثل 9-18",
    "autoreply_groups": "true/false پاسخ در گروه‌ها",
    "autoreply_offhours": "پیام خارج از ساعت کاری",
    "filters_cooldown": "کول‌داون فیلترها (ثانیه)",
    "notify_mentions": "true/false اعلان منشن‌ها",
    "notify_throttle": "فاصلهٔ اعلان‌های یک چت (ثانیه)",
    "rules_max_per_hour": "سقف اجرای قوانین در ساعت",
    "antispam_burst": "حد اسپم: چند پیام در ۱۰ ثانیه",
    "ai_url": "آدرس سرویس AI (مثل https://api.openai.com/v1)",
    "ai_key": "کلید API سرویس AI",
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
    # v2.8.0: typed validation — junk values used to crash the clock loop
    # (int('abc') every tick) and silently kill the 24/7 clock.
    ok, parsed, err = validate_setting(app, k, v)
    if not ok:
        await ev.reply(err)
        return
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
