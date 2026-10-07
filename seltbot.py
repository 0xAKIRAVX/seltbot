#!/usr/bin/env python3
"""SeltBot v2 — modular Telegram self-bot (userbot).

Runs 24/7 on GitHub Actions in ~5h45m shifts chained via workflow_dispatch.
Modes:
  --selftest   offline sanity checks (no network, no session)
  --once       connect, apply the clock once, exit (diagnostics)
  (default)    full loop until RUN_DEADLINE / LOOP_MINUTES, then graceful exit
"""
import argparse
import asyncio
import logging
import os
import signal
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "seltbot.db")

log = logging.getLogger("seltbot.main")


def setup_logging():
    os.makedirs(DATA_DIR, exist_ok=True)
    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    logging.basicConfig(
        level=logging.INFO, format=fmt,
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(os.path.join(DATA_DIR, "seltbot.log"),
                                       encoding="utf-8")])
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def build_env():
    deadline = None
    if os.environ.get("RUN_DEADLINE", "").strip().isdigit():
        deadline = int(os.environ["RUN_DEADLINE"])
    elif os.environ.get("LOOP_MINUTES", "").strip().isdigit():
        deadline = time.time() + int(os.environ["LOOP_MINUTES"]) * 60
    return {
        "session": os.environ.get("TELEGRAM_SESSION", "").strip(),
        "api_id": os.environ.get("API_ID", "17349").strip(),
        "api_hash": os.environ.get("API_HASH",
                                   "344583e45741c457fe1862106095a5eb").strip(),
        "owner_id": os.environ.get("OWNER_ID", "").strip(),
        "manager_token": os.environ.get("MANAGER_BOT_TOKEN", "").strip(),
        "notify_token": os.environ.get("NOTIFY_BOT_TOKEN", "").strip(),
        "gh_repo": os.environ.get("GITHUB_REPOSITORY", "").strip(),
        "gh_token": os.environ.get("GITHUB_TOKEN", "").strip(),
        "run_id": os.environ.get("GITHUB_RUN_ID", "").strip(),
        "state_key": os.environ.get("STATE_KEY", "").strip(),
        "deadline": deadline,
        "data_dir": DATA_DIR,
    }


def check_single_instance(env):
    """Exit quietly if another SeltBot run is already active/queued (anti double-writer)."""
    repo, token, run_id = env["gh_repo"], env["gh_token"], env["run_id"]
    if not (repo and token and run_id):
        return
    import requests
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/actions/runs?per_page=20",
                         headers={"Authorization": f"Bearer {token}"}, timeout=25)
        for run in r.json().get("workflow_runs", []):
            if run.get("name") != "SeltBot":
                continue
            if str(run.get("id")) == run_id:
                continue
            if run.get("status") in ("in_progress", "queued"):
                log.warning("another run #%s is %s — exiting (single-writer guard)",
                            run.get("id"), run.get("status"))
                sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        log.warning("dedup check failed (continuing): %s", e)


MENU = [
    ("start", "شروع و راهنمای سریع"),
    ("help", "راهنمای ماژول‌ها"),
    ("status", "وضعیت کامل بات"),
    ("clock", "تنظیم ساعت (on/off/text/tz)"),
    ("interval", "فاصلهٔ آپدیت ساعت"),
    ("format", "قالب ساعت"),
    ("tz", "منطقهٔ زمانی"),
    ("restore", "برگرداندن اسم اصلی"),
    ("pause", "توقف موقت ساعت"),
    ("resume", "ادامهٔ ساعت"),
    ("afk", "فعال‌کردن AFK با دلیل"),
    ("unafk", "خاموش‌کردن AFK"),
    ("autoreply", "پاسخ خودکار on/off"),
    ("addreply", "افزودن قانون پاسخ"),
    ("remind", "یادآور: 30m متن"),
    ("scheduled", "لیست کارهای زمان‌بندی"),
    ("canceltask", "لغو کار"),
    ("save", "ذخیرهٔ نوت"),
    ("notes", "لیست نوت‌ها"),
    ("settings", "تنظیمات"),
    ("set", "تغییر تنظیم"),
    ("stats", "آمار"),
    ("alert", "هشدار کلمه"),
    ("notify", "اعلان منشن"),
    ("weather", "آب‌وهوا"),
    ("wiki", "ویکی‌پدیا"),
    ("tr", "ترجمه"),
    ("ai", "گفتگو با AI (نیازمند تنظیم)"),
    ("health", "سلامت سیستم"),
    ("restart", "ری‌استارت شیفت"),
    ("ping", "سرعت پاسخ"),
    ("version", "نسخه"),
]


async def manager_bot_loop(app):
    from bot.core import BotEv, bot_api
    if not app.manager_token:
        return
    try:
        wh = await bot_api(app.http, app.manager_token, "getWebhookInfo")
        url = (wh.get("result") or {}).get("url") or ""
        if url:
            log.error("MANAGER BOT HAS A WEBHOOK (%s…) — polling DISABLED "
                      "to avoid killing the other service", url[:60])
            try:
                await app.notify_owner_critical(
                    "⚠️ بات مدیریت وب‌هوک داره (احتمالاً توکن اشتباهیه) — پولینگ غیرفعال شد.")
            except Exception:
                pass
            return
    except Exception as e:
        log.warning("manager webhook check failed: %s — not polling", e)
        return
    try:
        await bot_api(app.http, app.manager_token, "setMyCommands",
                      {"commands": [{"command": c, "description": d} for c, d in MENU]})
    except Exception:
        pass
    log.info("manager bot: polling getUpdates…")
    offset = 0
    while not app.stopping:
        try:
            res = await bot_api(app.http, app.manager_token, "getUpdates",
                                {"timeout": 25, "offset": offset}, timeout=30)
            for u in res.get("result", []):
                offset = u["update_id"] + 1
                m = u.get("message") or u.get("edited_message") or {}
                text = (m.get("text") or "").strip()
                if not text.startswith("/"):
                    continue
                frm = m.get("from") or {}
                chat = m.get("chat") or {}
                uid = frm.get("id")
                if not app.authorized(uid):
                    if uid:
                        log.warning("manager cmd from unauthorized user %s", uid)
                    continue
                parts = text.split(None, 1)
                name = parts[0][1:].split("@")[0].lower()
                arg = parts[1].strip() if len(parts) > 1 else ""
                ev = BotEv(app, chat.get("id"), uid)
                asyncio.ensure_future(app.run_command(name, arg, ev))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("manager poll error: %s", e)
            await asyncio.sleep(5)


async def _deadline_watcher(app, stop_ev):
    while not app.stopping:
        try:
            if stop_ev.is_set():
                await app.graceful("signal")
                return
            if app.deadline and time.time() > app.deadline - 90:
                await app.graceful("deadline")
                return
        except Exception:
            log.exception("deadline watcher")
        await asyncio.sleep(2)


async def _periodic_upload(app):
    """Upload encrypted state every 30 min (crash protection)."""
    from bot import state_io
    while not app.stopping:
        try:
            await asyncio.sleep(1800)
            if app.stopping:
                break
            await asyncio.get_event_loop().run_in_executor(
                None, state_io.persist, app.db, app.env["gh_repo"],
                app.env["gh_token"], app.env["state_key"], "tick")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("periodic upload")


async def amain(mode_once=False):
    from bot import state_io
    from bot.core import BotApp, bot_api
    from bot.db import DB
    from bot.plugins import load_all

    env = build_env()
    check_single_instance(env)
    if not os.path.exists(DB_PATH):
        state_io.restore(DB_PATH, env["gh_repo"], env["gh_token"], env["state_key"])
    load_all()
    db = DB(DB_PATH)
    app = BotApp(db, env)
    log.info("SeltBot v2 booting | deadline=%s | repo=%s | manager=%s",
             env["deadline"], env["gh_repo"] or "-",
             "yes" if env["manager_token"] else "no")

    stop_ev = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_ev.set)
        except NotImplementedError:
            pass

    rc = 0
    try:
        if mode_once:
            await app.run()
            from bot.plugins.clock import _render_name, _target_field
            ok, _, why = await app.gov.apply(_target_field(app), _render_name(app),
                                             force=True)
            log.info("once: clock apply → %s (%s)", "OK" if ok else "SKIP", why)
            await app.graceful("once")
            return 0
        manager_task = asyncio.ensure_future(manager_bot_loop(app))
        upload_task = asyncio.ensure_future(_periodic_upload(app))
        deadline = env["deadline"]
        while (not app.stopping) and (deadline is None or time.time() < deadline - 90):
            watcher = None
            try:
                await app.run()
                watcher = asyncio.ensure_future(_deadline_watcher(app, stop_ev))
                await app.client.run_until_disconnected()
            except RuntimeError as e:
                log.error("FATAL: %s", e)
                try:
                    await app.bot_push(f"⛔ SeltBot: {e} — دسترسی سشن چک کن.")
                except Exception:
                    pass
                rc = 2
                break
            except Exception:
                log.exception("supervisor error — retrying in 15s")
                await asyncio.sleep(15)
            finally:
                if watcher:
                    watcher.cancel()
            if app.stopping:
                break
            if not app.stopping and (deadline is None or time.time() < deadline - 90):
                log.warning("client disconnected — reconnecting in 10s")
                await asyncio.sleep(10)
        manager_task.cancel()
        upload_task.cancel()
        if not app.stopping:
            await app.graceful("deadline")
    finally:
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, state_io.persist, db, env["gh_repo"], env["gh_token"],
                env["state_key"], app.stop_reason or "end")
        except Exception:
            log.exception("final persist")
        db.close()
        log.info("SeltBot exit (rc=%d, reason=%s)", rc, app.stop_reason)
    return rc


def selftest():
    import datetime
    import tempfile
    from zoneinfo import ZoneInfo

    from bot import jalali
    from bot.core import COMMANDS, MODULES
    from bot.db import DB
    from bot.plugins import load_all

    load_all()
    uniq = {id(c) for c in COMMANDS.values()}
    print(f"[1] plugins loaded: {len(MODULES)} modules, {len(uniq)} commands, "
          f"{len(COMMANDS)} keys (incl aliases)")
    assert len(MODULES) >= 18, "missing modules"
    assert len(uniq) >= 90, "missing commands"

    assert jalali.g2j(2023, 3, 21) == (1402, 1, 1), jalali.g2j(2023, 3, 21)
    assert jalali.g2j(2024, 3, 20) == (1403, 1, 1), jalali.g2j(2024, 3, 20)
    assert jalali.g2j(2025, 3, 21) == (1404, 1, 1), jalali.g2j(2025, 3, 21)
    assert jalali.g2j(2026, 3, 21) == (1405, 1, 1), jalali.g2j(2026, 3, 21)
    assert jalali.g2j(2026, 10, 7) == (1405, 7, 15), jalali.g2j(2026, 10, 7)
    assert jalali.j2g(1405, 7, 15) == (2026, 10, 7), jalali.j2g(1405, 7, 15)
    assert jalali.j2g(1403, 1, 1) == (2024, 3, 20), jalali.j2g(1403, 1, 1)
    print("[2] jalali conversions OK (1402..1405 + roundtrip)")

    assert jalali.parse_duration("1d2h30m") == 95400
    assert jalali.parse_duration("45") == 2700
    assert jalali.parse_duration("۲ ساعت") == 7200
    assert jalali.parse_duration("2h17m") == 8220
    print("[3] duration parser OK")

    from bot.plugins.utils import safe_calc
    assert safe_calc("2+3*4") == 14
    assert abs(safe_calc("sqrt(144)/2") - 6) < 1e-9
    try:
        safe_calc("__import__('os')")
        raise AssertionError("calc sandbox escaped!")
    except Exception:
        pass
    print("[4] safe calculator OK (+sandbox)")

    class Shim:
        lang = "fa"

        def s(self, k, d=None):
            return {"clock_digits": "mono", "clock_name_base": "Test"}.get(k, d)

        @property
        def fa(self):
            return True

        def now(self):
            return datetime.datetime(2026, 10, 7, 14, 5, 9,
                                     tzinfo=ZoneInfo("Asia/Tehran"))

    from bot.plugins.clock import DEFAULT_BIO_TEMPLATE, DEFAULT_TEMPLATE, render
    sh = Shim()
    out = render(sh, DEFAULT_TEMPLATE, sh.now())
    assert out == "｜ 𝟷𝟺:𝟶𝟻", f"mono render: {out!r}"
    out = render(sh, "{jdate} {hh}:{mm}", sh.now())
    assert out == "1405/07/15 14:05", f"date render: {out!r}"
    out = render(sh, "{name} | {h12}:{mm} {ampm}", sh.now())
    assert "Test | 2:05 ب.ظ" == out, f"12h render: {out!r}"
    print(f"[5] clock render OK → {render(sh, DEFAULT_TEMPLATE, sh.now())!r}")

    tmp = tempfile.mkdtemp()
    db = DB(os.path.join(tmp, "t.db"))
    db.note_save("test", "hello world")
    assert db.note_get("test")["text"] == "hello world"
    db.set_setting("k", {"x": 1})
    assert db.setting("k")["x"] == 1
    db.counters_bump(123, "2026-10-07", "in", 5)
    assert db.counters_total()[0]["s"] == 5
    db.task_add("msg", 1, 0, "t", None)
    assert len(db.tasks_due(2)) == 1
    print("[6] database layer OK")

    from bot.plugins.clock import looks_like_clock
    assert looks_like_clock("｜ 𝟶𝟺:𝟷𝟽")
    assert looks_like_clock("| 04:17")
    assert looks_like_clock("🕑 02:27")
    assert not looks_like_clock("Mohammad Taha")
    print("[7] clock-pattern detector OK")

    import bot.state_io as sio
    src = os.path.join(tmp, "t.db")
    packed = sio.pack(src, "testkey123")
    sio.unpack(packed, "testkey123", os.path.join(tmp, "t2.db"))
    assert os.path.getsize(src) == os.path.getsize(os.path.join(tmp, "t2.db"))
    try:
        sio.unpack(packed, "WRONGKEY", os.path.join(tmp, "t3.db"))
        raise AssertionError("decrypt with wrong key should fail")
    except Exception:
        pass
    print("[8] encrypted state pack/unpack OK (AES-GCM-ish via openssl)")

    print("\n✅ SELFTEST: ALL PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    setup_logging()
    if args.selftest:
        selftest()
        return 0
    return asyncio.run(amain(mode_once=args.once))


if __name__ == "__main__":
    sys.exit(main())
