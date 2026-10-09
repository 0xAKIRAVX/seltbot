/* SeltBot Installer — core: state, navigation, matrix theme, GitHub API
   (telegram/botfather/secrets/launch live in tgflow.js) */
"use strict";

/* ─────────── global state ─────────── */
const S = {
  MOCK: new URLSearchParams(location.search).has("mock"),
  API_ID: 17349,
  API_HASH: "344583e45741c457fe1862106095a5eb",
  UPSTREAM: "0xAKIRAVX/seltbot",
  pat: "", login: "", repoFull: "",
  phone: "", me: null, sessionStr: "",
  tg: null,                     // live GramJS client (or mock)
  botToken: "", botUsername: "",
  stateKey: "",
};

/* ─────────── v1.1: crash-proof progress (localStorage) ───────────
   Android kills backgrounded activities all the time — especially while
   the user switches to Telegram to fetch the login code. Before v1.1 the
   whole wizard (PAT, phone, session string, bot token) died with it and the
   friend had to restart from zero. Now every milestone is persisted and a
   resume banner appears on the intro screen. Cleared on success. */
const PERSIST_KEY = "seltbot_install_v1";
function saveState() {
  try {
    localStorage.setItem(PERSIST_KEY, JSON.stringify({
      step: (history.state && history.state.step) || "sc-intro",
      pat: S.pat, login: S.login, repoFull: S.repoFull,
      phone: S.phone, me: S.me, sessionStr: S.sessionStr,
      botToken: S.botToken, botUsername: S.botUsername, stateKey: S.stateKey,
    }));
  } catch (e) { /* private mode / storage full — degrade gracefully */ }
}
function loadState() {
  try { return JSON.parse(localStorage.getItem(PERSIST_KEY) || "null"); }
  catch (e) { return null; }
}
function clearState() {
  try { localStorage.removeItem(PERSIST_KEY); } catch (e) {}
}

/* ─────────── tiny dom helpers ─────────── */
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const STEP_IDS = ["sc-intro", "sc-gh", "sc-repo", "sc-tg", "sc-bf", "sc-sec", "sc-go", "sc-done"];

/* v1.1: display() only paints a screen; show() also pushes browser history
   so the Android BACK button walks the wizard steps instead of killing the
   app mid-install (the old behavior: back = instant exit + total loss). */
function display(id) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.add("hidden"));
  $(id).classList.remove("hidden");
  window.scrollTo(0, 0);
  const idx = STEP_IDS.indexOf(id);
  if (idx > 0 && id !== "sc-done") buildStepper(idx, 6);
}
function show(id) {
  display(id);
  if (!(history.state && history.state.step === id)) {
    history.pushState({ step: id }, "");
  }
  /* v1.1: never persist ON the success screen — clearState() ran just
     before it; saving here would resurrect the session string in storage. */
  if (id !== "sc-done") saveState();
}
window.addEventListener("popstate", (e) => {
  display((e.state && e.state.step) || "sc-intro");
});
try { history.replaceState({ step: "sc-intro" }, ""); } catch (e) {}

/* v1.1: pressing Enter inside an input submits the paired button — on
   phones everyone types the code and hits Enter; nothing happened before. */
function wireEnter(inputId, btnId) {
  const el = $(inputId);
  if (!el) return;
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); $(btnId).click(); }
  });
}
function buildStepper(on, total) {
  document.querySelectorAll(".stepper").forEach((el) => {
    el.innerHTML = "";
    for (let i = 0; i < total; i++) {
      const d = document.createElement("div");
      d.className = "st" + (i < on ? " on" : "");
      el.appendChild(d);
    }
  });
}
function setStatus(id, msg, cls) {
  const el = $(id);
  if (!msg) { el.className = "status"; el.textContent = ""; return; }
  el.className = "status show " + (cls || "info");
  el.textContent = msg;
}
/* plan checklist rows: state = run|ok|fail */
function plan(boxId, key, st, textOverride) {
  const row = document.querySelector(`#${boxId} .plan-row[data-k="${key}"]`);
  if (!row) return;
  row.classList.remove("run", "ok", "fail");
  if (st) row.classList.add(st);
  if (textOverride) row.querySelector(".tx").textContent = textOverride;
}

/* ─────────── matrix rain background ─────────── */
(function rain() {
  const cv = $("rain"), ctx = cv.getContext("2d");
  const GLYPHS = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ0123456789";
  let cols, drops;
  function resize() {
    cv.width = innerWidth; cv.height = innerHeight;
    cols = Math.floor(cv.width / 16);
    drops = Array.from({ length: cols }, () => Math.random() * cv.height / 16);
  }
  resize(); addEventListener("resize", resize);
  setInterval(() => {
    if (document.hidden) return;
    ctx.fillStyle = "rgba(5,11,6,0.09)";
    ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.font = "14px monospace";
    for (let i = 0; i < cols; i++) {
      const ch = GLYPHS[(Math.random() * GLYPHS.length) | 0];
      ctx.fillStyle = Math.random() < 0.06 ? "#b9ffcf" : "#00b25c";
      ctx.fillText(ch, i * 16, drops[i] * 16);
      if (drops[i] * 16 > cv.height && Math.random() > 0.975) drops[i] = 0;
      drops[i]++;
    }
  }, 55);
})();

/* ─────────── live demo clock (mirror of the server-side matrix render) ─────────── */
const DemoClock = (() => {
  const KATA = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ0123456789";
  const FONTS = ["０１２３４５６７８９", "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿", "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵", "𝟢𝟣𝟤𝟥𝟦𝟧𝟨𝟩𝟪𝟫", "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"];
  function rainChar(k) {
    let h = (Math.imul(k, 2654435761)) >>> 0;
    h ^= h >>> 13; h = Math.imul(h, 1274126177) >>> 0; h ^= h >>> 16;
    return KATA[h % KATA.length];
  }
  function render() {
    const d = new Date();
    const m = d.getHours() * 60 + d.getMinutes();
    const rain = Array.from({ length: 5 }, (_, i) => rainChar(m - (4 - i))).join("");
    const spin = "◐◓◑◒"[d.getMinutes() % 4];
    const time = [d.getHours(), d.getMinutes()].map((v, half) =>
      String(v).padStart(2, "0").split("").map((c, i) =>
        Array.from(FONTS[(m + (half * 2 + i) * 3) % FONTS.length])[+c]).join("")).join(":");
    const blocks = 12, filled = Math.round((d.getMinutes() / 60) * blocks);
    const bar = "▓".repeat(filled) + "░".repeat(blocks - filled);
    return `${spin}｜ ${rain} ${time} ｜ ${bar}`;
  }
  function tickAll() {
    document.querySelectorAll(".hero-demo").forEach((el) => { el.textContent = render(); });
  }
  setInterval(() => { if (!document.hidden) tickAll(); }, 20000);
  tickAll();
  return { render };
})();

/* ─────────── GitHub API layer (mock-aware) ─────────── */
const GH_API = "https://api.github.com";
async function gh(path, method = "GET", body = null, extra = {}) {
  if (S.MOCK) return mockGH(path, method, body);
  const headers = {
    "Authorization": "token " + S.pat,
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
  };
  if (body) headers["Content-Type"] = "application/json";
  const r = await fetch(GH_API + path, {
    method, headers,
    body: body ? JSON.stringify(body) : undefined, ...extra,
  });
  let json = null;
  const txt = await r.text();
  try { json = txt ? JSON.parse(txt) : null; } catch { json = { raw: txt.slice(0, 200) }; }
  return { status: r.status, json };
}
function ghErr(res) {
  const j = res.json || {};
  return (j.message || ("HTTP " + res.status)).slice(0, 140);
}

/* ─────────── mock layer (for headless tests + dev) ─────────── */
async function mockGH(path, method, body) {
  console.log("[mock gh]", method, path, body || "");
  const j = (o) => ({ status: 200, json: o });
  if (path === "/user") return j({ login: "testuser", name: "Test User", avatar_url: "", id: 1 });
  if (path === `/repos/${S.login}/seltbot` && method === "GET") {
    if (!S._mockRepoReady) return { status: 404, json: { message: "Not Found" } };
    return j({ full_name: "testuser/seltbot", fork: true, default_branch: "main" });
  }
  if (path === `/repos/${S.UPSTREAM}/forks` && method === "POST") { S._mockRepoReady = true; return { status: 202, json: {} }; }
  if (path.includes("/actions/permissions")) return { status: 204, json: null };
  if (path === `/repos/${S.login}/seltbot/contents/state.db.enc` && method === "GET") return j({ sha: "abc123" });
  if (path === `/repos/${S.login}/seltbot/contents/state.db.enc` && method === "DELETE") return { status: 200, json: {} };
  if (path.includes("/actions/secrets/public-key")) return j({ key: "GTyWBsuZ0t6JaEKNmrr+w9/nd5oFyycR6BShNmnho1E=", key_id: "568250167242549743" });
  if (path.includes("/actions/secrets/") && method === "PUT") return { status: 204, json: null };
  if (path.includes("/actions/workflows/seltbot.yml/dispatches")) { S._mockRun = 555001; return { status: 204, json: null }; }
  if (path.includes("/actions/runs/") && path.endsWith("/jobs")) {
    return j({ jobs: [{ name: "run", status: "in_progress", conclusion: null,
      steps: [{ name: "Run SeltBot (shift ≈ 5h45m)", status: "in_progress", conclusion: null }] }] });
  }
  if (path.includes("/actions/runs")) {
    return j({ workflow_runs: [{ id: 555001, status: "in_progress", conclusion: null, name: "SeltBot", created_at: new Date().toISOString() }] });
  }
  if (path === "/repos/testuser/seltbot" ) return j({ full_name: "testuser/seltbot" });
  return { status: 404, json: { message: "mock miss: " + path } };
}

/* ─────────── STEP 1 — GitHub PAT ─────────── */
async function ghCheck() {
  const pat = $("in-pat").value.trim();
  const btn = $("btn-gh-check");
  if (pat.length < 20) { setStatus("st-gh", "❗ توکن کامل نیست — کد ghp_… رو کامل کپی کن.", "err"); return; }
  if (!/^gh[pousr]_/.test(pat)) setStatus("st-gh", "⚠️ توکن با ghp_ شروع نمی‌شه — باز چکش کن (ممکنه درست باشه، ادامه می‌دیم).", "info");
  btn.disabled = true;
  setStatus("st-gh", "⏳ در حال بررسی توکن…", "info");
  try {
    S.pat = pat;
    const res = await gh("/user");
    if (res.status !== 200) throw new Error(ghErr(res));
    S.login = res.json.login;
    setStatus("st-gh", `✅ سلام ${res.json.name || S.login}! (اکانت: ${S.login})`, "ok");
    saveState();                       // v1.1: survive app kills
    await sleep(600);
    show("sc-repo");
  } catch (e) {
    setStatus("st-gh", "❌ " + (String(e.message).includes("Bad credentials")
      ? "توکن خرابه یا منقضی شده — یه توکن تازه بساز."
      : String(e.message).includes("403") || String(e.message).includes("401")
        ? "توکن دسترسی کافی نداره — موقع ساخت، دسترسی repo رو فعال کن."
        : "خطا: " + e.message), "err");
  } finally { btn.disabled = false; }
}

/* ─────────── STEP 2 — fork repo + enable actions ─────────── */
async function repoBuild() {
  const btn = $("btn-repo");
  btn.disabled = true;
  try {
    // 1) existing?
    plan("st-repo-plan", "check", "run");
    setStatus("st-repo", "🔎 بررسی مخزن موجود…", "info");
    let res = await gh(`/repos/${S.login}/seltbot`);
    if (res.status === 200) {
      S.repoFull = res.json.full_name;
      plan("st-repo-plan", "check", "ok", "مخزن موجود بود ✓ (رفرش نصب)");
      plan("st-repo-plan", "fork", "ok", "لازم نبود");
      plan("st-repo-plan", "wait", "ok", "لازم نبود");
    } else {
      plan("st-repo-plan", "check", "ok");
      // 2) fork
      plan("st-repo-plan", "fork", "run");
      setStatus("st-repo", "🍴 در حال Fork کردن…", "info");
      res = await gh(`/repos/${S.UPSTREAM}/forks`, "POST", {});
      if (res.status !== 202) throw new Error(ghErr(res));
      plan("st-repo-plan", "fork", "ok");
      // 3) wait for ready
      plan("st-repo-plan", "wait", "run");
      setStatus("st-repo", "⏳ مخزن داره آماده می‌شه…", "info");
      let ok = false;
      for (let i = 0; i < 20; i++) {
        await sleep(3000);
        res = await gh(`/repos/${S.login}/seltbot`);
        if (res.status === 200) { ok = true; break; }
      }
      if (!ok) throw new Error("Fork بعد از ۶۰ ثانیه آماده نشد — دوباره امتحان کن.");
      S.repoFull = res.json.full_name;
      plan("st-repo-plan", "wait", "ok");
    }
    // 4) enable actions
    plan("st-repo-plan", "act", "run");
    setStatus("st-repo", "⚡ فعال‌سازی Actions…", "info");
    res = await gh(`/repos/${S.login}/seltbot/actions/permissions`, "PUT", { enabled: true });
    if (res.status !== 204) {
      if (String(ghErr(res)).includes("already")) { /* fine */ }
      else throw new Error(ghErr(res));
    }
    plan("st-repo-plan", "act", "ok");
    // 5) remove inherited encrypted state (belongs to upstream owner)
    plan("st-repo-plan", "clean", "run");
    res = await gh(`/repos/${S.login}/seltbot/contents/state.db.enc`);
    if (res.status === 200) {
      await gh(`/repos/${S.login}/seltbot/contents/state.db.enc`, "DELETE",
               { message: "installer: fresh start (remove upstream state)", sha: res.json.sha });
    }
    plan("st-repo-plan", "clean", "ok");
    setStatus("st-repo", `✅ مخزن آماده: ${S.repoFull}`, "ok");
    saveState();                       // v1.1: survive app kills
    await sleep(700);
    show("sc-tg");
  } catch (e) {
    setStatus("st-repo", "❌ " + e.message, "err");
    btn.disabled = false;
  }
}

/* wire step 1-2 buttons */
document.addEventListener("DOMContentLoaded", () => {
  $("btn-start").onclick = () => show("sc-gh");
  $("btn-gh-check").onclick = ghCheck;
  $("btn-repo").onclick = repoBuild;
  wireEnter("in-pat", "btn-gh-check");
  $("toggle-pat").onclick = () => {
    const i = $("in-pat");
    i.type = i.type === "password" ? "text" : "password";
    $("toggle-pat").textContent = i.type === "password" ? "👁 نمایش" : "🙈 مخفی";
  };

  /* v1.1: resume banner — the previous install attempt is still alive */
  const saved = loadState();
  if (saved && saved.pat && saved.step && saved.step !== "sc-intro"
      && saved.step !== "sc-done") {
    Object.assign(S, {
      pat: saved.pat || "", login: saved.login || "", repoFull: saved.repoFull || "",
      phone: saved.phone || "", me: saved.me || null, sessionStr: saved.sessionStr || "",
      botToken: saved.botToken || "", botUsername: saved.botUsername || "",
      stateKey: saved.stateKey || "",
    });
    if (saved.phone) $("in-phone").value = saved.phone;
    const box = $("resume-box");
    if (box) {
      const names = {
        "sc-gh": "اتصال گیت‌هاب", "sc-repo": "ساخت مخزن", "sc-tg": "ورود تلگرام",
        "sc-bf": "ساخت بات", "sc-sec": "نصب تنظیمات", "sc-go": "راه‌اندازی",
      };
      const nm = names[saved.step] || saved.step;
      box.classList.remove("hidden");
      $("resume-txt").textContent = `نصب نیمه‌کاره‌ای از «${nm}» یادم مونده 🧠 — ادامه بدی؟`;
      $("resume-go").onclick = () => { box.classList.add("hidden"); show(saved.step); };
      $("resume-no").onclick = () => {
        clearState();
        box.classList.add("hidden");
        /* forget the restored values too — a fresh start must be fresh */
        Object.assign(S, { pat: "", login: "", repoFull: "", phone: "",
          me: null, sessionStr: "", botToken: "", botUsername: "", stateKey: "" });
      };
    }
  }
});
