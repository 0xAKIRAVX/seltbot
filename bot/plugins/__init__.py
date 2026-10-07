"""Plugin loader: imports all modules and registers them into MODULES."""
import importlib

from ..core import MODULES, ModuleInfo

PLUGINS = [
    ("clock", "ساعت زنده در اسم/بیو", "Live clock in name/bio"),
    ("bio", "مدیریت بیو و اسم", "Bio & name manager"),
    ("afk", "حالت AFK", "AFK system"),
    ("autoreply", "پاسخ خودکار", "Auto reply"),
    ("filters", "فیلترهای چت", "Chat filters"),
    ("rules", "قوانین اگر-آنگاه + آنتی‌اسپم", "IF-THEN rules + anti-spam"),
    ("admintools", "ابزار گروه و کانال", "Group & channel tools"),
    ("notes", "نوت‌ها", "Notes"),
    ("scheduler", "زمان‌بند و یادآور", "Scheduler & reminders"),
    ("msgtools", "ابزار پیام", "Message tools"),
    ("utils", "ابزارهای کاربردی", "Utilities"),
    ("nettools", "ابزار شبکه", "Network tools"),
    ("search", "جستجو و اطلاعات", "Search & info"),
    ("media", "ابزار مدیا و عکس پروفایل", "Media tools"),
    ("ai", "هوش مصنوعی و خلاصه‌سازی", "AI & summarizer"),
    ("watcher", "اعلان دیدن و فعالیت", "Who-is-watching-you alerts"),
    ("security", "امنیت و دسترسی‌ها", "Security"),
    ("settingsmod", "تنظیمات", "Settings"),
    ("stats", "آمار", "Statistics"),
    ("notify", "اعلان‌ها", "Notifications"),
    ("helpmod", "راهنما و وضعیت", "Help & status"),
    ("pluginctl", "مدیریت ماژول‌ها", "Module control"),
]


def load_all():
    mods = {}
    for name, title_fa, title_en in PLUGINS:
        mod = importlib.import_module("." + name, __package__)
        mods[name] = mod
        MODULES[name] = ModuleInfo(name, title_fa, title_en,
                                   getattr(mod, "start", None),
                                   getattr(mod, "stop", None))
    return mods
