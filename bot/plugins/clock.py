"""Live clock in profile name/bio — with anti-ban governor pacing.

Targets: last_name (default, keeps first_name untouched), first_name, or bio.
Formats: mono/ascii/fa digits, 12/24h, Jalali/Gregorian date, custom templates.
"""
import asyncio
import datetime
import logging
import re
import time

from .. import jalali
from ..core import command

log = logging.getLogger("seltbot.clock")

DEFAULT_TEMPLATE = "｜ {hhm}:{mmm}"
DEFAULT_BIO_TEMPLATE = "{jdate} ｜ {hhm}:{mmm}"

# v2.5 — digit font registry (owner asked for a fancier clock font).
# key → (Persian label, transform fn). "bold" is the new default: clearly
# prettier than the thin mono digits and pairs well with a styled name.
DIGIT_STYLES = {
    "bold":   ("بولد",   lambda s: jalali.bold_digits(s)),
    "fa":     ("فارسی",  lambda s: jalali.fa_digits(s)),
    "mono":   ("مونو",   lambda s: jalali.mono_digits(s)),
    "double": ("توخالی", lambda s: jalali.double_digits(s)),
    "serif":  ("کلاسیک", lambda s: jalali.serif_digits(s)),
    "full":   ("عریض",   lambda s: jalali.full_digits(s)),
    "ascii":  ("ساده",   lambda s: s),
}
DEFAULT_DIGITS = "bold"


def _digit_fn(style):
    ent = DIGIT_STYLES.get(style or "")
    return ent[1] if ent else (lambda s: s)


def _rng(a, b):
    """regex range 'chr(a)-chr(b)', built from codepoints (typo-proof)."""
    return f"{chr(a)}-{chr(b)}"


# every digit font the clock can emit — keep in sync with DIGIT_STYLES
_DIGIT_CLS = (
    "0-9"                     # ascii
    + _rng(0x06F0, 0x06F9)    # fa
    + _rng(0x1D7F6, 0x1D7FF)  # mono
    + _rng(0x1D7EC, 0x1D7F5)  # bold
    + _rng(0x1D7D8, 0x1D7E1)  # double
    + _rng(0x1D7CE, 0x1D7D7)  # serif
    + _rng(0xFF10, 0xFF19)    # fullwidth
)

# v2.5.2 — the clock can emit DATE-shaped names too ({jdate} templates).
# The old pattern only matched "HH:MM" names, so a profile showing
# "1405/07/15 ｜ 𝟏𝟔:𝟑𝟒" was NOT recognized as our clock → the boot base
# capture archived that string as the user's "real" last_name, and
# .clock off / restore would write the date back as a permanent name.
_DATE_SH = (rf"[{_DIGIT_CLS}]{{1,4}}\s*[/.-]\s*[{_DIGIT_CLS}]{{1,2}}"
            rf"\s*[/.-]\s*[{_DIGIT_CLS}]{{1,2}}")
_TIME_SH = (rf"[{_DIGIT_CLS}]{{1,2}}\s*[:.،]\s*[{_DIGIT_CLS}]{{2}}"
            rf"(?:\s*[:.،]\s*[{_DIGIT_CLS}]{{2}})?")
CLOCK_NAME_RE = re.compile(
    rf"^[\W_]{{0,8}}?\s*{_TIME_SH}[\s\W_]*$"
    rf"|^[\W_]{{0,8}}?\s*{_DATE_SH}\s*[\W_]{{0,4}}?\s*{_TIME_SH}[\s\W_]*$"
    rf"|^[\W_]{{0,8}}?\s*{_DATE_SH}[\s\W_]*$")

TOKENS_HELP_FA = """🧩 توکن‌های قالب (ارقام همه با فونت انتخابی می‌شینن):
`{hhm}:{mmm}` → ساعت:دقیقه
`{jdate}` → 1405/07/15 (شمسی)
`{jWD} {jd} {jMon} {jy}` → چهارشنبه ۱۵ مهر ۱۴۰۵
`{h12}:{mm} {ampm}` → 4:45 ب.ظ
`{WD} {day} {Mon} {year}` → Thursday 7 October 2026
`{name}` → اسم/بیوی اصلیت
مثال: `.clock text {jdate} ｜ {hhm}:{mmm}`
فونت ارقام: `.clock digits` (بولد/فارسی/مونو/توخالی/کلاسیک/عریض/ساده)"""


def looks_like_clock(s, app=None):
    """True if s looks like something the clock itself wrote.
    v2.5.2: accepts date-shaped names in ANY digit font, and when `app` is
    given also matches anything the CURRENT template could have produced
    in the last few minutes (covers wordy templates like «چهارشنبه ۱۵ مهر»)."""
    if not s:
        return False
    s = s.strip()
    if CLOCK_NAME_RE.match(s):
        return True
    if app is not None and s in _recent_renders(app):
        return True
    return False


def _recent_renders(app):
    """All name/bio strings the current clock config could have emitted in
    the last ~3 minutes (used by the boot base-capture so a live clock value
    can never be archived as the user's real name)."""
    out = set()
    try:
        specs = [(app.s("clock_template", DEFAULT_TEMPLATE) or DEFAULT_TEMPLATE,
                  _target_field(app))]
        if app.s("clock_bio_on", False):
            specs.append((app.s("clock_bio_template", DEFAULT_BIO_TEMPLATE)
                          or DEFAULT_BIO_TEMPLATE, "about"))
        now = _shifted_now(app)
        pfx = str(app.s("clock_prefix", "") or "")
        sfx = str(app.s("clock_suffix", "") or "")
        for tpl, field in specs:
            for dmin in (0, -1, -2):
                try:
                    t = render(app, tpl, now + datetime.timedelta(minutes=dmin))
                except Exception:
                    continue
                out.add((pfx + t + sfx)[:_limit(app, field)])
    except Exception:
        pass
    return out


def render(app, template, dt):
    h24, mi, se = dt.hour, dt.minute, dt.second
    h12 = h24 % 12 or 12
    style = app.s("clock_digits", DEFAULT_DIGITS) or DEFAULT_DIGITS
    st = _digit_fn(style)

    ampm_fa = "ق.ظ" if h24 < 12 else "ب.ظ"
    ampm_en = "AM" if h24 < 12 else "PM"
    jy, jm, jd = jalali.g2j(dt.year, dt.month, dt.day)
    # v2.5.2: EVERY numeric token follows the chosen digit font. The old
    # render left {jdate}/{hh}/{mm}/… in plain ASCII, so «شمسی + ساعت» showed
    # "1405/07/15 ｜ 𝟏𝟔:𝟑𝟒" — mixed fonts, looked half-broken (owner report:
    # "تاریخ + ساعت کار نمی‌کنه"). Now the whole string is one consistent font.
    toks = {
        "h": st(str(h24)), "hh": st(f"{h24:02d}"),
        "m": st(str(mi)), "mm": st(f"{mi:02d}"),
        "s": st(str(se)), "ss": st(f"{se:02d}"),
        "h12": st(str(h12)), "H12": st(f"{h12:02d}"),
        "ampm": ampm_fa if app.fa else ampm_en,
        "hhm": st(f"{h24:02d}"), "mmm": st(f"{mi:02d}"), "ssm": st(f"{se:02d}"),
        "year": st(str(dt.year)), "month": st(f"{dt.month:02d}"),
        "day": st(f"{dt.day:02d}"),
        "Mon": (jalali.G_MONTHS_FA if app.fa else jalali.G_MONTHS_EN)[dt.month - 1],
        "WD": (jalali.WD_FA if app.fa else jalali.WD_EN)[dt.weekday()],
        "date": st(f"{dt.year}-{dt.month:02d}-{dt.day:02d}"),
        "jy": st(str(jy)), "jm": st(f"{jm:02d}"), "jd": st(f"{jd:02d}"),
        "jMon": jalali.J_MONTHS_FA[jm - 1],
        "jWD": jalali.WD_FA[dt.weekday()],
        "jdate": st(f"{jy}/{jm:02d}/{jd:02d}"),
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


def _offset(app):
    """v2.4 calibration: seconds to shift the clock so flips match the PHONE.

    The runner is NTP-synced, but the user's phone clock often runs up to a
    minute off true time (carrier NITZ drift — very common in Iran). +N makes
    the visible flip happen N seconds EARLIER (phone ahead of NTP), -N later.
    """
    try:
        v = int(str(app.s("clock_offset", 0) or 0).replace("+", ""))
        return max(-300, min(300, v))
    except Exception:
        return 0


def _shifted_now(app):
    return app.now() + datetime.timedelta(seconds=_offset(app))


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
    return _wrap_pfx(app, render(app, tpl, _shifted_now(app)), _target_field(app))[:_limit(app, _target_field(app))]


def _render_bio(app):
    tpl = app.s("clock_bio_template", DEFAULT_BIO_TEMPLATE) or DEFAULT_BIO_TEMPLATE
    return _wrap_pfx(app, render(app, tpl, _shifted_now(app)), "about")[:_limit(app, "about")]


def _profile_preview(app):
    """v2.5.2 — the exact string that will sit NEXT TO the owner's name.
    Showing only the clock fragment confused the owner ("nothing changed") —
    the real effect is first_name + last_name together."""
    try:
        sample = _render_name(app)
    except Exception:
        return ""
    if _target_field(app) == "first_name":
        return sample
    first = str(app.s("clock_first_base", "") or "").strip()
    return (first + " " + sample).strip() if first else sample


async def _apply_now(app):
    """v2.5.2 — a settings change (font/format/prefix) now writes to the
    profile IMMEDIATELY instead of waiting for the next minute flip. The
    owner clicked buttons and saw nothing change for up to a minute — and
    if the clock was OFF, nothing ever changed at all. Honors the governor
    pacing floor (anti-ban): too soon after the last write → report the wait
    (the next boundary write picks the change up automatically)."""
    if not app.s("clock_on", True):
        return "off"
    target = _target_field(app)
    gap = time.time() - app.gov.last_ok.get(target, 0)
    need = max(1.0, app.gov.min_gap() - 1)
    if gap >= need:
        try:
            ok, retry, why = await app.gov.apply(target,
                                                 lambda: _render_name(app),
                                                 force=True)
            return "ok" if ok else why
        except Exception:
            return "error"
    return f"wait:{int(need - gap) + 1}"


async def _apply_feedback(app):
    """Persian one-liner describing what _apply_now did (for command replies)."""
    r = await _apply_now(app)
    if r == "off":
        return ("\n⚠️ ساعت فعلاً خاموشه! تنظیم ذخیره شد ولی تا روشنش نکنی کنار اسمت"
                " نمی‌شینه — دکمهٔ «▶️ روشن‌کردن ساعت» یا `.clock on`")
    if r == "ok":
        return "\n✅ همین الان روی پروفایلت اعمال شد."
    if r.startswith("wait:"):
        return f"\n⏳ ذخیره شد — تا {r[5:]} ثانیهٔ دیگه کنار اسمت می‌شینه."
    return f"\n⏳ ذخیره شد — اعمال خودکار در آپدیت بعدی ({r})."


def _align_next(now, iv, off=0):
    # Write lands ~0.3s AFTER the (offset-shifted) minute boundary so the
    # visible change happens right as the phone's clock flips (epoch is
    # minute-aligned for whole-minute UTC offsets such as Iran's +3:30).
    # `off` shifts the whole schedule: the flip happens exactly when
    # (true_time + off) crosses a minute boundary — that is what makes the
    # profile clock match the user's PHONE even if the phone runs off NTP.
    if iv >= 60 and 60 % iv == 0:
        return (int((now + off) / iv) + 1) * iv + 0.3 - off
    return now + iv + 0.2


_task = None
_next_name = 0.0
_next_bio = 0.0
_next_verify = 0.0
_last_why = "init"
_force_name = False    # realign flag: force next boundary-window write
_force_bio = False


def _next_after(now, why, iv, retry, off=0):
    """Decide (next_ts, force_next) after a governor result.

    ok/same/keep → align to the next interval boundary (flip just after the
    minute change).  pace → the previous write landed mid-minute (e.g. the
    boot write or a flood-recovery write): wait for the NEXT boundary and
    force the write there, so the flip phase can never lock mid-minute —
    a locked mid-minute phase is exactly what made the clock flip late.
    flood/budget/error → timed retry (phase self-heals via pace→force later).
    """
    if why == "pace":
        return _align_next(now, iv, off), True
    if why in ("ok", "same", "keep"):
        return _align_next(now, iv, off), False
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
            off = _offset(app)
            if not app.module_off("clock") and app.s("clock_on", True):
                if now >= _next_name:
                    # v2.4: pass a CALLABLE — the governor re-renders it right
                    # before the actual profile write, so the minute shown is
                    # the minute at write-time (not at wake-time). Kills the
                    # rare stale-render that made the clock lag a full minute.
                    ok, retry, why = await app.gov.apply(
                        _target_field(app), lambda: _render_name(app),
                        force=_force_name)
                    _last_why = why
                    iv = max(app.gov.min_gap(), int(app.s("clock_interval", 60)))
                    _next_name, _force_name = _next_after(now, why, iv, retry, off)
                    # v2.4.1 THE phone-sync fix: a mid-minute write (boot,
                    # .clock on/text/prefix change, reconnect) leaves <60s to
                    # the next boundary — the governor would PACE that flip and
                    # the profile would show a FULL STALE MINUTE. One-shot
                    # force it (only while healthy; FloodWait/backoff still rule).
                    # The 0.5s tolerance keeps exact-boundary steady writes
                    # UNforced so a FloodWait can never escalate.
                    if why == "ok" and app.gov.healthy() \
                            and _next_name - now < app.gov.effective_interval(
                                _target_field(app)) - 0.5:
                        _force_name = True
            if not app.module_off("clock") and app.s("clock_bio_on", False):
                if now >= _next_bio:
                    text_fn = (lambda: _render_bio(app))
                    ok, retry, why = await app.gov.apply("bio", text_fn,
                                                         force=_force_bio)
                    iv = max(60, int(app.s("clock_bio_interval", 60)))
                    _next_bio, _force_bio = _next_after(now, why, iv, retry, off)
                    if why == "ok" and app.gov.healthy() \
                            and _next_bio - now < app.gov.effective_interval("bio"):
                        _force_bio = True
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


@command("clock", "clock", "[on/off/text/interval/tz/target/offset/digits/bio/status]",
         "ساعت زندهٔ کنار اسم/بیو + تنظیمات", "Live clock in name/bio + settings",
         aliases=("clockname",))
async def clock_cmd(app, ev, arg):
    global _next_name
    parts = arg.split(None, 1)
    sub = (parts[0].lower() if parts else "status")
    rest = parts[1].strip() if len(parts) > 1 else ""

    if sub in ("status", "وضعیت", ""):
        await _clock_status(app, ev)
    elif sub == "on":
        app.sets("clock_on", True)
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
        note = await _apply_feedback(app)
        await ev.reply("✅ قالب ساعت ست شد." + note
                       + "\n" + _profile_preview(app))
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
        await _clock_digits(app, ev, rest)
    elif sub == "prefix":
        app.sets("clock_prefix", rest)
        note = await _apply_feedback(app)
        await ev.reply("✅ پیشوند: «" + rest + "»" + note
                       + "\n" + _profile_preview(app))
    elif sub == "suffix":
        app.sets("clock_suffix", rest)
        note = await _apply_feedback(app)
        await ev.reply("✅ پسوند: «" + rest + "»" + note
                       + "\n" + _profile_preview(app))
    elif sub == "offset":
        if not rest:
            cur = _offset(app)
            await ev.reply(
                f"🎛 انحراف کالیبره با ساعت گوشی: {cur:+d} ثانیه\n\n"
                "ساعت پروفایل با ساعت واقعیِ اینترنت (NTP) همگامه، ولی ساعت"
                " گوشی‌ها گاهی تا یه دقیقه باهاش فرق داره (خطای اپراتور)."
                " اگه همیشه یه اختلاف ثابتی می‌بینی، این‌طوری کالیبره کن که"
                " تغییر دقیقه دقیقاً با گوشی‌ات بیفته:\n"
                "`.clock offset +40` → جلو بنداز (وقتی گوشی‌ات جلوته)\n"
                "`.clock offset -40` → عقب بنداز (وقتی گوشی‌ات عقبه)\n"
                "`.clock offset 0` → حذف انحراف\n\n"
                "چند دقیقه پشت‌سرهم مقایسه کن و میانگین بگیر (حداکثر ±۳۰۰ ثانیه)."
                if app.fa else
                f"🎛 Clock offset: {cur:+d}s\n.clock offset +N / -N / 0")
            return
        try:
            v = int(str(jalali.to_en_digits(rest.strip())).replace("+", ""))
        except ValueError:
            await ev.reply("❌ فرمت: `.clock offset +40` یا `-40` (ثانیه)" if app.fa
                           else "❌ `.clock offset +40` or `-40` (seconds)")
            return
        v = max(-300, min(300, v))
        app.sets("clock_offset", v)
        _next_name = 0
        await ev.reply((f"✅ انحراف ساعت: {v:+d} ثانیه — از همین لحظه اعمال شد.\n"
                        f"نمونهٔ فعلی: {_render_name(app)}") if app.fa else
                       (f"✅ Clock offset: {v:+d}s\nNow: {_render_name(app)}"))
    elif sub == "bio":
        await _clock_bio(app, ev, rest)
    else:
        await ev.reply(app.t("bad_arg") + "\n" + TOKENS_HELP_FA)


async def _clock_digits(app, ev, rest):
    """v2.5 — show/switch the clock digit font (7 styles)."""
    global _next_name
    cur = app.s("clock_digits", DEFAULT_DIGITS) or DEFAULT_DIGITS
    sample = f"{app.now().hour:02d}:{app.now().minute:02d}"
    if rest:
        key = rest.strip().lower()
        alias = {"fancy": "mono", "font": "mono", "persian": "fa", "en": "ascii",
                 "انگلیسی": "ascii", "مونو": "mono", "فارسی": "fa", "بولد": "bold",
                 "توخالی": "double", "کلاسیک": "serif", "عریض": "full", "ساده": "ascii"}
        key = alias.get(key, key)
        if key not in DIGIT_STYLES:
            await ev.reply("❌ سبک نامعتبره — لیست: " + " / ".join(DIGIT_STYLES))
            return
        app.sets("clock_digits", key)
        note = await _apply_feedback(app)
        await ev.reply(
            f"✅ فونت ارقام ساعت: **{DIGIT_STYLES[key][0]}** — نمونه: `{_digit_fn(key)(sample)}`"
            + note + "\n" + _profile_preview(app))
        return
    lines = ["🔢 **فونت ارقام ساعت** — یکی رو انتخاب کن:", ""]
    for key, (fa_label, fn) in DIGIT_STYLES.items():
        mark = "✅" if key == cur else "▫️"
        lines.append(f"{mark} {fa_label} → `{fn(sample)}`  (`.clock digits {key}`)")
    lines += ["", "از منوی مدیریت هم می‌تونی با دکمه عوضش کنی 🧊"]
    await ev.reply("\n".join(lines))


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
    off = _offset(app)
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
        f"• منطقهٔ زمانی: {app.s('tz', 'Asia/Tehran')} | ارقام: {DIGIT_STYLES.get(app.s('clock_digits', DEFAULT_DIGITS) or DEFAULT_DIGITS, ('?',))[0]}",
        f"• کالیبره با گوشی: {off:+d} ثانیه"
        + (" (`.clock offset` برای تنظیم)" if not off else ""),
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
    # v2.5.2 fix: the old `base_name or None` hit the governor's "keep"
    # branch whenever the original last_name was EMPTY → restore silently
    # did NOTHING and the clock text stayed on the profile forever.
    # An empty string is a valid, writable value for last_name/about.
    await app.gov.apply("last_name", base_name, force=True)
    await app.gov.apply("first_name", app.s("clock_first_base", "") or None, force=True)
    await app.gov.apply("bio", base_bio, force=True)
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
