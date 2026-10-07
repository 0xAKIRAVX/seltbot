"""Jalali (Shamsi) calendar conversion, Persian/Mono digits, duration helpers."""
import re

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
EN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
MONO_DIGITS = str.maketrans("0123456789", "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿")


# v2.5 — extra Unicode digit fonts for the profile clock (owner asked for a
# fancier digit font). Codepoints built programmatically so the source stays
# copy-paste-corruption-proof.
def _digit_font(base_cp):
    """str.translate map: '0'-'9' → U+<base_cp>..U+<base_cp+9>."""
    return {ord("0") + i: base_cp + i for i in range(10)}


BOLD_DIGITS = _digit_font(0x1D7EC)    # 𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵  (sans-serif bold)
DOUBLE_DIGITS = _digit_font(0x1D7D8)  # 𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡  (double-struck / outlined)
SERIF_DIGITS = _digit_font(0x1D7CE)   # 𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗  (serif bold / classic)
FULL_DIGITS = _digit_font(0xFF10)     # ０１２３４５６７８９  (fullwidth)


def fa_digits(s):
    return str(s).translate(FA_DIGITS)


def mono_digits(s):
    return str(s).translate(MONO_DIGITS)


def bold_digits(s):
    return str(s).translate(BOLD_DIGITS)


def double_digits(s):
    return str(s).translate(DOUBLE_DIGITS)


def serif_digits(s):
    return str(s).translate(SERIF_DIGITS)


def full_digits(s):
    return str(s).translate(FULL_DIGITS)


def to_en_digits(s):
    return str(s).translate(EN_DIGITS)


J_MONTHS_FA = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
               "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
G_MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
G_MONTHS_FA = ["ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن",
               "ژوئیه", "اوت", "سپتامبر", "اکتبر", "نوامبر", "دسامبر"]
# index = python datetime.weekday() (Mon=0)
WD_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WD_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]


def g2j(gy, gm, gd):
    """Gregorian → Jalali. Returns (jy, jm, jd)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) \
        + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def j2g(jy, jm, jd):
    """Jalali → Gregorian. Returns (gy, gm, gd)."""
    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) \
        + jd + ((jm < 7) * ((jm - 1) * 31)) + ((jm >= 7) * (((jm - 7) * 30) + 186))
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    sal_a = [0, 31, 59 if (gy % 4 != 0) else 60, 90, 120, 151, 181, 212,
             243, 273, 304, 334]
    gm = 0
    while gm < 13 and gd > sal_a[gm]:
        gm += 1
    gd -= sal_a[gm - 1]
    return gy, gm, gd


def j_date_tuple(dt):
    return g2j(dt.year, dt.month, dt.day)


def j_date_str(dt, fa=False):
    jy, jm, jd = g2j(dt.year, dt.month, dt.day)
    s = f"{jy}/{jm:02d}/{jd:02d}"
    return fa_digits(s) if fa else s


def j_date_long(dt, fa=True):
    jy, jm, jd = g2j(dt.year, dt.month, dt.day)
    wd = WD_FA[dt.weekday()] if fa else WD_EN[dt.weekday()]
    if fa:
        return f"{wd} {fa_digits(jd)} {J_MONTHS_FA[jm-1]} {fa_digits(jy)}"
    return f"{wd} {jd} {J_MONTHS_FA[jm-1]} {jy}"


def g_date_long(dt, fa=True):
    wd = WD_FA[dt.weekday()] if fa else WD_EN[dt.weekday()]
    if fa:
        return f"{wd} {fa_digits(dt.day)} {G_MONTHS_FA[dt.month-1]} {fa_digits(dt.year)}"
    return f"{wd} {dt.day} {G_MONTHS_EN[dt.month-1]} {dt.year}"


def fmt_dur(sec, fa=True):
    """Human duration: 2h 17m / ۲ ساعت و ۱۷ دقیقه"""
    sec = int(max(0, sec))
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    if fa:
        parts = []
        if d:
            parts.append(f"{fa_digits(d)} روز")
        if h:
            parts.append(f"{fa_digits(h)} ساعت")
        if m:
            parts.append(f"{fa_digits(m)} دقیقه")
        if not parts:
            parts.append(f"{fa_digits(s)} ثانیه")
        if len(parts) > 2:
            parts = parts[:2]
        return " و ".join(parts)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if not parts:
        parts.append(f"{s}s")
    return " ".join(parts[:2])


_DUR_RE = re.compile(r"(\d+)\s*([smhdw]|ساعت|دقیقه|ثانیه|روز|هفته)", re.IGNORECASE)


def parse_duration(s, default_minutes=None):
    """'1d2h30m' / '45m' / '90' → seconds. Persian digits & words supported.
    Plain number = minutes. Returns None if unparseable."""
    s = to_en_digits(str(s).strip())
    if not s:
        return None
    if re.fullmatch(r"\d+", s):
        return int(s) * 60
    unit_map = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800,
                "ثانیه": 1, "دقیقه": 60, "ساعت": 3600, "روز": 86400, "هفته": 604800}
    total = 0
    for num, unit in _DUR_RE.findall(s):
        total += int(num) * unit_map.get(unit.lower(), unit_map.get(unit, 0))
    return total if total > 0 else None
