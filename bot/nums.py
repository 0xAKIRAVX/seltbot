"""Crash-proof numeric coercion for stored settings (v2.8.0).

Lives in its own leaf module (no imports from the bot package) so BOTH
bot.core and bot.safety can use it without a circular import.

Why: settings persisted before typed validation existed may hold junk like
'abc'. Every background loop (clock tick, governor budget, AFK/autoreply
cooldowns…) must coerce those defensively — a ValueError on every tick used
to silently kill the 24/7 clock.
"""


def as_int(val, default, lo=None, hi=None):
    """int() that never raises; junk/None → default, then clamped to [lo, hi]."""
    try:
        v = int(str(val).strip())
    except Exception:
        return default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def as_float(val, default, lo=None, hi=None):
    """float() that never raises; junk/None/NaN → default, clamped to [lo, hi]."""
    try:
        v = float(str(val).strip())
    except Exception:
        return default
    if v != v:  # NaN
        return default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v
