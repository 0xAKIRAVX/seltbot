"""AI integration (OpenAI-compatible endpoint): chat, per-user history, system prompt.

Configure via env/secrets:
  AI_API_URL  e.g. https://api.openai.com/v1  (or any compatible proxy)
  AI_API_KEY  the key
  AI_MODEL    default model name
"""
import logging
import os

from ..core import command

log = logging.getLogger("seltbot.ai")

URL = os.environ.get("AI_API_URL", "").rstrip("/")
KEY = os.environ.get("AI_API_KEY", "")
DEFAULT_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")


def _configured():
    return bool(URL and KEY)


async def _chat(app, hist):
    payload = {
        "model": app.s("ai_model", DEFAULT_MODEL) or DEFAULT_MODEL,
        "messages": hist,
        "temperature": 0.7,
        "max_tokens": 800,
    }
    async with app.http.post(URL + "/chat/completions", json=payload,
                             headers={"Authorization": f"Bearer {KEY}"}) as r:
        data = await r.json()
    if not data.get("choices"):
        raise RuntimeError(str(data.get("error") or data)[:200])
    return data["choices"][0]["message"]["content"]


@command("ai", "ai", "<متن>", "گفتگو با AI", "AI chat", bot_ok=True)
async def ai_cmd(app, ev, arg):
    if not _configured():
        await ev.reply(
            "🧠 ماژول AI هنوز تنظیم نشده.\n"
            "این سه secret رو به ریپو اضافه کن تا فعال بشه:\n"
            "`AI_API_URL` (مثلاً https://api.openai.com/v1)\n"
            "`AI_API_KEY`\n`AI_MODEL`\n"
            "هر سرویس سازگار با OpenAI کار می‌کنه.")
        return
    text = arg.strip()
    if not text:
        await ev.reply("❌ `.ai سلام، حالت چطوره؟`")
        return
    uid = ev.sender_id or 0
    hist = app.db.ai_history(uid)
    prompt = app.s("ai_prompt", "") or "You are a helpful, concise assistant. Reply in the user's language (usually Persian)."
    msgs = [{"role": "system", "content": prompt}] + hist + [{"role": "user", "content": text}]
    try:
        await ev.reply("🧠 …")
        out = await _chat(app, msgs)
        hist.append({"role": "user", "content": text})
        hist.append({"role": "assistant", "content": out})
        app.db.ai_history_set(uid, hist)
        await ev.reply(f"🧠 {out[:3500]}")
    except Exception as e:
        await ev.reply(f"⛔ AI خطا داد: {type(e).__name__}: {str(e)[:200]}")


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
