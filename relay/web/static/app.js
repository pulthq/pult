// Pult — the Telegram Mini App. Claude Code sessions on the Mac: what waits for an answer, what is working, full
// transcripts, answers to questions and permission requests, new tasks, usage. Data comes from the Mac via the relay.
import { html, render, useState, useEffect, useRef, useMemo } from "./vendor/htm-preact-3.1.1.js";
import { md, esc } from "./md.js";
import { t, plural, q, setLang, LANG, locale } from "./i18n.js";

const tg = window.Telegram && window.Telegram.WebApp;
if (tg) { tg.ready(); tg.expand(); }
// the language: Telegram's right away, then Pult's own setting (overview / settings carry it)
setLang(String((tg && tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.language_code) || "en").startsWith("ru") ? "ru" : "en");

// ---------- connection: phone ↔ relay ↔ Mac ----------

const bus = new Map();
const on = (ev, fn) => { bus.has(ev) || bus.set(ev, new Set()); bus.get(ev).add(fn); return () => bus.get(ev).delete(fn); };
const emit = (ev, x) => (bus.get(ev) || []).forEach((fn) => fn(x));
// the re-render is deferred: a screen may learn the language while rendering, before the app has subscribed
const useLang = (l) => { if (l && l !== LANG) { setLang(l); setTimeout(() => emit("lang"), 0); } };

const conn = { ws: null, state: "connecting", ready: false, mac: null, seq: 0, wait: new Map(), retry: 0 };
const setState = (s) => { conn.state = s; emit("conn"); };

function connect() {
  if (conn.ws && conn.ws.readyState <= 1) return;
  const ws = (conn.ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/pult/ws"));
  setState("connecting");
  ws.onopen = () => ws.send(JSON.stringify({ t: "hello", init: (tg && tg.initData) || "",
    client: { platform: tg && tg.platform, version: tg && tg.version } }));
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.t === "hello") { conn.mac = m.mac; setState(m.mac ? "auth" : "nomac"); }
    else if (m.t === "ready") { conn.ready = true; conn.retry = 0; setState("ok"); emit("ready"); api("lang").then(useLang).catch(() => {}); }
    else if (m.t === "denied") { conn.ready = false; setState("denied"); }
    else if (m.t === "mac") { conn.mac = m.on; if (!m.on) { conn.ready = false; setState("nomac"); } else if (!conn.ready) setState("auth"); }
    else if (m.t === "res") {
      const w = conn.wait.get(m.id);
      if (w) { conn.wait.delete(m.id); clearTimeout(w.timer); m.error ? w.reject(new Error(m.error)) : w.resolve(m.data); }
    } else if (m.t === "event") emit("event", m);
  };
  ws.onclose = () => {
    conn.ready = false;
    for (const w of conn.wait.values()) { clearTimeout(w.timer); w.reject(new Error(t("conn.lost"))); }
    conn.wait.clear();
    if (conn.state === "denied") return;
    setState("offline");
    setTimeout(connect, [500, 1000, 2000, 5000, 10000][Math.min(conn.retry++, 4)]);
  };
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) connect(); });
connect();

function api(op, args = {}) {
  return new Promise((resolve, reject) => {
    if (!conn.ready) return reject(new Error(t("conn.nomac")));
    const id = ++conn.seq;
    const timer = setTimeout(() => { conn.wait.delete(id); reject(new Error(t("conn.timeout"))); }, 30000);
    conn.wait.set(id, { resolve, reject, timer });
    conn.ws.send(JSON.stringify({ t: "req", id, op, args }));
  });
}

// screen data: load when the connection is ready and on "something changed" events (at most every 0.4 s)
function useLive(load, deps, match) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const ref = useRef({ timer: null, alive: true });
  useEffect(() => {
    ref.current.alive = true;
    const run = () => load().then((d) => { if (ref.current.alive) { setData(d); setErr(null); } })
      .catch((e) => ref.current.alive && setErr(e.message));
    const soon = () => { clearTimeout(ref.current.timer); ref.current.timer = setTimeout(run, 400); };
    if (conn.ready) run();
    const offs = [on("ready", run), on("event", (m) => (!match || match(m)) && soon())];
    const tick = setInterval(() => conn.ready && run(), 30000);
    return () => { ref.current.alive = false; offs.forEach((f) => f()); clearInterval(tick); clearTimeout(ref.current.timer); };
  }, deps);
  return [data, err, setData];
}

function useConn() {
  const [, set] = useState(0);
  // subscribe, then re-read once: the connection may have changed between the first render and this effect
  // (opening a session link, "ready" came first and the banner stayed on "Connecting…")
  useEffect(() => { const off = on("conn", () => set((x) => x + 1)); set((x) => x + 1); return off; }, []);
  return conn;
}

// ---------- small helpers ----------

function dur(sec) {
  sec = Math.max(0, Math.floor(sec));
  if (sec < 60) return t("dur.s", { n: sec });
  if (sec < 3600) return t("dur.m", { n: Math.floor(sec / 60) });
  const m = Math.floor((sec % 3600) / 60);
  return t("dur.h", { n: Math.floor(sec / 3600) }) + (m ? " " + t("dur.m", { n: m }) : "");
}
const toDate = (ts) => new Date(typeof ts === "number" ? ts * 1000 : ts);
const hhmm = (d) => d.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit", hour12: false });
// "Today, 16 October", "Yesterday, 15 October", "12 October", "3 March 2025"
function dayLabel(d) {
  const now = new Date(), y = new Date(now - 86400000);
  const dm = d.toLocaleDateString(locale(), { day: "numeric", month: "long", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
  return d.toDateString() === now.toDateString() ? t("today", { d: dm }) : d.toDateString() === y.toDateString() ? t("yesterday", { d: dm }) : dm;
}
function ago(ts) {
  if (!ts) return "";
  const d = toDate(ts), now = new Date();
  const s = (now - d) / 1000;
  if (s < 60) return t("ago.now", { hm: hhmm(d) });
  if (s < 3600) return t("ago.min", { n: Math.floor(s / 60), hm: hhmm(d) });
  if (d.toDateString() === now.toDateString()) return hhmm(d);
  if (new Date(now - 86400000).toDateString() === d.toDateString()) return t("ago.yesterday", { hm: hhmm(d) });
  return d.toLocaleDateString(locale(), { day: "2-digit", month: "2-digit" }) + " " + hhmm(d);
}
function resetText(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000), left = ts - Date.now() / 1000;
  if (left > 86400) return t("weekdays").split(" ")[d.getDay()] + " " + hhmm(d);
  return t("reset.at", { hm: hhmm(d), left: dur(Math.max(0, left)) });
}
const num = (x, digits) => x.toLocaleString(locale(), { maximumFractionDigits: digits });
const kilo = (n) => (n >= 1e6 ? t("kilo.m", { n: num(n / 1e6, 1) }) : n >= 1000 ? t("kilo.k", { n: Math.round(n / 1000) }) : String(n || 0));
const modelName = (m) => {
  if (!m) return "";
  const [name, ...ver] = m.replace(/^claude-/, "").split("-");
  return name.charAt(0).toUpperCase() + name.slice(1) + (ver.length ? " " + ver.join(".") : "");
};
const haptic = (k) => tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred(k);
const alertBox = (s) => (tg && tg.showAlert ? tg.showAlert(s) : alert(s));
const confirmBox = (s) => new Promise((ok) => (tg && tg.showConfirm ? tg.showConfirm(s, ok) : ok(confirm(s))));
const go = (h) => { location.hash = h; };

// links in Claude's answers open outside, through Telegram, not inside the app
document.addEventListener("click", (e) => {
  const a = e.target.closest && e.target.closest("a[data-ext]");
  if (a) { e.preventDefault(); tg && tg.openLink ? tg.openLink(a.href) : window.open(a.href, "_blank", "noopener"); }
});

// ---------- pictures from the phone ----------

// a screenshot → a JPEG no wider than 1600 px, as base64: a few hundred kilobytes instead of megabytes
async function shrink(file) {
  const img = await new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = no; i.src = URL.createObjectURL(file); });
  const k = Math.min(1, 1600 / Math.max(img.naturalWidth, img.naturalHeight));
  const c = document.createElement("canvas");
  c.width = Math.max(1, Math.round(img.naturalWidth * k)); c.height = Math.max(1, Math.round(img.naturalHeight * k));
  c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
  URL.revokeObjectURL(img.src);
  const blob = await new Promise((ok) => c.toBlob(ok, "image/jpeg", 0.88));
  const url = await new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = no; r.readAsDataURL(blob); });
  return { name: (file.name || "screenshot").replace(/\.[^.]+$/, "") + ".jpg", data: url.split(",")[1], preview: url };
}
const MAX_PICS = 3;
function useAttach() {
  const [files, setFiles] = useState([]);
  const pick = async (e) => {
    const list = [...(e.target.files || [])].slice(0, MAX_PICS - files.length);
    e.target.value = "";
    const out = [];
    for (const f of list) { try { out.push(await shrink(f)); } catch (err) { alertBox(t("attach.failed")); } }
    setFiles((cur) => cur.concat(out).slice(0, MAX_PICS));
  };
  return { files, pick, remove: (i) => setFiles(files.filter((_, k) => k !== i)), clear: () => setFiles([]),
    payload: () => files.map((f) => ({ name: f.name, data: f.data })) };
}
const CLIP = html`<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>`;
function Attach({ a, disabled, wide }) {
  const full = a.files.length >= MAX_PICS;
  return html`<label class=${"clip" + (wide ? " wide" : "") + (full || disabled ? " off" : "")} aria-label=${t("attach")}>${CLIP}${wide ? html`<span>${t("attach")}</span>` : ""}
    <input type="file" accept="image/*" multiple disabled=${disabled || full} onChange=${a.pick}/></label>`;
}
function Thumbs({ a }) {
  return a.files.length ? html`<div class="thumbs">${a.files.map((f, i) => html`<div class="thumb" key=${i}><img src=${f.preview} alt=""/>
    <button aria-label=${t("attach.remove")} onClick=${() => a.remove(i)}>×</button></div>`)}</div>` : "";
}

// a picture the owner sent (from Telegram or the app): the chat shows it, not the path Claude got
function Pic({ a }) {
  const [src, setSrc] = useState(null);
  const [big, setBig] = useState(false);
  // full screen is a history entry: the system back gesture, Telegram's Back and a tap all go through history.back()
  const open = () => { lightboxes++; history.pushState({ lightbox: true }, ""); setBig(true); };
  useEffect(() => {
    if (!big) return;
    const onPop = () => { lightboxes = Math.max(0, lightboxes - 1); setBig(false); };
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, [big]);
  useEffect(() => {
    if (!a.image || !a.inbox) return;
    let alive = true;
    api("inbox", { name: a.name }).then((d) => alive && setSrc("data:image/" + (d.kind === "jpg" ? "jpeg" : d.kind) + ";base64," + d.data)).catch(() => {});
    return () => { alive = false; };
  }, [a.name]);
  if (src) return html`<img class="att" src=${src} alt="" onClick=${open}/>${big && html`<div class="lightbox" onClick=${() => history.back()}><img src=${src} alt=""/></div>`}`;
  return html`<span class="att-chip">${a.image ? "🖼 " + a.name.split("/").pop() : t("att.file")}</span>`;
}

function useNow(every = 15000) {
  const [now, set] = useState(Date.now() / 1000);
  useEffect(() => { const i = setInterval(() => set(Date.now() / 1000), every); return () => clearInterval(i); }, []);
  return now;
}

// ---------- routes ----------

// Telegram puts its own parameters after # (#tgWebAppData=…) — that's not a screen yet
const tgHash = (h) => /tgWebApp/.test(h);

function parse() {
  const h = tgHash(location.hash) ? "/" : location.hash.replace(/^#/, "") || "/";
  const [path, qs] = h.split("?");
  const parts = path.split("/").filter(Boolean);
  return { name: parts[0] || "home", id: parts[1] ? decodeURIComponent(parts[1]) : null, q: new URLSearchParams(qs || "") };
}
// our own navigation stack: Telegram's "Back" after opening a session link leads home, not nowhere
const stack = [location.hash];
addEventListener("hashchange", () => {
  if (stack.length > 1 && stack[stack.length - 2] === location.hash) stack.pop(); else stack.push(location.hash);
});
let lightboxes = 0;    // a picture open full screen is a step in the history: Back closes it, not the screen
function back() {
  if (lightboxes > 0 || stack.length > 1) history.back(); else { history.replaceState(null, "", "#/"); stack[0] = "#/"; dispatchEvent(new HashChangeEvent("hashchange")); }
}
function useRoute() {
  const [r, set] = useState(parse());
  useEffect(() => { const f = () => { set(parse()); window.scrollTo(0, 0); }; addEventListener("hashchange", f); return () => removeEventListener("hashchange", f); }, []);
  return r;
}
const start = tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param;
if ((!location.hash || tgHash(location.hash)) && start) {
  const h = start.startsWith("s_") ? "#/s/" + start.slice(2) : start.startsWith("p_") ? "#/p/" + encodeURIComponent(start.slice(2))
    : start === "new" ? "#/new" : start === "usage" ? "#/usage" : start === "settings" ? "#/settings" : start === "projects" ? "#/projects" : null;
  if (h) { history.replaceState(null, "", h); stack[0] = h; }
}

// ---------- cards: question, permission request, plan ----------

function Req({ r, onDone, showWhere = true }) {
  const [busy, setBusy] = useState(false);
  const [why, setWhy] = useState(null);
  const [picks, setPicks] = useState({});
  const [own, setOwn] = useState({});
  const send = async (args) => {
    setBusy(true);
    try {
      const res = await api("answer", Object.assign({ rid: r.rid }, args));
      if (res && res.ok === false) alertBox(res.note || t("failed"));
      else haptic("success");
      onDone && onDone();
    } catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  const where = showWhere && html`<div class="card-h"><b>${r.title}</b>${r.project !== r.title ? html`<span class="dim"> · ${r.project}</span>` : ""}</div>`;
  if (r.kind === "ask") {
    return html`<div class="card ask">${where}
      ${r.questions.map((qn, i) => r.chosen && r.chosen[i] ? html`<div class="q done"><div class="q-t">${qn.question}</div>→ <b>${r.chosen[i].join(", ")}</b></div>` : html`
        <div class="q"><div class="q-t">❓ ${qn.question}</div>
          ${(qn.options || []).map((o) => {
            const on_ = (picks[i] || []).includes(o.label);
            return html`<button class=${"opt" + (on_ ? " on" : "")} disabled=${busy} onClick=${() => {
              if (qn.multiSelect) setPicks(Object.assign({}, picks, { [i]: on_ ? picks[i].filter((x) => x !== o.label) : [...(picks[i] || []), o.label] }));
              else send({ answers: { [i]: [o.label] } });
            }}><b>${qn.multiSelect ? (on_ ? "☑ " : "☐ ") : ""}${o.label}</b>${o.description ? html`<span class="dim">${o.description}</span>` : ""}</button>`;
          })}
          ${qn.multiSelect && html`<button class="btn" disabled=${busy || !(picks[i] || []).length} onClick=${() => send({ answers: { [i]: picks[i] } })}>${t("done")}</button>`}
          <div class="own"><input placeholder=${t("ask.own")} value=${own[i] || ""} onInput=${(e) => setOwn(Object.assign({}, own, { [i]: e.target.value }))}/>
            <button class="btn ghost" disabled=${busy || !(own[i] || "").trim()} onClick=${() => send({ answers: { [i]: [own[i].trim()] } })}>${t("ask.answer")}</button></div>
        </div>`)}
    </div>`;
  }
  const isPlan = r.kind === "plan";
  return html`<div class="card perm">${where}
    <div class="perm-h">${isPlan ? t("req.plan") : t("req.perm")}</div>
    ${isPlan ? html`<details class="plan"><summary>${t("plan")}</summary><div class="md" dangerouslySetInnerHTML=${{ __html: md(r.plan) }}/></details>`
      : html`<div class="perm-b" dangerouslySetInnerHTML=${{ __html: r.html }}/>`}
    <div class="row">
      <button class="btn" disabled=${busy} onClick=${() => send({ act: "y" })}>${isPlan ? t("approve") : t("allow")}</button>
      <button class="btn danger" disabled=${busy} onClick=${() => send({ act: "n" })}>${isPlan ? t("reject.plan") : t("deny")}</button>
    </div>
    ${r.suggest && html`<button class="btn ghost wide" disabled=${busy} onClick=${() => send({ act: "a" })}>${t("always")}</button>`}
    ${why === null ? html`<button class="link" onClick=${() => setWhy("")}>${isPlan ? t("plan.notes") : t("deny.note")}</button>` : html`
      <div class="own"><input placeholder=${t("tell.claude")} value=${why} onInput=${(e) => setWhy(e.target.value)}/>
        <button class="btn ghost" disabled=${busy || !why.trim()} onClick=${() => send({ act: "n", text: why.trim() })}>${t("send")}</button></div>`}
  </div>`;
}

// ---------- screens ----------

// Claude's background tasks still running after a turn; when one ends, Claude starts a new turn by itself
const bgLine = (bg) => t("bg", { list: bg.map(q).join(", ") });

function Row({ s, now, onClick }) {
  const st = s.state === "ask" ? html`<span class="chip warn">${t("st.ask")}</span>`
    : s.state === "work" ? html`<span class="chip ok">${t("st.work", { dur: s.started ? dur(now - s.started) : "" })}</span>`
    : s.bg && s.bg.length ? html`<span class="chip">${t("st.bg")}</span>`
    : html`<span class="chip">${t("st.open")}</span>`;
  return html`<button class="item" onClick=${onClick}>
    <div class="item-h"><b>${s.driven ? "📱 " : ""}${s.title}</b>${st}</div>
    <div class="dim">${[s.project !== s.title ? s.project : "", s.prompt ? q(s.prompt) : s.note || ""].filter(Boolean).join(" · ")}</div>
    ${s.now && html`<div class="now">💬 ${s.now}</div>`}
    ${s.bg && s.bg.length > 0 && html`<div class="bg">${bgLine(s.bg)}</div>`}
  </button>`;
}

// where the owner is: it only changes the sound, messages always arrive
const MODES = ["auto", "mac", "phone"];
function ModePick({ mode, onSet }) {
  const pick = async (m) => {
    if (m === mode) return;
    try { await api("prefs", { mode: m }); onSet(m); haptic("success"); } catch (e) { alertBox(e.message); }
  };
  const cur = MODES.includes(mode) ? mode : "auto";
  return html`<div class="modes"><div class="seg">${MODES.map((k) =>
    html`<button key=${k} class=${k === cur ? "on" : ""} onClick=${() => pick(k)}>${t("mode." + k + ".btn")}</button>`)}</div>
    <div class="dim small">${t("mode." + cur + ".about")}</div></div>`;
}

// the Home strip: where you are in one line (tap — the mode picker), and the way to the settings. The strip is a
// setting, not the news: what waits for an answer comes right under it
const GEAR = html`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`;
function Where({ mac, onSet }) {
  const [open, setOpen] = useState(false);
  const cur = MODES.includes(mac.mode) ? mac.mode : "auto";
  const line = cur === "auto" ? (mac.away ? t("mac.away.short", { dur: dur(mac.idle) }) : t("mac.here.short")) : t("mode." + cur + ".short");
  return html`<div class="where">
    <div class="where-h">
      <button class="where-b" aria-expanded=${open} onClick=${() => setOpen(!open)}><b>${t("mode." + cur + ".btn")}</b><span class="dim">${line}</span><span class="caret">${open ? "▾" : "▸"}</span></button>
      <a class="gear" href="#/settings" aria-label=${t("settings")}>${GEAR}</a>
    </div>
    ${open && html`<${ModePick} mode=${cur} onSet=${onSet}/>`}
  </div>`;
}

function Home() {
  const now = useNow();
  const [d, err, set] = useLive(() => api("overview"), []);
  const [showOpen, setShowOpen] = useState(false);
  if (!d) return html`<${Loading} err=${err}/>`;
  useLang(d.lang);
  const quiet = !d.pending.length && !d.live.length;
  return html`<div>
    <${Where} mac=${d.mac} onSet=${(m) => set(Object.assign({}, d, { mac: Object.assign({}, d.mac, { mode: m }) }))}/>
    ${d.pending.length > 0 && html`<h3>${t("home.pending", { n: d.pending.length })}</h3>${d.pending.map((r) => html`<${Req} key=${r.rid} r=${r}/>`)}`}
    ${d.live.length > 0 && html`<h3>${t("home.live", { n: d.live.length })}</h3>
      <div class="list">${d.live.map((s) => html`<${Row} key=${s.sid} s=${s} now=${now} onClick=${() => go("#/s/" + s.sid)}/>`)}</div>`}
    ${quiet && html`<div class="empty">${t("home.quiet")}</div>`}
    ${d.open.length > 0 && html`<h3 class="toggle" onClick=${() => setShowOpen(!showOpen)}>${t("home.open", { n: d.open.length })} ${showOpen ? "▾" : "▸"}</h3>
      ${showOpen && html`<div class="list">${d.open.map((s) => html`<${Row} key=${s.sid} s=${s} now=${now} onClick=${() => go("#/s/" + s.sid)}/>`)}</div>`}`}
    ${d.jobs && d.jobs.length > 0 && html`<h3>${t("home.jobs")}</h3><div class="list">${d.jobs.map((j) => html`<${Job} key=${j.id} j=${j} now=${now}/>`)}</div>`}
    ${d.recent.length > 0 && html`<h3>${t("home.recent")}</h3><div class="list">${d.recent.map((x) => html`
      <button class="item" key=${x.sid + x.ts} onClick=${() => go("#/s/" + x.sid)}>
        <div class="item-h"><b>✅ ${x.title}</b><span class="dim">${ago(x.ts)}</span></div>
        <div class="dim">${[x.project !== x.title ? x.project : "", x.dur ? t("home.took", { dur: dur(x.dur) }) : ""].filter(Boolean).join(" · ")}</div>
        <div class="now">${x.text}</div></button>`)}</div>`}
  </div>`;
}

function Job({ j, now }) {
  const [open, setOpen] = useState(false);
  const st = j.ended == null ? html`<span class="chip ok">${t("job.running", { dur: dur(now - j.started) })}</span>`
    : j.code === 0 ? html`<span class="chip">✔ ${dur(j.ended - j.started)}</span>`
    : html`<span class="chip bad">${j.code == null ? t("job.killed") : t("job.code", { code: j.code })}</span>`;
  return html`<button class="item" onClick=${() => setOpen(!open)}>
    <div class="item-h"><b class="mono">${j.cmd}</b>${st}</div>
    <div class="dim">${j.project || j.cwd}${j.ended ? " · " + ago(j.ended) : ""}</div>
    ${!open && j.last && j.ended == null && html`<div class="now mono">${j.last}</div>`}
    ${open && html`<pre class="tail">${(j.tail.length ? j.tail : [j.last || t("job.noout")]).join("\n")}</pre>`}
  </button>`;
}

function Settings() {
  const [d, err, set] = useLive(() => api("settings"), [], () => false);
  if (!d) return html`<${Loading} err=${err}/>`;
  useLang(d.prefs.lang);
  const toggle = async (k) => {
    try { const p = await api("prefs", { [k]: !d.prefs[k] }); set(Object.assign({}, d, { prefs: Object.assign({}, d.prefs, p) })); haptic("success"); }
    catch (e) { alertBox(e.message); }
  };
  const sw = (k, label, hint) => html`<button class="item" onClick=${() => toggle(k)}>
    <div class="item-h"><b>${label}</b><span class=${"sw" + (d.prefs[k] ? " on" : "")}></span></div><div class="dim">${hint}</div></button>`;
  const setLangPref = async (k) => {
    try { await api("prefs", { lang: k }); set(Object.assign({}, d, { prefs: Object.assign({}, d.prefs, { lang: k }) })); useLang(k); haptic("success"); }
    catch (e) { alertBox(e.message); }
  };
  return html`<div><h2>${t("settings")}</h2>
    <h3>${t("notifications")}</h3><div class="list">${sw("vehi", t("vehi"), t("vehi.about"))}</div>
    <h3>${t("where")}</h3>
    <${ModePick} mode=${d.prefs.mode} onSet=${(m) => set(Object.assign({}, d, { prefs: Object.assign({}, d.prefs, { mode: m }) }))}/>
    <h3>${t("language")}</h3>
    <div class="seg">${[["en", "English"], ["ru", "Русский"]].map(([k, label]) => html`<button key=${k}
      class=${d.prefs.lang === k ? "on" : ""} onClick=${() => setLangPref(k)}>${label}</button>`)}</div>
    <h3>${t("status")}</h3><div class="list"><div class="item static">
      <div>${t("status.pult", { v: d.version, mac: d.mac.away ? t("mac.away", { dur: dur(d.mac.idle) }) : t("mac.here") })}</div>
      <div class="dim">${t("status.tg", { how: t("tg." + (d.telegram === "proxy" ? "proxy" : "direct")) })}</div>
      <div class="dim">${d.hooks.length ? t("status.hooks", { n: d.hooks.length }) : t("status.nohooks")}</div>
    </div></div>
    <details class="logbox"><summary>${t("log", { n: d.log.length })}</summary>
      <pre class="log">${d.log.slice().reverse().join("\n")}</pre></details>
  </div>`;
}

function Projects() {
  const [d, err] = useLive(() => api("projects"), []);          // live: the counts change with every turn
  if (!d) return html`<${Loading} err=${err}/>`;
  if (!d.projects.length) return html`<div><h3>${t("projects")}</h3><div class="empty">${t("projects.none")}</div></div>`;
  return html`<div><h3>${t("projects")}</h3><div class="list">${d.projects.map((p) => html`
    <button class="item" key=${p.pkey} onClick=${() => go("#/p/" + encodeURIComponent(p.pkey))}>
      <div class="item-h"><b>${p.name}</b><span class="dim">${ago(p.last)}</span></div>
      ${(p.open || p.work || p.ask) ? html`<div class="chips">
        ${p.work ? html`<span class="chip ok">${t("pj.work", { n: p.work })}</span>` : ""}
        ${p.ask ? html`<span class="chip warn">${t("pj.ask", { n: p.ask })}</span>` : ""}
        ${p.open ? html`<span class="chip">${t("pj.open", { n: p.open })}</span>` : ""}</div>` : ""}
      <div class="dim path">${p.path}</div></button>`)}</div></div>`;
}

function Project({ pkey }) {
  const [d, err] = useLive(() => api("sessions", { pkey }), [pkey]);
  if (!d) return html`<${Loading} err=${err}/>`;
  return html`<div><h2>${d.name}</h2>
    <button class="btn wide" onClick=${() => go("#/new?pkey=" + encodeURIComponent(pkey))}>${t("project.new")}</button>
    <h3>${t("sessions")}</h3>${!d.sessions.length && html`<div class="empty">${t("sessions.none")}</div>`}<div class="list">${d.sessions.map((s) => html`
      <button class="item" key=${s.sid} onClick=${() => go("#/s/" + s.sid)}>
        <div class="item-h"><b>${s.driven ? "📱 " : ""}${s.title}</b><span class="dim">${ago(s.last)}</span></div>
        ${s.open && html`<div class="dim">${t("open.mac")}</div>`}</button>`)}</div></div>`;
}

// consecutive steps — one "N steps" block that expands
function Steps({ steps }) {
  const [open, setOpen] = useState(false);
  const [one, setOne] = useState(null);
  const bad = steps.filter((s) => s.ok === false).length;
  const label = steps.length + " " + plural(steps.length, "step");
  return html`<div class="steps">
    <button class="steps-h" onClick=${() => setOpen(!open)}>${open ? "▾" : "▸"} ${steps[0].ts ? hhmm(toDate(steps[0].ts)) + " · " : ""}${label}${bad ? " · ⚠️ " + bad : ""}
      <span class="dim">${open ? "" : " · " + steps[steps.length - 1].step}</span></button>
    ${open && steps.map((s) => html`<div class="step" key=${s.id}>
      <button class="step-h" onClick=${() => setOne(one === s.id ? null : s.id)}><span class="dim">${s.ts ? hhmm(toDate(s.ts)) + " " : ""}</span>${s.ok === false ? "⚠️ " : ""}${s.step}</button>
      ${one === s.id && html`<pre>${s.input}</pre>${s.out ? html`<pre class="out">${s.out}</pre>` : ""}`}</div>`)}
  </div>`;
}

function merge(items) {
  // step results that came separately (the step is in another chunk) — attach them to their steps
  const tools = new Map(items.filter((i) => i.k === "tool").map((i) => [i.id, i]));
  return items.filter((i) => {
    if (i.k !== "result") return true;
    const tl = tools.get(i.id);
    if (tl) { tl.ok = i.ok; tl.out = i.out; return false; }
    return true;            // the step is in an earlier chunk: attached once that chunk loads
  });
}

function group(items) {
  const out = [];
  let day = null;
  for (const i of items) {
    if (i.k === "result") continue;
    const d = i.ts ? toDate(i.ts).toDateString() : day;
    if (d && d !== day) { out.push({ k: "day", label: dayLabel(toDate(i.ts)), key: "d" + d }); day = d; }
    if (i.k === "tool") {
      const last = out[out.length - 1];
      if (last && last.k === "steps") last.steps.push(i);
      else out.push({ k: "steps", steps: [i], key: "g" + i.id, ts: i.ts });
    } else out.push(i);
  }
  return out;
}
const At = ({ ts, mid }) => (ts ? html`<span class="t">${mid ? t("mid.turn") : ""}${hhmm(toDate(ts))}</span>` : "");

function Session({ sid }) {
  const now = useNow(10000);
  const [s, setS] = useState({ items: [], before: null, end: null, info: null, err: null });
  const ref = useRef(s);
  ref.current = s;
  const bottom = useRef(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [unread, setUnread] = useState(false);
  const [far, setFar] = useState(false);          // scrolled up more than a screen: a way straight to the bottom
  const a = useAttach();
  const comp = useRef(null);
  const ta = useRef(null);
  useEffect(() => {
    const el = comp.current, main = document.querySelector("main");
    if (!el || !main || !window.ResizeObserver) return;
    const ro = new ResizeObserver(() => {
      main.style.paddingBottom = (el.offsetHeight + 12) + "px";
      document.documentElement.style.setProperty("--composer-h", el.offsetHeight + "px");
    });
    ro.observe(el);
    return () => { ro.disconnect(); main.style.paddingBottom = ""; };
  }, [!!s.info]);
  useEffect(() => {
    const f = () => {
      const gap = document.body.scrollHeight - (window.innerHeight + window.scrollY);
      if (gap < 120) setUnread(false);
      setFar(gap > window.innerHeight);
    };
    addEventListener("scroll", f, { passive: true });
    return () => removeEventListener("scroll", f);
  }, []);

  const load = async (mode) => {
    const cur = ref.current;
    if (mode === "after" && cur.end == null) mode = "full";
    try {
      const args = { sid };
      if (mode === "after") args.after = cur.end;
      if (mode === "before") args.before = cur.before;
      const d = await api("session", args);
      const p = d.page;
      if (mode === "after" && p.reset) return load("full");       // too much new — reload everything
      const items = mode === "after" ? merge([...cur.items, ...p.items])
        : mode === "before" ? merge([...p.items, ...cur.items]) : merge(p.items);
      const stick = mode !== "before" && (!cur.info || window.innerHeight + window.scrollY > document.body.scrollHeight - 120);
      setS({ items, before: mode === "after" ? cur.before : p.before, end: mode === "before" ? cur.end : p.end,
             info: d, err: null });
      if (stick) setTimeout(() => bottom.current && bottom.current.scrollIntoView({ block: "end" }), 30);
      else if (mode === "after" && p.items.some((i) => i.k !== "result")) setUnread(true);
    } catch (e) { setS(Object.assign({}, ref.current, { err: e.message })); }
  };
  useEffect(() => {
    setS({ items: [], before: null, end: null, info: null, err: null });
    ref.current = { items: [], before: null, end: null, info: null, err: null };
    let timer;
    if (conn.ready) load("full");
    const offs = [on("ready", () => load("full")),
      on("event", (m) => { if (!m.sid || m.sid === sid) { clearTimeout(timer); timer = setTimeout(() => load("after"), 400); } })];
    return () => { offs.forEach((f) => f()); clearTimeout(timer); };
  }, [sid]);

  const sendText = async (fork) => {
    if (!text.trim() && !a.files.length) return;
    setBusy(true);
    try {
      const r = await api("send", { sid, text, fork: !!fork, files: a.payload() });
      if (r.need === "fork") {
        setBusy(false);
        if (await confirmBox(t("fork.ask"))) return sendText(true);
        return;
      }
      haptic("success");
      setText("");
      a.clear();
      if (ta.current) ta.current.style.height = "auto";       // back to one line: the field grew with the message
      if (r.how === "fork") alertBox(t("fork.started"));
    } catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  const stop = async () => {
    const r = await api("stop", { sid }).catch((e) => ({ note: e.message }));
    r.ok ? haptic("success") : alertBox(r.note || t("failed"));
  };

  const info = s.info;
  if (!info) return html`<${Loading} err=${s.err && (/not found|не найден/.test(s.err) ? t("sess.starting") : s.err)}/>`;
  const lv = info.live;
  const st = lv.state === "ask" ? html`<span class="chip warn">${t("st.ask")}</span>`
    : lv.state === "work" ? html`<span class="chip ok">${t("st.work", { dur: lv.started ? dur(now - lv.started) : "" })}</span>` : "";
  const ts = info.stats && info.stats.turn;
  // the context gauge, the same number VS Code shows: used ÷ (window − the reserve for the answer)
  const pct = info.ctx && info.stats ? Math.min(100, Math.round(info.stats.context * 100 / info.ctx.usable)) : null;
  // the status under the message field: where the text goes (a tab, a copy), the model, the context gauge
  const dest = lv.tab ? t("dest.tab") : lv.open ? t("dest.copy") : "";
  const ctxText = info.stats && info.stats.model ? (pct !== null ? t("ctx.pct", { pct, win: kilo(info.ctx.window) }) : t("context", { n: kilo(info.stats.context) })) : "";
  const status = html`${dest}${dest && info.stats && info.stats.model ? " · " : ""}${info.stats && info.stats.model ? modelName(info.stats.model) + " · " : ""}<span class=${pct >= 90 ? "bad" : pct >= 70 ? "warn" : ""}>${ctxText}</span>`;
  return html`<div class="session">
    <div class="sess-h"><h2>${info.title}</h2><div class="dim">${info.project !== info.title ? html`<a class="crumb" href=${"#/p/" + encodeURIComponent(info.pkey)}>${info.project}</a>` : ""} ${st}</div>
      ${info.stats && info.stats.model && html`<div class="stats">${[modelName(info.stats.model), info.stats.effort].filter(Boolean).join(" · ")} · <span class=${pct >= 90 ? "bad" : pct >= 70 ? "warn" : ""}>${t("context", { n: kilo(info.stats.context) })}${pct !== null ? t("context.pct", { pct, win: kilo(info.ctx.window) }) : ""}</span><br/>
        ${t("turn.stats", { n: ts.req, requests: plural(ts.req, "request"), out: kilo(ts.out) })}${ts.think ? t("turn.think", { n: kilo(ts.think) }) : ""}</div>`}
      ${lv.bg && lv.bg.length > 0 && html`<div class="bg">${bgLine(lv.bg)}</div>`}</div>
    ${s.before != null && html`<button class="link center" onClick=${() => load("before")}>${t("earlier")}</button>`}
    ${group(s.items).map((i, n) => i.k === "day" ? html`<div class="day" key=${i.key}>${i.label}</div>`
      : i.k === "steps" ? html`<${Steps} key=${i.key} steps=${i.steps}/>`
      : i.k === "user" ? html`<div class="msg me" key=${n}>${i.text}${i.att && i.att.length ? html`<div class="atts">${i.att.map((a, k) => html`<${Pic} key=${k} a=${a}/>`)}</div>` : ""}<${At} ts=${i.ts} mid=${i.mid}/></div>`
      : i.k === "note" ? html`<div class="note" key=${n}>${i.text}${i.ts ? " · " + hhmm(toDate(i.ts)) : ""}</div>`
      : html`<div class="msg" key=${n}><div class="md" dangerouslySetInnerHTML=${{ __html: md(i.text) }}/><${At} ts=${i.ts}/></div>`)}
    ${lv.state === "work" && html`<div class="working">${t("working")}</div>`}
    ${info.pending.map((r) => html`<${Req} key=${r.rid} r=${r} showWhere=${false}/>`)}
    <div ref=${bottom}></div>
    ${(unread || far) && html`<button class=${"tobottom" + (unread ? " fresh" : "")} aria-label=${t("to.bottom")} onClick=${() => { bottom.current && bottom.current.scrollIntoView({ block: "end" }); setUnread(false); }}>${unread ? t("new.msgs") : "↓"}</button>`}
    <div class="composer" ref=${comp}>
      <${Thumbs} a=${a}/>
      <textarea ref=${ta} rows="1" placeholder=${t("write")} value=${text} onInput=${(e) => { setText(e.target.value); e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px"; }}/>
      <div class="ctl"><${Attach} a=${a} disabled=${busy}/>
        <span class="status">${status}</span>
        ${lv.driven && lv.state === "work" ? html`<button class="btn danger" onClick=${stop}>${t("stop")}</button>` : ""}
        <button class="btn send" aria-label=${t("send")} disabled=${busy || (!text.trim() && !a.files.length)} onClick=${() => sendText(false)}><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="M5 12l7-7 7 7"/></svg></button></div>
    </div>
  </div>`;
}

function NewTask({ pkey }) {
  const [d, err] = useLive(() => api("projects"), [], () => false);
  const [p, setP] = useState(pkey || "");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const a = useAttach();
  if (!d) return html`<${Loading} err=${err}/>`;
  const send = async () => {
    setBusy(true);
    try { const r = await api("new", { pkey: p, text, files: a.payload() }); haptic("success"); go("#/s/" + r.sid); }
    catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  return html`<div><h2>${t("new.title")}</h2>
    <label class="lbl">${t("new.project")}</label>
    <select value=${p} onChange=${(e) => setP(e.target.value)}>
      <option value="">${t("new.pick")}</option>
      ${d.projects.map((x) => html`<option value=${x.pkey}>${x.name}</option>`)}
    </select>
    <label class="lbl">${t("new.what")}</label>
    <textarea rows="6" placeholder=${t("new.placeholder")} value=${text} onInput=${(e) => setText(e.target.value)}/>
    <${Thumbs} a=${a}/>
    <${Attach} a=${a} disabled=${busy} wide=${true}/>
    <button class="btn wide" disabled=${busy || !p || (!text.trim() && !a.files.length)} onClick=${send}>${t("new.start")}</button>
    <div class="dim small">${t("new.about")}</div>
  </div>`;
}

function Usage() {
  const [d, err, set] = useLive(() => api("usage"), [], () => false);
  const [busy, setBusy] = useState(false);
  useNow(30000);
  const refresh = async () => {
    setBusy(true);
    try { set(await api("usage", { force: true })); haptic("success"); } catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  if (!d) return html`<div><${Loading} err=${err && t("usage.failed", { err })}/><${Today}/></div>`;
  const level = (p) => (p >= 90 ? "bad" : p >= 70 ? "warn" : "");
  return html`<div><h2>${t("usage")}</h2>
    <div class="dim">${d.plan ? t("usage.plan", { plan: d.plan.charAt(0).toUpperCase() + d.plan.slice(1) }) : ""}</div>
    <div class="list">${d.limits.map((x) => html`<div class="lim" key=${x.name}>
      <div class="item-h"><b>${x.name}</b><b class=${"pct " + level(x.percent)}>${x.percent} %</b></div>
      <div class="meter"><i class=${level(x.percent)} style=${"width:" + Math.min(100, x.percent) + "%"}></i></div>
      <div class="dim">${t("usage.reset", { when: resetText(x.resets_at) })}</div></div>`)}</div>
    ${d.week_by.length > 0 && html`<div class="dim small">${t("usage.week", { list: d.week_by.map((x) => x.name + " " + x.percent + " %").join(" · ") })}</div>`}
    ${d.extra.enabled && html`<div class="dim small">${t("usage.extra", { used: d.extra.used ?? 0, limit: d.extra.limit ?? "—", cur: d.extra.currency || "" })}</div>`}
    <button class="btn ghost wide" disabled=${busy} onClick=${refresh}>${busy ? t("refreshing") : t("refresh")}</button>
    <div class="dim small">${t("usage.updated", { ago: ago(d.ts) })}</div>
    <${Today}/>
  </div>`;
}

// tokens today by project — from the Mac's transcripts; refreshes itself every 30 s
function Today() {
  const [d] = useLive(() => api("today"), [], () => false);
  if (!d || !d.projects.length) return "";
  const all = d.projects.reduce((s, p) => s + p.out, 0) || 1;
  return html`<h3>${t("today.title")}</h3>
    <div class="list">${d.projects.slice(0, 12).map((p) => html`<div class="lim" key=${p.pkey}>
      <div class="item-h"><b>${p.name}</b><b class="pct">${Math.round(p.out * 100 / all)} %</b></div>
      <div class="meter"><i style=${"width:" + Math.max(1, p.out * 100 / all) + "%"}></i></div>
      <div class="dim">${t("today.row", { n: p.req, requests: plural(p.req, "request"), out: kilo(p.out), read: kilo(p.read) })}</div></div>`)}</div>
    <div class="dim small">${t("today.about")}</div>`;
}

function Loading({ err }) {
  return html`<div class="empty">${err || t("loading")}</div>`;
}

function Banner() {
  const c = useConn();
  const text = ["connecting", "offline", "auth", "nomac", "denied"].includes(c.state) ? t("banner." + c.state) : "";
  return text ? html`<div class=${"banner " + c.state}>${text}</div>` : "";
}

function App() {
  const r = useRoute();
  const [, relang] = useState(0);
  useEffect(() => { const off = on("lang", () => relang((x) => x + 1)); relang((x) => x + 1); return off; }, []);
  useEffect(() => {
    if (!tg || !tg.BackButton) return;
    if (r.name === "home") tg.BackButton.hide(); else tg.BackButton.show();
    tg.BackButton.onClick(back);
    return () => tg.BackButton.offClick(back);
  }, [r.name, r.id]);
  const screen = r.name === "s" ? html`<${Session} sid=${r.id}/>`
    : r.name === "p" ? html`<${Project} pkey=${r.id}/>`
    : r.name === "projects" ? html`<${Projects}/>`
    : r.name === "new" ? html`<${NewTask} pkey=${r.q.get("pkey")}/>`
    : r.name === "usage" ? html`<${Usage}/>`
    : r.name === "settings" ? html`<${Settings}/>`
    : html`<${Home}/>`;
  const tab = (name, h, label) => html`<a class=${r.name === name ? "on" : ""} href=${h}>${label}</a>`;
  return html`<${Banner}/><main class=${r.name === "s" ? "with-composer" : ""}>${screen}</main>
    ${r.name !== "s" && html`<nav class="tabs">${tab("home", "#/", t("tab.home"))}${tab("projects", "#/projects", t("tab.projects"))}${tab("usage", "#/usage", t("tab.usage"))}${tab("new", "#/new", "＋")}</nav>`}`;
}

render(html`<${App}/>`, document.getElementById("app"));
