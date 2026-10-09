/* SeltBot Installer — telegram login (promise-callback auth), BotFather automation,
   secrets, launch. Uses S / $ / sleep / show / setStatus / plan / gh / ghErr / DemoClock
   from wizard.js. */
"use strict";

/* ─────────── pending-input bridge (UI events → auth callbacks) ─────────── */
let _pendingResolve = null;
function uiWait(inputId, btnId) {
  return new Promise((resolve) => {
    _pendingResolve = resolve;
    const btn = $(btnId);
    const input = $(inputId);
    btn.disabled = false;
    function cleanup() {
      btn.removeEventListener("click", handler);
      input.removeEventListener("keydown", onKey);
      btn.disabled = true;
      _pendingResolve = null;
    }
    const handler = () => {
      const v = input.value.trim();
      if (v.length === 0) return;
      cleanup();
      resolve(v);
    };
    /* v1.1: Enter submits too — on phones nobody taps the button after
       typing the code, they hit Enter and the wizard appeared frozen. */
    const onKey = (e) => { if (e.key === "Enter") { e.preventDefault(); handler(); } };
    btn.addEventListener("click", handler, { once: false });
    input.addEventListener("keydown", onKey);
  });
}
function uiResolvePending(v) {
  if (_pendingResolve) { const r = _pendingResolve; _pendingResolve = null; r(v); }
}

/* ─────────── mock telegram client (scripted, for ?mock=1 tests) ─────────── */
function mockTgClient() {
  const replies = [];
  let msgId = 1000;
  const errOf = (m) => { const e = new Error(m); e.errorMessage = m; return e; };
  return {
    _isMock: true,
    async connect() { },
    async start(p) {
      const phone = await p.phoneNumber();
      if (!/^\+\d{10,15}$/.test(phone)) { await p.onError(errOf("PHONE_NUMBER_INVALID")); throw new Error("auth failed"); }
      let code = await p.phoneCode(false);
      if (code === "") { await p.phoneNumber(); code = await p.phoneCode(false); }
      if (code === "99999") {
        const pw = await p.password("hint");
        if (pw !== "1234") { await p.onError(errOf("PASSWORD_HASH_INVALID")); throw new Error("auth failed"); }
        return;
      }
      for (let i = 0; i < 2; i++) {
        if (code === "12345") return;
        const stop = await p.onError(errOf("PHONE_CODE_INVALID"));
        if (stop) throw new Error("cancelled");
        code = await p.phoneCode(false);
      }
      throw new Error("auth failed");
    },
    async get_me() { return { id: 111222333, first_name: "رفیقِ تست", username: "testuser" }; },
    async sendMessage(to, text) {
      msgId += 1;
      if (to === "BotFather") setTimeout(() => {
        if (text === "/newbot") replies.push("Alright, a new bot. How are we going to call it? Please choose a name for your bot.");
        else if (/^seltbot_[a-z0-9_]+$/.test(text)) {
          if (!S._bfTaken) { S._bfTaken = true;
            replies.push("Sorry, this username is already taken."); }
          else replies.push("Done! Congratulations on your new bot. You will find it at t.me/" + text +
            ". You can now add a description for your bot: 5550001111:AAHmockmockmockmockmockmockmockxx");
        } else replies.push("Alright, a new bot. Now let's choose a username.");
      }, 250);
    },
    async getMessages(from, { limit = 1 } = {}) {
      if (from === "BotFather") { await sleep(350); return replies.splice(0).map((message, i) => ({ id: ++msgId, message, chat: { username: "BotFather" } })); }
      return [];
    },
    session: { save() { return "1BQANOTEuMTA1dXNlcgDqu3TvD5FIyNRj1MX2k9l0ZFAAAAAAAAAAAAAAAAAAA=="; } },
    async destroy() { },
  };
}

/* ─────────── STEP 3 — telegram login ─────────── */
function normalizePhone(p) {
  p = (p || "").replace(/[\s\-()]/g, "");
  if (p.startsWith("00")) p = "+" + p.slice(2);
  if (/^0\d+$/.test(p)) p = "+98" + p.slice(1);
  if (/^9\d{9}$/.test(p)) p = "+98" + p;
  if (/^98\d+$/.test(p)) p = "+" + p;
  return p;
}

async function tgConnect() {
  if (S.tg) return S.tg;
  if (S.MOCK) { S.tg = mockTgClient(); return S.tg; }
  const K = window.SeltKit;
  if (!K) throw new Error("کتابخانهٔ تلگرام لود نشده — صفحه رو رفرش کن.");
  const client = new K.TelegramClient(new K.StringSession(), S.API_ID, S.API_HASH, {
    useWSS: true, connectionRetries: 3, timeout: 15, requestRetries: 2,
  });
  await client.connect();
  S.tg = client;
  return client;
}

async function tgStartLogin() {
  const phone = normalizePhone($("in-phone").value.trim());
  if (!/^\+\d{10,15}$/.test(phone)) { setStatus("st-tg", "❗ شماره رو کامل بنویس — مثلاً +989121234567", "err"); return; }
  $("btn-tg-send").disabled = true;
  setStatus("st-tg", "⏳ در حال اتصال به تلگرام…", "info");
  let client;
  try { client = await tgConnect(); }
  catch (e) { setStatus("st-tg", "❌ اتصال برقرار نشد: " + (e.message || e), "err"); $("btn-tg-send").disabled = false; return; }

  setStatus("st-tg", "⏳ در حال ارسال کد به تلگرامت…", "info");
  let first = true;
  try {
    await client.start({
      phoneNumber: async () => {
        if (first) { first = false; return phone; }
        ["tg-phase-code", "tg-phase-pass"].forEach((id) => $(id).classList.add("hidden"));
        $("tg-phase-phone").classList.remove("hidden");
        setStatus("st-tg", "شمارهٔ جدید رو بنویس و دوباره «ارسال کد» رو بزن.", "info");
        const v = await uiWait("in-phone", "btn-tg-send");
        return normalizePhone(v);
      },
      phoneCode: async () => {
        ["tg-phase-phone", "tg-phase-pass"].forEach((id) => $(id).classList.add("hidden"));
        $("tg-phase-code").classList.remove("hidden");
        $("in-code").value = "";
        setStatus("st-tg", "", "");
        const v = await uiWait("in-code", "btn-tg-code");
        if (v === "") { const e = new Error("RESTART_AUTH"); e.errorMessage = "RESTART_AUTH"; throw e; }
        return v;
      },
      password: async () => {
        $("tg-phase-code").classList.add("hidden");
        $("tg-phase-pass").classList.remove("hidden");
        $("in-pass").value = "";
        setStatus("st-tg", "", "");
        const v = await uiWait("in-pass", "btn-tg-pass");
        if (v === "") { const e = new Error("RESTART_AUTH"); e.errorMessage = "RESTART_AUTH"; throw e; }
        return v;
      },
      onError: async (err) => { setStatus("st-tg", "⚠️ " + telErrText(err), "err"); return false; },
    });
  } catch (e) {
    setStatus("st-tg", "❌ " + telErrText(e), "err");
    ["tg-phase-code", "tg-phase-pass"].forEach((id) => $(id).classList.add("hidden"));
    $("tg-phase-phone").classList.remove("hidden");
    $("btn-tg-send").disabled = false;
    return;
  }
  S.me = await client.get_me();
  S.sessionStr = client.session.save();
  S.phone = phone;                  // v1.1: persisted for resume
  saveState();                      // v1.1: survive app kills mid-wizard
  ["tg-phase-phone", "tg-phase-code", "tg-phase-pass"].forEach((id) => $(id).classList.add("hidden"));
  $("tg-phase-done").classList.remove("hidden");
  $("tg-me-line").textContent = `✅ خوش اومدی ${S.me.first_name}!`;
  $("tg-id-line").textContent = `آیدی عددی: ${S.me.id} — فقط با این آیدی می‌شه به سلف‌باتت دستور داد.`;
  setStatus("st-tg", "", "");
}

function telErrText(e) {
  const m = (e && (e.errorMessage || e.message)) || String(e);
  if (m.includes("PHONE_CODE_INVALID") || m.includes("CODE_INVALID")) return "کد درست نیست — دوباره واردش کن.";
  if (m.includes("PHONE_CODE_EXPIRED")) return "کد منقضی شده — دوباره کد بگیر.";
  if (m.includes("FLOOD")) return "تلگرام موقتاً محدودت کرده — چند دقیقه صبر کن و دوباره امتحان کن.";
  if (m.includes("PASSWORD_HASH_INVALID")) return "رمز دوم درست نیست — دوباره بنویس.";
  if (m.includes("PHONE_NUMBER_INVALID")) return "شماره رو با فرمت +98912… بنویس.";
  if (m.includes("PHONE_NUMBER_BANNED")) return "این شماره از تلگرام بن شده.";
  return "خطا: " + String(m).slice(0, 120);
}

/* ─────────── STEP 4 — BotFather automation ─────────── */
async function bfLastId(client) {
  const msgs = await client.getMessages("BotFather", { limit: 1 });
  return msgs && msgs[0] ? msgs[0].id : 0;
}
async function bfWaitReply(client, prevId, timeoutS = 50) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutS * 1000) {
    await sleep(1600);
    const msgs = await client.getMessages("BotFather", { limit: 3 });
    if (msgs && msgs.length) {
      const fresh = msgs.filter((m) => m.id > prevId);
      if (fresh.length) return fresh.map((m) => m.message || "").join("\n");
    }
  }
  throw new Error("BotFather جواب نداد — دوباره امتحان کن یا توکن دستی بذار.");
}
function rand4() { return String(Math.floor(1000 + Math.random() * 9000)); }

async function bfCreate() {
  const name = ($("in-botname").value.trim() || "SeltBot Manager").slice(0, 60);
  let base = $("in-botuser").value.trim().replace(/^@/, "").replace(/_bot$/, "");
  base = (base || "seltbot_" + rand4()).replace(/[^A-Za-z0-9_]/g, "").toLowerCase();
  const btn = $("btn-bf-create");
  btn.disabled = true;
  setStatus("st-bf", "⏳ دارم به BotFather پیام می‌دم…", "info");
  try {
    const client = S.tg;
    for (let attempt = 0; attempt < 3 && !S.botToken; attempt++) {
      const uname = (base + "_" + rand4() + "_bot").slice(0, 30);
      await client.sendMessage("BotFather", "/newbot");
      await sleep(1200);
      let prev = await bfLastId(client);
      await client.sendMessage("BotFather", name);
      await bfWaitReply(client, prev, 30);
      prev = await bfLastId(client);
      await client.sendMessage("BotFather", uname);
      setStatus("st-bf", `⏳ منتظر تأیید @${uname}…`, "info");
      const reply = await bfWaitReply(client, prev, 60);
      const m = reply.match(/(\d{7,10}:[A-Za-z0-9_-]{30,})/);
      if (m) { S.botToken = m[1]; S.botUsername = uname; }
      else setStatus("st-bf", `↩ آیدی @${uname} گرفته شده بود — با آیدی دیگه…`, "info");
    }
    if (!S.botToken) throw new Error("سه بار آیدی تکراری بود — آیدی دیگه‌ای بنویس یا توکن دستی بذار.");
    await botApiVerify();
    await client.destroy();          // hand-off: browser never reuses this session
    S.tg = null;
    saveState();                     // v1.1: survive app kills mid-wizard
    $("bf-auto").classList.add("hidden");
    $("bf-done").classList.remove("hidden");
    $("bf-line").textContent = `✅ بات مدیریت ساخته شد: @${S.botUsername}`;
    setStatus("st-bf", "", "");
  } catch (e) {
    setStatus("st-bf", "❌ " + e.message, "err");
    btn.disabled = false;
  }
}

async function bfManual() {
  const tok = $("in-bottoken").value.trim();
  if (!/^\d{7,10}:[A-Za-z0-9_-]{30,}$/.test(tok)) { setStatus("st-bf", "❗ فرمت توکن درست نیست (مثل 123456:AA…).", "err"); return; }
  $("btn-bf-manual").disabled = true;
  S.botToken = tok;
  try {
    await botApiVerify();
    if (S.tg) { try { await S.tg.destroy(); } catch (e) {} S.tg = null; }
    $("bf-auto").classList.add("hidden");
    $("bf-done").classList.remove("hidden");
    $("bf-line").textContent = `✅ بات مدیریتت: @${S.botUsername}`;
    setStatus("st-bf", "", "");
  } catch (e) {
    setStatus("st-bf", "❌ " + e.message, "err");
    $("btn-bf-manual").disabled = false;
  }
}

async function botApiVerify() {
  if (S.MOCK) { S.botUsername = S.botUsername || "seltbot_1234_bot"; return; }
  const r = await fetch(`https://api.telegram.org/bot${S.botToken}/getMe`);
  const j = await r.json();
  if (!j.ok) throw new Error("توکن بات قبول نشد: " + (j.description || ""));
  S.botUsername = j.result.username;
  const cmds = [
    ["start", "شروع و پنل مدیریت"], ["menu", "پنل مدیریت با دکمه"], ["help", "راهنمای ماژول‌ها"],
    ["status", "وضعیت کامل بات"], ["clock", "تنظیم ساعت"], ["afk", "فعال‌کردن AFK با دلیل"],
    ["unafk", "خاموش‌کردن AFK"], ["remind", "یادآور: 30m متن"], ["save", "ذخیرهٔ نوت"],
    ["notes", "لیست نوت‌ها"], ["ping", "زنده بودن"], ["restore", "برگرداندن اسم اصلی"],
  ].map(([command, description]) => ({ command, description }));
  fetch(`https://api.telegram.org/bot${S.botToken}/setMyCommands`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ commands: cmds }),
  }).catch(() => {});
}

/* ─────────── STEP 5 — secrets ─────────── */
function randomHex(nBytes) {
  const b = new Uint8Array(nBytes);
  crypto.getRandomValues(b);
  return Array.from(b).map((x) => x.toString(16).padStart(2, "0")).join("");
}

async function putSecret(name, value) {
  const K = window.SeltKit;
  let pk;
  if (S.MOCK) pk = { key: "GTyWBsuZ0t6JaEKNmrr+w9/nd5oFyycR6BShNmnho1E=", key_id: "568250167242549743" };
  else {
    const res = await gh(`/repos/${S.login}/seltbot/actions/secrets/public-key`);
    if (res.status !== 200) throw new Error(ghErr(res));
    pk = res.json;
  }
  await K.sodium.ready;
  const binKey = K.sodium.from_base64(pk.key, K.sodium.base64_variants.ORIGINAL);
  const sealed = K.sodium.crypto_box_seal(K.sodium.from_string(String(value)), binKey);
  const b64 = K.sodium.to_base64(sealed, K.sodium.base64_variants.ORIGINAL);
  const res = await gh(`/repos/${S.login}/seltbot/actions/secrets/${name}`, "PUT",
                       { encrypted_value: b64, key_id: pk.key_id });
  if (res.status !== 201 && res.status !== 204) throw new Error(ghErr(res));
}

async function secretsInstall() {
  const btn = $("btn-sec");
  btn.disabled = true;
  S.stateKey = S.stateKey || randomHex(32);
  const list = [
    ["TELEGRAM_SESSION", S.sessionStr],
    ["API_ID", S.API_ID],
    ["API_HASH", S.API_HASH],
    ["OWNER_ID", S.me.id],
    ["MANAGER_BOT_TOKEN", S.botToken],
    ["NOTIFY_BOT_TOKEN", S.botToken],
    ["STATE_KEY", S.stateKey],
  ];
  try {
    for (const [name, val] of list) {
      plan("pb-sec", name, "run");
      setStatus("st-sec", `⏳ نصب ${name}…`, "info");
      await putSecret(name, val);
      plan("pb-sec", name, "ok");
    }
    setStatus("st-sec", "✅ هر ۷ تنظیم نصب شد!", "ok");
    saveState();                     // v1.1: survive app kills mid-wizard
    await sleep(600);
    show("sc-go");
  } catch (e) {
    setStatus("st-sec", "❌ " + e.message, "err");
    btn.disabled = false;
  }
}

/* ─────────── STEP 6 — launch + verify ─────────── */
async function launch() {
  const btn = $("btn-go");
  btn.disabled = true;
  try {
    plan("pb-go", "dispatch", "run");
    setStatus("st-go", "📣 فرمان اجرا ارسال می‌شه…", "info");
    let res = await gh(`/repos/${S.login}/seltbot/actions/workflows/seltbot.yml/dispatches`, "POST", { ref: "main" });
    if (res.status !== 204) throw new Error(ghErr(res));
    plan("pb-go", "dispatch", "ok");

    plan("pb-go", "run", "run");
    setStatus("st-go", "⏳ منتظر شروع سرور…", "info");
    let runId = null;
    for (let i = 0; i < 30 && !runId; i++) {
      await sleep(4000);
      res = await gh(`/repos/${S.login}/seltbot/actions/runs?per_page=5`);
      const runs = (res.json && res.json.workflow_runs) || [];
      const live = runs.find((r) => r.name === "SeltBot" && ["queued", "pending", "in_progress"].includes(r.status));
      if (live) runId = live.id;
    }
    if (!runId) throw new Error("سرور بعد از ۲ دقیقه شروع نشد — تب Actions مخزنت رو چک کن.");
    plan("pb-go", "run", "ok", `سرور اجرا شد (run #${runId})`);

    plan("pb-go", "boot", "run");
    setStatus("st-go", "⚙️ سلف‌بات داره بوت می‌شه… (۱-۲ دقیقه)", "info");
    let booted = false;
    for (let i = 0; i < 25 && !booted; i++) {
      await sleep(6000);
      res = await gh(`/repos/${S.login}/seltbot/actions/runs/${runId}/jobs`);
      const job = res.json && res.json.jobs && res.json.jobs[0];
      const step = job && job.steps && job.steps.find((s) => s.name.startsWith("Run SeltBot"));
      if (step && ["in_progress", "completed"].includes(step.status)) booted = true;
      if (job && job.conclusion === "failure") throw new Error("اجرای سرور شکست خورد — لاگ Actions رو ببین.");
    }
    if (!booted) throw new Error("بوت خیلی طول کشید — بعداً دوباره status بگیر.");
    plan("pb-go", "boot", "ok");

    plan("pb-go", "verify", "run");
    /* v1.1 CRITICAL FIX: a fresh bot cannot getChat its creator until the
       creator OPENS THE BOT and presses START — the old wizard silently
       polled for 3 minutes and ALWAYS fell into "check later yourself".
       Now we tell the user up-front (they must /start the bot anyway to
       control it) and surface the exact reason if verification can't run. */
    const botLink = $("lnk-openbot-go");
    if (botLink) {
      botLink.href = S.botUsername ? `https://t.me/${S.botUsername}` : "#";
      botLink.classList.remove("hidden");
    }
    setStatus("st-go", "🕐 دو کار کوچیک: ۱) توی تلگرام باتت رو باز کن و START بزن"
      + (S.botUsername ? ` (@${S.botUsername})` : "")
      + ". ۲) صبر کن ساعت کنار اسمت بیاد…", "info");
    let lastName = null;
    let needStart = false;
    for (let i = 0; i < 12 && !lastName; i++) {
      await sleep(15000);
      const r = await readProfileClock();
      if (r.lastName) { lastName = r.lastName; break; }
      if (r.needStart) needStart = true;
    }
    if (lastName) {
      plan("pb-go", "verify", "ok");
      $("done-clock").textContent = lastName;
      $("done-lead").textContent = "ساعت الان کنار اسمته — هر دقیقه بارون کدش می‌لغزه 🌧";
    } else {
      plan("pb-go", "verify", "run");
      plan("pb-go", "verify", "ok", needStart
        ? "هنوز به بات START نزدی — بعد از استارت چند دقیقه صبر کن"
        : "چند دقیقه بعد خودت چک کن");
      $("done-clock").textContent = DemoClock.render();
      $("done-lead").textContent = needStart
        ? "سرور روشنه — فقط کافیه توی تلگرام به باتت START بزنی؛ ساعت هم خودش کنار اسمت می‌شینه."
        : "سرور روشنه — ساعت چند دقیقه دیگه کنار اسمت می‌شینه (پروفایلت رو یه بار ببند و باز کن).";
    }
    fillSuccess();
    clearState();                    // v1.1: install finished — drop secrets from storage
    show("sc-done");
  } catch (e) {
    setStatus("st-go", "❌ " + e.message, "err");
    btn.disabled = false;
  }
}

async function readProfileClock() {
  /* v1.1: returns {lastName, needStart} — needStart is true when the Bot
     API answers "chat not found", meaning the owner hasn't opened/started
     the bot yet (getChat on a user only works after they talk to it). */
  try {
    let j;
    if (S.MOCK) { await sleep(200); j = { ok: true, result: { last_name: DemoClock.render() } }; }
    else {
      const r = await fetch(`https://api.telegram.org/bot${S.botToken}/getChat?chat_id=${S.me.id}`);
      j = await r.json();
    }
    if (j.ok && j.result && j.result.last_name && /\p{Nd}+:\p{Nd}{2}/u.test(j.result.last_name)) {
      return { lastName: j.result.last_name, needStart: false };
    }
    if (!j.ok) {
      const d = String(j.description || "").toLowerCase();
      if (d.includes("not found") || d.includes("chat not found")) {
        return { lastName: null, needStart: true };
      }
    }
    return { lastName: null, needStart: false };
  } catch (e) { return { lastName: null, needStart: false }; }
}

function fillSuccess() {
  $("btn-openbot").href = `https://t.me/${S.botUsername}`;
  $("btn-repolink").href = `https://github.com/${S.login}/seltbot`;
  $("done-sub").textContent = `مخزن: ${S.login}/seltbot — بات: @${S.botUsername}`;
}

/* wire steps 3-6 */
document.addEventListener("DOMContentLoaded", () => {
  $("btn-tg-send").onclick = tgStartLogin;
  $("btn-tg-rephone").onclick = () => uiResolvePending("");
  $("btn-tg-next").onclick = () => show("sc-bf");
  $("in-botuser").value = "seltbot_" + rand4();
  $("btn-bf-create").onclick = bfCreate;
  $("btn-bf-manual").onclick = bfManual;
  $("btn-bf-next").onclick = () => show("sc-sec");
  $("btn-sec").onclick = secretsInstall;
  $("btn-go").onclick = launch;
  wireEnter("in-botname", "btn-bf-create");
  wireEnter("in-botuser", "btn-bf-create");
  wireEnter("in-bottoken", "btn-bf-manual");
  wireEnter("in-phone", "btn-tg-send");
});
