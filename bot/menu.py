"""Glass-button (inline keyboard) control panel for the manager bot.

/start → main menu with shiny inline buttons. Every button runs a REAL
command through the exact same engine as typed /.commands (app.run_command),
so the panel and text commands behave identically — one engine, two frontends.

callback_data schema (must stay ≤64 bytes):
  n/<page>      → navigate to page
  <action key>  → ACTIONS[key] = (cmd, arg) → run_command → re-render last page
"""
import logging

from .core import BotEv, bot_api

log = logging.getLogger("seltbot.menu")

_last_page = {}      # chat_id → page id (re-render target after actions)


# ---------------------------------------------------------------- buttons
def B(text, data):
    return {"text": text, "callback_data": data}


def grid(buttons, cols=2):
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]


BACK = [[B("⬅️ منوی اصلی", "n/main")]]


# ---------------------------------------------------------------- actions
# Every entry executes a real registered command (bot_ok=True only).
ACTIONS = {
    # — ساعت —
    "ck_on":      ("clock", "on"),
    "ck_off":     ("clock", "off"),
    "ck_fmt1":    ("clock", "text ｜ {hhm}:{mmm}"),
    "ck_fmt2":    ("clock", "text {jdate} ｜ {hhm}:{mmm}"),
    "ck_fmt3":    ("clock", "text {h12}:{mm} {ampm}"),
    "ck_fmt4":    ("clock", "text {name} ｜ {hhm}:{mmm}"),
    "ck_dg_mono": ("clock", "digits mono"),
    "ck_dg_fa":   ("clock", "digits fa"),
    "ck_dg_asc":  ("clock", "digits ascii"),
    "ck_bio_on":  ("clock", "bio on"),
    "ck_bio_off": ("clock", "bio off"),
    "ck_restore": ("restore", ""),
    # — AFK —
    "afk_on":     ("afk", "فعلاً در دسترس نیستم"),
    "afk_off":    ("unafk", ""),
    # — پاسخ خودکار —
    "ar_on":      ("autoreply", "on"),
    "ar_off":     ("autoreply", "off"),
    "ar_list":    ("replies", ""),
    # — قوانین اگر-آنگاه —
    "rl_on":      ("rule", "on"),
    "rl_off":     ("rule", "off"),
    "rl_list":    ("rules", ""),
    "rl_clear":   ("clearrules", ""),
    # — آنتی‌اسپم —
    "as_on":      ("antispam", "on"),
    "as_off":     ("antispam", "off"),
    # — نوت‌ها —
    "nt_list":    ("notes", ""),
    "nt_clear":   ("clearnotes", ""),
    # — زمان‌بند —
    "sc_list":    ("scheduled", ""),
    "sc_clear":   ("cleartasks", ""),
    # — هوش مصنوعی —
    "ai_test":    ("ai", "سلام! یه جمله درباره خودت بگو"),
    "ai_status":  ("aistatus", ""),
    "ai_reset":   ("aireset", ""),
    # — دیده‌شدن و فعالیت —
    "wt_on":      ("watch", "on"),
    "wt_off":     ("watch", "off"),
    "wt_list":    ("watch", "list"),
    # — آمار —
    "st_stats":   ("stats", ""),
    "st_top":     ("topchats", ""),
    "st_usage":   ("usage", ""),
    # — تنظیمات —
    "se_lang_fa": ("lang", "fa"),
    "se_lang_en": ("lang", "en"),
    "se_dc_on":   ("set", "delcmd true"),
    "se_dc_off":  ("set", "delcmd false"),
    "se_all":     ("settings", ""),
    # — سلامت —
    "hl_ping":    ("ping", ""),
    "hl_status":  ("status", ""),
    "hl_health":  ("health", ""),
    # — راهنما —
    "hp_cmds":    ("commands", ""),
    "hp_mods":    ("modules", ""),
}

PAGES = ("main", "clock", "afk", "autoreply", "rules", "antispam", "notes",
         "sched", "ai", "watch", "stats", "settings", "health", "help")


# ---------------------------------------------------------------- helpers
def _yn(app, key, default=False):
    return "✅" if app.s(key, default) else "⛔"


def _clock_sample(app):
    try:
        from .plugins.clock import _render_name
        return _render_name(app)
    except Exception:
        return "—"


def _ai_line(app):
    try:
        url = (app.s("ai_url", "") or "").rstrip("/")
        key = app.s("ai_key", "") or ""
        model = app.s("ai_model", "") or "gpt-4o-mini"
        if not url:
            url = "OpenRouter (env)"
        if not key:
            key = ""
        masked = (key[:7] + "…" + key[-4:]) if len(key) > 14 else ("ست شده" if key else "—")
        return url, model, masked, bool(url and key)
    except Exception:
        return "—", "—", "—", False


# ---------------------------------------------------------------- pages
def page_main(app):
    afk = app.db.setting("afk") or {}
    lines = [
        "🧊 **پنل مدیریت SeltBot**",
        "━━━━━━━━━━━━━━━━━━",
        f"🕐 ساعت زنده: {_yn(app, 'clock_on', True)}   💤 AFK: {'✅' if afk.get('active') else '⛔'}",
        f"🤖 پاسخ خودکار: {_yn(app, 'autoreply_on')}   ⚡ قوانین: {_yn(app, 'rules_on')}",
        f"🛡 آنتی‌اسپم: {_yn(app, 'antispam_on')}   📋 نوت‌ها: {len(app.db.notes_list() or [])}",
        "",
        "یک بخش رو انتخاب کن 👇",
    ]
    kb = grid([
        B("🕐 ساعت زنده", "n/clock"),
        B("💤 AFK", "n/afk"),
        B("🤖 پاسخ خودکار", "n/autoreply"),
        B("⚡ قوانین هوشمند", "n/rules"),
        B("🛡 آنتی‌اسپم", "n/antispam"),
        B("📋 نوت‌ها", "n/notes"),
        B("⏰ یادآورها", "n/sched"),
        B("🧠 هوش مصنوعی", "n/ai"),
        B("👁 دیده‌شدن‌ها", "n/watch"),
        B("📊 آمار", "n/stats"),
        B("⚙️ تنظیمات", "n/settings"),
        B("🩺 سلامت سیستم", "n/health"),
        B("❓ راهنما", "n/help"),
    ], cols=2)
    return "\n".join(lines), kb


def page_clock(app):
    digits = app.s("clock_digits", "mono") or "mono"
    dg_fa = {"mono": "مونو 𝟷𝟸𝟹", "fa": "فارسی ۱۲۳", "ascii": "انگلیسی 123"}.get(digits, digits)
    tpl = app.s("clock_template", "｜ {hhm}:{mmm}") or "｜ {hhm}:{mmm}"
    lines = [
        "🕐 **ساعت زنده**",
        "━━━━━━━━━━━━━━━━━━",
        f"• وضعیت: {_yn(app, 'clock_on', True)}",
        f"• نمونهٔ زنده: {_clock_sample(app)}",
        f"• قالب فعلی: {tpl}",
        f"• ارقام: {dg_fa}",
        f"• ساعت در بیو: {_yn(app, 'clock_bio_on')}",
        "",
        "قالب آماده (دکمه بزن، همون لحقه اعمال می‌شه):",
    ]
    on = app.s("clock_on", True)
    kb = [
        [B("⏹ خاموش‌کردن ساعت" if on else "▶️ روشن‌کردن ساعت",
           "ck_off" if on else "ck_on")],
        [B("🖌 ساده ｜ 𝟷𝟶:𝟺𝟻", "ck_fmt1"),
         B("📅 شمسی 𝟷𝟺𝟶𝟻/𝟶𝟽/𝟷𝟻", "ck_fmt2")],
        [B("🌗 ۱۲ساعته ۴:۴۵ ب.ظ", "ck_fmt3"),
         B("👤 با اسم اصلی", "ck_fmt4")],
        [B("🔢 مونو 𝟷𝟸𝟹", "ck_dg_mono"),
         B("🔢 فارسی ۱۲۳", "ck_dg_fa")],
        [B("🔢 انگلیسی 123", "ck_dg_asc")],
        [B("📝 ساعت در بیو: " + ("خاموش‌کردن" if app.s("clock_bio_on") else "روشن‌کردن"),
           "ck_bio_off" if app.s("clock_bio_on") else "ck_bio_on")],
        [B("↩️ برگرداندن اسم اصلی", "ck_restore")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_afk(app):
    afk = app.db.setting("afk") or {}
    active = bool(afk.get("active"))
    reason = (afk.get("reason") or "—")[:60]
    lines = [
        "💤 **حالت AFK (موجود نیستم)**",
        "━━━━━━━━━━━━━━━━━━",
        f"• وضعیت: {'✅ فعال' if active else '⛔ غیرفعال'}",
        f"• دلیل: {reason}",
        "",
        "وقتی AFK فعاله، به پیام‌های خصوصی و منشن‌ها خودکار جواب می‌ده و",
        "مدت نبودنت رو می‌گه. با اولین پیام خودت خودکار خاموش می‌شه.",
        "دلیل دلخواه: /afk دلیل دلخواهت",
    ]
    kb = [
        [B("▶️ فعال‌کردن AFK" if not active else "⛔ AFK فعاله — خاموش کن؟",
           "afk_off" if active else "afk_on")],
        [B("🔄 خاموش‌کردن AFK", "afk_off")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_autoreply(app):
    n = len(app.db.reply_rules() or [])
    lines = [
        "🤖 **پاسخ خودکار**",
        "━━━━━━━━━━━━━━━━━━",
        f"• وضعیت: {_yn(app, 'autoreply_on')}",
        f"• قوانین ثبت‌شده: {n}",
        f"• تأخیر پاسخ: {app.s('autoreply_delay', 3)}s | کول‌داون: {app.s('autoreply_cooldown', 60)}s",
        "",
        "افزودن قانون: /addreply <کلمه> <جواب>",
        "مثال: /addreply سلام سلام علیکم عزیزم",
    ]
    kb = [
        [B("▶️ روشن", "ar_on") if not app.s("autoreply_on") else B("⏹ خاموش", "ar_off"),
         B("📋 لیست قوانین", "ar_list")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_rules(app):
    n = len(app.db.rules_all() or [])
    lines = [
        "⚡ **قوانین اگر-آنگاه**",
        "━━━━━━━━━━━━━━━━━━",
        f"• موتور قوانین: {_yn(app, 'rules_on')}",
        f"• قوانین ثبت‌شده: {n}",
        "",
        "افزودن قانون: /rule add kw:سلام -> reply:سلام علیکم",
        "تریگرها: kw (کلمه) | from (کاربر) | media (مدیا/لینک)",
        "اکشن‌ها: reply | del | react | alert | fwd | note",
    ]
    kb = [
        [B("▶️ روشن" if not app.s("rules_on") else "⏹ خاموش",
           "rl_on" if not app.s("rules_on") else "rl_off"),
         B("📋 لیست", "rl_list")],
        [B("🗑 پاک‌کردن همه", "rl_clear")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_antispam(app):
    lines = [
        "🛡 **آنتی‌اسپم**",
        "━━━━━━━━━━━━━━━━━━",
        f"• وضعیت: {_yn(app, 'antispam_on')}",
        f"• حد: {app.s('antispam_burst', 8)} پیام در ۱۰ ثانیه → حذف + زندان ۲ دقیقه‌ای",
        "",
        "⚠️ فقط وقتی تو چت ادمین باشی می‌تونه پیام رو حذف کنه.",
        "تغییر حد: /antispam 12",
    ]
    kb = [
        [B("▶️ روشن" if not app.s("antispam_on") else "⏹ خاموش",
           "as_on" if not app.s("antispam_on") else "as_off")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_notes(app):
    rows = app.db.notes_list() or []
    lines = [
        "📋 **نوت‌ها**",
        "━━━━━━━━━━━━━━━━━━",
        f"• تعداد: {len(rows)}",
    ]
    if rows:
        lines.append("• آخرین‌ها: " + "، ".join(f"#{r['key']}" for r in rows[:12]))
    else:
        lines.append("هنوز نوتی ذخیره نشده.")
    lines += [
        "",
        "ذخیره: /save <کلید> <متن> — فراخوانی: هر جا #کلید بنویسی",
        "مثال: /save wifi پسورد کافه 12345",
    ]
    kb = [
        [B("📋 لیست کامل", "nt_list"), B("🗑 پاک‌کردن همه", "nt_clear")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_sched(app):
    rows = app.db.tasks_all() or []
    lines = [
        "⏰ **یادآورها و زمان‌بند**",
        "━━━━━━━━━━━━━━━━━━",
        f"• کارهای فعال: {len(rows)}",
    ]
    if rows:
        lines.append("• نمونه: " + "، ".join(str(r["id"]) for r in rows[:10]))
    lines += [
        "",
        "یادآور: /remind 30m شیر بخر",
        "روزانه: /daily 09:00 صبح بخیر",
        "هفتگی: /weekly شنبه 10:00 گزارش",
    ]
    kb = [
        [B("📋 لیست کامل", "sc_list"), B("🗑 پاک‌کردن همه", "sc_clear")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_ai(app):
    url, model, masked, ok = _ai_line(app)
    lines = [
        "🧠 **هوش مصنوعی**",
        "━━━━━━━━━━━━━━━━━━",
        f"• وضعیت: {'✅ فعال' if ok else '⛔ کلید/تنظیم نیست'}",
        f"• سرویس: {url}",
        f"• مدل: {model}",
        f"• کلید: {masked}",
        "",
        "گفتگو: /ai <سوال> — خلاصه: ریپلای روی متن + /sum",
        "ترجمه: /tr <متن> — شخصیت: /setprompt <متن>",
    ]
    kb = [
        [B("🔍 تست هوشمند", "ai_test"), B("📊 وضعیت", "ai_status")],
        [B("🧹 پاک‌کردن حافظهٔ گفتگو", "ai_reset")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_watch(app):
    try:
        users = app.s("watch_users", []) or []
    except Exception:
        users = []
    on = app.s("watch_on", True)
    names = "، ".join(str(u.get("name", f"#{u.get('id')}")) for u in users[:10]) or "—"
    lines = [
        "👁 **دیده‌شدن و فعالیت**",
        "━━━━━━━━━━━━━━━━━━",
        f"• وضعیت: {'✅ فعال' if on else '⛔ غیرفعال'}",
        f"• افراد تحت نظر: {len(users)}",
        f"• لیست: {names}",
        "",
        "ℹ️ تلگرام «دیدن پروفایل» رو به هیچ رباتی نمی‌ده (حریم خصوصی)",
        "— ولی نزدیک‌ترین سیگنال‌های واقعی الان فعاله:",
        "• ⌨️ کسی که داره بهت پیام خصوصی می‌نویسه",
        "• 👁 کی پیام خصوصی‌ت رو می‌خونه",
        "• 🟢 آنلاین‌شدن افراد لیست (افزودن: /watch add @user)",
    ]
    kb = [
        [B("▶️ روشن" if not on else "⏹ خاموش",
           "wt_off" if on else "wt_on"),
         B("📋 لیست", "wt_list")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_stats(app):
    tot = {r["direction"]: r["s"] for r in (app.db.counters_total() or [])}
    lines = [
        "📊 **آمار**",
        "━━━━━━━━━━━━━━━━━━",
        f"• پیام‌های دریافتی: {tot.get('in', 0):,}",
        f"• پیام‌های ارسالی: {tot.get('out', 0):,}",
        f"• نوت‌ها: {len(app.db.notes_list() or [])} | کارهای زمان‌بندی: {len(app.db.tasks_all() or [])}",
        f"• دیتابیس: {max(1, app.db.size() // 1024)}KB",
    ]
    kb = [
        [B("📈 آمار کامل", "st_stats"), B("🔥 پرترافیک‌ها", "st_top")],
        [B("⌨️ پرکاربردترین دستورات", "st_usage")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_settings(app):
    lang = app.s("lang", "fa") or "fa"
    lines = [
        "⚙️ **تنظیمات**",
        "━━━━━━━━━━━━━━━━━━",
        f"• زبان: {'فارسی' if lang == 'fa' else 'English'}",
        f"• حذف پیام دستور: {'روشن' if app.s('delcmd', True) else 'خاموش'}",
        f"• پیشوند دستورات: {app.s('prefix', '.')}",
        f"• منطقهٔ زمانی: {app.s('tz', 'Asia/Tehran')}",
        "",
        "تغییر پیشوند/تایم‌زون: /set tz Europe/London",
        "کلیدهای بیشتر: دکمهٔ «همهٔ تنظیمات»",
    ]
    kb = [
        [B("🌍 English" if lang == "fa" else "🌍 فارسی",
           "se_lang_en" if lang == "fa" else "se_lang_fa"),
         B("🧹 حذف دستور: " + ("خاموش" if app.s("delcmd", True) else "روشن"),
           "se_dc_off" if app.s("delcmd", True) else "se_dc_on")],
        [B("📋 همهٔ تنظیمات", "se_all")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_health(app):
    lines = [
        "🩺 **سلامت سیستم**",
        "━━━━━━━━━━━━━━━━━━",
        f"• آپ‌تایم شیفت: {app.uptime_str()}",
        f"• باقی‌ماندهٔ شیفت: {app.deadline_in_str()}",
        f"• هاست: GitHub Actions run {app.run_id or '—'}",
    ]
    kb = [
        [B("🏓 سرعت پاسخ", "hl_ping"), B("📊 وضعیت کامل", "hl_status")],
        [B("🩺 سلامت خودکار", "hl_health")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_help(app):
    lines = [
        "❓ **راهنمای سریع**",
        "━━━━━━━━━━━━━━━━━━",
        "دو راه کنترل داری:",
        "۱) همین پنل — همه‌چیز با دکمه",
        "۲) دستور متنی: /<دستور> همین‌جا، یا .<دستور> از اکانت خودت",
        "",
        "پرکاربردترین‌ها:",
        "• /remind 30m یادآور • /afk دلیل • /save کلید متن",
        "• /weather تهران • /tr متن • /calc 2+2 • /ip google.com",
        "• /ai سوال • /status وضعیت • /restart ری‌استارت",
    ]
    kb = [
        [B("⌨️ همهٔ دستورات", "hp_cmds"), B("📦 ماژول‌ها", "hp_mods")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


PAGE_BUILDERS = {
    "main": page_main, "clock": page_clock, "afk": page_afk,
    "autoreply": page_autoreply, "rules": page_rules, "antispam": page_antispam,
    "notes": page_notes, "sched": page_sched, "ai": page_ai, "watch": page_watch,
    "stats": page_stats, "settings": page_settings, "health": page_health,
    "help": page_help,
}


def render_page(app, page):
    fn = PAGE_BUILDERS.get(page) or page_main
    return fn(app)


# ---------------------------------------------------------------- transport
async def _send(app, chat_id, text, kb=None):
    payload = {"chat_id": chat_id, "text": text[:4000]}
    if kb:
        payload["reply_markup"] = {"inline_keyboard": kb}
    return await bot_api(app.http, app.manager_token, "sendMessage", payload)


async def _edit(app, chat_id, mid, text, kb=None):
    payload = {"chat_id": chat_id, "message_id": mid, "text": text[:4000]}
    if kb:
        payload["reply_markup"] = {"inline_keyboard": kb}
    r = await bot_api(app.http, app.manager_token, "editMessageText", payload)
    if not r.get("ok"):
        # too old / deleted / not modified → fresh menu message instead
        await _send(app, chat_id, text, kb)
    return r


# ---------------------------------------------------------------- entries
async def handle_start(app, chat_id):
    """Send the main glass menu (used by /start and /menu)."""
    text, kb = render_page(app, "main")
    r = await _send(app, chat_id, text, kb)
    if r.get("ok"):
        _last_page[chat_id] = "main"
    return r


async def handle_callback(app, cb):
    cid = cb.get("id")

    async def answer(text=None):
        try:
            payload = {"callback_query_id": cid}
            if text:
                payload["text"] = text[:190]
                payload["show_alert"] = False
            await bot_api(app.http, app.manager_token, "answerCallbackQuery", payload)
        except Exception:
            pass

    frm = (cb.get("from") or {}).get("id")
    if not app.authorized(frm):
        await answer("⛔ دسترسی نداری")
        return
    msg = cb.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    mid = msg.get("message_id")
    data = cb.get("data") or ""
    if not chat_id or not mid:
        await answer()
        return

    # navigation
    if data.startswith("n/"):
        page = data[2:]
        await answer()
        text, kb = render_page(app, page)
        await _edit(app, chat_id, mid, text, kb)
        _last_page[chat_id] = page
        return

    # action → run the REAL command engine
    act = ACTIONS.get(data)
    if not act:
        await answer("؟")
        return
    cmd, arg = act
    await answer()
    ev = BotEv(app, chat_id, frm)
    try:
        await app.run_command(cmd, arg, ev)
    except Exception:
        log.exception("menu action %s failed", data)
    # re-render the page the user came from (buttons reflect the new state)
    page = _last_page.get(chat_id, "main")
    text, kb = render_page(app, page)
    await _edit(app, chat_id, mid, text, kb)
