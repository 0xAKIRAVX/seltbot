"""SeltBot core: command registry, module registry, BotApp, event routing."""
import asyncio
import datetime
import json
import logging
import re
import time
from zoneinfo import ZoneInfo

import aiohttp
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl import functions, types

from . import jalali
from .db import DB
from .i18n import get as i18n_get
from .safety import Limiter, ProfileGovernor

log = logging.getLogger("seltbot")

COMMANDS = {}          # name -> Cmd
MODULES = {}           # name -> ModuleInfo
INCOMING_HOOKS = []    # async (app, event) -> bool consumed
OUTGOING_HOOKS = []    # async (app, event) -> bool consumed
PROTECTED_MODULES = {"helpmod", "settingsmod", "security", "pluginctl"}


class Cmd:
    __slots__ = ("name", "fn", "module", "usage", "d_fa", "d_en",
                 "aliases", "bot_ok", "hidden")

    def __init__(self, name, fn, module, usage, d_fa, d_en, aliases, bot_ok, hidden):
        self.name, self.fn, self.module, self.usage = name, fn, module, usage
        self.d_fa, self.d_en, self.aliases = d_fa, d_en, aliases
        self.bot_ok, self.hidden = bot_ok, hidden


class ModuleInfo:
    __slots__ = ("name", "title_fa", "title_en", "start", "stop")

    def __init__(self, name, title_fa, title_en, start=None, stop=None):
        self.name, self.title_fa, self.title_en = name, title_fa, title_en
        self.start, self.stop = start, stop


def command(name, module, usage="", d_fa="", d_en="", aliases=(), bot_ok=True,
            hidden=False):
    def deco(fn):
        c = Cmd(name, fn, module, usage, d_fa, d_en, tuple(aliases), bot_ok, hidden)
        COMMANDS[name] = c
        for a in aliases:
            COMMANDS.setdefault(a, c)
        return fn
    return deco


def incoming_hook():
    def deco(fn):
        INCOMING_HOOKS.append(fn)
        return fn
    return deco


def outgoing_hook():
    def deco(fn):
        OUTGOING_HOOKS.append(fn)
        return fn
    return deco


class BotEv:
    """Pseudo-event for manager-bot (Bot API) commands."""
    is_bot_ev = True

    def __init__(self, app, chat_id, sender_id):
        self.app = app
        self.chat_id = chat_id
        self.sender_id = sender_id
        self.message = None
        self.is_private = True

    async def reply(self, text, **kw):
        await self.app.manager_send(self.chat_id, text)


async def bot_api(http, token, method, data=None, timeout=30):
    if http is None:
        raise RuntimeError("no http session")
    url = f"https://api.telegram.org/bot{token}/{method}"
    async with http.post(url, json=data or {}, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
        return await r.json()


class BotApp:
    def __init__(self, db: DB, env: dict):
        self.db = db
        self.env = env
        self.session_str = env.get("session") or ""
        self.api_id = int(env.get("api_id") or 0)
        self.api_hash = env.get("api_hash") or ""
        self.owner_id = int(env.get("owner_id") or 0)
        self.manager_token = env.get("manager_token") or ""
        self.notify_token = env.get("notify_token") or ""
        self.gh_repo = env.get("gh_repo") or ""
        self.gh_token = env.get("gh_token") or ""
        self.run_id = env.get("run_id") or ""
        self.state_key = env.get("state_key") or ""
        self.deadline = env.get("deadline")
        self.data_dir = env.get("data_dir") or "data"
        self.client = None
        self.http = None
        self.me = None
        self.started = time.time()
        self.stopping = False
        self.stop_reason = ""
        self._grace_done = False
        self.gov = ProfileGovernor(self)
        self.limiter = Limiter()
        self._sent_ids = set()
        self._stat_pending = {}
        self._tasks = {}
        self._tzcache = ("", None)
        self._last_push = (0.0, "")
        self.manager_chat_ok = False
        self._handlers_added = False
        self._chat_seen = set()

    # ---------- settings / i18n ----------
    def s(self, k, d=None):
        return self.db.setting(k, d)

    def sets(self, k, v):
        self.db.set_setting(k, v)

    def dels(self, k):
        self.db.del_setting(k)

    @property
    def lang(self):
        return self.s("lang", "fa") or "fa"

    @property
    def fa(self):
        return self.lang == "fa"

    def t(self, key, default=None):
        return i18n_get(self.lang, key, default)

    @property
    def prefix(self):
        p = self.s("prefix", ".")
        return p if p else "."

    @property
    def tzinfo(self):
        name = self.s("tz", "Asia/Tehran") or "Asia/Tehran"
        if self._tzcache[0] != name:
            try:
                self._tzcache = (name, ZoneInfo(name))
            except Exception:
                log.warning("bad tz %s — fallback Asia/Tehran", name)
                self._tzcache = (name, ZoneInfo("Asia/Tehran"))
        return self._tzcache[1]

    def now(self):
        return datetime.datetime.now(self.tzinfo)

    # ---------- security ----------
    def is_owner(self, uid):
        if not uid:
            return False
        uid = int(uid)
        # the session account itself is ALWAYS the owner — belt & suspenders
        # in case the OWNER_ID secret is missing/wrong (symptom: total silence
        # on both .commands and the manager menu = "nothing responds")
        if self.me is not None and uid == self.me.id:
            return True
        return uid == self.owner_id

    def is_sudo(self, uid):
        try:
            return int(uid) in self.db.sudoers()
        except Exception:
            return False

    def is_blocked(self, uid):
        try:
            return int(uid) in self.db.blocked()
        except Exception:
            return False

    def authorized(self, uid):
        return self.is_owner(uid) or self.is_sudo(uid)

    def module_off(self, name):
        if name in PROTECTED_MODULES:
            return False
        off = self.s("modules_off", []) or []
        return name in off

    # ---------- chat allow-list for AUTO features (commands unaffected) ----------
    def auto_chat_ok(self, chat_id):
        """all | whitelist | blacklist — controls where AFK/autoreply/rules/antispam act."""
        try:
            mode = self.s("auto_chats_mode", "all") or "all"
            if mode == "all":
                return True
            lst = self.s("auto_chats_list", []) or []
            hit = int(chat_id) in [int(x) for x in lst]
            return hit if mode == "whitelist" else (not hit)
        except Exception:
            return True

    # ---------- bot-sent tracking (so AFK auto-clear ignores our own replies) ----------
    def mark_bot_sent(self, msg_id):
        if msg_id:
            self._sent_ids.add(msg_id)
            if len(self._sent_ids) > 3000:
                self._sent_ids = set(list(self._sent_ids)[-1500:])

    def is_bot_sent(self, msg_id):
        return msg_id in self._sent_ids

    # ---------- messaging ----------
    async def send(self, chat, text, **kw):
        msg = await self.client.send_message(chat, text, **kw)
        self.mark_bot_sent(msg.id)
        return msg

    async def send_saved(self, text):
        try:
            return await self.send("me", text)
        except Exception:
            log.exception("send_saved failed")

    async def manager_send(self, chat_id, text, parse_mode="Markdown"):
        if not self.manager_token:
            return None
        payload = {"chat_id": chat_id, "text": text[:4000]}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        try:
            r = await bot_api(self.http, self.manager_token, "sendMessage", payload)
            if r.get("ok"):
                self.manager_chat_ok = True
                return r
            desc = str(r.get("description") or "")
            if parse_mode and ("parse" in desc.lower() or "entities" in desc.lower()):
                return await self.manager_send(chat_id, text, None)
            log.warning("manager_send failed: %s", desc)
        except Exception as e:
            log.warning("manager_send error: %s", e)
        return None

    async def bot_push(self, text):
        """Push critical alert to owner: manager bot first, notify bot fallback."""
        now = time.time()
        if self._last_push[1] == text and now - self._last_push[0] < 900:
            return
        self._last_push = (now, text)
        r = await self.manager_send(self.owner_id, text)
        if r is None and self.notify_token:
            try:
                await bot_api(self.http, self.notify_token, "sendMessage",
                              {"chat_id": self.owner_id, "text": text[:4000]})
            except Exception:
                log.exception("notify push failed")

    async def notify_owner_critical(self, text):
        log.warning("CRITICAL: %s", text)
        await self.send_saved("🔔 " + text)
        await self.bot_push(text)

    def user_link(self, user, plain=False):
        name = (getattr(user, "first_name", None) or getattr(user, "username", None)
                or str(getattr(user, "id", "?")))
        uid = getattr(user, "id", 0)
        if plain or not uid:
            return str(name)
        return f"[{name}](tg://user?id={uid})"

    # ---------- stats ----------
    def stats_bump(self, chat_id, direction):
        key = (chat_id, direction)
        self._stat_pending[key] = self._stat_pending.get(key, 0) + 1

    def stats_flush(self):
        if not self._stat_pending:
            return
        day = self.now().strftime("%Y-%m-%d")
        for (chat_id, direction), n in list(self._stat_pending.items()):
            self.db.counters_bump(chat_id, day, direction, n)
        self._stat_pending.clear()
        self.db.commit()

    # ---------- command routing ----------
    async def try_command(self, event, text=None):
        if text is None:
            text = (getattr(event, "message", None) and event.message.raw_text) or ""
        text = (text or "").strip()
        p = self.prefix
        if not text.startswith(p) or len(text) <= len(p):
            return False
        line = text[len(p):].strip()
        parts = line.split(None, 1)
        if not parts:
            return False
        name = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        return await self.run_command(name, arg, event)

    async def run_command(self, name, arg, ev):
        cmd = COMMANDS.get(name)
        if not cmd:
            if getattr(ev, "is_bot_ev", False):
                await ev.reply(self.t("unknown_cmd"))
            return False
        if getattr(ev, "is_bot_ev", False) and not cmd.bot_ok:
            await ev.reply("⛔ این دستور فقط از اکانت خودت (پیام ذخیره‌شده‌ها) اجرا می‌شه.")
            return False
        if self.module_off(cmd.module):
            await ev.reply(self.t("module_off"))
            return False
        if not self.authorized(ev.sender_id):
            log.warning("unauthorized command '%s' from %s", name, ev.sender_id)
            if getattr(ev, "is_bot_ev", False):
                await ev.reply(self.t("not_allowed"))
            return False
        try:
            log.info("cmd %s%r from %s", self.s("prefix", ".") if not getattr(ev, "is_bot_ev", False) else "/",
                     name, ev.sender_id)
            await cmd.fn(self, ev, arg)
            self.db.cmd_bump(name)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("command .%s failed", name)
            try:
                await ev.reply(f"⛔ `.{name}` → {type(e).__name__}: {str(e)[:250]}")
            except Exception:
                pass
            return False
        if self.s("delcmd", True) and not getattr(ev, "is_bot_ev", False):
            try:
                await ev.message.delete()
            except Exception:
                pass
        return True

    # ---------- telethon event pipeline ----------
    async def on_new_message(self, event):
        try:
            msg = event.message
            chat_id = event.chat_id or 0
            out = bool(msg.out)
            if chat_id:
                self.stats_bump(chat_id, "out" if out else "in")
                if chat_id not in self._chat_seen:
                    self._chat_seen.add(chat_id)
                    asyncio.ensure_future(self._remember_chat(chat_id, event))
            if out:
                if self.is_bot_sent(msg.id):
                    return
                for hook in OUTGOING_HOOKS:
                    try:
                        if await hook(self, event):
                            return
                    except Exception:
                        log.exception("outgoing hook %s", hook.__name__)
                await self.try_command(event)
            else:
                if self.stopping:
                    return
                for hook in INCOMING_HOOKS:
                    try:
                        if await hook(self, event):
                            return
                    except Exception:
                        log.exception("incoming hook %s", hook.__name__)
        except Exception:
            log.exception("on_new_message")

    async def _remember_chat(self, chat_id, event):
        """Save a human-readable chat title once per shift (for .topchats)."""
        try:
            if self.db.setting(f"chat_title_{chat_id}"):
                return
            chat = await event.get_chat()
            if chat is None:
                return
            title = (getattr(chat, "title", None)
                     or getattr(chat, "first_name", None)
                     or getattr(chat, "username", None)
                     or str(chat_id))
            if title and title != str(chat_id):
                self.db.set_setting(f"chat_title_{chat_id}", str(title)[:64])
                self.db.commit()
        except Exception:
            pass

    async def on_message_edited(self, event):
        try:
            msg = event.message
            if not msg.out or self.is_bot_sent(msg.id):
                return
            for hook in OUTGOING_HOOKS:
                try:
                    if await hook(self, event):
                        return
                except Exception:
                    log.exception("outgoing hook (edit) %s", hook.__name__)
            await self.try_command(event)
        except Exception:
            log.exception("on_message_edited")

    # ---------- lifecycle ----------
    async def run(self):
        if self.http is None or self.http.closed:
            self.http = aiohttp.ClientSession()
        session_to_use = self.session_str
        self.client = TelegramClient(StringSession(session_to_use), self.api_id,
                                     self.api_hash, connection_retries=10,
                                     retry_delay=3, auto_reconnect=True, timeout=30)
        await self.client.connect()
        if not await self.client.is_user_authorized():
            alt = self.db.setting("session_backup")
            if alt and alt != session_to_use:
                log.warning("env session dead — trying state backup session")
                await self.client.disconnect()
                self.client = TelegramClient(StringSession(alt), self.api_id,
                                             self.api_hash, connection_retries=10,
                                             retry_delay=3, auto_reconnect=True)
                await self.client.connect()
                if not await self.client.is_user_authorized():
                    raise RuntimeError("SESSION DEAD (both env and backup)")
                session_to_use = alt
            else:
                raise RuntimeError("SESSION DEAD")
        self.session_str = session_to_use
        self.me = await self.client.get_me()
        try:
            self.session_str = self.client.session.save()  # capture post-migration string
        except Exception:
            pass
        log.info("connected as %s | id=%s | premium=%s",
                 self.me.first_name, self.me.id, bool(getattr(self.me, "premium", False)))
        if not self.owner_id:
            self.owner_id = self.me.id
        # boot defaults: remember original name/bio (strip any live clock)
        from .plugins.clock import looks_like_clock
        if self.db.setting("clock_name_base") is None:
            cur = self.me.last_name or ""
            self.db.set_setting("clock_name_base", "" if looks_like_clock(cur) else cur)
        if self.db.setting("clock_first_base") is None:
            self.db.set_setting("clock_first_base", self.me.first_name or "")
        if self.db.setting("clock_bio_base") is None:
            self.db.set_setting("clock_bio_base", (getattr(self.me, "about", None) or ""))
        # register dispatch handlers on THIS client object. run() creates a
        # fresh TelegramClient on every call (reconnect path), so a persistent
        # _handlers_added flag would leave the NEW client with ZERO handlers →
        # all features silently dead after a hard reconnect. Register always:
        # a brand-new client starts with an empty handler list, so this cannot
        # double-register.
        # ⚠️ signature: add_event_handler(callback, event) — swapped args kill
        # ALL event dispatch with "type object 'method' has no attribute 'build'"
        self.client.add_event_handler(self.on_new_message, events.NewMessage())
        self.client.add_event_handler(self.on_message_edited,
                                      events.MessageEdited())
        # start plugin background loops
        for name, info in MODULES.items():
            if info.start:
                try:
                    self._tasks[name] = asyncio.ensure_future(info.start(self))
                except Exception:
                    log.exception("start module %s", name)
        log.info("modules started: %s", ", ".join(self._tasks.keys()) or "none")

    async def graceful(self, reason=""):
        if self._grace_done:
            return
        self._grace_done = True
        self.stopping = True
        self.stop_reason = reason
        log.info("graceful shutdown: %s", reason)
        for name, t in list(self._tasks.items()):
            if t and not t.done():
                t.cancel()
        for name, info in MODULES.items():
            if info.stop:
                try:
                    await info.stop(self)
                except Exception:
                    log.exception("stop module %s", name)
        self._tasks.clear()
        try:
            self.stats_flush()
        except Exception:
            log.exception("stats flush")
        try:
            if self.client and self.client.session:
                cur = self.client.session.save()
                if cur and cur != self.session_str:
                    self.db.set_setting("session_backup", cur)
                    log.warning("session string changed — saved into state backup")
        except Exception:
            log.exception("session backup")
        self.db.commit()
        try:
            if self.client and self.client.is_connected():
                await self.client.disconnect()
        except Exception:
            pass
        try:
            if self.http:
                await self.http.close()
        except Exception:
            pass
        log.info("graceful done")

    # ---------- module runtime control ----------
    async def start_module(self, name):
        info = MODULES.get(name)
        if not info or not info.start:
            return False
        t = self._tasks.get(name)
        if t and not t.done():
            return False
        self._tasks[name] = asyncio.ensure_future(info.start(self))
        log.info("module %s started", name)
        return True

    async def stop_module(self, name):
        t = self._tasks.pop(name, None)
        if t and not t.done():
            t.cancel()
        info = MODULES.get(name)
        if info and info.stop:
            try:
                await info.stop(self)
            except Exception:
                log.exception("stop module %s", name)
        log.info("module %s stopped", name)
        return True

    # ---------- helpers for status ----------
    def uptime_str(self):
        return jalali.fmt_dur(time.time() - self.started, fa=self.fa)

    def deadline_in_str(self):
        if not self.deadline:
            return "∞"
        return jalali.fmt_dur(max(0, self.deadline - time.time()), fa=self.fa)
