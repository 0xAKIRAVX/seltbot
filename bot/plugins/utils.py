"""Utilities: ping, calculator, base64, hashing, uuid, password, json, ts, count, regex, qr."""
import ast
import base64
import hashlib
import json as jsonlib
import math
import operator as opmod
import re as re_mod
import time
import uuid as uuid_mod

from .. import jalali
from ..core import command

_OPS = {
    ast.Add: opmod.add, ast.Sub: opmod.sub, ast.Mult: opmod.mul,
    ast.Div: opmod.truediv, ast.FloorDiv: opmod.floordiv,
    ast.Mod: opmod.mod, ast.Pow: opmod.pow,
}
_UOPS = {ast.USub: opmod.neg, ast.UAdd: opmod.pos}
_FUNCS = {name: getattr(math, name) for name in
          ("sqrt", "sin", "cos", "tan", "log", "log2", "log10", "exp",
           "floor", "ceil", "fabs", "factorial")}
_FUNCS.update({"abs": abs, "round": round, "pow": pow, "min": min, "max": max})

# v2.8.0 — resource guards for the sandboxed calculator. The AST whitelist
# blocked code injection but NOT resource exhaustion: `9**9**9` asks Python
# for an integer with ~370 MILLION digits → the single-threaded event loop
# froze for minutes+ → the clock stopped ticking and the whole shift looked
# dead (self-DoS). These caps make every pathological input fail FAST with a
# clean Persian error instead. Legit mental-math values are far below them.
_MAX_OPERAND = 10 ** 15        # any single literal
_MAX_EXPONENT = 4096           # kills 9**9**9 (exp 387,420,489) and 2**2**2**2
_MAX_RESULT = 10 ** 4000       # < Python's 4300-digit int→str limit anyway
_MAX_FACTORIAL = 1500          # 1500! has ~3.8k digits — prints fine


def safe_calc(expr):
    def _ev(n):
        if isinstance(n, ast.Expression):
            return _ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            if abs(n.value) > _MAX_OPERAND:
                raise ValueError("عدد خیلی بزرگ")
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            l, r = _ev(n.left), _ev(n.right)
            if isinstance(n.op, ast.Pow) and (abs(r) > _MAX_EXPONENT or abs(l) > _MAX_OPERAND):
                raise ValueError("توان بزرگ‌تر از حد مجاز")
            v = _OPS[type(n.op)](l, r)
        elif isinstance(n, ast.UnaryOp) and type(n.op) in _UOPS:
            v = _UOPS[type(n.op)](_ev(n.operand))
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS:
            if n.func.id == "factorial":
                arg = n.args[0] if len(n.args) == 1 else None
                if arg is None or _ev(arg) > _MAX_FACTORIAL:
                    raise ValueError("فاکتوریل فقط تا ۱۵۰۰")
            v = _FUNCS[n.func.id](*[_ev(a) for a in n.args])
        else:
            raise ValueError("عبارت مجاز نیست")
        if isinstance(v, (int, float)) and abs(v) > _MAX_RESULT:
            raise ValueError("نتیجه خیلی بزرگ")
        return v
    return _ev(ast.parse(expr, mode="eval"))


@command("ping", "utils", "", "سرعت پاسخ", "Ping", bot_ok=True)
async def ping_cmd(app, ev, arg):
    from telethon.tl import functions
    t0 = time.time()
    try:
        await app.client(functions.PingRequest(0))
    except Exception:
        pass
    ms = int((time.time() - t0) * 1000)
    await ev.reply(f"🏓 پونگ — {ms}ms\n⏱ آپ‌تایم: {app.uptime_str()}"
                   if app.fa else f"🏓 Pong — {ms}ms\n⏱ Uptime: {app.uptime_str()}")


@command("calc", "utils", "<عبارت>", "ماشین‌حساب امن", "Safe calculator", bot_ok=True)
async def calc_cmd(app, ev, arg):
    expr = jalali.to_en_digits(arg.strip())
    if not expr:
        await ev.reply("❌ مثال: `.calc 2+3*4` یا `.calc sqrt(144)/2`")
        return
    try:
        r = safe_calc(expr)
        if isinstance(r, float) and r == int(r) and abs(r) < 1e15:
            r = int(r)
        await ev.reply(f"🧮 `{expr}` = **{r}**")
    except Exception:
        await ev.reply("⛔ عبارت نامعتبره. عملیات مجاز: + - * / // % ** و sqrt/sin/cos/log/abs/round…")


@command("b64", "utils", "e|d <متن>", "Base64 کد/دی‌کد", "Base64 encode/decode",
         bot_ok=True)
async def b64_cmd(app, ev, arg):
    parts = arg.split(None, 1)
    if len(parts) < 2:
        await ev.reply("❌ `.b64 e متن` یا `.b64 d <base64>`")
        return
    mode, data = parts[0].lower(), parts[1]
    try:
        if mode == "e":
            await ev.reply("🔤 " + base64.b64encode(data.encode()).decode())
        else:
            await ev.reply("🔤 " + base64.b64decode(data.strip().encode()).decode("utf-8", "replace"))
    except Exception:
        await ev.reply(app.t("err"))


@command("url", "utils", "e|d <متن>", "URL کد/دی‌کد", "URL encode/decode", bot_ok=True)
async def url_cmd(app, ev, arg):
    import urllib.parse
    parts = arg.split(None, 1)
    if len(parts) < 2:
        await ev.reply("❌ `.url e <متن>` یا `.url d <encoded>`")
        return
    mode, data = parts[0].lower(), parts[1]
    try:
        if mode == "e":
            await ev.reply("🔗 " + urllib.parse.quote(data))
        else:
            await ev.reply("🔗 " + urllib.parse.unquote(data))
    except Exception:
        await ev.reply(app.t("err"))


@command("hash", "utils", "<md5|sha1|sha256|sha512> <متن>", "هش متن",
         "Hash text", bot_ok=True)
async def hash_cmd(app, ev, arg):
    parts = arg.split(None, 1)
    if len(parts) < 2:
        await ev.reply("❌ `.hash sha256 متن`")
        return
    algo, data = parts[0].lower(), parts[1]
    try:
        h = hashlib.new(algo)
        h.update(data.encode())
        await ev.reply(f"🔐 `{algo}`:\n`{h.hexdigest()}`")
    except Exception:
        await ev.reply("⛔ الگوریتم مجاز: md5 / sha1 / sha256 / sha512")


@command("uuid", "utils", "", "ساخت UUID", "Generate UUID", bot_ok=True)
async def uuid_cmd(app, ev, arg):
    await ev.reply(f"🆔 `{uuid_mod.uuid4()}`")


@command("pass", "utils", "[طول]", "رمز تصادفی قوی", "Random password", bot_ok=True)
async def pass_cmd(app, ev, arg):
    import secrets
    import string
    try:
        n = min(max(int(jalali.to_en_digits(arg.strip() or "16")), 8), 64)
    except ValueError:
        n = 16
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
    pw = "".join(secrets.choice(alphabet) for _ in range(n))
    await ev.reply(f"🔑 `{pw}`")


@command("json", "utils", "[ریپلای]", "فرمت/اعتبارسنجی JSON", "Format/validate JSON",
         bot_ok=True)
async def json_cmd(app, ev, arg):
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    data = (reply.raw_text if reply else None) or arg.strip()
    if not data:
        await ev.reply("❌ متن JSON بده یا ریپلای کن.")
        return
    try:
        obj = jsonlib.loads(data)
        await ev.reply("✅ JSON معتبره:\n```json\n"
                       + jsonlib.dumps(obj, ensure_ascii=False, indent=2)[:3000] + "\n```")
    except Exception as e:
        await ev.reply(f"⛔ JSON نامعتبر: {str(e)[:200]}")


@command("ts", "utils", "<unix>|<YYYY-MM-DD HH:MM>|now", "تبدیل زمان",
         "Timestamp converter", bot_ok=True)
async def ts_cmd(app, ev, arg):
    import datetime
    from ..core import log  # noqa
    s = jalali.to_en_digits(arg.strip())
    if not s:
        await ev.reply("❌ `.ts 1770000000` یا `.ts 2026-10-08 14:30` یا `.ts now`")
        return
    try:
        if s.lower() == "now":
            dt = app.now()
        elif re_mod.fullmatch(r"\d{9,13}", s):
            v = int(s)
            if v > 1e12:
                v /= 1000
            dt = datetime.datetime.fromtimestamp(v, app.tzinfo)
        else:
            dt = None
            m = re_mod.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})[T\s]+(\d{1,2}):(\d{2})", s)
            if m:
                dt = datetime.datetime(*map(int, m.groups()), tzinfo=app.tzinfo)
            if dt is None:
                m = re_mod.fullmatch(r"(\d{1,2}):(\d{2})", s)
                if m:
                    now = app.now()
                    dt = now.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                                     second=0, microsecond=0)
            if dt is None:
                raise ValueError
        await ev.reply(f"⏱ `{int(dt.timestamp())}`\n"
                       f"🕒 {dt.strftime('%Y-%m-%d %H:%M:%S')} ({app.s('tz', 'Asia/Tehran')})\n"
                       f"📅 شمسی: {jalali.j_date_long(dt, fa=True)}")
    except Exception:
        await ev.reply(app.t("bad_arg"))


@command("count", "utils", "[ریپلای]", "شمارش حروف/کلمات", "Count chars/words",
         bot_ok=True)
async def count_cmd(app, ev, arg):
    reply = await ev.get_reply_message() if getattr(ev, "message", None) else None
    text = (reply.raw_text if reply else None) or arg
    if not text:
        await ev.reply("❌ ریپلای کن یا متن بده.")
        return
    words = len(text.split())
    chars = len(text)
    nospace = len(text.replace(" ", "").replace("\n", ""))
    await ev.reply(f"📊 حروف: {chars} | بدون فاصله: {nospace} | کلمات: {words} | خطوط: {text.count(chr(10)) + 1}")


@command("regex", "utils", "<الگو> <متن>", "تست رجکس", "Test regex", bot_ok=True)
async def regex_cmd(app, ev, arg):
    parts = arg.split(None, 1)
    if len(parts) < 2:
        await ev.reply("❌ `.regex \\d+ سلام123`")
        return
    try:
        matches = list(re_mod.finditer(parts[0], parts[1]))[:20]
        if not matches:
            await ev.reply("🔍 هیچ تطبیقی پیدا نشد.")
        else:
            await ev.reply("🔍 تطبیق‌ها:\n" + "\n".join(
                f"• `{m.group(0)[:80]}`" for m in matches))
    except re_mod.error as e:
        await ev.reply(f"⛔ رجکس نامعتبر: {e}")


@command("qr", "utils", "<متن>", "ساخت QR", "Generate QR code", bot_ok=True)
async def qr_cmd(app, ev, arg):
    if not arg.strip():
        await ev.reply("❌ `.qr https://example.com`")
        return
    try:
        import qrcode
        import qrcode.image.pure
        img = qrcode.QRCode(box_size=8, border=2,
                            image_factory=qrcode.image.pure.PyPNGImage)
        img.add_data(arg.strip())
        img.make(fit=True)
        png = img.make_image()
        import io
        import os
        path = os.path.join(app.data_dir, "downloads", "qr.png")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            png.save(f)
        await app.client.send_file(ev.chat_id, path, caption="🔲 QR")
    except ImportError:
        await ev.reply("⛔ کتابخانهٔ qrcode نصب نیست.")
    except Exception as e:
        await ev.reply(f"⛔ {type(e).__name__}: {str(e)[:150]}")
