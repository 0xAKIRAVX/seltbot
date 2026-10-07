"""Live clock in profile name/bio — with anti-ban governor pacing.

Targets: last_name (default, keeps first_name untouched), first_name, or bio.
Formats: mono/ascii/fa digits, 12/24h, Jalali/Gregorian date, custom templates.
"""
import asyncio
import logging
import re
import time

from .. import jalali
from ..core import command

log = logging.getLogger("seltbot.clock")

DEFAULT_TEMPLATE = "｜ {hhm}:{mmm}"
DEFAULT_BIO_TEMPLATE = "{jdate} ｜ {hhm}:{mmm}"

CLOCK_NAME_RE = re.compile(
    r"^[\W_]{0,8}?\s*[0-9۰-۹𝟶-𝟿]{1,2}\s*[:.،]\s*[0-9۰-۹𝟶-𝟿]{2}"
    r"(\s*[:.،]\s*[0-9۰-۹𝟶-𝟿]{2})?[\s\W_]*$")

TOKENS_HELP_FA = """🧩 توکن‌های قالب:
`{hhm}:{mmm}` → 𝟶𝟺:𝟺𝟻 (مونو، مثل الان)
`{hh}:{mm}:{ss}` → 04:45:12
`{h12} {ampm}` → 4 ب.ظ
`{jdate}` → 1405/07/15
`{jWD} {jd} {jMon} {jy}` → چهارشنبه ۱۵ مهر ۱۴۰۵
`{WD} {day} {Mon} {year}` → Thursday 7 October 2026
`{name}` → اسم/بیوی اصلیت
مثال: `.clock text ｜ {hhm}:{mmm}`"""


def looks_like_clock(s):
    return bool(s) and bool(CLOCK_NAME_RE.match(s.strip()))


def render(app, template, dt):
    h24, mi, se = dt.hour, dt.minute, dt.second
    h12 = h24 % 12 or 12
    style = app.s("clock_digits", "mono") or "mono"

    def st(x):
        if style == "mono":
            return jalali.mono_digits(x)
        if style == "fa":
            return jalali.fa_digits(x)
        return x

    ampm_fa = "ق.ظ" if h24 < 12 else "ب.ظ"
    ampm_en = "AM" if h24 < 12 else "PM"
    jy, jm, jd = jalali.g2j(dt.year, dt.month, dt.day)
    toks = {
        "h": str(h24), "hh": f"{h24:02d}", "m": str(mi), "mm": f"{mi:02d}",
        "s": str(se), "ss": f"{se:02d}",
        "h12": str(h12), "H12": f"{h12:02d}",
        "ampm": ampm_fa if app.fa else ampm_en,
        "hhm": st(f"{h24:02d}"), "mmm": st(f"{mi:02d}"), "ssm": st(f"{se:02d}"),
        "year": str(dt.year), "month": f"{dt.month:02d}", "day": f"{dt.day:02d}",
        "Mon": (jalali.G_MONTHS_FA if app.fa else jalali.G_MONTHS_EN)[dt.month - 1],
        "WD": (jalali.WD_FA if app.fa else jalali.WD_EN)[dt.weekday()],
        "date": f"{dt.year}-{dt.month:02d}-{dt.day:02d}",
        "jy": str(jy), "jm": f"{jm:02d}", "jd": f"{jd:02d}",
        "jMon": jalali.J_MONTHS_FA[jm - 1],
        "jWD": jalali.WD_FA[dt.weekday()],
        "jdate": f"{jy}/{jm:02d}/{jd:02d}",
        "jdatefa": jalali.fa_digits(f"{jy}/{jm:02d}/{jd:02d}"),
    }
    out = template
    for k, v in toks.items():
        out = out.replace("{" + k + "}", v)
    if "{name}" in out:
        out = out.replace("{name}", str(app.s("clock_name_base", "") or ""))
    return out.strip()


def _target_field(app):
    return "first_name" if app.s("clock_target", "last_name") == "first_name" else "last_name"


def _limit(app, target):
    if target == "about":
        return 139 if getattr(app.me, "premium", False) else 69
    return 63


def _wrap_pfx(app, s, target):
    pfx = str(app.s("clock_prefix", "") or "")
    sfx = str(app.s("clock_suffix", "") or "")
    if not (pfx or sfx):
        return s
    return (pfx + s + sfx)[:_limit(app, target)]


def _render_name(app):
    tpl = app.s("clock_template", DEFAULT_TEMPLATE) or DEFAULT_TEMPLATE
    return _wrap_pfx(app, render(app, tpl, app.now()), _target_field(app))[:_limit(app, _target_field(app))]


def _render_bio(app):
    tpl = app.s("clock_bio_template", DEFAULT_BIO_TEMPLATE) or DEFAULT_BIO_TEMPLATE
    return _wrap_pfx(app, render(app, tpl, app.now()), "about")[:_limit(app, "about")]


def _align_next(now, iv):
    # Write lands ~0.3s AFTER the minute boundary so the visible change happens
    # right as the phone's clock flips (epoch is minute-aligned for whole-minute
    # UTC offsets such as Iran's +3:30). The loop then sleeps precisely until
    # the next action (see _loop) instead of polling at 1s granularity.
    if iv >= 60 and 60 % iv == 0:
        return (int(now / iv) + 1) * iv + 0.3
    return now + iv + 0.2


_task = None
_next_name = 0.0
_next_bio = 0.0
_next_verify = 0.0
_last_why = "init"
_force_name = False    # realign flag: force next boundary-window write
_force_bio = False


def _next_after(now, why, iv, retry):
    """Decide (next_ts, force_next) after a governor result.

    ok/same/keep → align to the next interval boundary (flip just after the
    minute change).  pace → the previous write landed mid-minute (e.g. the
    boot write or a flood-recovery write): wait for the NEXT boundary and
    force the write there, so the flip phase can never lock mid-minute —
    a locked mid-minute phase is exactly what made the clock flip late.
    flood/budget/error → timed retry (phase self-heals via pace→force later).
    """
    if why == "pace":
        return _align_next(now, iv), True
    if why in ("ok", "same", "keep"):
        return _align_next(now, iv), False
    return now + max(5, min(retry or 30, 600)), False


async def start(app):
    global _task
    # cancel a previous incarnation first — run() re-calls start()
    # after reconnects; without this the loop runs TWICE (double
    # profile writes → flood/ban risk)
    if _task and not _task.done():
        _task.cancel()
    _task = asyncio.ensure_future(_loop(app))


async def stop(app):
    if _task:
        _task.cancel()


async def _loop(app):
    global _next_name, _next_bio, _next_verify, _last_why, _force_name, _force_bio
    while not app.stopping:
        try:
            now = time.time()
            if not app.module_off("clock") and app.s("clock_on", True):
                if now >= _next_name:
                    text = _render_name(app)
                    ok, retry, why = await app.gov.apply(_target_field(app), text,
                                                         force=_force_name)
                    _last_why = why
                    iv = max(app.gov.min_gap(), int(app.s("clock_interval", 60)))
                    _next_name, _force_name = _next_after(now, why, iv, retry)
            if not app.module_off("clock") and app.s("clock_bio_on", False):
                if now >= _next_bio:
                    text = _render_bio(app)
                    ok, retry, why = await app.gov.apply("bio", text,
                                                         force=_force_bio)
                    iv = max(60, int(app.s("clock_bio_interval", 60)))
                    _next_bio, _force_bio = _next_after(now, why, iv, retry)
            if now >= _next_verify:
                _next_verify = now + 300
                if app.s("clock_on", True) or app.s("clock_bio_on", False):
                    await app.gov.verify()
            # sleep until just before the earliest pending action (precise sync)
            pending = [t for t in (_next_name, _next_bio, _next_verify) if t > now]
            nxt = min(pending) if pending else now + 5
            await asyncio.sleep(min(5.0, max(0.05, nxt - now - 0.02)))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("clock loop")
            await asyncio.sleep(5)


def _fmt_ts(app, ts):
    if not ts:
        return app.t("never")
    return app.now().fromtimestamp(ts, app.tzinfo).strftime("%H:%M:%S")


@command("clock", "clock", "[on/off/text/interval/tz/target/digits/bio/status]",
         "ساعت زندهٔ کنار اسم/بیو + تنظیمات", "Live clock in name/bio + settings",
         aliases=("clockname",))
async def clock_cmd(app, ev, arg):
    parts = arg.split(None, 1)
    sub = (parts[0].lower() if parts else "status")
    rest = parts[1].strip() if len(parts) > 1 else ""

    if sub in ("status", "وضعیت", ""):
        await _clock_status(app, ev)
    elif sub == "on":
        app.sets("clock_on", True)
        global _next_name
        _next_name = 0
        await ev.reply("🕐 ساعت روشن شد — همین الان کنار اسمت می‌شینه."
                       if app.fa else "🕐 Clock enabled.")
    elif sub in ("off", "pause"):
        app.sets("clock_on", False)
        if sub == "off":
            base = app.s("clock_name_base", "") or ""
            await app.gov.apply(_target_field(app), base or None, force=True)
        await ev.reply("⏸ ساعت متوقف شد." if app.fa else "⏸ Clock paused.")
    elif sub == "resume":
        app.sets("clock_on", True)
        _next_name = 0
        await ev.reply("▶️ ساعت ادامه پیدا کرد." if app.fa else "▶️ Clock resumed.")
    elif sub == "text":
        if not rest:
            await ev.reply(TOKENS_HELP_FA)
            return
        app.sets("clock_template", rest)
        _next_name = 0
        await ev.reply("✅ قالب ساعت:\n" + render(app, rest, app.now()))
    elif sub == "interval":
        try:
            v = int(jalali.to_en_digits(rest))
        except ValueError:
            await ev.reply(app.t("bad_arg"))
            return
        floor = app.gov.min_gap()
        if v < floor:
            v = floor
            await ev.reply(f"⚠️ برای امنیت اکانت، کمترین فاصله {floor} ثانیه‌ست — همین مقدار ست شد.")
        app.sets("clock_interval", v)
        await ev.reply(f"✅ فاصلهٔ آپدیت: {v} ثانیه")
    elif sub == "tz":
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(rest)
        except Exception:
            await ev.reply("❌ منطقهٔ زمانی نامعتبره — مثال: Asia/Tehran یا Europe/London")
            return
        app.sets("tz", rest)
        await ev.reply(f"✅ منطقهٔ زمانی: {rest}")
    elif sub == "target":
        if rest in ("first", "firstname", "اسم", "first_name"):
            app.sets("clock_target", "first_name")
        else:
            app.sets("clock_target", "last_name")
        await ev.reply(f"✅ ساعت روی {'اسم اول' if rest.startswith('first') else 'اسم آخر'} می‌شینه")
    elif sub == "digits":
        if rest in ("mono", "مونو", "fancy", "font"):
            app.sets("clock_digits", "mono")
        elif rest in ("fa", "فارسی", "persian"):
            app.sets("clock_digits", "fa")
        else:
            app.sets("clock_digits", "ascii")
        await ev.reply(f"✅ سبک ارقام: {app.s('clock_digits')}")
    elif sub == "prefix":
        app.sets("clock_prefix", rest)
        _next_name = 0
        await ev.reply(f"✅ پیشوند: «{rest}»\nنمونه: {_render_name(app)}")
    elif sub == "suffix":
        app.sets("clock_suffix", rest)
        _next_name = 0
        await ev.reply(f"✅ پسوند: «{rest}»\nنمونه: {_render_name(app)}")
    elif sub == "bio":
        await _clock_bio(app, ev, rest)
    else:
        await ev.reply(app.t("bad_arg") + "\n" + TOKENS_HELP_FA)


async def _clock_bio(app, ev, rest):
    global _next_bio
    parts = rest.split(None, 1)
    sub = parts[0].lower() if parts else "status"
    arg = parts[1].strip() if len(parts) > 1 else ""
    if sub == "on":
        app.sets("clock_bio_on", True)
        _next_bio = 0
        await ev.reply("🕐 ساعت در بیو روشن شد (بیوی اصلیت backup گرفته شد).")
    elif sub in ("off",):
        app.sets("clock_bio_on", False)
        base = app.s("clock_bio_base", "") or ""
        await app.gov.apply("bio", base or None, force=True)
        await ev.reply("⏸ ساعت بیو خاموش شد و بیوی اصلی برگشت.")
    elif sub == "text":
        if not arg:
            await ev.reply(TOKENS_HELP_FA + "\n(برای بیو)")
            return
        app.sets("clock_bio_template", arg)
        _next_bio = 0
        await ev.reply("✅ قالب ساعت بیو:\n" + render(app, arg, app.now()))
    else:
        await ev.reply(f"بیوکلاک: {'روشن' if app.s('clock_bio_on', False) else 'خاموش'}"
                       f" | قالب: {app.s('clock_bio_template', DEFAULT_BIO_TEMPLATE)}")


async def _clock_status(app, ev):
    g = app.gov.status_line()
    nxt = max(0, int(_next_name - time.time())) if app.s("clock_on", True) else None
    lines = [
        "🕐 **وضعیت ساعت**",
        f"• وضعیت: " + ("✅ روشن" if app.s("clock_on", True) else "⛔ خاموش"),
        f"• هدف: {'اسم اول' if _target_field(app) == 'first_name' else 'اسم آخر'}"
        + (" + بیو" if app.s("clock_bio_on", False) else ""),
        f"• قالب: `{app.s('clock_template', DEFAULT_TEMPLATE)}`"
        + (f"\n• پیشوند/پسوند: «{app.s('clock_prefix', '')}» … «{app.s('clock_suffix', '')}»"
           if (app.s("clock_prefix", "") or app.s("clock_suffix", "")) else ""),
        f"• نمونه: {_render_name(app)}",
        f"• فاصله: {app.s('clock_interval', 60)}s (بیو: {app.s('clock_bio_interval', 60)}s)",
        f"• منطقهٔ زمانی: {app.s('tz', 'Asia/Tehran')} | ارقام: {app.s('clock_digits', 'mono')}",
        f"• آپدیت بعدی: {jalali.fmt_dur(nxt, fa=True) if nxt is not None else '—'}",
        f"• آخرین نوشتن: {_last_why}",
        f"• 🛡 ضدبن: backoff ×{g['backoff']} | strikes: {g['strikes_1h']}"
        f" | بودجهٔ امروز: {g['budget_used']}/{g['budget_cap']}",
    ]
    await ev.reply("\n".join(lines))


@command("restore", "clock", "", "برگردوندن اسم/بیو به حالت اصلی",
         "Restore original name/bio")
async def restore_cmd(app, ev, arg):
    app.sets("clock_on", False)
    app.sets("clock_bio_on", False)
    base_name = app.s("clock_name_base", "") or ""
    base_bio = app.s("clock_bio_base", "") or ""
    await app.gov.apply("last_name", base_name or None, force=True)
    await app.gov.apply("first_name", app.s("clock_first_base", "") or None, force=True)
    await app.gov.apply("bio", base_bio or None, force=True)
    app.dels("clock_expected")
    await ev.reply("↩️ اسم و بیو به حالت اصلی برگشت. (برای روشن کردن دوباره: .clock on)")


# ---- manager-bot compatibility aliases (old menu: pause/resume/format/tz) ----
@command("pause", "clock", "", "توقف موقت ساعت (مدیریت)", "Pause clock", bot_ok=True, hidden=True)
async def pause_cmd(app, ev, arg):
    await clock_cmd(app, ev, "off")


@command("resume", "clock", "", "ادامهٔ ساعت (مدیریت)", "Resume clock", bot_ok=True, hidden=True)
async def resume_cmd(app, ev, arg):
    await clock_cmd(app, ev, "on")


@command("format", "clock", "<قالب>", "تغییر فرمت ساعت (مدیریت)", "Set clock format",
         bot_ok=True, hidden=True)
async def format_cmd(app, ev, arg):
    if not arg:
        await ev.reply(TOKENS_HELP_FA)
        return
    await clock_cmd(app, ev, "text " + arg)


@command("tz", "clock", "<zone>", "منطقهٔ زمانی (مدیریت)", "Set timezone", bot_ok=True, hidden=True)
async def tz_cmd(app, ev, arg):
    await clock_cmd(app, ev, "tz " + (arg or "Asia/Tehran"))


@command("interval", "clock", "<sec>", "فاصلهٔ آپدیت (مدیریت)", "Set interval",
         bot_ok=True, hidden=True)
async def interval_cmd(app, ev, arg):
    await clock_cmd(app, ev, "interval " + (arg or "60"))
