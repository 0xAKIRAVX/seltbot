"""AI integration (OpenAI-compatible endpoint): chat, summarize, history, persona.

تنظیم از داخل خود تلگرام (بدون needing ری‌استارت):
  .set ai_url https://api.openai.com/v1        (یا هر سرویس سازگار)
  .set ai_key sk-...
  .set ai_model gpt-4o-mini
یا از طریق secrets ریپو: AI_API_URL / AI_API_KEY / AI_MODEL
"""
import logging
import os
import re

from ..core import command

log = logging.getLogger("seltbot.ai")

ENV_URL = os.environ.get("AI_API_URL", "").rstrip("/")
ENV_KEY = os.environ.get("AI_API_KEY", "")
ENV_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")


def _cfg(app):
    url = (app.s("ai_url", "") or "").rstrip("/") or ENV_URL
    key = app.s("ai_key", "") or ENV_KEY
    model = app.s("ai_model", "") or ENV_MODEL
    return url, key, model


def _configured(app):
    url, key, _ = _cfg(app)
    return bool(url and key)


async def _chat(app, hist, max_tokens=800):
    url, key, model = _cfg(app)
    payload = {"model": model, "messages": hist,
               "temperature": 0.7, "max_tokens": max_tokens}
    async with app.http.post(url + "/chat/completions", json=payload,
                             headers={"Authorization": f"Bearer {key}"}) as r:
        data = await r.json()
    if not data.get("choices"):
        raise RuntimeError(str(data.get("error") or data)[:200])
    return data["choices"][0]["message"]["content"]


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
