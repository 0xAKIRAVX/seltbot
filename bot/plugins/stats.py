"""Statistics: message counters per chat/day, command usage."""
import asyncio
import logging

from ..core import command

log = logging.getLogger("seltbot.stats")

_task = None


async def start(app):
    global _task
    _task = asyncio.ensure_future(_flush_loop(app))


async def stop(app):
    if _task:
        _task.cancel()
    try:
        app.stats_flush()
    except Exception:
        pass


async def _flush_loop(app):
    while not app.stopping:
        try:
            await asyncio.sleep(30)
            app.stats_flush()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("stats flush")


def _title_of(app, chat_id):
    return app.s(f"chat_title_{chat_id}", None) or str(chat_id)


@command("stats", "stats", "[روزها]", "آمار پیام‌ها", "Message statistics", bot_ok=True)
async def stats_cmd(app, ev, arg):
    import datetime
    try:
        days = min(int(arg.strip() or 7), 30)
    except ValueError:
        days = 7
    since = (datetime.datetime.now(app.tzinfo) - datetime.timedelta(days=days)) \
        .strftime("%Y-%m-%d")
    rows = app.db.counters_days(since)
    totals = app.db.counters_total()
    tin = sum(r["s"] for r in totals if r["direction"] == "in")
    tout = sum(r["s"] for r in totals if r["direction"] == "out")
    by_day = {}
    for r in rows:
        d = by_day.setdefault(r["day"], {"in": 0, "out": 0})
        d[r["direction"]] += r["s"]
    lines = [
        f"📊 **آمار ({days} روز اخیر)**",
        f"• کل از اول: 📨 {tout} ارسالی | 📥 {tin} دریافتی",
    ]
    for day in sorted(by_day.keys(), reverse=True)[:7]:
        d = by_day[day]
        lines.append(f"• {day}: ⬆️ {d['out']} ⬇️ {d['in']}")
    await ev.reply("\n".join(lines))


@command("topchats", "stats", "", "پرترافیک‌ترین چت‌ها", "Most active chats", bot_ok=True)
async def topchats_cmd(app, ev, arg):
    import datetime
    day_prefix = datetime.datetime.now(app.tzinfo).strftime("%Y-%m")
    rows = app.db.top_chats(day_prefix, limit=5)
    if not rows:
        await ev.reply(app.t("empty"))
        return
    await ev.reply("🔥 چت‌های این ماه:\n" + "\n".join(
        f"• {_title_of(app, r['chat_id'])}: {r['s']} پیام" for r in rows))


@command("usage", "stats", "", "پرکاربردترین دستورات", "Command usage", bot_ok=True)
async def usage_cmd(app, ev, arg):
    rows = app.db.cmd_top(limit=10)
    if not rows:
        await ev.reply(app.t("empty"))
        return
    await ev.reply("📈 دستورات پرتکرار:\n" + "\n".join(
        f"• `.{r['name']}` ×{r['n']}" for r in rows))
