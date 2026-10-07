"""Scheduler: reminders, scheduled/recurring messages, scheduled bio/name changes."""
import asyncio
import datetime
import logging
import re
import time
from zoneinfo import ZoneInfo

from .. import jalali
from ..core import command

log = logging.getLogger("seltbot.scheduler")

_task = None

WEEKDAYS = {
    "sat": 5, "sun": 6, "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4,
    "شنبه": 5, "یکشنبه": 6, "دوشنبه": 0, "سه‌شنبه": 1, "چهارشنبه": 2,
    "پنجشنبه": 3, "جمعه": 4,
}


async def start(app):
    global _task
    _task = asyncio.ensure_future(_loop(app))


async def stop(app):
    if _task:
        _task.cancel()


async def _loop(app):
    while not app.stopping:
        try:
            now = time.time()
            for t in app.db.tasks_due(now):
                await _run_task(app, t, now)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler loop")
        await asyncio.sleep(20)


async def _run_task(app, t, now):
    late = now - t["at"] > 120
    try:
        if t["kind"] == "msg":
            text = t["text"]
            if late:
                text = "⏰ (عقب‌افتاده)\n" + text
            chat = t["chat_id"] or "me"
            try:
                await app.send(chat, text)
            except Exception:
                await app.send_saved("📨 پیام زمان‌بندی‌شده (چت مقصد در دسترس نبود):\n\n" + text)
        elif t["kind"] == "bio":
            await app.gov.apply("bio", t["text"], force=True)
        elif t["kind"] == "name":
            await app.gov.apply("last_name", t["text"], force=True)
    except Exception:
        log.exception("task %s failed", t["id"])
    finally:
        if t["every"] and t["every"] > 0:
            app.db.task_next(t["id"], max(now, t["at"] + t["every"]))
        else:
            app.db.task_done(t["id"])
        app.db.commit()


def _parse_dt(app, s):
    """'2026-10-08 14:30' or '14:30' (today/tomorrow) → epoch ts in app tz."""
    s = jalali.to_en_digits(s.strip())
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})[T\s]+(\d{1,2}):(\d{2})", s)
    if m:
        y, mo, d, h, mi = map(int, m.groups())
        dt = datetime.datetime(y, mo, d, h, mi, tzinfo=app.tzinfo)
    else:
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
        if not m:
            return None
        h, mi = map(int, m.groups())
        now = app.now()
        dt = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if dt <= now:
            dt += datetime.timedelta(days=1)
    return dt.timestamp()


def _parse_daily(app, s):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", jalali.to_en_digits(s.strip()))
    if not m:
        return None
    h, mi = map(int, m.groups())
    now = app.now()
    dt = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if dt <= now:
        dt += datetime.timedelta(days=1)
    return dt.timestamp()


def _parse_weekly(app, day_s, time_s):
    d = day_s.strip().lower()[:3]
    if day_s.strip() in WEEKDAYS:
        wd = WEEKDAYS[day_s.strip()]
    elif d in WEEKDAYS:
        wd = WEEKDAYS[d]
    else:
        return None
    ts = _parse_daily(app, time_s)
    if ts is None:
        return None
    dt = datetime.datetime.fromtimestamp(ts, app.tzinfo)
    delta = (wd - dt.weekday()) % 7
    return (dt + datetime.timedelta(days=delta)).timestamp()


def _fmt_next(app, ts):
    dt = datetime.datetime.fromtimestamp(ts, app.tzinfo)
    return f"{jalali.j_date_str(dt)} {dt.strftime('%H:%M')}"


@command("remind", "scheduler", "<زمان> <متن>", "یادآور", "Set a reminder", bot_ok=True)
async def remind_cmd(app, ev, arg):
    parts = arg.split(None, 1)
    if len(parts) < 2:
        await ev.reply("❌ مثال: `.remind 30m شیر بخر` یا `.remind 2h30m جلسه`"
                       " یا `.remind 1d پروژه`")
        return
    sec = jalali.parse_duration(parts[0])
    if not sec:
        await ev.reply("❌ زمان رو مثلاً اینجوری بده: 30m / 2h / 1d / 2h30m")
        return
    chat = ev.chat_id if not getattr(ev, "is_bot_ev", False) else "me"
    tid = app.db.task_add("msg", time.time() + sec, 0, parts[1].strip(), chat)
    await ev.reply(f"⏰ یادآور #{tid} — {jalali.fmt_dur(sec, fa=True)} دیگه "
                   f"( {_fmt_next(app, time.time() + sec)} )")


@command("schedule", "scheduler", "<YYYY-MM-DD HH:MM> <متن>",
         "پیام زمان‌بندی‌شده", "Schedule a message", bot_ok=True)
async def schedule_cmd(app, ev, arg):
    parts = arg.split(None, 2)
    if len(parts) < 2:
        await ev.reply("❌ مثال: `.schedule 2026-10-08 14:30 تولد مامان`"
                       " یا `.schedule 21:30 ساعت خواب`")
        return
    ts = None
    text = None
    if len(parts) >= 3:
        ts = _parse_dt(app, parts[0] + " " + parts[1])
        if ts is not None:
            text = parts[2]
    if ts is None:
        ts = _parse_daily(app, parts[0])
        if ts is not None:
            text = " ".join(parts[1:])
    if ts is None:
        await ev.reply("❌ تاریخ/ساعت رو اینجوری بده: `2026-10-08 14:30` یا `21:30`")
        return
    if ts < time.time():
        await ev.reply("❌ این زمان گذشته!")
        return
    chat = ev.chat_id if not getattr(ev, "is_bot_ev", False) else "me"
    tid = app.db.task_add("msg", ts, 0, text.strip(), chat)
    await ev.reply(f"📅 پیام #{tid} برای {_fmt_next(app, ts)} ثبت شد.")


@command("daily", "scheduler", "<HH:MM> <متن>", "کار روزانه", "Daily recurring task",
         bot_ok=True)
async def daily_cmd(app, ev, arg):
    parts = arg.split(None, 1)
    if len(parts) < 2:
        await ev.reply("❌ مثال: `.daily 08:00 صبح بخیر ☀️`")
        return
    ts = _parse_daily(app, parts[0])
    if ts is None:
        await ev.reply("❌ ساعت رو اینجوری بده: `08:00`")
        return
    chat = ev.chat_id if not getattr(ev, "is_bot_ev", False) else "me"
    tid = app.db.task_add("msg", ts, 86400, parts[1].strip(), chat)
    await ev.reply(f"🔁 کار روزانه #{tid} — هر روز {_fmt_next(app, ts)} (شروع از فردا چون امروز گذشت)")


@command("weekly", "scheduler", "<روز> <HH:MM> <متن>", "کار هفتگی",
         "Weekly recurring task", bot_ok=True)
async def weekly_cmd(app, ev, arg):
    parts = arg.split(None, 2)
    if len(parts) < 3:
        await ev.reply("❌ مثال: `.weekly sat 09:00 گزارش هفتگی` (sat/sun/... یا شنبه/جمعه)")
        return
    ts = _parse_weekly(app, parts[0], parts[1])
    if ts is None:
        await ev.reply("❌ روز رو انگلیسی (sat|sun|mon|tue|wed|thu|fri) یا فارسی بده.")
        return
    chat = ev.chat_id if not getattr(ev, "is_bot_ev", False) else "me"
    tid = app.db.task_add("msg", ts, 604800, parts[2].strip(), chat)
    await ev.reply(f"🔁 کار هفتگی #{tid} — {_fmt_next(app, ts)}")


@command("every", "scheduler", "<بازه> <متن>", "تکرار با بازهٔ دلخواه",
         "Custom-interval recurring task", bot_ok=True)
async def every_cmd(app, ev, arg):
    parts = arg.split(None, 1)
    if len(parts) < 2:
        await ev.reply("❌ مثال: `.every 45m زنگ ورزش`")
        return
    sec = jalali.parse_duration(parts[0])
    if not sec or sec < 300:
        await ev.reply("❌ بازه حداقل ۵ دقیقه باشه (مثلاً 45m).")
        return
    chat = ev.chat_id if not getattr(ev, "is_bot_ev", False) else "me"
    tid = app.db.task_add("msg", time.time() + sec, sec, parts[1].strip(), chat)
    await ev.reply(f"🔁 تکرار #{tid} هر {jalali.fmt_dur(sec, fa=True)}.")


@command("schedulebio", "scheduler", "<زمان> <متن>", "زمان‌بندی تغییر بیو",
         "Schedule a bio change", bot_ok=True)
async def schedulebio_cmd(app, ev, arg):
    parts = arg.split(None, 1)
    if len(parts) < 2:
        await ev.reply("❌ مثال: `.schedulebio 22:00 شب بخیر 🌙`")
        return
    ts = _parse_dt(app, parts[0])
    if ts is None:
        await ev.reply("❌ زمان: `21:30` یا `2026-10-08 14:30`")
        return
    tid = app.db.task_add("bio", ts, 0, parts[1].strip()[:139], None)
    await ev.reply(f"📝 بیو #{tid} در {_fmt_next(app, ts)} عوض می‌شه.")


@command("scheduled", "scheduler", "", "لیست کارهای زمان‌بندی‌شده", "List tasks",
         bot_ok=True)
async def scheduled_cmd(app, ev, arg):
    rows = app.db.tasks_all()
    if not rows:
        await ev.reply(app.t("empty"))
        return
    lines = []
    for t in rows[:30]:
        icon = {"msg": "💬", "bio": "📝", "name": "📛"}.get(t["kind"], "•")
        rep = f" (تکرار هر {jalali.fmt_dur(t['every'], fa=True)})" if t["every"] else ""
        lines.append(f"{icon} #{t['id']} — {_fmt_next(app, t['at'])}{rep}: "
                     f"{(t['text'] or '')[:40]}")
    await ev.reply("📅 کارها:\n" + "\n".join(lines))


@command("canceltask", "scheduler", "<id>", "لغو کار", "Cancel a task", bot_ok=True)
async def canceltask_cmd(app, ev, arg):
    try:
        tid = int(arg.strip())
    except ValueError:
        await ev.reply(app.t("bad_arg"))
        return
    await ev.reply(app.t("deleted") if app.db.task_del(tid) else app.t("not_found"))


@command("cleartasks", "scheduler", "", "حذف همهٔ کارها", "Clear all tasks", bot_ok=True)
async def cleartasks_cmd(app, ev, arg):
    app.db.tasks_clear()
    await ev.reply("🗑 همهٔ کارهای زمان‌بندی‌شده حذف شد.")
