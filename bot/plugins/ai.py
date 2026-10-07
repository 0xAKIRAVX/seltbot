"""AI integration (OpenAI-compatible endpoint): chat, summarize, history, persona.

تنظیم از داخل خود تلگرام (بدون needing ری‌استارت):
  .set ai_url https://api.openai.com/v1        (یا هر سرویس سازگار)
  .set ai_key sk-...
  .set ai_model gpt-4o-mini
یا از طریق secrets ریپو: AI_API_URL / AI_API_KEY / AI_MODEL

v2.3 fixes:
  • request TIMEOUT (was: aiohttp default 5min → user saw endless "🧠 …")
  • automatic model FAILOVER: free OpenRouter models rotate/die constantly
    (ultra-550b → 'Service temporarily overloaded'); we now retry on a
    fallback chain so AI keeps working without redeploying secrets
  • reasoning models (nemotron ultra) spill English chain-of-thought into
    content → we ask OpenRouter to exclude reasoning for those
"""
import asyncio
import logging
import os
import re

import aiohttp

from ..core import command

log = logging.getLogger("seltbot.ai")

ENV_URL = os.environ.get("AI_API_URL", "").rstrip("/")
ENV_KEY = os.environ.get("AI_API_KEY", "")
ENV_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")

# fallback chain used when the configured model errors/overloads/empties.
# v2.3.1 order: openrouter/free is OpenRouter's own maintained free router
# (most stable) → then nemotron tiers; gemma last (persistent 429s).
FALLBACK_MODELS = [
    "openrouter/free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-31b-it:free",
]


def _cfg(app):
    url = (app.s("ai_url", "") or "").rstrip("/") or ENV_URL
    key = app.s("ai_key", "") or ENV_KEY
    model = app.s("ai_model", "") or ENV_MODEL
    return url, key, model


def _configured(app):
    url, key, _ = _cfg(app)
    return bool(url and key)


async def _try_model(app, url, key, model, hist, max_tokens):
    """One attempt against one model. Returns content or raises."""
    payload = {"model": model, "messages": hist,
               "temperature": 0.7, "max_tokens": max_tokens}
    if "openrouter" in url.lower():
        # strips chain-of-thought from reasoning models; ignored otherwise
        payload["reasoning"] = {"exclude": True}
    async with app.http.post(
            url + "/chat/completions", json=payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=aiohttp.ClientTimeout(total=90)) as r:
        data = await r.json()
    ch = (data.get("choices") or [{}])[0]
    content = ((ch.get("message") or {}).get("content") or "").strip()
    if not content:
        err = data.get("error")
        err = (err.get("message") if isinstance(err, dict) else err) or \
            f"empty content (finish={ch.get('finish_reason')})"
        raise RuntimeError(str(err)[:200])
    return content


async def _chat(app, hist, max_tokens=1000):
    """Chat completion with automatic failover across free models."""
    url, key, model = _cfg(app)
    models = [model] + [m for m in FALLBACK_MODELS if m != model]
    errs = []
    for m in models[:3]:                       # configured + 2 fallbacks
        try:
            return await _try_model(app, url, key, m, hist, max_tokens)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            errs.append(f"{m.rsplit('/', 1)[-1]}: {str(e)[:90]}")
            log.warning("AI model %s failed: %s", m, e)
    raise RuntimeError(" | ".join(errs))


def _howto(app):
    return ("🧠 ماژول AI هنوز تنظیم نشده. از تلگرام خودت:\n"
            "`.set ai_url https://api.openai.com/v1`\n"
            "`.set ai_key sk-...`\n"
            "`.set ai_model gpt-4o-mini`\n"
            "هر سرویس سازگار با OpenAI کار می‌کنه (OpenRouter، Groq، …).\n"
            "کلید تو دیتابیس رمزنگاری‌شدهٔ خودت ذخیره می‌شه.")


@command("ai", "ai", "<متن>", "گفتگو با AI", "AI chat", bot_ok=True)
async def ai_cmd(app, ev, arg):
    if not _configured(app):
        await ev.reply(_howto(app))
        return
    text = arg.strip()
    if not text:
        await ev.reply("❌ `.ai سلام، حالت چطوره؟`")
        return
    uid = ev.sender_id or 0
    hist = app.db.ai_history(uid)
    prompt = (app.s("ai_prompt", "")
              or "You are a helpful, concise assistant. Reply in the user's language (usually Persian).")
    msgs = [{"role": "system", "content": prompt}] + hist + [{"role": "user", "content": text}]
    try:
        placeholder = await ev.reply("🧠 …")
        out = await _chat(app, msgs)
        hist.append({"role": "user", "content": text})
        hist.append({"role": "assistant", "content": out})
        app.db.ai_history_set(uid, hist)
        try:
            await placeholder.edit("🧠 " + out[:3900])
        except Exception:
            await ev.reply(f"🧠 {out[:3500]}")
    except Exception as e:
        await ev.reply(f"⛔ AI خطا داد: {type(e).__name__}: {str(e)[:200]}")


@command("sum", "ai", "[ریپلای|متن]", "خلاصه‌سازی متن", "Summarize text", bot_ok=True)
async def sum_cmd(app, ev, arg):
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    text = ((reply.raw_text if reply else None) or arg.strip()).strip()
    if not text or len(text) < 120:
        await ev.reply("❌ متنی که ریپلای کردی کوتاه‌تر از حد خلاصه‌ست (حداقل ~۱۲۰ حرف).")
        return
    if _configured(app):
        try:
            placeholder = await ev.reply("🧠 دارم خلاصه می‌کنم…")
            out = await _chat(app, [
                {"role": "system", "content":
                    "You are a summarizer. Summarize the user's text in Persian, "
                    "3-6 bullet points, keep key facts and numbers."},
                {"role": "user", "content": text[:9000]}], max_tokens=500)
            try:
                await placeholder.edit("📄 **خلاصه:**\n" + out[:3900])
            except Exception:
                await ev.reply("📄 **خلاصه:**\n" + out[:3500])
        except Exception as e:
            await ev.reply(f"⛔ AI خطا داد: {type(e).__name__}: {str(e)[:200]}")
        return
    # بدون AI → خلاصهٔ استخراجی (آفلاین)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?؟।\n])\s+", text) if s.strip()]
    words = re.findall(r"[\w\u0600-\u06FF]{3,}", text.lower())
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    def score(s):
        return sum(freq.get(w, 0) for w in re.findall(r"[\w\u0600-\u06FF]{3,}", s.lower()))
    ranked = sorted(sentences, key=score, reverse=True)[:5]
    keep = sorted(ranked, key=sentences.index)
    lines = ["📄 **خلاصه (استخراجی — برای خلاصهٔ هوشمند AI رو فعال کن):**", ""]
    lines += [f"• {s[:220]}" for s in keep]
    lines.append(f"\n📊 {len(sentences)} جمله | {len(words)} کلمه")
    await ev.reply("\n".join(lines)[:3900])


@command("aireset", "ai", "", "پاک‌کردن تاریخچهٔ AI", "Clear AI history", bot_ok=True)
async def aireset_cmd(app, ev, arg):
    app.db.ai_history_clear(ev.sender_id or 0)
    await ev.reply("🧹 تاریخچهٔ AI پاک شد.")


@command("setprompt", "ai", "<متن>", "پرامپت شخصیت AI", "Set AI system prompt",
         bot_ok=True)
async def setprompt_cmd(app, ev, arg):
    if not arg.strip():
        await ev.reply(f"پرامپت فعلی:\n`{app.s('ai_prompt', '—')}`")
        return
    app.sets("ai_prompt", arg.strip())
    await ev.reply("✅ شخصیت AI به‌روز شد.")


@command("aistatus", "ai", "", "وضعیت تنظیمات AI", "AI config status", bot_ok=True)
async def aistatus_cmd(app, ev, arg):
    url, key, model = _cfg(app)
    if not (url and key):
        await ev.reply(_howto(app))
        return
    masked = (key[:6] + "…" + key[-4:]) if len(key) > 12 else "…"
    await ev.reply(f"🧠 AI آماده‌ست:\n• سرویس: `{url}`\n• مدل: `{model}`\n"
                   f"• کلید: `{masked}`")
