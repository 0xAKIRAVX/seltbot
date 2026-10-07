# 🤖 SeltBot v2 — سلف‌بات کامل تلگرام

سلف‌بات ماژولار روی **اکانت خودت** (Telethon userbot) — بدون ترموکس، اجرای ۲۴/۷ روی GitHub Actions، با طراحی **ضدبن**.

## 🚀 استفاده (۵ ثانیه)

هر چیزی که می‌خوای رو توی تلگرام از **اکانت خودت** بفرست (بهترین جا: **Saved Messages / پیام‌های ذخیره‌شده**):

```
.help              ← لیست همهٔ ماژول‌ها
.help afk          ← راهنمای یک ماژول
.status            ← وضعیت کامل
.start             ← شروع سریع
```

بات مدیریت هم همین دستورات رو با `/` اجرا می‌کنه: `@clockname_8913976432_bot`
(اول یه بار بازش کن و START بزن.)

## 🕐 ساعت زنده

پیش‌فرض: `اسم اول شما ｜ 𝟶𝟺:𝟺𝟻` — هر دقیقه، دقیق با ساعت گوشی (Asia/Tehran)، ارقام مونو.

```
.clock text ｜ {hhm}:{mmm} {ssm}     ← قالب دلخواه
.clock interval 60                   ← فاصله (کمتر از ۳۰ ثانیه نمی‌شه — ضدبن)
.clock digits fa|mono|ascii          ← سبک ارقام
.clock tz Asia/Tehran                ← منطقهٔ زمانی
.clock bio on                        ← ساعت در بیو
.clock off / .clock on / .restore    ← خاموش/روشن/برگرداندن اسم اصلی
```

توکن‌های قالب: `{hhm} {mmm} {ssm} {hh} {mm} {ss} {h12} {ampm} {jdate} {jy} {jMon} {jWD} {date} {name}` …

## 💤 AFK

```
.afk دارم می‌رم بیرون      ← فعال (با دلیل)
.unafk / .afkstatus
```
پیام‌های خصوصی/منشن‌ها رو خودکار جواب می‌ده (مدت + دلیل)، هر نفر هر ۳۰ دقیقه یک‌بار، با تأخیر انسانی. اولین پیامی که خودت بفرستی AFK رو خاموش می‌کنه.

## 🤖 پاسخ خودکار

```
.autoreply on
.addreply سلام سلام! چطوری؟ | به سلامت!      ← تصادفی از بین متن‌ها
.addreply @username الان در دسترس نیستم
.addreply * بیننده نیستم
.replies / .delreply 3 / .clearreplies
```

## 📋 نوت‌ها

```
.save لینک https://...        ← ذخیره
#لینک                          ← نوشتنش همین‌طوری، متنش رو جایگزین می‌کنه!
.notes / .notes جستجو / .delnote لینک
```

## ⏰ زمان‌بند و یادآور

```
.remind 30m شیر بخر
.remind 2h30m جلسه
.schedule 2026-10-08 14:30 تولد مامان
.schedule 21:30 ساعت خواب
.daily 08:00 صبح بخیر ☀️
.weekly sat 09:00 گزارش هفتگی
.every 45m زنگ ورزش
.schedulebio 22:00 شب بخیر 🌙     ← تغییر بیو در زمان مشخص
.scheduled / .canceltask 3 / .cleartasks
```

## 🧰 ابزارها

```
.ping .calc 2+3*4 .calc sqrt(144)
.b64 e متن / .url d ...  .hash sha256 متن
.uuid  .pass 20  .json {…}  .ts 1770000000  .count
.regex \d+ abc123  .qr https://...
.ip 8.8.8.8  .dns google.com  .http example.com  .port host 443
.wiki تهران  .weather تهران  .tr hello  .web جستجو
```

## ✉️ ابزار پیام

```
.del (ریپلای)  .purge  .edit متن  .pin  .unpin
.forward saved  .copy  .react 👍  .info  .id  .msgjson  .common
.online / .offline
```

## 📎 مدیا و پروفایل

```
.download / .rename new.pdf / .upload / .mediainfo
.setphoto (ریپلای عکس)  .photos add|list|rotate on|6h
.bio متن  .biopresets add …  .biorotate 240
.setname اسم‌جدید  .username جدید
```

## 🔐 امنیت

```
.allow @user / .deny @user     ← کاربر مجاز برای دستورات
.block @user / .unblock / .blocked
.sudoers
```
همهٔ دستورات فقط برای صاحب اکانت + sudoers اجرا می‌شن. بلاک‌شده‌ها جواب خودکار نمی‌گیرن.

## ⚙️ تنظیمات و ماژول‌ها

```
.settings / .set lang en / .lang fa / .tz Europe/London / .prefix !
.on afk / .off afk / .modules / .plugins
.restart / .update / .health / .stats / .topchats / .usage
.notify on / .alert add فوریت
```

## 🧠 AI (اختیاری)

این secret ها رو اضافه کن تا فعال شه: `AI_API_URL` + `AI_API_KEY` (+`AI_MODEL`)
هر سرویس سازگار با OpenAI. بعد: `.ai سلام` / `.setprompt …` / `.aireset`

## 🏗 معماری ۲۴/۷ (بدون ترموکس)

- **شیفت‌های ~۵:۴۵ ساعته** روی GitHub Actions (ریپو پابلیک = دقیقه‌های نامحدود رایگان)
- آخر هر شیفت، خودش **شیفت بعدی رو زنجیر می‌کنه** (workflow_dispatch) → قطعی نمی‌شه
- کرون ۳ساعته هم فول‌بکه — اگر زنجیر بشکنه حداکثر ۳ ساعت بعد خودش بالا میاد
- **گارد single-writer**: اگر دو تا ران همزمان بشن، جدیدترین خودش رو می‌بنده (سشن امان می‌مونه)
- وضعیت (نوت‌ها/تنظیمات/آمار) **رمزنگاری‌شده (AES-256) هر ۳۰ دقیقه** توی خود ریپو ذخیره می‌شه (`state.db.enc`) و اول هر شیفت برگردونده می‌شه
- هاست جایگزین بدون وقفه: `Dockerfile` رو بزن روی Render/Koyeb/HF Spaces

## 🛡 چرا بن نمی‌شی؟

- اسم اول هیچ‌وقت دست نمی‌شه، فقط اسم آخر، و فقط وقتی متن واقعاً عوض شه
- کف فاصلهٔ آپدیت ۳۰ ثانیه (پیش‌فرض ۶۰) + هم‌ترازی با دقیقهٔ ساعت
- سقف روزانهٔ آپدیت پروفایل (پیش‌فرض ۱۶۰۰) — پر شد؟ خودکار نگه می‌داره و خبر می‌ده
- FloodWait → backoff نمایی ×۱٫۵ (بعد از ۳۰ دقیقهٔ سالم، آرام برمی‌گرده)
- تشخیص **ریست سایلنت** تلگرام: هر ۵ دقیقه اسم واقعی چک می‌شه؛ اگر تلگرام ریست کرده باشه، دوباره می‌شینه + strike؛ ۳ strike در ساعت = فاصله ×۲
- جواب‌های AFK/پاسخ خودکار: کول‌داون per-user + سقف + تأخیر تصادفی انسانی
- حذف پیام‌ها فقط مال خودت، با فاصلهٔ ۰٫۴ ثانیه
- عکس پروفایل: حداقل ۳۰ دقیقه فاصله

## 🔧 رفع اشکال

| مشکل | راه |
|---|---|
| ساعت متوقف شد | `.status` بفرست؛ توی Actions لاگ ببین؛ `.clock on` |
| سشن باطل شد | `gen_session.py` رو اجرا کن → رشتهٔ جدید → secret `TELEGRAM_SESSION` |
| کد جدید اعمال شه | `.restart` (شیفت بعد کد تازه می‌کشه) |
| ریست مداوم اسم | `.clock interval 120` بذار (تلگرام حساس شده) |

## 📂 ساختار

```
seltbot.py              ← نقطهٔ ورود (--selftest/--once)
bot/core.py             ← روتینگ دستورات + BotApp
bot/safety.py           ← فرماندار ضدبن پروفایل
bot/db.py               ← SQLite (نوت/فیلتر/زمان‌بند/آمار)
bot/state_io.py         ← بکاپ رمزنگاری‌شدهٔ وضعیت
bot/jalali.py           ← تقویم شمسی + ارقام فارسی/مونو
bot/plugins/*.py        ← ۱۹ ماژول — فایل جدید = ماژول جدید
.github/workflows/seltbot.yml
```
