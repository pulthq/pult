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
// the message fields take the words as typed: no auto-capitals, no autocorrect, no spelling marks (the webview on
// the Mac and the phone's keyboard both read these). Set as attributes: as a DOM property, autocorrect is a
// boolean, so the string "off" would switch it on
const plainField = (el) => { if (el) for (const [k, v] of [["autocapitalize", "none"], ["autocorrect", "off"], ["spellcheck", "false"]]) el.setAttribute(k, v); };
// Cmd+Enter on the Mac, Ctrl+Enter elsewhere — send, as in Telegram; Enter alone still makes a new line
const sendKey = (send) => (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); } };
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

// ---------- voice from the phone ----------

// MediaRecorder: webm/opus on Android and in Chrome, m4a in Safari; 32 kbit/s is plenty for speech. The words come
// back from the computer (Groq) and land in the message field — to be checked and sent with one more tap
const REC_MIME = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus", "audio/ogg"];
const REC_MAX = 5 * 60;      // s; the recording stops by itself
function useRecorder(onText) {
  const [st, setSt] = useState("idle");           // idle | rec | busy
  const [secs, setSecs] = useState(0);
  const cur = useRef(null);
  const stop = () => { const x = cur.current; if (x && x.rec.state !== "inactive") x.rec.stop(); };
  const toggle = async () => {
    if (st !== "idle") return stop();
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder)) return alertBox(t("rec.unsupported"));
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (e) { return alertBox(t("rec.denied")); }
    const mime = REC_MIME.find((m) => MediaRecorder.isTypeSupported(m)) || "";
    let rec;
    try { rec = new MediaRecorder(stream, Object.assign({ audioBitsPerSecond: 32000 }, mime ? { mimeType: mime } : {})); }
    catch (e) { stream.getTracks().forEach((tr) => tr.stop()); return alertBox(t("rec.unsupported")); }
    const chunks = [], t0 = Date.now();
    const x = (cur.current = { rec, timer: 0 });
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = async () => {
      clearInterval(x.timer); stream.getTracks().forEach((tr) => tr.stop()); cur.current = null;
      const blob = new Blob(chunks, { type: rec.mimeType || mime || "audio/webm" });
      if (blob.size < 1000) { setSt("idle"); setSecs(0); return alertBox(t("rec.empty")); }
      setSt("busy");
      try {
        const url = await new Promise((ok, no) => { const f = new FileReader(); f.onload = () => ok(f.result); f.onerror = no; f.readAsDataURL(blob); });
        const res = await api("stt", { data: url.split(",")[1], mime: blob.type });
        if (res.text) { onText(res.text); haptic("success"); }
      } catch (e) { alertBox(e.message); }
      setSt("idle"); setSecs(0);
    };
    x.timer = setInterval(() => { const s = Math.round((Date.now() - t0) / 1000); setSecs(s); if (s >= REC_MAX) stop(); }, 500);
    rec.start(1000);
    setSt("rec"); setSecs(0);
  };
  useEffect(() => () => { const x = cur.current; if (x) { clearInterval(x.timer); try { x.rec.stream.getTracks().forEach((tr) => tr.stop()); } catch (e) { /* already gone */ } } }, []);
  return { st, secs, toggle };
}
const MIC = html`<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/></svg>`;
function Mic({ v, disabled, wide }) {
  const label = v.st === "rec" ? t("rec.stop") : v.st === "busy" ? t("rec.busy") : t("rec");
  const cls = "clip mic" + (wide ? " wide" : "") + (v.st === "rec" ? " rec" : "") + (disabled || v.st === "busy" ? " off" : "");
  return html`<button type="button" class=${cls} aria-label=${label} disabled=${disabled || v.st === "busy"} onClick=${v.toggle}>
    ${v.st === "rec" ? html`<span class="dot"></span><span class="secs">${Math.floor(v.secs / 60)}:${String(v.secs % 60).padStart(2, "0")}</span>` : MIC}
    ${wide ? html`<span>${label}</span>` : ""}</button>`;
}

// a picture the owner sent (from Telegram or the app): the chat shows it, not the path Claude got
function Pic({ a }) {
  const [src, setSrc] = useState(null);
  const [big, setBig] = useState(false);
  const [open, close] = useOverlay(big, setBig);
  useEffect(() => {
    if (!a.image || !a.inbox) return;
    let alive = true;
    api("inbox", { name: a.name }).then((d) => alive && setSrc("data:image/" + (d.kind === "jpg" ? "jpeg" : d.kind) + ";base64," + d.data)).catch(() => {});
    return () => { alive = false; };
  }, [a.name]);
  if (src) return html`<img class="att" src=${src} alt="" onClick=${open}/>${big && html`<div class="lightbox" onClick=${close}><img src=${src} alt=""/></div>`}`;
  return html`<span class="att-chip">${a.image ? "🖼 " + a.name.split("/").pop() : t("att.file")}</span>`;
}

// the model of a session from Telegram: aliases Claude Code accepts, plus whatever the settings say
const MODELS = [["", "model.default"], ["opus", "Opus"], ["sonnet", "Sonnet"], ["haiku", "Haiku"]];
const EFFORTS = ["", "low", "medium", "high", "xhigh", "max"];
const effortName = (e) => (!e ? t("pick.default") : EFFORT_N[e] ? t("effort." + e) : e);
// effort as VS Code draws it by its model name: five dots, as many lit as the level
const EFFORT_N = { low: 1, medium: 2, high: 3, xhigh: 4, max: 5 };
function Dots({ e }) {
  const n = EFFORT_N[e] || 0;
  return html`<svg class="dots" width="29" height="10" viewBox="0 0 29 10" role="img" aria-label=${effortName(e)}>
    ${[0, 1, 2, 3, 4].map((i) => html`<circle key=${i} cx=${2.5 + i * 6} cy="5" r="2.5" fill="currentColor" opacity=${i < n ? 1 : 0.25}/>`)}</svg>`;
}
// a note over the composer: Telegram's own alert box is capped at 256 characters and shows nothing beyond that
function Sheet({ title, lines, onClose }) {
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick"><div class="q-t pick-h">${title}<button class="x" aria-label=${t("close")} onClick=${onClose}>×</button></div>
    ${lines.map((l, i) => html`<p class="sheet-p" key=${i}>${l}</p>`)}</div>`;
}

// the model and the effort of a session, side by side; each tap switches one of them and the menu stays open
function ModelPick({ sid, choice, now, driven, tab, canModel, canEffort, onDone, onClose }) {
  const [busy, setBusy] = useState(false);
  const [cur, setCur] = useState(choice || {});
  const [nudge, setNudge] = useState(0);          // a tap on a column that can't switch here: its reason lights up
  const pick = async (args) => {
    setBusy(true);
    try { const r = await api("model", Object.assign({ sid }, args)); haptic("success"); setCur(r.choice || {}); onDone(r); }
    catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  // "Default" says what it is right now — the last request's model or effort, while nothing is picked here
  // a column that can't switch here looks dim but still answers a tap: the reason under the columns lights up
  const col = (title, items, on, key, can, cur) => html`<div class="pick-col"><div class="pick-t">${title}</div>
    ${items.map(([v, label]) => html`<button key=${v} class=${"opt" + (v === on ? " on" : "") + (can ? "" : " off")} disabled=${busy}
      onClick=${() => (can ? pick({ [key]: v }) : (haptic("warning"), setNudge(nudge + 1)))}>${label}${!v && !on && cur ? html`<span class="dim">${cur}</span>` : ""}</button>`)}</div>`;
  const notes = [driven ? t("model.next") : tab ? t("model.next") + " " + t("model.tab") : t("model.later"), t("pick.default.note"),
    tab && canEffort ? t("effort.tab") : ""];
  const why = tab && !canModel ? t("model.reload") : tab && !canEffort ? t("effort.reload") : "";
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick"><div class="q-t pick-h">${t("model.pick")}<button class="x" aria-label=${t("close")} onClick=${onClose}>×</button></div>
    <div class="pick-cols">
      ${col(t("model"), MODELS.map(([m, label]) => [m, m ? label : t("pick.default")]), cur.model || "", "model", canModel, now.model && modelName(now.model))}
      ${col(t("effort"), EFFORTS.map((e) => [e, effortName(e)]), cur.effort || "", "effort", canEffort, now.effort && effortName(now.effort))}
    </div>
    ${why && html`<div key=${nudge} class=${"pick-why" + (nudge ? " lit" : "")}>${why}</div>`}
    <div class="dim small">${notes.filter(Boolean).join(" ")}</div></div>`;
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
let overlays = 0;      // a picture full screen, the model menu: steps in the history, so Back closes them, not the screen
function back() {
  if (overlays > 0 || stack.length > 1) history.back(); else { history.replaceState(null, "", "#/"); stack[0] = "#/"; dispatchEvent(new HashChangeEvent("hashchange")); }
}
// an overlay's open/close go through the history: the system back gesture, Telegram's Back, a tap outside — all the same
function useOverlay(open, setOpen) {
  useEffect(() => {
    if (!open) return;
    const onPop = () => { overlays = Math.max(0, overlays - 1); setOpen(false); };
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, [open]);
  return [() => { if (!open) { overlays++; history.pushState({ overlay: true }, ""); setOpen(true); } },
          () => { if (open) history.back(); }];
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
  const now = useNow(1000);            // "working 14 s" ticks every second: a turn in progress should look alive
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
  const [key, setKey] = useState("");
  const [kbusy, setKbusy] = useState(false);
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
  const saveKey = async (k) => {
    setKbusy(true);
    try { const r = await api("stt_key", { key: k.trim() }); set(Object.assign({}, d, { stt: Object.assign({}, d.stt || {}, { on: r.on }) })); setKey(""); haptic("success"); alertBox(t(r.on ? "voice.saved" : "voice.removed")); }
    catch (e) { alertBox(e.message); }
    setKbusy(false);
  };
  return html`<div><h2>${t("settings")}</h2>
    <h3>${t("notifications")}</h3><div class="list">${sw("vehi", t("vehi"), t("vehi.about"))}</div>
    <h3>${t("where")}</h3>
    <${ModePick} mode=${d.prefs.mode} onSet=${(m) => set(Object.assign({}, d, { prefs: Object.assign({}, d.prefs, { mode: m }) }))}/>
    <h3>${t("language")}</h3>
    <div class="seg">${[["en", "English"], ["ru", "Русский"]].map(([k, label]) => html`<button key=${k}
      class=${d.prefs.lang === k ? "on" : ""} onClick=${() => setLangPref(k)}>${label}</button>`)}</div>
    <h3>${t("voice")}</h3><div class="list"><div class="item static">
      <div>${d.stt && d.stt.on ? t("voice.on") : t("voice.off")}</div>
      <div class="dim">${t("voice.privacy", { lang: (d.stt && d.stt.lang) || "auto" })}</div>
      <div class="keyrow"><input type="password" ref=${plainField} placeholder=${t("voice.key")} value=${key} onInput=${(e) => setKey(e.target.value)}/>
        <button class="btn" disabled=${!key.trim() || kbusy} onClick=${() => saveKey(key)}>${t("voice.save")}</button></div>
      ${d.stt && d.stt.on ? html`<button class="link" disabled=${kbusy} onClick=${() => saveKey("")}>${t("voice.remove")}</button>` : ""}
    </div></div>
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

// consecutive steps — one "N steps" block that expands; Claude's own lines about its progress (what the VS Code
// tab shows as "summary") sit among the steps, and the collapsed block ends with the latest step or line
const brief = (s, n) => (s && s.length > n ? s.slice(0, n - 1) + "…" : s || "");
function Steps({ steps }) {
  const [open, setOpen] = useState(false);
  const [one, setOne] = useState(null);
  const tools = steps.filter((s) => s.k === "tool");
  const bad = tools.filter((s) => s.ok === false).length;
  const label = tools.length + " " + plural(tools.length, "step");
  const last = steps[steps.length - 1];
  return html`<div class="steps">
    <button class="steps-h" onClick=${() => setOpen(!open)}>${open ? "▾" : "▸"} ${steps[0].ts ? hhmm(toDate(steps[0].ts)) + " · " : ""}${label}${bad ? " · ⚠️ " + bad : ""}
      <span class="dim">${open ? "" : " · " + (last.k === "update" ? brief(last.text, 90) : last.step)}</span></button>
    ${open && steps.map((s, n) => s.k === "update" ? html`<div class="upd" key=${"u" + n}>${s.text}</div>` : html`<div class="step" key=${s.id}>
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
    if (i.k === "tool" || i.k === "update") {
      const last = out[out.length - 1];
      if (last && last.k === "steps") last.steps.push(i);
      else if (i.k === "tool") out.push({ k: "steps", steps: [i], key: "g" + i.id, ts: i.ts });
      else out.push(i);                       // Claude's line before any step: on its own
    } else out.push(i);
  }
  return out;
}
const At = ({ ts, mid }) => (ts ? html`<span class="t">${mid ? t("mid.turn") : ""}${hhmm(toDate(ts))}</span>` : "");

function Session({ sid }) {
  const now = useNow(1000);
  const [s, setS] = useState({ items: [], before: null, end: null, info: null, err: null });
  const ref = useRef(s);
  ref.current = s;
  const bottom = useRef(null);
  // the very bottom of the page, past the padding that keeps the last message above the composer (the end marker
  // sits before that padding, so scrollIntoView stopped short)
  const toBottom = () => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "instant" });
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [pick, setPick] = useState(false);
  const [openPick, closePick] = useOverlay(pick, setPick);
  const [note, setNote] = useState(null);
  const [openNote, closeNote] = useOverlay(!!note, (v) => { if (!v) setNote(null); });
  const [unread, setUnread] = useState(false);
  const [far, setFar] = useState(false);          // scrolled up more than a screen: a way straight to the bottom
  // your own message that went up past the top of the screen: pinned there, like a pinned message in Telegram;
  // a tap shows it in full. "Your message" is the nearest one above what is on screen — the one being answered
  const [pin, setPin] = useState(null);
  const [full, setFull] = useState(null);
  const [openFull, closeFull] = useOverlay(!!full, (v) => { if (!v) setFull(null); });
  const shown = useRef([]);
  // earlier history loads by itself as the top comes near — no button to hunt for; the place being read stays put
  const [early, setEarly] = useState(false);
  const earlyRef = useRef(false);
  const loadRef = useRef(null);
  const earlier = () => {
    if (earlyRef.current || !ref.current.info || ref.current.before == null) return;
    earlyRef.current = true;
    setEarly(true);
    loadRef.current("before").finally(() => { earlyRef.current = false; setEarly(false); });
  };
  const a = useAttach();
  const comp = useRef(null);
  const ta = useRef(null);
  const v = useRecorder((w) => { setText((c) => (c ? c.replace(/\s+$/, "") + " " : "") + w);
    setTimeout(() => { const el = ta.current; if (el) { el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 160) + "px"; } }, 0); });
  const taRef = useMemo(() => (el) => { ta.current = el; plainField(el); }, []);   // one function: Preact sets the ref once
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
    let frame = 0;
    const findPin = () => {
      frame = 0;
      let last = null;
      for (const el of document.querySelectorAll(".msg.me[data-n]")) {
        if (el.getBoundingClientRect().bottom < 0) last = el; else break;
      }
      const n = last ? +last.dataset.n : -1, it = shown.current[n];
      setPin((p) => (!it ? null : p && p.n === n && p.text === it.text ? p : { n, text: it.text, ts: it.ts, att: it.att }));
    };
    const f = () => {
      const gap = document.body.scrollHeight - (window.innerHeight + window.scrollY);
      if (gap < 120) setUnread(false);
      setFar(gap > window.innerHeight);
      if (window.scrollY < 900) earlier();
      if (!frame) frame = requestAnimationFrame(findPin);
    };
    addEventListener("scroll", f, { passive: true });
    return () => { removeEventListener("scroll", f); cancelAnimationFrame(frame); };
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
      // earlier messages go in above: keep the distance to the page's end, so what is on screen doesn't jump
      const fromEnd = document.documentElement.scrollHeight - window.scrollY;
      setS({ items, before: mode === "after" ? cur.before : p.before, end: mode === "before" ? cur.end : p.end,
             info: d, err: null });
      if (stick) setTimeout(toBottom, 30);
      else if (mode === "before") setTimeout(() => window.scrollTo(0, document.documentElement.scrollHeight - fromEnd), 0);
      else if (mode === "after" && p.items.some((i) => i.k !== "result")) setUnread(true);
    } catch (e) { setS(Object.assign({}, ref.current, { err: e.message })); }
  };
  loadRef.current = load;
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
  // two steady lines: the model with its effort (a tap picks them) · where the text goes and the context gauge
  // the model: the one picked for the session, else the one its last request used; the effort — the same way
  const chosen = info.choice && info.choice.model;
  const modelText = chosen ? chosen.charAt(0).toUpperCase() + chosen.slice(1) + (info.stats && info.stats.model && !modelName(info.stats.model).toLowerCase().startsWith(chosen) ? " ▸" : "")
    : info.stats && info.stats.model ? modelName(info.stats.model) : "";
  const effortNow = (info.choice && info.choice.effort) || (info.stats && info.stats.effort) || "";
  const canPick = info.switch || info.switch_effort;
  // a tap on the status explains it in plain words, in a sheet of our own
  const explain = () => { setNote([lv.tab ? t("ex.tab") : lv.open ? t("ex.copy") : t("ex.session"),
    info.stats && info.stats.model ? t("ex.model", { m: modelName(info.stats.model) }) + (info.switch ? "" : " " + (lv.tab ? t("model.reload") : t("model.fixed"))) : "",
    effortNow ? t("ex.effort", { e: effortName(effortNow).toLowerCase() }) + (lv.tab && info.switch && !info.switch_effort ? " " + t("effort.reload") : "") : "",
    info.stats && info.stats.model ? t("ex.ctx", { n: kilo(info.stats.context), win: pct !== null ? t("ex.ctx.win", { w: kilo(info.ctx.window), pct }) : "" }) : ""
  ].filter(Boolean)); openNote(); };
  const line1 = (modelText || canPick) && html`<button class=${"mchip" + (canPick ? " on" : "")} onClick=${canPick ? () => (pick ? closePick() : openPick()) : explain}>
    <span>${modelText || t("model")}</span>${effortNow && html`<${Dots} e=${effortNow}/>`}${canPick ? html`<span class="caret">▾</span>` : ""}</button>`;
  const line2 = (dest || ctxText) && html`<button class="where" onClick=${explain}>${dest}${dest && ctxText ? " · " : ""}<span class=${pct >= 90 ? "bad" : pct >= 70 ? "warn" : ""}>${ctxText}</span></button>`;
  return html`<div class="session">
    <div class="sess-h"><h2>${info.title}</h2><div class="dim">${info.project !== info.title ? html`<a class="crumb" href=${"#/p/" + encodeURIComponent(info.pkey)}>${info.project}</a>` : ""} ${st}</div>
      ${info.stats && info.stats.model && html`<div class="stats">${[modelName(info.stats.model), info.stats.effort && t("effort.is", { e: effortName(info.stats.effort).toLowerCase() })].filter(Boolean).join(" · ")} · <span class=${pct >= 90 ? "bad" : pct >= 70 ? "warn" : ""}>${t("context", { n: kilo(info.stats.context) })}${pct !== null ? t("context.pct", { pct, win: kilo(info.ctx.window) }) : ""}</span><br/>
        ${t("turn.stats", { n: ts.req, requests: plural(ts.req, "request"), out: kilo(ts.out) })}${ts.think ? t("turn.think", { n: kilo(ts.think) }) : ""}</div>`}
      ${lv.bg && lv.bg.length > 0 && html`<div class="bg">${bgLine(lv.bg)}</div>`}</div>
    ${s.before != null && html`<button class="link center earlier" disabled=${early} onClick=${earlier}>${t(early ? "earlier.loading" : "earlier")}</button>`}
    ${pin && html`<button class="pinned" onClick=${() => { setFull(pin); openFull(); }}><span class="pin-in"><span class="pin-bar"></span>
      <span class="pin-body"><span class="pin-h">${t("pin.you")}${pin.ts ? " · " + hhmm(toDate(pin.ts)) : ""}${pin.att && pin.att.length ? " · 📎 " + pin.att.length : ""}</span>
      <span class="pin-tx">${pin.text}</span></span></span></button>`}
    ${(shown.current = group(s.items)).map((i, n) => i.k === "day" ? html`<div class="day" key=${i.key}>${i.label}</div>`
      : i.k === "steps" ? html`<${Steps} key=${i.key} steps=${i.steps}/>`
      : i.k === "user" ? html`<div class="msg me" key=${n} data-n=${n}>${i.voice ? html`<span class="mic-i">🎤</span>` : ""}${i.text}${i.att && i.att.length ? html`<div class="atts">${i.att.map((a, k) => html`<${Pic} key=${k} a=${a}/>`)}</div>` : ""}<${At} ts=${i.ts} mid=${i.mid}/></div>`
      : i.k === "note" ? html`<div class="note" key=${n}>${i.text}${i.ts ? " · " + hhmm(toDate(i.ts)) : ""}</div>`
      : i.k === "update" ? html`<div class="upd solo" key=${n}>${i.text}</div>`
      : html`<div class="msg" key=${n}><div class="md" dangerouslySetInnerHTML=${{ __html: md(i.text) }}/><${At} ts=${i.ts}/></div>`)}
    ${lv.state === "work" && html`<div class="working">${t("working")}</div>`}
    ${info.pending.map((r) => html`<${Req} key=${r.rid} r=${r} showWhere=${false}/>`)}
    <div ref=${bottom}></div>
    ${(unread || far) && html`<button class=${"tobottom" + (unread ? " fresh" : "")} aria-label=${t("to.bottom")} onClick=${() => { toBottom(); setUnread(false); }}>${unread ? t("new.msgs") : "↓"}</button>`}
    <div class="composer" ref=${comp}>
      ${pick && html`<${ModelPick} sid=${sid} choice=${info.choice} now=${info.stats || {}} driven=${lv.driven} tab=${lv.tab} canModel=${info.switch} canEffort=${info.switch_effort} onClose=${closePick} onDone=${() => load("after")}/>`}
      ${note && html`<${Sheet} title=${info.title} lines=${note} onClose=${closeNote}/>`}
      ${full && html`<div class="backdrop" onClick=${closeFull}></div><div class="card pick"><div class="q-t pick-h">${t("pin.you")}${full.ts ? " · " + hhmm(toDate(full.ts)) : ""}<button class="x" aria-label=${t("close")} onClick=${closeFull}>×</button></div>
        <div class="full-tx">${full.text}</div>
        ${full.att && full.att.length ? html`<div class="atts">${full.att.map((x, k) => html`<${Pic} key=${k} a=${x}/>`)}</div>` : ""}
        <button class="link" onClick=${() => { const el = document.querySelector('.msg.me[data-n="' + full.n + '"]'); closeFull();
          if (el) setTimeout(() => el.scrollIntoView({ block: "start" }), 60); }}>${t("pin.goto")}</button></div>`}
      <${Thumbs} a=${a}/>
      <textarea ref=${taRef} rows="1" placeholder=${t("write")} value=${text} onKeyDown=${sendKey(() => { if (!busy) sendText(false); })} onInput=${(e) => { setText(e.target.value); e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px"; }}/>
      <div class="ctl"><${Attach} a=${a} disabled=${busy}/><${Mic} v=${v} disabled=${busy}/>
        <div class="status">${line1}${line2}</div>
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
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const a = useAttach();
  const v = useRecorder((w) => setText((c) => (c ? c.replace(/\s+$/, "") + " " : "") + w));
  if (!d) return html`<${Loading} err=${err}/>`;
  const send = async () => {
    setBusy(true);
    try { const r = await api("new", { pkey: p, text, files: a.payload(), model, effort }); haptic("success"); go("#/s/" + r.sid); }
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
    <textarea ref=${plainField} rows="6" placeholder=${t("new.placeholder")} value=${text} onKeyDown=${sendKey(() => { if (!busy && p && (text.trim() || a.files.length)) send(); })} onInput=${(e) => setText(e.target.value)}/>
    <${Thumbs} a=${a}/>
    <${Attach} a=${a} disabled=${busy} wide=${true}/>
    <${Mic} v=${v} disabled=${busy} wide=${true}/>
    <div class="row2">
      <label class="lbl">${t("model")}<select value=${model} onChange=${(e) => setModel(e.target.value)}>
        ${MODELS.map(([m, label]) => html`<option key=${m} value=${m}>${m ? label : t(label)}</option>`)}</select></label>
      <label class="lbl">${t("effort")}<select value=${effort} onChange=${(e) => setEffort(e.target.value)}>
        ${EFFORTS.map((x) => html`<option key=${x} value=${x}>${x ? effortName(x) : t("effort.default")}</option>`)}</select></label>
    </div>
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
