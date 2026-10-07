"""Glass-button (inline keyboard) control panel for the manager bot.

/start → main menu with shiny inline buttons. Every button runs a REAL
command through the exact same engine as typed /.commands (app.run_command),
so the panel and text commands behave identically — one engine, two frontends.

v2.5 redesign:
  • messages are sent with parse_mode=HTML — the old panel was sent with NO
    parse mode at all, so every **bold** marker rendered as literal
    asterisks (the "messy" look the owner complained about).
  • one visual system on every page: bold header → heavy divider → status
    rows (status marker first — reads as a clean column in RTL) →
    <blockquote> examples/previews → italic hint. Single column, consistent
    icons, no scattered two-item rows.
  • clock page gained the v2.5 digit-font buttons (bold/fa/mono/double/
    serif/full/ascii) and the AFK page shows a live preview of the exact
    message a contact will receive.
  • ALL dynamic values go through esc() — nothing can break the HTML.

callback_data schema (must stay ≤64 bytes):
  n/<page>      → navigate to page
  <action key>  → ACTIONS[key] = (cmd, arg) → run_command → re-render last page
"""
import html as _htmlmod
import logging
import time as _time

from . import jalali
from .core import BotEv, bot_api

log = logging.getLogger("seltbot.menu")

_last_page = {}      # chat_id → page id (re-render target after actions)

HR = "━━━━━━━━━━━━━━━━━━"          # page divider (18 chars, everywhere)
HR_THIN = "──────────────────"


def esc(s):
    """Escape a dynamic value for parse_mode=HTML."""
    return _htmlmod.escape(str(s if s is not None else ""), quote=False)


def _fa_num(n):
    return jalali.fa_digits(str(n)).replace(",", "٬")


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
    "ck_nodate":  ("clock", "nodate"),
    "ck_matrix":  ("clock", "matrix"),
    "ck_matrix_off": ("clock", "matrix off"),
    "ck_dg_bold":   ("clock", "digits bold"),
    "ck_dg_fa":     ("clock", "digits fa"),
    "ck_dg_mono":   ("clock", "digits mono"),
    "ck_dg_double": ("clock", "digits double"),
    "ck_dg_serif":  ("clock", "digits serif"),
    "ck_dg_full":   ("clock", "digits full"),
    "ck_dg_asc":    ("clock", "digits ascii"),
    "ck_bio_on":  ("clock", "bio on"),
    "ck_bio_off": ("clock", "bio off"),
    "ck_restore": ("restore", ""),
    # — AFK —
    "afk_on":     ("afk", ""),
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

# v2.5.2 — instant visual feedback: tapping a button pops a toast on the
# button itself (answerCallbackQuery), so the owner SEES that the click did
# something even before the command's own reply arrives.
ACTION_TOASTS = {
    "ck_on": "✅ ساعت روشن شد", "ck_off": "⏹ ساعت خاموش شد",
    "ck_fmt1": "✅ قالب ساده اعمال شد", "ck_fmt2": "✅ شمسی + ساعت اعمال شد",
    "ck_fmt3": "✅ قالب ۱۲ساعته اعمال شد", "ck_fmt4": "✅ قالب با اسم اعمال شد",
    "ck_nodate": "🗑 تاریخ حذف شد — فقط ساعت می‌مونه",
    "ck_matrix": "🌀 ماتریکس روشن شد — هر دقیقه می‌رقصه!",
    "ck_matrix_off": "🌀 ماتریکس خاموش شد — قالب قبلی برگشت",
    "ck_dg_bold": "✅ فونت بولد اعمال شد", "ck_dg_fa": "✅ فونت فارسی اعمال شد",
    "ck_dg_mono": "✅ فونت مونو اعمال شد", "ck_dg_double": "✅ فونت توخالی اعمال شد",
    "ck_dg_serif": "✅ فونت کلاسیک اعمال شد", "ck_dg_full": "✅ فونت عریض اعمال شد",
    "ck_dg_asc": "✅ فونت ساده اعمال شد",
    "ck_bio_on": "✅ ساعت در بیو روشن شد", "ck_bio_off": "⏹ ساعت بیو خاموش شد",
    "ck_restore": "↩️ اسم اصلی برگشت",
    "afk_on": "✅ AFK روشن شد", "afk_off": "✅ AFK خاموش شد",
}


# ---------------------------------------------------------------- helpers
def _yn(app, key, default=False):
    return "✅" if app.s(key, default) else "⛔"


def _clock_sample(app):
    try:
        from .plugins.clock import _render_name
        return _render_name(app)
    except Exception:
        return "—"


def _clock_offset(app):
    try:
        from .plugins.clock import _offset
        return _offset(app)
    except Exception:
        return 0


def _clock_info(app):
    try:
        from .plugins.clock import DEFAULT_TEMPLATE, DEFAULT_DIGITS, DIGIT_STYLES
        return DEFAULT_TEMPLATE, DEFAULT_DIGITS, DIGIT_STYLES
    except Exception:
        return "｜ {hhm}:{mmm}", "mono", {}


def _clock_has_date(app):
    """v2.6 — does the current clock template render a date part?"""
    try:
        from .plugins.clock import has_date_tokens
        default_tpl, _, _ = _clock_info(app)
        return has_date_tokens(app.s("clock_template", default_tpl) or default_tpl)
    except Exception:
        return False


def _clock_days(app):
    try:
        from .plugins.clock import _days_since
        return _days_since(app, app.now())
    except Exception:
        return "—"


def _ai_line(app):
    try:
        # v2.3.1: was DB-only → menu lied "کلید/تنظیم نیست" even when the
        # AI env secrets (AI_API_URL/KEY/MODEL from repo secrets) were live.
        # Now we use the SAME config resolution as the real .ai command.
        from .plugins.ai import _cfg
        url, key, model = _cfg(app)
        if not url:
            url = "—"
        masked = (key[:7] + "…" + key[-4:]) if len(key) > 14 else ("ست شده" if key else "—")
        return url, model, masked, bool(url and key)
    except Exception:
        return "—", "—", "—", False


# ---------------------------------------------------------------- pages
def page_main(app):
    afk = app.db.setting("afk") or {}
    rows = [
        f"{_yn(app, 'clock_on', True)} ساعت زنده",
        f"{'✅' if afk.get('active') else '⛔'} حالت AFK",
        f"{_yn(app, 'autoreply_on')} پاسخ خودکار",
        f"{_yn(app, 'rules_on')} قوانین هوشمند",
        f"{_yn(app, 'antispam_on')} آنتی‌اسپم",
        f"📋 نوت‌ها: {_fa_num(len(app.db.notes_list() or []))}",
    ]
    text = "\n".join([
        "🧊 <b>پنل مدیریت SeltBot</b>",
        HR,
        *rows,
        "",
        "<i>یک بخش را انتخاب کن 👇</i>",
    ])
    kb = grid([
        B("🕐 ساعت زنده", "n/clock"),
        B("💤 حالت AFK", "n/afk"),
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
    return text, kb


def page_clock(app):
    default_tpl, default_digits, styles = _clock_info(app)
    digits = app.s("clock_digits", default_digits) or default_digits
    dg_label = styles.get(digits, ("ساده",))[0]
    tpl = app.s("clock_template", default_tpl) or default_tpl
    off = _clock_offset(app)
    on = app.s("clock_on", True)
    # v2.5.2 — show the FULL profile (first name + clock), because that is
    # what the owner actually sees next to their messages. Showing only the
    # clock fragment made font/format changes look like "nothing happened".
    try:
        first = str(app.s("clock_first_base", "") or "").strip()
    except Exception:
        first = ""
    sample = _clock_sample(app)
    if app.s("clock_target", "last_name") == "first_name" or not first:
        full = sample
    else:
        full = first + " " + sample
    lines = [
        "🕐 <b>ساعت زنده</b>",
        HR,
        f"{'✅' if on else '⛔'} فعال — نمایش کنار اسمت:",
        f"<code>{esc(full)}</code>",
        f"🔠 فونت ارقام: <b>{esc(dg_label)}</b>",
        f"🧩 قالب: <code>{esc(tpl)}</code>",
        ("📅 تاریخ: ✅ کنار ساعت می‌شینه" if _clock_has_date(app)
         else "📅 تاریخ: ⛔ نیست — فقط ساعت می‌شینه"),
        ("🌀 ماتریکس: ✅ فعال — اسپینر/فونت/نوار هر دقیقه عوض می‌شن"
         if app.s("clock_matrix_on", False)
         else "🌀 ماتریکس: ⛔ خاموش — با دکمهٔ پایین متحرکش کن"),
        (f"📆 شمارش روز: روز {_clock_days(app)} (`.clock since ...`)"
         if app.s("clock_since", "") else
         "📆 شمارش روز: ⛔ (`.clock since 1405/7/15`)"),
        (f"📞 کالیبره با گوشی: <b>{off:+d} ثانیه</b>" if off
         else "📞 کالیبره با گوشی: بدون انحراف"),
        f"{'✅' if app.s('clock_bio_on') else '⛔'} ساعت در بیو",
        "",
        "<i>یک کلیک = اعمال فوری:</i>",
        "<i>ℹ️ تلگرام گاهی چند دقیقه‌ای طول می‌کشه اسم جدید رو تو لیست چت‌ها"
        " نشون بده (کشِ خودشه) — ولی از لحظهٔ کلیک، روی پروفایلت فعاله.</i>",
    ]
    kb = [
        [B("⏹ خاموش‌کردن ساعت" if on else "▶️ روشن‌کردن ساعت",
           "ck_off" if on else "ck_on")],
        [B("🖌 ساده ｜ ساعت:دقیقه", "ck_fmt1"),
         B("📅 شمسی + ساعت", "ck_fmt2")],
        [B("🌗 ۱۲ساعته", "ck_fmt3"),
         B("👤 با اسم اصلی", "ck_fmt4")],
        [B("🗑 حذف تاریخ (فقط ساعت بمونه)", "ck_nodate")],
        [B("🌀 ماتریکس متحرک: " + ("خاموش‌کردن" if app.s("clock_matrix_on", False) else "روشن‌کردن"),
           "ck_matrix_off" if app.s("clock_matrix_on", False) else "ck_matrix")],
        [B("🔢 بولد 𝟭𝟮:𝟯𝟬", "ck_dg_bold"),
         B("🔢 فارسی ۱۲:۳۰", "ck_dg_fa")],
        [B("🔢 مونو 𝟷𝟸:𝟹𝟶", "ck_dg_mono"),
         B("🔢 توخالی 𝟙𝟚:𝟛𝟘", "ck_dg_double")],
        [B("🔢 کلاسیک 𝟏𝟐:𝟑𝟎", "ck_dg_serif"),
         B("🔢 عریض １２:３０", "ck_dg_full")],
        [B("🔢 ساده 12:30", "ck_dg_asc")],
        [B("📝 ساعت در بیو: " + ("خاموش‌کردن" if app.s("clock_bio_on") else "روشن‌کردن"),
           "ck_bio_off" if app.s("clock_bio_on") else "ck_bio_on")],
        [B("↩️ برگرداندن اسم اصلی", "ck_restore")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_afk(app):
    try:
        from .plugins.afk import _build_afk_text
        st = app.db.setting("afk") or {}
        active = bool(st.get("active"))
        reason = (st.get("reason") or "").strip()
        since = float(st.get("since") or 0)
        dur_s = max(0.0, _time.time() - since) if (active and since) else 305.0
        # v2.5.2: the old preview used a hardcoded «زهرا» — the owner thought
        # the bot literally replies «زهرا جان» to EVERYONE. The real message
        # carries each sender's own name; the placeholder + note makes that
        # unmistakable.
        preview = _build_afk_text(
            app, "نامِ مخاطب", dur_s, since or (_time.time() - 305),
            reason or "فعلاً در دسترس نیستم")
    except Exception:
        active = False
        reason = ""
        dur_s = 0
        preview = "💤 …"
        st = {}
    dur_line = ""
    if active and dur_s > 90:
        dur_line = f" · مدت: {jalali.fmt_dur(dur_s, fa=True)}"
    lines = [
        "💤 <b>حالت AFK</b>",
        HR,
        f"{'✅ فعال' if active else '⛔ غیرفعال'}{dur_line}",
        f"📝 دلیل: {esc(reason) if reason else '—'}",
        "",
        "پیش‌نمایش پیامی که برای مخاطب ارسال می‌شود:",
        f"<blockquote>{esc(preview)}</blockquote>",
        "<i>«نامِ مخاطب» یعنی اسمِ همون کسی که بهت پیام داده — خودکار"
        " جایگزین می‌شود و اسمش کلیک‌شدنیه.</i>",
        "",
        "<i>با اولین پیام خودت، AFK خودکار خاموش می‌شود.</i>",
        "<i>دلیل دلخواه: /afk دلیل — قالب اختصاصی: /afktext</i>",
    ]
    kb = [
        [B("⛔ خاموش‌کردن AFK" if active else "▶️ فعال‌کردن AFK",
           "afk_off" if active else "afk_on")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_autoreply(app):
    n = len(app.db.reply_rules() or [])
    lines = [
        "🤖 <b>پاسخ خودکار</b>",
        HR,
        f"{_yn(app, 'autoreply_on')} فعال",
        f"📋 قوانین ثبت‌شده: {_fa_num(n)}",
        f"⏳ تأخیر پاسخ: {_fa_num(app.s('autoreply_delay', 3))} ثانیه"
        f" · کول‌داون: {_fa_num(app.s('autoreply_cooldown', 60))} ثانیه",
        "",
        "<i>افزودن قانون: /addreply &lt;کلمه&gt; &lt;جواب&gt;</i>",
        "<blockquote>/addreply سلام سلام علیکم عزیزم</blockquote>",
    ]
    kb = [
        [B("▶️ روشن" if not app.s("autoreply_on") else "⏹ خاموش",
           "ar_on" if not app.s("autoreply_on") else "ar_off"),
         B("📋 لیست قوانین", "ar_list")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_rules(app):
    n = len(app.db.rules_all() or [])
    lines = [
        "⚡ <b>قوانین هوشمند (اگر-آنگاه)</b>",
        HR,
        f"{_yn(app, 'rules_on')} موتور قوانین",
        f"📋 قوانین ثبت‌شده: {_fa_num(n)}",
        "",
        "<blockquote>/rule add kw:سلام -> reply:سلام علیکم</blockquote>",
        "<i>تریگرها: kw (کلمه) · from (کاربر) · media (مدیا/لینک)</i>",
        "<i>اکشن‌ها: reply · del · react · alert · fwd · note</i>",
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
        "🛡 <b>آنتی‌اسپم</b>",
        HR,
        f"{_yn(app, 'antispam_on')} فعال",
        f"⚙️ حد: {_fa_num(app.s('antispam_burst', 8))} پیام در ۱۰ ثانیه"
        " → حذف + قطع دسترسی ۲ دقیقه‌ای",
        "",
        "<i>فقط در چت‌هایی که ادمین باشی می‌تواند پیام را حذف کند.</i>",
        "<i>تغییر حد: /antispam 12</i>",
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
        "📋 <b>نوت‌ها</b>",
        HR,
        f"تعداد: {_fa_num(len(rows))}",
    ]
    if rows:
        lines.append("آخرین‌ها: " + "، ".join(f"#{esc(r['key'])}" for r in rows[:12]))
    else:
        lines.append("<i>هنوز نوتی ذخیره نشده.</i>")
    lines += [
        "",
        "<i>ذخیره: /save &lt;کلید&gt; &lt;متن&gt; — فراخوانی: هر جا #کلید بنویسی</i>",
        "<blockquote>/save wifi پسورد کافه ۱۲۳۴۵</blockquote>",
    ]
    kb = [
        [B("📋 لیست کامل", "nt_list"), B("🗑 پاک‌کردن همه", "nt_clear")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_sched(app):
    rows = app.db.tasks_all() or []
    lines = [
        "⏰ <b>یادآورها و زمان‌بند</b>",
        HR,
        f"📋 کارهای فعال: {_fa_num(len(rows))}",
        "",
        "<blockquote>/remind 30m شیر بخر\n/daily 09:00 صبح بخیر\n/weekly شنبه 10:00 گزارش</blockquote>",
    ]
    kb = [
        [B("📋 لیست کامل", "sc_list"), B("🗑 پاک‌کردن همه", "sc_clear")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_ai(app):
    url, model, masked, ok = _ai_line(app)
    host = url.split("//")[-1].split("/")[0] if url and url != "—" else "—"
    lines = [
        "🧠 <b>هوش مصنوعی</b>",
        HR,
        ("✅ فعال" if ok else "⛔ کلید/تنظیم نیست") + f" · {esc(host)}",
        f"🤖 مدل: <code>{esc(model)}</code>",
        f"🔑 کلید: <code>{esc(masked)}</code>",
        "",
        "<i>گفتگو: /ai &lt;سوال&gt; — خلاصه: ریپلای روی متن + /sum</i>",
        "<i>ترجمه: /tr &lt;متن&gt; — شخصیت: /setprompt &lt;متن&gt;</i>",
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
    names = "، ".join(esc(str(u.get("name", f"#{u.get('id')}"))) for u in users[:10]) or "—"
    lines = [
        "👁 <b>دیده‌شدن و فعالیت</b>",
        HR,
        ("✅ فعال" if on else "⛔ غیرفعال"),
        f"👥 افراد تحت نظر: {_fa_num(len(users))}",
        f"📋 لیست: {names}",
        "",
        "<blockquote>ℹ️ تلگرام «دیدن پروفایل» را به هیچ رباتی نمی‌دهد (حریم خصوصی)"
        " — ولی نزدیک‌ترین سیگنال‌های واقعی فعال است:\n"
        "⌨️ کسی که در حال تایپ پیام خصوصی است\n"
        "👁 کسی که پیام خصوصی‌ات را می‌خواند\n"
        "🟢 آنلاین‌شدن افراد لیست</blockquote>",
        "<i>افزودن: /watch add @user</i>",
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
    s_in = _fa_num("{:,.0f}".format(tot.get("in", 0)))
    s_out = _fa_num("{:,.0f}".format(tot.get("out", 0)))
    lines = [
        "📊 <b>آمار</b>",
        HR,
        f"📥 پیام‌های دریافتی: {s_in}",
        f"📤 پیام‌های ارسالی: {s_out}",
        f"📋 نوت‌ها: {_fa_num(len(app.db.notes_list() or []))}"
        f" · ⏰ کارهای زمان‌بندی: {_fa_num(len(app.db.tasks_all() or []))}",
        f"💾 دیتابیس: {_fa_num(max(1, app.db.size() // 1024))}KB",
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
        "⚙️ <b>تنظیمات</b>",
        HR,
        f"🌍 زبان: {'فارسی' if lang == 'fa' else 'English'}",
        f"🧹 حذف پیام دستور: {'روشن' if app.s('delcmd', True) else 'خاموش'}",
        f"⌨️ پیشوند دستورات: <code>{esc(app.s('prefix', '.'))}</code>",
        f"🕐 منطقهٔ زمانی: <code>{esc(app.s('tz', 'Asia/Tehran'))}</code>",
        "",
        "<i>تغییر پیشوند/تایم‌زون: /set tz Europe/London</i>",
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
        "🩺 <b>سلامت سیستم</b>",
        HR,
        f"⏱ آپ‌تایم شیفت: {esc(app.uptime_str())}",
        f"⌛ باقی‌ماندهٔ شیفت: {esc(app.deadline_in_str())}",
        f"🖥 هاست: GitHub Actions · <code>{esc(app.run_id or '—')}</code>",
    ]
    kb = [
        [B("🏓 سرعت پاسخ", "hl_ping"), B("📊 وضعیت کامل", "hl_status")],
        [B("🩺 سلامت خودکار", "hl_health")],
        [B("⬅️ منوی اصلی", "n/main")],
    ]
    return "\n".join(lines), kb


def page_help(app):
    lines = [
        "❓ <b>راهنمای سریع</b>",
        HR,
        "دو راه کنترل داری:",
        "۱) همین پنل — همه‌چیز با دکمه",
        "۲) دستور متنی: /دستور همین‌جا، یا .دستور از اکانت خودت",
        "",
        "<blockquote>/remind 30m یادآور · /afk دلیل · /save کلید متن\n"
        "/weather تهران · /tr متن · /calc 2+2 · /ip google.com\n"
        "/ai سوال · /status وضعیت · /restart ری‌استارت</blockquote>",
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
    payload = {"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML"}
    if kb:
        payload["reply_markup"] = {"inline_keyboard": kb}
    r = await bot_api(app.http, app.manager_token, "sendMessage", payload)
    if not r.get("ok") and "parse" in str(r.get("description") or "").lower():
        # never lose a message to a formatting edge case
        payload.pop("parse_mode", None)
        r = await bot_api(app.http, app.manager_token, "sendMessage", payload)
    return r


async def _edit(app, chat_id, mid, text, kb=None):
    payload = {"chat_id": chat_id, "message_id": mid, "text": text[:4000],
               "parse_mode": "HTML"}
    if kb:
        payload["reply_markup"] = {"inline_keyboard": kb}
    r = await bot_api(app.http, app.manager_token, "editMessageText", payload)
    if not r.get("ok"):
        desc = str(r.get("description") or "").lower()
        if "parse" in desc:
            payload.pop("parse_mode", None)
            r = await bot_api(app.http, app.manager_token, "editMessageText", payload)
        elif "not modified" in desc:
            pass  # nothing changed (e.g. re-tapped the active font) — keep the message
        else:
            # too old / deleted → fresh menu message instead
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
    await answer(ACTION_TOASTS.get(data))
    ev = BotEv(app, chat_id, frm)
    try:
        await app.run_command(cmd, arg, ev)
    except Exception:
        log.exception("menu action %s failed", data)
    # re-render the page the user came from (buttons reflect the new state)
    page = _last_page.get(chat_id, "main")
    text, kb = render_page(app, page)
    await _edit(app, chat_id, mid, text, kb)
