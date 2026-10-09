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


# v2.7 — «ساعت ماتریسی متحرک». Telegram profile names are STATIC text:
# no real frame-rate animation exists, and writing faster than once a minute
# would violate the anti-ban pacing (hard requirement). What IS possible —
# safely, at zero extra API writes: change the glyphs every minute, riding
# the normal clock flip.
# v2.7.1 — «بارون کد»: owner feedback «این حرکت نمی‌کنه» — the v2.7 per-minute
# delta (braille dots + font swaps) was too subtle to SEE at a glance. Now
# FOUR moving parts, led by {rain}: a sliding half-width-katakana code column
# (the Matrix «digital rain» — each minute the window slides one char: a fresh
# glyph enters on the right, the oldest drops off the left, so the name
# visibly FLOWS), a high-contrast quarter-circle spinner, glitch-mixed digit
# fonts, and a filling hour progress bar.
MATRIX_TEMPLATE_V27 = "{spin}｜ {gtime} {hbar}"      # pre-2.7.1 (migration match)
MATRIX_TEMPLATE = "{spin}｜ {rain} {gtime} ｜ {hbar}"
_SPIN_FRAMES = "◐◓◑◒"     # quarter-circle fill rotating, one frame per minute
_RAIN_POOL = ("ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ"
              "0123456789")  # the Matrix «digital rain» glyph pool
_GLITCH_FONTS = (jalali.mono_digits, jalali.bold_digits,
                 jalali.double_digits, jalali.full_digits,
                 jalali.serif_digits)


def _rain_char(k):
    """Deterministic pseudo-random pool glyph for stream index k
    (multiplicative hash + xorshift mix — same k → same char, always)."""
    h = (k * 2654435761) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 1274126177) & 0xFFFFFFFF
    h ^= h >> 16
    return _RAIN_POOL[h % len(_RAIN_POOL)]


def _rain(dt, n=5):
    """v2.7.1 — «بارون کد»: sliding window over an endless deterministic
    glyph stream indexed by ABSOLUTE minute (toordinal-based, never resets).
    One minute → the window slides one char: a new glyph enters on the right,
    the oldest leaves on the left. Minute-stable within the minute →
    idempotent writes, zero extra profile writes (anti-ban pacing intact)."""
    m = dt.toordinal() * 1440 + dt.hour * 60 + dt.minute
    return "".join(_rain_char(m - i) for i in range(n - 1, -1, -1))


def _spin_frame(dt):
    """Spinner frame for this minute (full rotation every 4 minutes)."""
    return _SPIN_FRAMES[dt.minute % 4]


def _glitch_time(dt):
    """Matrix «digital rain» time: every digit picks its font family from a
    seed that advances each minute — the digits visibly re-style themselves
    on every flip. Self-animating (ignores clock_digits on purpose: the mix
    IS the effect). Deterministic within a minute (idempotent writes)."""
    s = f"{dt.hour:02d}:{dt.minute:02d}"
    seed = dt.hour * 60 + dt.minute
    out = []
    for i, ch in enumerate(s):
        if ch.isdigit():
            fn = _GLITCH_FONTS[(seed + i * 3) % len(_GLITCH_FONTS)]
            out.append(fn(ch))
        else:
            out.append(ch)
    return "".join(out)


def _progress_bar(frac, blocks=12):
    filled = max(0, min(blocks, int(round(frac * blocks))))
    return "▓" * filled + "░" * (blocks - filled)


def _hour_bar(dt):
    """▓▓▓▓░░░░░░░░ — how far into the current hour (one block ≈ 5 min)."""
    return _progress_bar((dt.minute * 60 + dt.second) / 3600.0)


def _day_bar(dt):
    """▓▓░░░░░░░░░░ — how far into the current day."""
    return _progress_bar((dt.hour * 3600 + dt.minute * 60 + dt.second) / 86400.0)


def _phase_emoji(dt):
    """☀️/🌤/🌇/🌙 by local hour — day/night indicator token."""
    h = dt.hour
    if 5 <= h < 12:
        return "☀️"
    if 12 <= h < 17:
        return "🌤"
    if 17 <= h < 20:
        return "🌇"
    return "🌙"


def _parse_since(text):
    """v2.7 — parse the `.clock since` date: Jalali «1405/7/15» (year < 1700)
    or Gregorian «2026-10-07» / «2026.10.7»; accepts fa-digits. Returns ISO
    "YYYY-MM-DD" or None when invalid."""
    s = jalali.to_en_digits(str(text or "").strip()).replace(".", "/").replace("-", "/")
    m = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})$", s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        if y < 1700:                       # Jalali year → Gregorian
            if not (1 <= mo <= 12 and 1 <= d <= 31):
                return None
            y, mo, d = jalali.j2g(y, mo, d)
        return datetime.date(y, mo, d).isoformat()
    except Exception:
        return None


def _days_since(app, dt):
    """Whole days between `.clock since` date and dt (floor, never negative).
    «—» when no start date is set."""
    try:
        d0 = datetime.date.fromisoformat(str(app.s("clock_since", "") or ""))
        return str(max(0, (dt.date() - d0).days))
    except Exception:
        return "—"


# v2.6 — «حذف تاریخ» (owner: "یه گزینه حذف تاریخ بزار که بتونم از پروفایلم
# تاریخ رو پاک کنم"). These are every token (and icon) that renders a DATE
# part; the rest of the template (clock, dividers, {name}) must survive.
_DATE_TOKENS = ("{jdate}", "{jdatefa}", "{date}", "{jy}", "{jm}", "{jd}",
                "{jMon}", "{jWD}", "{year}", "{month}", "{day}",
                "{Mon}", "{WD}")
_DATE_EMOJI = ("📅", "🗓", "📆")


def has_date_tokens(tpl):
    """True if this clock template renders any date part."""
    tpl = tpl or ""
    return any(t in tpl for t in _DATE_TOKENS) or any(e in tpl for e in _DATE_EMOJI)


def _strip_date(tpl):
    """v2.6 — remove every date token (+ date icon) from a clock template
    and tidy what the date left behind, so «{jdate} ｜ {hhm}:{mmm}» becomes
    the clean «｜ {hhm}:{mmm}». A single leading «｜» divider is KEPT (that's
    the canonical «name ｜ clock» look); dangling «-»/«—» stubs at either
    end are dropped; doubled dividers collapse to one. Idempotent."""
    out = tpl or ""
    for t in _DATE_TOKENS:
        out = out.replace(t, "")
    for e in _DATE_EMOJI:
        out = out.replace(e, "")
    out = re.sub(r"[ \t]{2,}", " ", out)                 # collapse space runs
    out = re.sub(r"\s*[｜|]\s*[｜|]\s*", " ｜ ", out)     # «｜ ｜» → «｜»
    out = re.sub(r"(?<=\S)\s*[｜|—–\-·/]+\s*$", "", out)  # trailing stub
    out = re.sub(r"^[\s]*[—–\-·/]+\s*", "", out)          # leading dash stub
    out = out.strip()
    out = re.sub(r"^\|", "｜", out)                        # normalize half-width
    return out


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
# v2.7.1 — matrix names now carry a half-width-katakana rain column
# (U+FF66–FF9F are \w LETTERS, not symbols!) — allow that range in the noise
# zones around the time/date, or looks_like_clock() would miss
# «◐｜ ﾊﾐﾋｰｼ 𝟶𝟯:𝟰𝟺 ｜ ▓░»-shaped names and the boot base-capture could
# archive a live clock value as the user's "real" last_name
# (_recent_renders still backstops whenever `app` is passed).
_RAIN_CLS = _rng(0xFF66, 0xFF9F)
CLOCK_NAME_RE = re.compile(
    rf"^[\W_{_RAIN_CLS}]{{0,16}}?\s*{_TIME_SH}[\s\W_{_RAIN_CLS}]*$"
    rf"|^[\W_{_RAIN_CLS}]{{0,16}}?\s*{_DATE_SH}\s*[\W_{_RAIN_CLS}]{{0,4}}?\s*{_TIME_SH}[\s\W_{_RAIN_CLS}]*$"
    rf"|^[\W_{_RAIN_CLS}]{{0,16}}?\s*{_DATE_SH}[\s\W_{_RAIN_CLS}]*$")

TOKENS_HELP_FA = """🧩 توکن‌های قالب (ارقام همه با فونت انتخابی می‌شینن):
`{hhm}:{mmm}` → ساعت:دقیقه
`{jdate}` → 1405/07/15 (شمسی)
`{jWD} {jd} {jMon} {jy}` → چهارشنبه ۱۵ مهر ۱۴۰۵
`{h12}:{mm} {ampm}` → 4:45 ب.ظ
`{WD} {day} {Mon} {year}` → Thursday 7 October 2026
`{name}` → اسم/بیوی اصلیت

🌀 توکن‌های متحرک (هر دقیقه عوض می‌شن — ماتریکس):
`{rain}` → ﾊﾐﾋｰｼ بارون کد — هر دقیقه می‌لغزه و کاراکتر جدید می‌باره
`{spin}` → ◐ اسپینر چرخان (◐→◓→◑→◒)
`{gtime}` → 𝟶𝟑:𝟺𝟒 ساعت گلیچی — فونت هر رقم هر دقیقه می‌رقصه
`{hbar}` → ▓▓▓▓░░░░ نوار پیشرفت ساعت | `{dbar}` → نوار پیشرفت روز
`{phase}` → ☀️/🌙 بر اساس شب‌وروز
`{days}` → شمارش روز از تاریخ (`.clock since 1405/7/15`)

مثال: `.clock text {jdate} ｜ {hhm}:{mmm}`
ماتریکس یک‌کلیکی: `.clock matrix` (خاموشش: `.clock matrix off`)
فونت ارقام: `.clock digits` (بولد/فارسی/مونو/توخالی/کلاسیک/عریض/ساده)
حذف تاریخ (فقط ساعت بمونه): `.clock nodate`"""


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
        # v2.7 — matrix/animated tokens. All are minute-stable (identical
        # within a minute → idempotent writes) but minute-ADVANCING (the
        # visible "motion"), and they ride the existing once-per-minute
        # flip — zero extra profile writes, anti-ban pacing untouched.
        "spin": _spin_frame(dt),
        "rain": _rain(dt),
        "gtime": _glitch_time(dt),
        "hbar": _hour_bar(dt),
        "dbar": _day_bar(dt),
        "phase": _phase_emoji(dt),
        "days": st(_days_since(app, dt)),
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


@command("clock", "clock", "[on/off/text/nodate/matrix/since/interval/tz/target/offset/digits/bio/status]",
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
            # v2.7.2: pass the base AS-IS — an EMPTY base must be written as ""
            # to actually CLEAR the clock text. The old `base or None` hit the
            # governor's "keep" branch and the clock stayed on the profile
            # forever (this owner's original last_name IS empty!).
            base = str(app.s("clock_name_base", "") or "")
            await app.gov.apply(_target_field(app), base, force=True)
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
    elif sub in ("nodate", "no-date", "dateoff", "date-off", "بدون تاریخ",
                 "بدون-تاریخ", "حذف تاریخ", "حذف-تاریخ", "حذف"):
        await _clock_nodate(app, ev)
    elif sub in ("matrix", "ماتریکس", "ماتریک"):
        await _clock_matrix(app, ev, rest)
    elif sub == "since":
        await _clock_since(app, ev, rest)
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
        new = ("first_name" if rest in ("first", "firstname", "اسم", "first_name")
               else "last_name")
        if new != _target_field(app):
            # v2.7.2: switching the target must CLEAR the clock text from the
            # OLD field (restore its base) — before, the old field kept showing
            # a frozen clock next to the new one. Reply also follows the REAL
            # target now («.clock target اسم» used to say “اسم آخر”).
            app.sets("clock_target", new)
            old = "last_name" if new == "first_name" else "first_name"
            old_base = str(app.s("clock_first_base" if old == "first_name"
                                 else "clock_name_base", "") or "")
            await app.gov.apply(old, old_base, force=True)
            _next_name = 0
        await ev.reply(f"✅ ساعت روی {'اسم اول' if _target_field(app) == 'first_name' else 'اسم آخر'} می‌شینه")
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


async def _clock_nodate(app, ev):
    """v2.6 — «حذف تاریخ»: one tap / one command and the profile shows ONLY
    the clock again. Strips date tokens from the NAME template (always) and
    from the BIO template too when the bio clock is on; everything else the
    owner configured (font, 12/24h, {name}, dividers) is preserved."""
    global _next_bio
    tpl = app.s("clock_template", DEFAULT_TEMPLATE) or DEFAULT_TEMPLATE
    had_date = has_date_tokens(tpl)
    bio_on = app.s("clock_bio_on", False)
    bio_tpl = (app.s("clock_bio_template", DEFAULT_BIO_TEMPLATE)
               or DEFAULT_BIO_TEMPLATE) if bio_on else ""
    bio_had = bool(bio_tpl) and has_date_tokens(bio_tpl)

    if not had_date and not bio_had:
        await ev.reply("🙂 تاریخی توی ساعتت نیست — الان هم فقط ساعت نشون می‌دی.\n"
                       + _profile_preview(app))
        return

    new_tpl = _strip_date(tpl) or DEFAULT_TEMPLATE
    app.sets("clock_template", new_tpl)
    if bio_had:
        app.sets("clock_bio_template", _strip_date(bio_tpl) or DEFAULT_BIO_TEMPLATE)
        _next_bio = 0          # bio clock loop picks it up on its next wake
    note = await _apply_feedback(app)
    msg = ("🗑 تاریخ حذف شد — از این به بعد فقط ساعت کنار اسمت می‌شینه."
           if had_date else
           "🗑 تاریخ از ساعتِ بیو حذف شد — فقط ساعت می‌مونه.")
    hint = ("\nبرای برگردوندن تاریخ هر وقت خواستی: دکمهٔ «📅 شمسی + ساعت» یا "
            "`.clock text {jdate} ｜ {hhm}:{mmm}`") if had_date else ""
    await ev.reply(msg + note + "\n" + _profile_preview(app) + hint)


async def _clock_matrix(app, ev, rest):
    """v2.7 — one tap «ساعت ماتریسی متحرک»: preset template with a sliding
    katakana code-rain column, a rotating quarter-circle spinner, glitch-mixed
    digit fonts and an hour progress bar. All four change EVERY minute, riding
    the normal clock flip (zero extra API writes — anti-ban pacing untouched).
    `matrix off` restores the previous look, date-stripped (the owner's
    standing «no date» choice is kept)."""
    arg = (rest or "").strip().lower()
    on = bool(app.s("clock_matrix_on", False))
    if arg in ("off", "خاموش", "بستن"):
        want = False
    elif arg in ("on", "روشن", ""):
        want = True
    else:
        want = not on                      # bare `.clock matrix` toggles
    if want and not on:
        prev = app.s("clock_template", DEFAULT_TEMPLATE) or DEFAULT_TEMPLATE
        app.sets("clock_matrix_prev", prev)
    if want:
        app.sets("clock_matrix_on", True)
        app.sets("clock_template", MATRIX_TEMPLATE)
    else:
        app.sets("clock_matrix_on", False)
        prev = app.s("clock_matrix_prev", "") or ""
        app.sets("clock_template", _strip_date(prev) or DEFAULT_TEMPLATE)
    note = await _apply_feedback(app)
    if want:
        msg = ("🌀 ماتریکس v2.7.1 روشن شد — بارون کد اومد!\n"
               "هر دقیقه چهار چیز عوض می‌شه:\n"
               "• ﾊﾐﾋｰｼ بارون کد می‌لغزه — کاراکتر جدید از راست می‌باره\n"
               "• اسپینر می‌چرخه ◐→◓→◑→◒\n"
               "• فونت ارقام می‌رقصه (گلیچ دیجیتال)\n"
               "• نوار پیشرفت ساعت پُر می‌شه ▓\n"
               "ⓘ اسم پروفایل تلگرام متن ثابته و انیمیشن واقعی نداره — این"
               " امن‌ترین شکل «متحرک» ممکنه: هر دقیقه، روی همون تیکِ همیشگی"
               " ساعت، بدون حتی یک نوشتنِ اضافه (ریسک بن صفر).")
    else:
        msg = "🌀 حالت ماتریکس خاموش شد — قالب قبلی (بدون تاریخ) برگشت."
    await ev.reply(msg + note + "\n" + _profile_preview(app))


async def _clock_since(app, ev, rest):
    """v2.7 — `{days}` شمارش روز: `.clock since 1405/7/15` (شمسی یا میلادی).
    محبوب برای «روز X بدون ...» کنار ساعت."""
    rest = (rest or "").strip()
    cur = app.s("clock_since", "") or ""
    if rest.lower() in ("off", "حذف", "پاک"):
        if cur:
            app.dels("clock_since")
        await ev.reply("🗑 شمارش روز حذف شد.")
        return
    if not rest:
        if cur:
            await ev.reply(
                f"📅 شمارش روز فعال: از {cur}\n"
                f"امروز روز {_days_since(app, app.now())} است.\n"
                "توکنش `{days}` — مثل: `.clock text روز {{days}} ｜ {{hhm}}:{{mmm}}`\n"
                "حذف: `.clock since off`")
        else:
            await ev.reply(
                "📆 شمارش روز — تاریخ شروع رو بده (شمسی یا میلادی):\n"
                "`.clock since 1405/7/15` ← شمسی\n"
                "`.clock since 2026-10-07` ← میلادی\n"
                "بعد با توکن `{days}` توی قالب ساعت استفاده‌ش کن:\n"
                "`.clock text روز {days} ｜ {hhm}:{mmm}`")
        return
    iso = _parse_since(rest)
    if not iso:
        await ev.reply("❌ فرمت تاریخ درست نیست — مثال‌ها: `1405/7/15` یا `2026-10-07`")
        return
    app.sets("clock_since", iso)
    await ev.reply(
        f"✅ شمارش روز از {iso} ست شد — امروز روز {_days_since(app, app.now())} است.\n"
        "نمونه‌ش رو ببین: `روز " + _days_since(app, app.now()) + "` — با دستور"
        " `.clock text روز {days} ｜ {hhm}:{mmm}` بچسبونش کنار ساعت.")


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
        # v2.7.2: same empty-base fix as `.clock off` — write "" (not None)
        # so an originally-empty bio really gets cleared.
        base = str(app.s("clock_bio_base", "") or "")
        await app.gov.apply("bio", base, force=True)
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
        "• وضعیت: " + ("✅ روشن" if app.s("clock_on", True) else "⛔ خاموش"),
        f"• هدف: {'اسم اول' if _target_field(app) == 'first_name' else 'اسم آخر'}"
        + (" + بیو" if app.s("clock_bio_on", False) else ""),
        f"• قالب: `{app.s('clock_template', DEFAULT_TEMPLATE)}`"
        + (f"\n• پیشوند/پسوند: «{app.s('clock_prefix', '')}» … «{app.s('clock_suffix', '')}»"
           if (app.s("clock_prefix", "") or app.s("clock_suffix", "")) else ""),
        f"• نمونه: {_render_name(app)}",
        f"• فاصله: {app.s('clock_interval', 60)}s (بیو: {app.s('clock_bio_interval', 60)}s)",
        f"• منطقهٔ زمانی: {app.s('tz', 'Asia/Tehran')} | ارقام: {DIGIT_STYLES.get(app.s('clock_digits', DEFAULT_DIGITS) or DEFAULT_DIGITS, ('?',))[0]}",
        "• 🌀 ماتریکس: " + ("✅ فعال (بارون کد + اسپینر، هر دقیقه می‌لغزه)" if app.s("clock_matrix_on", False)
                             else "⛔ خاموش (`.clock matrix`)"),
        (f"• 📆 شمارش روز: روز {_days_since(app, app.now())} از {app.s('clock_since', '')}"
         if app.s("clock_since", "") else "• 📆 شمارش روز: ⛔ (`.clock since 1405/7/15`)"),
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
    # v2.7.2: first_name had the same latent bug (`or None` → governor "keep"
    # when the original first_name was empty) — write the string AS-IS now.
    await app.gov.apply("first_name", str(app.s("clock_first_base", "") or ""), force=True)
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
