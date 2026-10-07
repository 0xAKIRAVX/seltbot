"""Search & info: Wikipedia, weather (open-meteo), translation (MyMemory), web search."""
import asyncio
import logging
import re
import urllib.parse

import aiohttp

from .. import jalali
from ..core import command

log = logging.getLogger("seltbot.search")

TO = aiohttp.ClientTimeout(total=25)

WEATHER_FA = {
    0: "☀️ صاف", 1: "🌤 اکثراً صاف", 2: "⛅ کمی ابری", 3: "☁️ ابری",
    45: "🌫 مه", 48: "🌫 مه یخ‌زده", 51: "🌦 بارش ریز سبک", 53: "🌦 بارش ریز",
    55: "🌦 بارش ریز شدید", 61: "🌧 باران سبک", 63: "🌧 باران", 65: "🌧 باران شدید",
    71: "🌨 برف سبک", 73: "🌨 برف", 75: "🌨 برف شدید", 77: "🌨 دانه‌های برف",
    80: "🌦 رگبار سبک", 81: "🌦 رگبار", 82: "⛈ رگبار شدید",
    95: "⛈ رعدوبرق", 96: "⛈ رعدوبرق با تگرگ", 99: "⛈ رعدوبرق شدید با تگرگ",
}


@command("wiki", "search", "<جستجو>", "ویکی‌پدیا", "Wikipedia search", bot_ok=True)
async def wiki_cmd(app, ev, arg):
    q = arg.strip()
    if not q:
        await ev.reply("❌ `.wiki تهران`")
        return
    lang = "fa" if app.fa else "en"
    try:
        async with app.http.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={"action": "query", "list": "search", "srsearch": q,
                        "format": "json", "srlimit": 1},
                timeout=TO) as r:
            data = await r.json()
        hits = data.get("query", {}).get("search", [])
        if not hits:
            await ev.reply("🔍 چیزی پیدا نشد.")
            return
        title = hits[0]["title"]
        async with app.http.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={"action": "query", "prop": "extracts", "explaintext": 1,
                        "exintro": 1, "titles": title, "format": "json",
                        "redirects": 1},
                timeout=TO) as r:
            data2 = await r.json()
        pages = data2.get("query", {}).get("pages", {})
        extract = ""
        for p in pages.values():
            extract = (p.get("extract") or "")[:900]
        url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
        await ev.reply(f"📚 **{title}**\n\n{extract}…\n\n🔗 {url}")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}")


@command("weather", "search", "<شهر>", "آب‌وهوا", "Weather", bot_ok=True)
async def weather_cmd(app, ev, arg):
    q = arg.strip()
    if not q:
        await ev.reply("❌ `.weather تهران`")
        return
    try:
        async with app.http.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": q, "count": 1, "language": "fa" if app.fa else "en"},
                timeout=TO) as r:
            geo = await r.json()
        places = geo.get("results") or []
        if not places:
            await ev.reply("🔍 شهر پیدا نشد.")
            return
        p = places[0]
        async with app.http.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": p["latitude"], "longitude": p["longitude"],
                    "current": "temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,weather_code",
                    "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                    "timezone": "auto", "forecast_days": 2,
                },
                timeout=TO) as r:
            w = await r.json()
        c = w.get("current", {})
        d = w.get("daily", {})
        wc = c.get("weather_code", 0)
        desc = WEATHER_FA.get(wc, "؟")
        lines = [
            f"🌤 **{p.get('name', q)}** ({p.get('country', '')})",
            f"• الان: **{c.get('temperature_2m', '?')}°C** — {desc}",
            f"• حس واقعی: {c.get('apparent_temperature', '?')}°C | رطوبت: {c.get('relative_humidity_2m', '?')}%",
            f"• باد: {c.get('wind_speed_10m', '?')} km/h",
        ]
        if d.get("temperature_2m_max"):
            lines.append(f"• امروز: {d['temperature_2m_max'][0]}° / {d['temperature_2m_min'][0]}°")
        if len(d.get("temperature_2m_max", [])) > 1:
            lines.append(f"• فردا: {d['temperature_2m_max'][1]}° / {d['temperature_2m_min'][1]}°")
        await ev.reply("\n".join(lines))
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}")


@command("tr", "search", "<متن>", "ترجمه", "Translate", bot_ok=True)
async def tr_cmd(app, ev, arg):
    text = arg.strip()
    if not text:
        await ev.reply("❌ `.tr متن` (جهت خودکار: انگلیسی→فارسی / فارسی→انگلیسی)")
        return
    ascii_ratio = sum(1 for ch in text if ord(ch) < 128) / max(1, len(text))
    pair = "en|fa" if ascii_ratio > 0.5 else "fa|en"
    try:
        async with app.http.get(
                "https://api.mymemory.translated.net/get",
                params={"q": text[:480], "langpair": pair},
                timeout=TO) as r:
            data = await r.json()
        rd = data.get("responseData", {})
        out = rd.get("translatedText") or ""
        if not out or "MYMEMORY WARNING" in out.upper():
            await ev.reply("⛔ سرویس ترجمه جواب نداد — بعداً دوباره امتحان کن.")
            return
        await ev.reply(f"🌍 `{pair}`\n\n{out}")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}")


@command("web", "search", "<جستجو>", "جستجوی وب", "Web search", bot_ok=True)
async def web_cmd(app, ev, arg):
    q = arg.strip()
    if not q:
        await ev.reply("❌ `.web بهترین گوشی ۲۰۲۶`")
        return
    try:
        from ddgs import DDGS
    except ImportError:
        await ev.reply("⛔ ماژول ddgs نصب نیست (در requirements هست — روی GitHub نصبه).")
        return

    def run():
        with DDGS() as d:
            return list(d.text(q, max_results=4))
    try:
        results = await asyncio.get_event_loop().run_in_executor(None, run)
    except Exception as e:
        await ev.reply(f"⛔ جستجو ناموفق: {type(e).__name__}")
        return
    if not results:
        await ev.reply("🔍 نتیجه‌ای نبود.")
        return
    lines = []
    for r in results:
        title = (r.get("title") or "")[:60]
        url = (r.get("href") or r.get("url") or "")[:80]
        body = (r.get("body") or "")[:90]
        lines.append(f"• [{title}]({url})\n  {body}")
    await ev.reply("🌐 نتایج:\n" + "\n".join(lines))
