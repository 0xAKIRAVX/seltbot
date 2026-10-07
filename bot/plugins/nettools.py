"""Network tools: IP info, DNS, HTTP check, port check (authorized systems only)."""
import asyncio
import logging
import socket
import time

import aiohttp

from .. import jalali
from ..core import command

log = logging.getLogger("seltbot.nettools")

TO = aiohttp.ClientTimeout(total=20)


@command("ip", "nettools", "<ip|domain>", "اطلاعات IP", "IP information", bot_ok=True)
async def ip_cmd(app, ev, arg):
    q = arg.strip()
    if not q:
        await ev.reply("❌ `.ip 8.8.8.8` یا `.ip google.com`")
        return
    try:
        async with app.http.get(
                f"http://ip-api.com/json/{q}",
                params={"fields": "status,message,country,countryCode,city,isp,org,as,proxy,hosting,query"},
                timeout=TO) as r:
            data = await r.json(content_type=None)
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}")
        return
    if data.get("status") != "success":
        await ev.reply(f"⛔ {data.get('message', 'failed')}")
        return
    flags = []
    if data.get("proxy"):
        flags.append("پروکسی")
    if data.get("hosting"):
        flags.append("دیتاسنتر")
    lines = [
        f"🌐 **{data.get('query')}**",
        f"• کشور: {data.get('country')} ({data.get('countryCode')})",
        f"• شهر: {data.get('city') or '—'}",
        f"• ISP: {data.get('isp') or '—'}",
        f"• Org/AS: {data.get('org') or '—'}",
    ]
    if flags:
        lines.append("• ⚠️ " + "، ".join(flags))
    await ev.reply("\n".join(lines))


@command("dns", "nettools", "<domain>", "رکوردهای DNS", "DNS lookup", bot_ok=True)
async def dns_cmd(app, ev, arg):
    q = arg.strip()
    if not q:
        await ev.reply("❌ `.dns example.com`")
        return

    def lookup():
        out = {}
        for family, name in ((socket.AF_INET, "A"), (socket.AF_INET6, "AAAA")):
            try:
                infos = socket.getaddrinfo(q, None, family)
                addrs = sorted({i[4][0] for i in infos})
                if addrs:
                    out[name] = addrs[:6]
            except Exception:
                pass
        return out

    try:
        res = await asyncio.get_event_loop().run_in_executor(None, lookup)
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}")
        return
    if not res:
        await ev.reply("🔍 رکوردی پیدا نشد.")
        return
    lines = [f"🔍 DNS **{q}**"]
    for k, v in res.items():
        lines.append(f"• {k}: " + ", ".join(f"`{x}`" for x in v))
    await ev.reply("\n".join(lines))


@command("http", "nettools", "<url>", "بررسی وضعیت HTTP", "HTTP status check",
         bot_ok=True)
async def http_cmd(app, ev, arg):
    url = arg.strip()
    if not url:
        await ev.reply("❌ `.http https://example.com`")
        return
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    t0 = time.time()
    try:
        import aiohttp
        async with app.http.head(url, allow_redirects=True,
                                 timeout=aiohttp.ClientTimeout(total=15)) as r:
            ms = int((time.time() - t0) * 1000)
            await ev.reply(f"🌐 `{url}`\n• کد: **{r.status}** {r.reason or ''}\n"
                           f"• زمان: {ms}ms\n• سرور: {r.headers.get('Server', '—')}")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}: {str(e)[:120]}")


@command("port", "nettools", "<host> <port>", "بررسی پورت (فقط سیستم‌های خودت)",
         "Port check (authorized only)", bot_ok=True)
async def port_cmd(app, ev, arg):
    parts = arg.split()
    if len(parts) != 2:
        await ev.reply("❌ `.port example.com 443` — فقط برای سیستم‌هایی که مجاز خودتی.")
        return
    host, port_s = parts
    try:
        port = int(port_s)
    except ValueError:
        await ev.reply(app.t("bad_arg"))
        return

    async def check():
        try:
            fut = asyncio.open_connection(host, port)
            r, w = await asyncio.wait_for(fut, timeout=8)
            w.close()
            return True
        except Exception:
            return False

    ok = await check()
    await ev.reply(f"🔌 `{host}:{port}` → " + ("🟢 باز" if ok else "🔴 بسته/فیلتر"))


@command("revdns", "nettools", "<ip>", "Reverse DNS", "Reverse DNS", bot_ok=True)
async def revdns_cmd(app, ev, arg):
    ip = arg.strip()
    if not ip:
        await ev.reply("❌ `.revdns 8.8.8.8`")
        return

    def rd():
        try:
            return socket.gethostbyaddr(ip)[0]
        except Exception:
            return None

    name = await asyncio.get_event_loop().run_in_executor(None, rd)
    await ev.reply(f"🔁 `{ip}` → {name or 'پیدا نشد'}")
