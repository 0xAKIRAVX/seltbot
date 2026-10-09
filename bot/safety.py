"""Anti-ban safety layer: profile-update governor, flood backoff, daily budget.

The user explicitly asked for account safety ("اکانتم آسیب نبینه و بن نشه"),
so every profile write goes through this governor:
  - skip identical no-op writes
  - enforce per-target pacing (min gap floors, hard floor 30s / 15s risky mode)
  - FloodWait → exponential backoff (x1.5, decays after 30 clean minutes)
  - daily update budget, auto-pause + notify when exhausted
  - silent-reset detection (fresh read + compare) → strike → escalate interval
"""
import logging
import time

from telethon.errors import FloodWaitError
from telethon.tl import functions, types

from .nums import as_int

log = logging.getLogger("seltbot.safety")

TARGETS = ("first_name", "last_name", "bio")


class ProfileGovernor:
    def __init__(self, app):
        self.app = app
        self.last_try = {}
        self.last_ok = {}
        self.last_text = {}
        self.backoff = 1.0
        self._last_flood = 0.0
        self.strikes = []
        self._budget_day = None
        self._budget_n = 0
        self._notified_budget = False
        self._notified_strikes = 0.0

    # ---------- config ----------
    def base_interval(self, target):
        if target == "bio":
            return max(60, as_int(self.app.s("clock_bio_interval", 60), 60, 60, 86400))
        return max(20, as_int(self.app.s("clock_interval", 60), 60, 20, 7200))

    def min_gap(self):
        return 15 if self.app.s("clock_accept_risk", False) else 30

    def healthy(self):
        """True when not in a degraded state (no backoff, no recent strikes).
        Used by the clock to decide whether a mid-minute write may force the
        next boundary flip (keeps the clock minute-exact) or must respect
        the strike-multiplied interval (Telegram is resetting us — slow down)."""
        now = time.time()
        recent = [t for t in self.strikes if now - t < 3600]
        return self.backoff <= 1.01 and len(recent) < 3

    def effective_interval(self, target):
        mult = self.backoff
        now = time.time()
        self.strikes = [t for t in self.strikes if now - t < 3600]
        if len(self.strikes) >= 3:
            mult *= 2 ** min(len(self.strikes) - 2, 2)
        return max(self.min_gap(), self.base_interval(target) * mult)

    def budget_left(self):
        day = self.app.now().strftime("%Y-%m-%d")
        if day != self._budget_day:
            self._budget_day = day
            self._budget_n = 0
            self._notified_budget = False
        cap = as_int(self.app.s("safety_daily_updates", 1600), 1600, 100, 20000)
        return cap - self._budget_n

    def budget_used(self):
        self.budget_left()
        return self._budget_n

    # ---------- main entry ----------
    async def apply(self, target, text, force=False):
        """target: first_name | last_name | bio. text: new value (None = keep),
        or a CALLABLE — re-evaluated right before the actual profile write so
        the value written is fresh at write-time (v2.4: the clock passes a
        lambda; the minute rendered is the minute at write, not at wake).
        Returns (applied: bool, retry_after: sec, why: str)."""
        app = self.app
        if target == "bio":
            target = "about"
        if target not in ("first_name", "last_name", "about"):
            return (False, 0, "bad-target")
        if text is None:
            return (False, 0, "keep")
        render_fn = text if callable(text) else None
        if render_fn is not None:
            text = render_fn()
        now = time.time()
        if not force and self.last_text.get(target) == text \
                and now - self.last_ok.get(target, 0) < 600:
            return (False, 0, "same")
        if not force:
            gap = now - self.last_try.get(target, 0)
            # v2.5.1 pacing fix: the clock loop wakes at exactly boundary+0.3s,
            # so consecutive aligned writes land 60s ± ~50ms apart. Using
            # effective_interval (== 60) as the floor made every other boundary
            # write get "paced" out (gap 59.97s < 60) → the profile skipped a
            # full minute. When healthy, the floor must sit strictly BELOW the
            # aligned cadence (iv ≥ 30s → floor 29s). When degraded (flood
            # backoff / silent-reset strikes) we keep the cautious wide spacing.
            if self.healthy():
                need = max(1.0, self.min_gap() - 1)
            else:
                need = self.effective_interval(target)
            if gap < need:
                return (False, need - gap, "pace")
            if self.budget_left() <= 0:
                if not self._notified_budget:
                    self._notified_budget = True
                    try:
                        await app.notify_owner_critical(
                            "🛡 سقف روزانهٔ آپدیت پروفایل پر شد — ساعت تا فردا خودکار نگه داشته شد "
                            "(محافظت از بن).")
                    except Exception:
                        pass
                return (False, 3600, "budget")
        if render_fn is not None:
            text = render_fn()          # FRESH value — the write below is ms away
        self.last_try[target] = now
        try:
            res = await app.client(functions.account.UpdateProfileRequest(**{target: text}))
            self.last_ok[target] = time.time()
            self.last_text[target] = text
            self._budget_n += 1
            if self.backoff > 1.0 and time.time() - self._last_flood > 1800:
                self.backoff = max(1.0, self.backoff / 1.5)
            exp = app.db.setting("clock_expected", {}) or {}
            exp[target if target != "about" else "bio"] = text
            app.db.set_setting("clock_expected", exp)
            return (True, 0, "ok")
        except FloodWaitError as e:
            self.backoff = min(self.backoff * 1.5, 10.0)
            self._last_flood = time.time()
            log.warning("FLOOD_WAIT %ss on %s (backoff x%.1f)", e.seconds, target, self.backoff)
            return (False, e.seconds + 15, "flood")
        except Exception as e:
            log.exception("UpdateProfile(%s) failed", target)
            return (False, 60, "error:" + type(e).__name__)

    # ---------- silent-reset watchdog ----------
    async def verify(self):
        """Fresh-read own profile, compare with expected; re-apply on silent reset.

        v2.7.2: only fields the clock CURRENTLY owns are verified. The old
        unconditional check misread the owner's MANUAL renames as "silent
        resets" whenever the name clock was off but e.g. the bio clock still
        ran — it then re-wrote the OLD value (fighting the user) and piled up
        strikes that slowed the whole governor down."""
        app = self.app
        exp = app.db.setting("clock_expected", {}) or {}
        if not exp:
            return
        active = {}
        try:
            tgt = ("first_name"
                   if app.s("clock_target", "last_name") == "first_name"
                   else "last_name")
            if app.s("clock_on", True):
                active[tgt] = True
            if app.s("clock_bio_on", False):
                active["bio"] = True
        except Exception:
            active = {"first_name": True, "last_name": True, "bio": True}
        try:
            res = await app.client(functions.users.GetUsersRequest(id=[types.InputUserSelf()]))
            u = res[0]
        except Exception:
            return
        # v2.7.2 CRITICAL: bio is NOT on types.User (it lives in
        # users.getFullUser). Reading `u.about` always gave "" → every verify
        # pass with a live bio clock saw a fake mismatch → re-wrote + struck
        # every 5 minutes. Fetch the full user for the bio comparison.
        about = None
        try:
            full = await app.client(functions.users.GetFullUserRequest(
                id=[types.InputUserSelf()]))
            about = getattr(full.full_user, "about", None)
        except Exception:
            pass
        mismatch = []
        for api_field, key in (("first_name", "first_name"), ("last_name", "last_name"),
                               ("about", "bio")):
            want = exp.get(key)
            if want is None or key not in active:
                continue
            got = (about if key == "bio" else getattr(u, api_field, None)) or ""
            if (want or "") != got:
                mismatch.append((api_field, key, want))
        if not mismatch:
            return
        self.strikes.append(time.time())
        for api_field, key, want in mismatch:
            ok, _, why = await self.apply(api_field, want, force=True)
            log.warning("silent reset on %s → re-applied (%s)", key, why)
        n_recent = len([t for t in self.strikes if time.time() - t < 3600])
        if n_recent >= 3 and time.time() - self._notified_strikes > 3600:
            self._notified_strikes = time.time()
            try:
                await app.notify_owner_critical(
                    "⚠️ تلگرام چند بار اسم/بیو رو ریست کرده — فاصلهٔ آپدیت‌ها خودکار بیشتر شد "
                    "تا اکانتت امن بمونه. اگه خودت داری عوض می‌کنی: .clock off")
            except Exception:
                pass

    def status_line(self):
        now = time.time()
        self.strikes = [t for t in self.strikes if now - t < 3600]
        return {
            "backoff": round(self.backoff, 2),
            "strikes_1h": len(self.strikes),
            "budget_used": self.budget_used(),
            "budget_cap": as_int(self.app.s("safety_daily_updates", 1600), 1600, 100, 20000),
            "last_name_write": int(now - self.last_ok.get("last_name", 0)) or None,
            "last_bio_write": int(now - self.last_ok.get("about", 0)) or None,
        }


class Limiter:
    """Simple per-key rate limiter for reply/delete actions (anti-spam)."""

    def __init__(self):
        self.last = {}

    def allow(self, key, gap):
        now = time.time()
        if now - self.last.get(key, 0) < gap:
            return False
        self.last[key] = now
        return True

    def seconds_left(self, key, gap):
        return max(0, int(gap - (time.time() - self.last.get(key, 0))))
