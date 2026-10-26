// Pult — the Telegram Mini App. Claude Code sessions on the Mac: what waits for an answer, what is working, full
// transcripts, answers to questions and permission requests, new tasks, usage. Data comes from the Mac via the relay.
import { html, render, useState, useEffect, useRef, useMemo } from "./vendor/htm-preact-3.1.1.js";
import { md, esc } from "./md.js";
import { t, plural, q, setLang, LANG, locale } from "./i18n.js";

const tg = window.Telegram && window.Telegram.WebApp;
if (tg) { tg.ready(); tg.expand(); }
// the app's own colours (the ones Telegram doesn't send, the chart's) follow Telegram's theme, not only the phone's —
// when Telegram sent one: outside it (the stand, a browser) its script says "light" anyway, and the phone decides
const scheme = () => { if (tg && tg.colorScheme && tg.themeParams && tg.themeParams.bg_color) document.documentElement.dataset.scheme = tg.colorScheme; };
scheme();
if (tg && tg.onEvent) tg.onEvent("themeChanged", scheme);
// the language: Telegram's right away, then Pult's own setting (overview / settings carry it)
setLang(String((tg && tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.language_code) || "en").startsWith("ru") ? "ru" : "en");

// ---------- connection: phone ↔ relay ↔ Mac ----------

const bus = new Map();
const on = (ev, fn) => { bus.has(ev) || bus.set(ev, new Set()); bus.get(ev).add(fn); return () => bus.get(ev).delete(fn); };
const emit = (ev, x) => (bus.get(ev) || []).forEach((fn) => fn(x));
// the re-render is deferred: a screen may learn the language while rendering, before the app has subscribed
const useLang = (l) => { if (l && l !== LANG) { setLang(l); setTimeout(() => emit("lang"), 0); } };

// the resume key this Mac gave the window at its last login: a reconnect (the network blinked, the Mac restarted)
// logs in with it, since only a fresh initData opens a new login. sessionStorage — it lives as long as this window
// (a reload keeps it) and goes nowhere else
const keyStore = {
  get() { try { return sessionStorage.getItem("pult.resume"); } catch (e) { return null; } },
  set(k) { try { k ? sessionStorage.setItem("pult.resume", k) : sessionStorage.removeItem("pult.resume"); } catch (e) {} },
};
const conn = { ws: null, state: "connecting", ready: false, mac: null, seq: 0, wait: new Map(), retry: 0,
  key: keyStore.get(), why: null, fresh: 0, updating: 0 };   // updating: since when Pult installs an update (stage U)       // fresh: when the Mac last answered — what's on screen is from then
const setState = (s) => { conn.state = s; emit("conn"); };
const setKey = (k) => { conn.key = k || null; keyStore.set(k); };

function connect() {
  if (conn.ws && conn.ws.readyState <= 1) return;
  const ws = (conn.ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/pult/ws"));
  setState("connecting");
  ws.onopen = () => ws.send(JSON.stringify({ t: "hello", init: (tg && tg.initData) || "", resume: conn.key,
    client: { platform: tg && tg.platform, version: tg && tg.version } }));
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.t === "hello") { conn.mac = m.mac; setState(m.mac ? "auth" : "nomac"); }
    else if (m.t === "ready") {
      if (m.resume) setKey(m.resume);
      conn.ready = true; conn.retry = 0; setState("ok"); emit("ready"); api("lang").then(useLang).catch(() => {});
    }
    else if (m.t === "denied") { conn.ready = false; conn.why = m.why || null; if (m.why === "out") setKey(null); setState("denied"); }
    else if (m.t === "mac") { conn.mac = m.on; if (!m.on) { conn.ready = false; setState("nomac"); } else if (!conn.ready) setState("auth"); }
    else if (m.t === "res") {
      const w = conn.wait.get(m.id);
      if (w) { conn.wait.delete(m.id); clearTimeout(w.timer); if (!m.error) conn.fresh = Date.now(); m.error ? w.reject(new Error(m.error)) : w.resolve(m.data); }
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

// screen data: load when the connection is ready, on "something changed" events (at most every 0.4 s) and every
// `every` ms
function useLive(load, deps, match, every = 30000) {
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
    const tick = setInterval(() => conn.ready && run(), every);
    return () => { ref.current.alive = false; offs.forEach((f) => f()); clearInterval(tick); clearTimeout(ref.current.timer); };
  }, deps);
  return [data, err, setData];
}

// where you are, for Pult (stage V): the app says "on screen" while it is visible — every 20 s and at once on a change
// (the page's visibility and Telegram's own activated / deactivated). Pult then calls you in the app, not in Telegram
let shownTimer = 0;
const sayShown = () => {
  const on_ = document.visibilityState === "visible" && !(tg && tg.isActive === false);
  if (conn.ready) api("presence", { on: on_ }).catch(() => {});
  clearInterval(shownTimer);
  if (on_) shownTimer = setInterval(() => conn.ready && api("presence", { on: true }).catch(() => {}), 20000);
};
document.addEventListener("visibilitychange", sayShown);
if (tg && tg.onEvent) { tg.onEvent("activated", sayShown); tg.onEvent("deactivated", sayShown); }
on("ready", sayShown);

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
// the board's short time: "now", "12 min", "14:05" today, "yesterday", "18.10" — a row keeps its title on one line
function agoShort(ts) {
  if (!ts) return "";
  const d = toDate(ts), now = new Date(), s = (now - d) / 1000;
  if (s < 60) return t("ago.s.now");
  if (s < 3600) return t("dur.m", { n: Math.floor(s / 60) });
  if (d.toDateString() === now.toDateString()) return hhmm(d);
  if (new Date(now - 86400000).toDateString() === d.toDateString()) return t("ago.s.yesterday");
  return d.toLocaleDateString(locale(), { day: "2-digit", month: "2-digit" });
}
// a duration at a glance: whole hours past the first one ("2 h"), minutes before
const durShort = (sec) => (sec >= 3600 ? t("dur.h", { n: Math.floor(sec / 3600) }) : dur(sec));
// a chip with a running time — "working 14 s", "background 3 min", "running 2 h": all of them one width, whatever
// the time; the text sits over invisible samples of the widest ("working 59 min"), digits tabular
const TIMED = ["st.work", "st.bg.t", "job.running", "st.queue"];
function TimeChip({ cls, text, onClick }) {
  const widest = TIMED.flatMap((k) => [t(k, { dur: t("dur.s", { n: 59 }) }), t(k, { dur: t("dur.m", { n: 59 }) })]);
  return html`<span class=${"chip timer " + cls + (onClick ? " tap" : "")} onClick=${onClick}><span>${text}</span>${widest.map((w) => html`<span class="ghost" aria-hidden="true">${w}</span>`)}</span>`;
}
const workChip = (since, now) => html`<${TimeChip} cls="ok" text=${since ? t("st.work", { dur: durShort(now - since) }) : t("load.st.work")}/>`;
// a message waits for a place among the turns that may run at once (Driven.slot): amber, since when it waits
const queueChip = (since, now) => html`<${TimeChip} cls="warn" text=${t("st.queue", { dur: durShort(now - (since || now)) })}/>`;
// background tasks run, Claude rests: grey, pulsing too — something still goes on
const bgChip = (since, now, onClick) => html`<${TimeChip} cls="mute" text=${since ? t("st.bg.t", { dur: durShort(now - since) }) : t("st.bg")} onClick=${onClick}/>`;
function resetText(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000), left = ts - Date.now() / 1000;
  if (left > 86400) return t("weekdays").split(" ")[d.getDay()] + " " + hhmm(d);
  return t("reset.at", { hm: hhmm(d), left: dur(Math.max(0, left)) });
}
const num = (x, digits) => x.toLocaleString(locale(), { maximumFractionDigits: digits });
const kilo = (n) => (n >= 1e6 ? t("kilo.m", { n: num(n / 1e6, 1) }) : n >= 1000 ? t("kilo.k", { n: Math.round(n / 1000) }) : String(n || 0));
// a short value that a wrapping line keeps whole: "641 MB", "7 min"
const nb = (s) => String(s).replace(/ /g, "\u00a0");
// memory: megabytes up to a gigabyte, then gigabytes with one decimal
const bytes = (b) => nb(b >= 1024 ** 3 ? t("gb", { n: num(b / 1024 ** 3, 1) }) : t("mb", { n: Math.max(0, Math.round((b || 0) / 1024 ** 2)) }));
const pct = (x) => (x >= 10 ? Math.round(x) : num(x || 0, 1)) + "\u00a0%";
const level = (p) => (p >= 90 ? "bad" : p >= 70 ? "warn" : "");
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
// the message field's keys, as in Telegram (the owner's check on the Mac, 2026-10-18): with a real keyboard Enter sends,
// Shift+Enter and Cmd/Ctrl+Enter break the line; on the phone Enter breaks the line and the button sends
const DESKTOP = tg && tg.platform && tg.platform !== "unknown" ? !/^(android|ios)/.test(tg.platform)
  : !!(window.matchMedia && matchMedia("(hover: hover) and (pointer: fine)").matches);
const breakLine = (e, setText) => {           // the browser inserts no newline on Cmd/Ctrl+Enter — do it by hand
  e.preventDefault();
  const el = e.target, s = el.selectionStart, n = el.selectionEnd;
  setText(el.value.slice(0, s) + "\n" + el.value.slice(n));
  requestAnimationFrame(() => { el.setSelectionRange(s + 1, s + 1);
    if (el.rows === 1) { el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 160) + "px"; } });
};
const sendKey = (send, setText) => (e) => {
  if (e.key !== "Enter" || e.isComposing) return;
  if (e.metaKey || e.ctrlKey) breakLine(e, setText);
  else if (DESKTOP && !e.shiftKey && !e.altKey) { e.preventDefault(); send(); }
};
// replace: the screen being left is done with — a form that has started its session — so Back skips it
const go = (h, replace) => { if (replace) { stack[stack.length - 1] = h; location.replace(h); } else location.hash = h; };

// links in Claude's answers open outside, through Telegram, not inside the app
document.addEventListener("click", (e) => {
  const a = e.target.closest && e.target.closest("a[data-ext]");
  if (a) { e.preventDefault(); tg && tg.openLink ? tg.openLink(a.href) : window.open(a.href, "_blank", "noopener"); }
});
// a link to a project file in Claude's words opens it over the screen (stage F5): the session's project, from the
// chat's address or the card's own; inside a file's page the path counts from that file's folder (data-base)
const openFile = (a) => {
  const box = a.closest("[data-sid]");
  const sid = box ? box.dataset.sid : (/^#\/s\/([0-9a-f-]{36})/.exec(location.hash) || [])[1];
  if (sid) emit("file", { sid, p: a.dataset.file, base: (box && box.dataset.base) || "" });
};
document.addEventListener("click", (e) => {
  const a = e.target.closest && e.target.closest("a[data-file]");
  if (a) { e.preventDefault(); openFile(a); }
});
document.addEventListener("keydown", (e) => {
  const a = e.key === "Enter" && e.target.closest && e.target.closest("a[data-file]");
  if (a) { e.preventDefault(); openFile(a); }
});

// ---------- pictures from the phone ----------

// an edit: quarter turns clockwise, mirrored or not (after the turn), the frame in shares of the turned picture, and
// the frame's proportion (pixel width / height, null — free) with the chip that set it
const FULL = { x: 0, y: 0, w: 1, h: 1 };
const PLAIN = { rot: 0, flip: false, cut: FULL, ratio: null, rk: "free" };
const plain = (e) => !e || (!e.rot && !e.flip && !e.cut.x && !e.cut.y && e.cut.w === 1 && e.cut.h === 1);
const loadPic = (file) => new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = no; i.src = URL.createObjectURL(file); });
const turned = (img, e) => (e.rot % 2 ? [img.naturalHeight, img.naturalWidth] : [img.naturalWidth, img.naturalHeight]);
// the picture turned and mirrored, the frame `cut` cut out, at scale k → into canvas c. The browser turns a camera
// photo upright by its EXIF itself, before any of this
function paint(c, img, e, cut, k) {
  const [W, H] = turned(img, e);
  c.width = Math.max(1, Math.round(cut.w * W * k)); c.height = Math.max(1, Math.round(cut.h * H * k));
  const g = c.getContext("2d");
  g.imageSmoothingQuality = "high";
  g.scale(c.width / (cut.w * W), c.height / (cut.h * H));
  g.translate(-cut.x * W, -cut.y * H);
  if (e.flip) { g.translate(W, 0); g.scale(-1, 1); }
  g.translate(W / 2, H / 2); g.rotate(e.rot * Math.PI / 2);
  g.drawImage(img, -img.naturalWidth / 2, -img.naturalHeight / 2);
  return c;
}
// a picture and its edit → a JPEG no longer than 1600 px, as base64: a few hundred kilobytes instead of megabytes.
// Always from the original file: a frame cut out of the shrunk copy would blur the small print
async function bake(file, e, loaded) {
  const img = loaded || await loadPic(file);
  e = e || PLAIN;
  const [W, H] = turned(img, e);
  const c = paint(document.createElement("canvas"), img, e, e.cut, Math.min(1, 1600 / Math.max(e.cut.w * W, e.cut.h * H)));
  if (!loaded) URL.revokeObjectURL(img.src);
  const blob = await new Promise((ok, no) => c.toBlob((b) => (b ? ok(b) : no(new Error("toBlob"))), "image/jpeg", 0.88));
  const url = await new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = no; r.readAsDataURL(blob); });
  return { name: (file.name || "screenshot").replace(/\.[^.]+$/, "") + ".jpg", data: url.split(",")[1], preview: url,
    src: file, edit: plain(e) ? null : e };
}
const MAX_PICS = 3;
// a document from the app goes as it is, through the relay's one message (8 MB with base64): 5 MB in all; bigger files
// go to the project's topic in Telegram (up to 20 MB) — stage F
const DOC_MAX = 5 * 1048576;
const asB64 = (f) => new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1] || ""); r.onerror = no; r.readAsDataURL(f); });
function useAttach() {
  const [files, setFiles] = useState([]);
  const pick = async (e) => {
    const list = [...(e.target.files || [])].slice(0, MAX_PICS - files.length);
    e.target.value = "";
    const out = [];
    let docs = files.reduce((n, f) => n + (f.doc ? f.size : 0), 0);
    for (const f of list) {
      if (/^image\/(jpeg|png|gif|webp|heic|heif)$/.test(f.type)) { try { out.push(await bake(f)); } catch (err) { alertBox(t("attach.failed")); } continue; }
      if (docs + f.size > DOC_MAX) { alertBox(t("attach.big", { name: f.name, mb: num(f.size / 1048576, 1) })); continue; }
      try { out.push({ name: f.name, data: await asB64(f), doc: true, size: f.size }); docs += f.size; } catch (err) { alertBox(t("attach.failed")); }
    }
    setFiles((cur) => cur.concat(out).slice(0, MAX_PICS));
  };
  const edit = (f) => emit("edit", { f, done: (x) => setFiles((cur) => cur.map((y) => (y === f ? x : y))) });
  const drop = (f) => setFiles((cur) => cur.filter((y) => y !== f));
  // a thumbnail opens the pictures on the whole screen, Crop and Remove at the bottom
  const view = (i) => { const pics = files.filter((f) => !f.doc);
    emit("view", { items: pics.map((f) => ({ src: f.preview, f })), at: Math.max(0, pics.indexOf(files[i])), crop: edit, remove: drop }); };
  return { files, pick, view, remove: (i) => setFiles(files.filter((_, k) => k !== i)), clear: () => setFiles([]),
    payload: () => files.map((f) => ({ name: f.name, data: f.data })) };
}
const CLIP = html`<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>`;
// a picture and a file are two pickers, not one. Telegram on Android hands the page's file input to the system as it is
// (onShowFileChooser → createIntent): "pictures" opens the phone's gallery, "any file" its file manager. With one
// "any file" input (0.13.0) the owner's phone came back at once with nothing (2026-10-23: the app off the screen for a
// second), while pictures alone had worked for days. A form shows both buttons; the composer's paperclip opens a menu
// of the two
const PICKERS = [["pic", "image/*", "image"], ["file", undefined, "file"]];
function Attach({ a, disabled, wide }) {
  const off = disabled || a.files.length >= MAX_PICS;
  const [open, setOpen] = useState(false);
  const [show, hide] = useOverlay(open, setOpen);
  const inputs = useRef({});
  if (wide) return html`<div class="attach-row">${PICKERS.map(([k, accept, icon]) => html`<label key=${k} class=${"clip wide" + (off ? " off" : "")}>
    ${k === "pic" ? ic(icon, 20) : CLIP}<span>${t("attach." + k)}</span>
    <input type="file" accept=${accept} multiple disabled=${off} onChange=${a.pick}/></label>`)}</div>`;
  // the inputs stay out of the menu: it closes as the picker opens, and the files come back to an input still there
  const choose = (k) => { const el = inputs.current[k]; hide(); if (el) el.click(); };
  return html`<span class="attach">
    ${PICKERS.map(([k, accept]) => html`<input key=${k} ref=${(el) => { inputs.current[k] = el; }} type="file" accept=${accept} multiple disabled=${off} onChange=${a.pick}/>`)}
    <button type="button" class=${"clip" + (off ? " off" : "")} aria-label=${t("attach")} disabled=${off} onClick=${open ? hide : show}>${CLIP}</button>
    ${open && html`<div class="backdrop" onClick=${hide}></div><div class="card attach-menu">
      ${PICKERS.map(([k, , icon]) => html`<button key=${k} class="opt" onClick=${() => choose(k)}>${ic(icon, 18)}<span>${t("attach." + k)}</span></button>`)}</div>`}</span>`;
}
function Thumbs({ a }) {
  return a.files.length ? html`<div class="thumbs">${a.files.map((f, i) => f.doc ? html`<div class="thumb doc" key=${i}>
    <span class="doc-n">${ic("file", 14)} ${f.name}</span>
    <button class="thumb-x" aria-label=${t("attach.remove")} onClick=${() => a.remove(i)}>${ic("x", 14)}</button></div>` : html`<div class="thumb" key=${i}>
    <button class="thumb-view" aria-label=${t("view.open")} onClick=${() => a.view(i)}><img src=${f.preview} alt=""/></button>
    <button class="thumb-x" aria-label=${t("attach.remove")} onClick=${() => a.remove(i)}>${ic("x", 14)}</button></div>`)}</div>` : "";
}

// ---------- the picture editor: turn, mirror, cut ----------

// Telegram's own editor is Telegram's: a Mini App gets a plain file picker. So the app has its own, like Telegram's
// crop screen: the whole picture, a frame with corners, the proportions under it. One finger: no pinch
const RATIOS = [["free"], ["orig"], ["1:1", 1], ["4:3", 4 / 3], ["16:9", 16 / 9]];
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
// the frame after dragging zone z (a corner, a side or "move") by dx, dy shares of the picture; q — the frame's
// width / height in shares while its proportion is fixed (then only corners pull); mw, mh — the smallest frame
function reframe(c, z, dx, dy, q, mw, mh) {
  if (z === "move") return { ...c, x: clamp(c.x + dx, 0, 1 - c.w), y: clamp(c.y + dy, 0, 1 - c.h) };
  const E = z.includes("e"), Wt = z.includes("w"), S = z.includes("s"), N = z.includes("n");
  const ax = E ? c.x : c.x + c.w, ay = S ? c.y : c.y + c.h;          // the side the finger isn't on stays put
  const maxW = E ? 1 - c.x : Wt ? ax : 1, maxH = S ? 1 - c.y : N ? ay : 1;
  let w = E ? c.w + dx : Wt ? c.w - dx : c.w, h = S ? c.h + dy : N ? c.h - dy : c.h;
  if (q) {
    w = Math.abs(w - c.w) >= Math.abs(h * q - c.w) ? w : h * q;      // whichever way the finger went further
    w = clamp(w, Math.max(mw, mh * q), Math.min(maxW, maxH * q));
    h = w / q;
  } else { w = clamp(w, mw, maxW); h = clamp(h, mh, maxH); }
  return { x: E ? ax : Wt ? ax - w : c.x, y: S ? ay : N ? ay - h : c.y, w, h };
}
// the display turned a quarter left / mirrored: the frame goes with the picture. A turn left of a mirrored picture is
// the mirror of a turn right
const turnLeft = (e) => ({ ...e, rot: (e.rot + (e.flip ? 1 : 3)) % 4, ratio: e.ratio && 1 / e.ratio,
  cut: { x: e.cut.y, y: 1 - e.cut.x - e.cut.w, w: e.cut.h, h: e.cut.w } });
const mirror = (e) => ({ ...e, flip: !e.flip, cut: { ...e.cut, x: 1 - e.cut.x - e.cut.w } });
const tick = () => tg && tg.HapticFeedback && tg.HapticFeedback.selectionChanged();
const ROT = html`<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="10" width="11" height="11" rx="2"/><path d="M8 6.5h5.5a5.5 5.5 0 0 1 5.5 5.5v1.5"/><path d="M10.5 4 8 6.5 10.5 9"/></svg>`;
const FLIP = html`<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v2M12 9.5v2M12 16v2M12 21.5v.5"/><path d="M9 6 3 18h6z"/><path d="M15 6l6 12h-6z" fill="currentColor"/></svg>`;

function Editor({ f, onDone, onClose }) {
  const [img, setImg] = useState(null);
  const [e, setE] = useState(f.edit || PLAIN);
  const [box, setBox] = useState(null);
  const [moving, setMoving] = useState(false);
  const [busy, setBusy] = useState(false);
  const stage = useRef(null), cv = useRef(null), drag = useRef(null);
  useEffect(() => {
    let alive = true, got = null;
    loadPic(f.src).then((i) => { got = i; if (alive) setImg(i); else URL.revokeObjectURL(i.src); })
      .catch(() => { if (alive) { alertBox(t("attach.failed")); onClose(); } });
    const fit = () => { const r = stage.current && stage.current.getBoundingClientRect(); if (r) setBox({ w: r.width, h: r.height }); };
    fit(); addEventListener("resize", fit);
    return () => { alive = false; removeEventListener("resize", fit); if (got) URL.revokeObjectURL(got.src); };
  }, []);
  const PAD = 24;                    // room around the picture for the corners
  let v = null;
  if (img && box) {
    const [W, H] = turned(img, e);
    const s = Math.min((box.w - 2 * PAD) / W, (box.h - 2 * PAD) / H);
    v = { W, H, s, dw: W * s, dh: H * s, ox: (box.w - W * s) / 2, oy: (box.h - H * s) / 2 };
  }
  useEffect(() => { if (v && cv.current) paint(cv.current, img, e, FULL, v.s * Math.min(3, devicePixelRatio || 1)); },
    [img, e.rot, e.flip, v && v.dw, v && v.dh]);
  const fr = v && { l: v.ox + e.cut.x * v.dw, t: v.oy + e.cut.y * v.dh, w: e.cut.w * v.dw, h: e.cut.h * v.dh };
  const q = v && e.ratio ? e.ratio * v.H / v.W : null;
  // what a finger at x, y (px in the stage) takes: a corner, a side (only while free), the frame itself or nothing
  const zone = (x, y) => {
    const C = 28, r = fr.l + fr.w, b = fr.t + fr.h;
    const near = (d, inner) => d > -C && d < Math.min(C, inner);   // d: how far inside the frame from that side
    const nx = near(x - fr.l, fr.w / 3) ? "w" : near(r - x, fr.w / 3) ? "e" : "";
    const ny = near(y - fr.t, fr.h / 3) ? "n" : near(b - y, fr.h / 3) ? "s" : "";
    if (nx && ny) return ny + nx;
    if (!q && nx && y > fr.t && y < b) return nx;
    if (!q && ny && x > fr.l && x < r) return ny;
    return x > fr.l && x < r && y > fr.t && y < b ? "move" : null;
  };
  const at = (ev) => { const r = stage.current.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; };
  const down = (ev) => {
    if (drag.current || !v || busy) return;
    const [x, y] = at(ev), z = zone(x, y);
    if (!z) return;
    try { stage.current.setPointerCapture(ev.pointerId); } catch (err) {}
    drag.current = { id: ev.pointerId, z, x, y, cut: e.cut };
    setMoving(true);
  };
  const move = (ev) => {
    const d = drag.current;
    if (!d || ev.pointerId !== d.id) return;
    const [x, y] = at(ev);
    const cut = reframe(d.cut, d.z, (x - d.x) / v.dw, (y - d.y) / v.dh, q, Math.min(1, 48 / v.dw), Math.min(1, 48 / v.dh));
    setE((cur) => ({ ...cur, cut }));
  };
  // where the finger lifted counts too: the last move may come merged into the lift
  const up = (ev) => {
    if (!drag.current || ev.pointerId !== drag.current.id) return;
    if (ev.type === "pointerup") move(ev);
    drag.current = null; setMoving(false);
  };
  // a proportion: the largest frame of it in the picture, around the frame's centre; 4:3 and 16:9 stand upright
  // while the frame does
  const upright = v && e.cut.w * v.W < e.cut.h * v.H;
  const setRatio = (k, R) => {
    tick();
    if (k === "free") return setE({ ...e, ratio: null, rk: k });
    if (k === "orig") return setE({ ...e, ratio: v.W / v.H, rk: k, cut: FULL });
    const ratio = upright ? 1 / R : R, qq = ratio * v.H / v.W;
    let w = Math.min(1, qq), h = w / qq;
    if (h > 1) { h = 1; w = qq; }
    const cx = e.cut.x + e.cut.w / 2, cy = e.cut.y + e.cut.h / 2;
    setE({ ...e, ratio, rk: k, cut: { x: clamp(cx - w / 2, 0, 1 - w), y: clamp(cy - h / 2, 0, 1 - h), w, h } });
  };
  const label = (k) => (k === "free" ? t("edit.free") : k === "orig" ? t("edit.orig") : upright ? k.split(":").reverse().join(":") : k);
  const done = async () => {
    setBusy(true);
    try { onDone(await bake(f.src, e, img)); } catch (err) { alertBox(t("attach.failed")); setBusy(false); }
  };
  return html`<div class="ed" role="dialog" aria-label=${t("edit.title")}>
    <div class="ed-top">${!plain(e) && html`<button class="ed-b" onClick=${() => { tick(); setE(PLAIN); }}>${t("edit.reset")}</button>`}</div>
    <div class="ed-stage" ref=${stage} onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${up}>
      ${v && html`<canvas ref=${cv} style=${{ left: v.ox + "px", top: v.oy + "px", width: v.dw + "px", height: v.dh + "px" }}/>
        <div class=${"ed-frame" + (moving ? " moving" : "")} style=${{ left: fr.l + "px", top: fr.t + "px", width: fr.w + "px", height: fr.h + "px" }}>
          <i class="nw"></i><i class="ne"></i><i class="sw"></i><i class="se"></i></div>`}
    </div>
    <div class="ed-ratios">${RATIOS.map(([k, R]) => html`<button key=${k} class=${"ed-r" + (e.rk === k ? " on" : "")} disabled=${!v}
      onClick=${() => setRatio(k, R)}>${label(k)}</button>`)}</div>
    <div class="ed-bar"><button class="ed-b" onClick=${onClose}>${t("edit.cancel")}</button>
      <button class="ed-i" aria-label=${t("edit.rotate")} disabled=${!v} onClick=${() => { tick(); setE(turnLeft(e)); }}>${ROT}</button>
      <button class="ed-i" aria-label=${t("edit.flip")} disabled=${!v} onClick=${() => { tick(); setE(mirror(e)); }}>${FLIP}</button>
      <button class="ed-b ok" disabled=${busy || !v} onClick=${done}>${t("done")}</button></div>
  </div>`;
}
// one editor for the whole app, over everything: the composer is its own layer and would hold it under the banner.
// Opened through the history like the other overlays — Back is "Cancel"; while it is open Telegram doesn't fold the
// window on a swipe down, or pulling the frame down would close the app
function EditHost() {
  const [job, setJob] = useState(null);
  const [show, hide] = useOverlay(!!job, (open) => { if (!open) setJob(null); });
  useEffect(() => on("edit", (x) => { setJob(x); show(); }), [show]);
  useNoFold(!!job);
  return job ? html`<${Editor} f=${job.f} onDone=${(x) => { job.done(x); haptic("success"); hide(); }} onClose=${hide}/>` : "";
}
// while a layer that takes the finger is open, Telegram doesn't fold the window on a swipe down
function useNoFold(open) {
  useEffect(() => {
    if (!open || !tg || !tg.disableVerticalSwipes || !(tg.isVersionAtLeast && tg.isVersionAtLeast("7.7"))) return;
    const was = tg.isVerticalSwipesEnabled;
    tg.disableVerticalSwipes();
    return () => { if (was) tg.enableVerticalSwipes(); };
  }, [open]);
}

// ---------- a picture on the whole screen ----------

// as in Telegram: a tap on a picture in the chat, or on a thumbnail before sending, opens it over everything. Two
// fingers or a double tap zoom, one finger drags the zoomed picture; at its own size a swipe sideways goes to the next
// picture and a swipe up or down closes, as does Back; a single tap hides the bars. Before sending the bottom bar has
// Crop (the editor) and Remove
const ZOOM_MAX = 5, ZOOM_TAP = 2.5, V_GAP = 16;
const CROP = html`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/></svg>`;
const TRASH = html`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 6h17M9 6V4h6v2M6 6l1 14a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-14"/></svg>`;
const inboxSrc = (a) => api("inbox", a.pkey ? { name: a.name, pkey: a.pkey } : { name: a.name })
  .then((d) => "data:image/" + (d.kind === "jpg" ? "jpeg" : d.kind) + ";base64," + d.data);
const dist = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1]);
const midOf = (p, q) => [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
const UNZOOMED = { s: 1, x: 0, y: 0 };

// job: items [{src} | {a: an inbox picture}, each with f — the attachment, before sending], at, crop(f), remove(f).
// then(fn) closes the viewer and runs fn once it is out of the history (Crop opens the editor in its place)
function Viewer({ job, onClose, then }) {
  const [items, setItems] = useState(() => job.items.map((x) => ({ ...x })));
  const [at, setAt] = useState(job.at || 0);
  const [box, setBox] = useState({ l: 0, t: 0, w: innerWidth, h: innerHeight });
  const [z, setZ] = useState(UNZOOMED);     // the current picture: zoom, and its middle's shift from the screen's, px
  const [pull, setPull] = useState({ x: 0, y: 0 });   // unzoomed, the finger pulls it sideways (next) or up/down (close)
  const [anim, setAnim] = useState(false);
  const [bare, setBare] = useState(false);
  const root = useRef(null), zr = useRef(UNZOOMED), g = useRef({ pts: new Map() });
  const put = (v) => { zr.current = v; setZ(v); };
  useEffect(() => {
    const fit = () => { const r = root.current && root.current.getBoundingClientRect(); if (r) setBox({ l: r.left, t: r.top, w: r.width, h: r.height }); };
    fit(); addEventListener("resize", fit);
    return () => { removeEventListener("resize", fit); clearTimeout(g.current.tap); };
  }, []);
  useEffect(() => {                      // a computer's keyboard: Esc closes, the arrows go through the pictures
    const key = (e) => { if (e.key === "Escape") onClose(); else if (e.key === "ArrowLeft") goTo(at - 1); else if (e.key === "ArrowRight") goTo(at + 1); };
    addEventListener("keydown", key);
    return () => removeEventListener("keydown", key);
  });
  // the pictures from the chat come from the computer: this one and its neighbours
  useEffect(() => {
    let alive = true;
    items.forEach((x, k) => {
      if (x.src || !x.a || x.asked || Math.abs(k - at) > 1) return;
      x.asked = true;
      inboxSrc(x.a).then((src) => alive && setItems((cur) => cur.map((y) => (y.a === x.a ? { ...y, src } : y)))).catch(() => {});
    });
    return () => { alive = false; };
  }, [at, items.length]);
  // a picture fills the screen by its longer side, small ones too
  const size = (x) => { if (!x || !x.nat) return null; const f = Math.min(box.w / x.nat[0], box.h / x.nat[1]); return [x.nat[0] * f, x.nat[1] * f]; };
  const held = (v) => {                  // a zoomed picture's edges don't leave the screen's
    const d = size(items[at]);
    if (!d || v.s <= 1) return UNZOOMED;
    const mx = Math.max(0, (d[0] * v.s - box.w) / 2), my = Math.max(0, (d[1] * v.s - box.h) / 2);
    return { s: v.s, x: clamp(v.x, -mx, mx), y: clamp(v.y, -my, my) };
  };
  const zoomAt = (p, s) => { const c = zr.current; return held({ s, x: p[0] - (p[0] - c.x) * s / c.s, y: p[1] - (p[1] - c.y) * s / c.s }); };
  const goTo = (k) => { setAnim(true); setPull({ x: 0, y: 0 }); if (k < 0 || k >= items.length || k === at) return; setAt(k); put(UNZOOMED); };
  const pos = (ev) => [ev.clientX - box.l - box.w / 2, ev.clientY - box.t - box.h / 2];     // from the screen's middle
  const down = (ev) => {
    if (ev.target.closest("button")) return;
    const G = g.current;
    try { root.current.setPointerCapture(ev.pointerId); } catch (err) {}
    G.pts.set(ev.pointerId, pos(ev));
    setAnim(false);
    if (G.pts.size === 1) Object.assign(G, { mode: null, p0: pos(ev), t0: Date.now(), z0: zr.current, moved: false });
    else if (G.pts.size === 2) {
      const [p, q] = [...G.pts.values()];
      Object.assign(G, { mode: "pinch", d0: dist(p, q) || 1, m0: midOf(p, q), z0: zr.current, moved: true });
      setPull({ x: 0, y: 0 });
    }
  };
  const move = (ev) => {
    const G = g.current;
    if (!G.pts.has(ev.pointerId)) return;
    G.pts.set(ev.pointerId, pos(ev));
    if (G.mode === "pinch") {
      if (G.pts.size < 2) return;
      const [p, q] = [...G.pts.values()], m = midOf(p, q), z0 = G.z0;
      const s = clamp(z0.s * dist(p, q) / G.d0, 0.6, ZOOM_MAX);
      put({ s, x: m[0] - (G.m0[0] - z0.x) * s / z0.s, y: m[1] - (G.m0[1] - z0.y) * s / z0.s });
      return;
    }
    if (G.pts.size !== 1) return;
    const p = pos(ev), dx = p[0] - G.p0[0], dy = p[1] - G.p0[1];
    if (!G.mode) {
      if (Math.hypot(dx, dy) < 8) return;
      G.moved = true;
      G.mode = zr.current.s > 1.01 ? "pan" : Math.abs(dx) > Math.abs(dy) ? "page" : "close";
    }
    if (G.mode === "pan") put(held({ ...G.z0, x: G.z0.x + dx, y: G.z0.y + dy }));
    else if (G.mode === "page") setPull({ x: (at === 0 && dx > 0) || (at === items.length - 1 && dx < 0) ? dx / 3 : dx, y: 0 });
    else setPull({ x: 0, y: dy });
  };
  const up = (ev) => {
    const G = g.current;
    if (!G.pts.has(ev.pointerId)) return;
    G.pts.delete(ev.pointerId);
    if (G.mode === "pinch") {
      if (G.pts.size === 1) { Object.assign(G, { mode: "pan", p0: [...G.pts.values()][0], z0: zr.current }); return; }
      if (G.pts.size) return;
      setAnim(true); put(held(zr.current)); G.mode = null;
      return;
    }
    if (G.pts.size) return;
    const p = pos(ev), dx = p[0] - G.p0[0], dy = p[1] - G.p0[1], quick = Date.now() - G.t0 < 250;
    if (G.mode === "pan") { setAnim(true); put(held(zr.current)); }      // the last finger of a pinch: shrunk springs back
    else if (G.mode === "page") goTo(dx < -box.w / 5 || (quick && dx < -40) ? at + 1 : dx > box.w / 5 || (quick && dx > 40) ? at - 1 : at);
    else if (G.mode === "close") { if (Math.abs(dy) > 90 || (quick && Math.abs(dy) > 40)) onClose(); else { setAnim(true); setPull({ x: 0, y: 0 }); } }
    else if (!G.moved) {
      const last = G.last;
      if (last && Date.now() - last.t < 300 && dist(p, last.p) < 30) {      // a double tap: zoom in there, or back out
        clearTimeout(G.tap); G.last = null; setAnim(true);
        put(zr.current.s > 1.01 ? UNZOOMED : zoomAt(p, ZOOM_TAP));
      } else {
        G.last = { t: Date.now(), p };
        G.tap = setTimeout(() => { G.last = null; setBare((b) => !b); }, 300);
      }
    }
    G.mode = null;
  };
  const wheel = (ev) => { ev.preventDefault(); setAnim(false); put(zoomAt(pos(ev), clamp(zr.current.s * Math.exp(-ev.deltaY / 300), 1, ZOOM_MAX))); };
  const drop = () => {
    const x = items[at];
    job.remove(x.f);
    if (items.length === 1) return onClose();
    setItems(items.filter((y) => y !== x)); setAt(Math.min(at, items.length - 2)); put(UNZOOMED);
  };
  const step = box.w + V_GAP;
  return html`<div ref=${root} class=${"viewer" + (anim ? " anim" : "") + (bare ? " bare" : "")} role="dialog" aria-label=${t("view.title")}
    onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${up} onWheel=${wheel}>
    <div class="v-bg" style=${{ opacity: 1 - Math.min(0.8, Math.abs(pull.y) / 300) }}></div>
    ${items.map((x, k) => {
      if (Math.abs(k - at) > 1) return "";
      const d = size(x), cur = k === at;
      return html`<div key=${x.src || (x.a ? x.a.name : "wait")} class="v-pic" style=${{ transform: "translate3d(" + ((k - at) * step + pull.x) + "px," + (cur ? pull.y : 0) + "px,0)" }}>
        ${x.src ? html`<img src=${x.src} alt="" draggable="false" onLoad=${(e) => { const n = [e.target.naturalWidth, e.target.naturalHeight]; setItems((all) => all.map((y) => (y === x ? { ...y, nat: n } : y))); }}
          style=${d ? { width: d[0] + "px", height: d[1] + "px", transform: cur ? "translate(" + z.x + "px," + z.y + "px) scale(" + z.s + ")" : "" } : { visibility: "hidden" }}/>`
          : html`<span class="v-wait">${ic("image", 40)}</span>`}</div>`;
    })}
    <div class="v-top"><button class="v-b" aria-label=${t("close")} onClick=${onClose}>${ic("x", 24)}</button>
      ${items.length > 1 ? html`<span class="v-n">${at + 1} / ${items.length}</span>` : ""}</div>
    ${job.crop && html`<div class="v-bar">
      <button class="v-b" onClick=${() => { const f = items[at].f; then(() => job.crop(f)); }}>${CROP}<span>${t("view.crop")}</span></button>
      <button class="v-b" onClick=${drop}>${TRASH}<span>${t("attach.remove")}</span></button></div>`}
    ${job.send && html`<div class="v-bar"><button class="v-b" disabled=${!items[at].src} onClick=${job.send}>${ic("send", 22)}<span>${t("fv.send")}</span></button></div>`}
  </div>`;
}
// one viewer for the whole app, over everything, like the editor; opened through the history — Back closes it
function ViewHost() {
  const [job, setJob] = useState(null);
  const after = useRef(null);
  const [show, hide] = useOverlay(!!job, (open) => { if (!open) setJob(null); });
  useEffect(() => on("view", (x) => { setJob(x); show(); }), [show]);
  useEffect(() => { if (!job && after.current) { const fn = after.current; after.current = null; fn(); } }, [job]);
  useNoFold(!!job);
  return job ? html`<${Viewer} job=${job} onClose=${hide} then=${(fn) => { after.current = fn; hide(); }}/>` : "";
}

// ---------- voice from the phone ----------

// MediaRecorder: webm/opus on Android and in Chrome, m4a in Safari; 32 kbit/s is plenty for speech. The words come
// back from the computer (Groq) and land in the message field — to be checked and sent with one more tap
const REC_MIME = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus", "audio/ogg"];
const REC_MAX = 5 * 60;      // s; the recording stops by itself
// Whisper drops the first syllable when a recording starts quietly (tests/probe_stt.py, 2026-10-23), while a pause
// before the words does no harm. So the phone's own sound processing is off — its gain control starts low and ramps
// up, its noise suppression eats soft starts of words, Whisper copes with noise itself — and "speak" (a buzz, the red
// dot) comes only once sound really flows, not when the button is tapped
const REC_WAIT = 1500;       // ms; no sound by then — "speak" anyway (the level meter may not work here)
const REC_TAIL = 300;        // ms still recorded after "Stop": the last word isn't cut
// a window of ~43 ms louder than VOICE_DB (dBFS) counts as voice; fewer than VOICE_MIN of them — nothing was said,
// and the recording isn't sent: over silence Whisper makes up film subtitle credits
const VOICE_DB = -50, VOICE_MIN = 3;
const MIC_AUDIO = { echoCancellation: false, noiseSuppression: false, autoGainControl: false };
// Telegram on Android asks "allow the microphone?" at every new getUserMedia, even one already allowed in this very
// session (the owner saw it at each tap, 2026-10-18). So the microphone is asked for once and kept while the app is on
// the screen: recordings reuse the stream, muted in between; it is let go when the app goes to the background or after
// MIC_HOLD without a recording — the next tap asks again, once
// Telegram's own code (DrKLO/Telegram 12.10.4, BotWebViewContainer.onPermissionRequest) asks at every request and keeps
// nothing, and the owner's visits are 20–60 s: so the question comes at almost every first recording of a visit. The
// owner keeps it so (decision Q58) rather than hold the microphone in the background
const MIC_HOLD = 10 * 60 * 1000;
let mic = null, micTimer = 0;
const dropMic = () => { clearTimeout(micTimer); meterOff(); if (actx && actx.state === "running") actx.suspend().catch(() => {}); if (mic) { mic.getTracks().forEach((tr) => tr.stop()); mic = null; } };
// → [the stream, ms the phone took when it was asked anew (the owner's answer to Telegram's question in it) or null]
async function getMic() {
  clearTimeout(micTimer);
  if (mic && mic.getTracks().some((tr) => tr.readyState === "live")) { mic.getTracks().forEach((tr) => { tr.enabled = true; }); return [mic, null]; }
  const t0 = Date.now();
  mic = await navigator.mediaDevices.getUserMedia({ audio: MIC_AUDIO });
  return [mic, Date.now() - t0];
}
const restMic = () => { if (mic) mic.getTracks().forEach((tr) => { tr.enabled = false; }); clearTimeout(micTimer); micTimer = setTimeout(dropMic, MIC_HOLD); };
document.addEventListener("visibilitychange", () => { if (document.hidden) dropMic(); });
// the level meter: one AudioContext for the page, an analyser on the current microphone. Nothing is played — the
// meter only tells when sound starts to flow, whether there was a voice, and how loud (for the computer's log)
let actx = null, meter = null;
function audioCtx() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!actx && AC) { try { actx = new AC(); } catch (e) { actx = null; } }
  if (actx && actx.state === "suspended") actx.resume().catch(() => {});
  return actx;
}
function meterOn(stream) {
  if (meter && meter.stream === stream) return meter;
  meterOff();
  const ac = audioCtx();
  if (!ac) return null;
  try {
    const src = ac.createMediaStreamSource(stream), an = ac.createAnalyser();
    an.fftSize = 2048;
    src.connect(an);
    meter = { stream, src, an, buf: new Float32Array(an.fftSize) };
  } catch (e) { meter = null; }
  return meter;
}
function meterOff() { if (meter) { try { meter.src.disconnect(); } catch (e) { /* already gone */ } meter = null; } }
// the last ~43 ms: the loudest sample (0 while the microphone is still waking up) and the level, dBFS
function loudness(m) {
  m.an.getFloatTimeDomainData(m.buf);
  let peak = 0, sum = 0;
  for (const x of m.buf) { const a = Math.abs(x); if (a > peak) peak = a; sum += x * x; }
  return { peak, db: 20 * Math.log10(Math.sqrt(sum / m.buf.length) || 1e-10) };
}
// the recording's figures ride along for the computer's log; a computer before 0.14.2 refuses a field it doesn't
// know — then once more without them, and not again until the app is reopened
let sttNotes = true;
async function sttSend(data, mime, notes) {
  if (sttNotes) {
    try { return await api("stt", { data, mime, notes }); }
    catch (e) { if (!/unexpected keyword/.test(e.message)) throw e; sttNotes = false; }
  }
  return api("stt", { data, mime });
}
function useRecorder(onText) {
  const [st, setSt] = useState("idle");           // idle | wait (the microphone wakes up) | rec | busy
  const [secs, setSecs] = useState(0);
  const cur = useRef(null);
  const dot = useRef(null);                       // the red dot: it breathes with the voice
  const stop = () => {
    const x = cur.current;
    if (!x || x.stopping || x.rec.state === "inactive") return;
    x.stopping = true;
    if (!x.live) return x.rec.stop();
    setSt("busy");
    setTimeout(() => { if (x.rec.state !== "inactive") x.rec.stop(); }, REC_TAIL);
  };
  const toggle = async () => {
    if (st !== "idle") return stop();
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder)) return alertBox(t("rec.unsupported"));
    audioCtx();                                   // within the tap itself: a browser lets audio start only from one
    setSt("wait");
    let stream, asked;
    try { [stream, asked] = await getMic(); } catch (e) { dropMic(); setSt("idle"); return alertBox(t("rec.denied")); }
    // the wait for sound counts from the microphone given, not from the tap: Telegram's question took its own time,
    // and "speak" right after it, before sound flows, was what lost the first syllable
    const t0 = Date.now();
    const mime = REC_MIME.find((m) => MediaRecorder.isTypeSupported(m)) || "";
    let rec;
    try { rec = new MediaRecorder(stream, Object.assign({ audioBitsPerSecond: 32000 }, mime ? { mimeType: mime } : {})); }
    catch (e) { dropMic(); setSt("idle"); return alertBox(t("rec.unsupported")); }
    const m = meterOn(stream), chunks = [];
    const x = (cur.current = { rec, timer: 0, started: false, stopping: false, live: 0, heard: false, secs: 0,
                               loud: 0, voice: null, first: -200, peak: -200 });
    const goLive = (heard) => {
      x.live = Date.now(); x.heard = heard;
      setSt("rec"); setSecs(0);
      if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("medium");
    };
    rec.onstart = () => { x.started = true; };
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = async () => {
      clearInterval(x.timer); restMic(); cur.current = null;
      if (dot.current) { dot.current.style.transform = ""; dot.current.style.animation = ""; }
      const blob = new Blob(chunks, { type: rec.mimeType || mime || "audio/webm" });
      if (blob.size < 1000 || !x.live) { setSt("idle"); setSecs(0); return alertBox(t("rec.empty")); }
      if (x.heard && x.loud < VOICE_MIN) { setSt("idle"); setSecs(0); return alertBox(t("rec.silent")); }
      setSt("busy");
      const r1 = (v) => Math.round(v * 10) / 10;
      const notes = { secs: r1((Date.now() - x.live) / 1000) };
      if (asked !== null) notes.asked = asked;
      if (x.heard) Object.assign(notes, { ready: x.live - t0, voice: x.voice, first: r1(x.first), peak: r1(x.peak) });
      try {
        const url = await new Promise((ok, no) => { const f = new FileReader(); f.onload = () => ok(f.result); f.onerror = no; f.readAsDataURL(blob); });
        const res = await sttSend(url.split(",")[1], blob.type, notes);
        if (res.text) { onText(res.text); haptic("success"); }
      } catch (e) { alertBox(e.message); }
      setSt("idle"); setSecs(0);
    };
    x.timer = setInterval(() => {
      const now = Date.now();
      if (m) {
        const { peak, db } = loudness(m);
        if (!x.live && x.started && peak > 1e-5) goLive(true);
        if (x.heard) {
          if (db > x.peak) x.peak = db;
          if (now - x.live <= 1000 && db > x.first) x.first = db;
          if (db > VOICE_DB) { x.loud++; if (x.voice === null) x.voice = now - x.live; }
          if (dot.current) {                      // breathes with the voice instead of blinking
            dot.current.style.animation = "none";
            dot.current.style.transform = "scale(" + (1 + Math.min(0.8, Math.max(0, db - VOICE_DB) / 40)).toFixed(2) + ")";
          }
        }
      }
      if (!x.live && now - t0 > REC_WAIT) goLive(false);
      if (!x.live) return;
      const s = Math.floor((now - x.live) / 1000);
      if (s !== x.secs) { x.secs = s; setSecs(s); }
      if (s >= REC_MAX) stop();
    }, 50);
    rec.start(1000);
  };
  useEffect(() => () => { const x = cur.current; if (x) { clearInterval(x.timer); try { x.rec.stop(); } catch (e) { /* already gone */ } } }, []);
  return { st, secs, toggle, dot };
}
const MIC = html`<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/></svg>`;
function Mic({ v, disabled, wide }) {
  const on = v.st === "rec" || v.st === "wait";
  const label = v.st === "wait" ? t("rec.wait") : v.st === "rec" ? t("rec.stop") : v.st === "busy" ? t("rec.busy") : t("rec");
  const cls = "clip mic" + (wide ? " wide" : "") + (on ? " rec" : "") + (v.st === "wait" ? " wait" : "") + (disabled || v.st === "busy" ? " off" : "");
  return html`<button type="button" class=${cls} aria-label=${label} disabled=${disabled || v.st === "busy"} onClick=${v.toggle}>
    ${on ? html`<span class="dot" ref=${v.dot}></span><span class="secs">${v.st === "wait" ? "…" : Math.floor(v.secs / 60) + ":" + String(v.secs % 60).padStart(2, "0")}</span>` : MIC}
    ${wide ? html`<span>${label}</span>` : ""}</button>`;
}

// a picture the owner sent (from Telegram or the app): the chat shows it, not the path Claude got
// all — the pictures of the same message: the viewer goes through them
function Pic({ a, all }) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    if (!a.image || !a.inbox) return;
    let alive = true;
    inboxSrc(a).then((s) => alive && setSrc(s)).catch(() => {});
    return () => { alive = false; };
  }, [a.name]);
  const open = () => { const pics = (all || [a]).filter((x) => x.image && x.inbox);
    emit("view", { items: pics.map((x) => (x === a ? { a: x, src } : { a: x })), at: Math.max(0, pics.indexOf(a)) }); };
  if (src) return html`<img class="att" src=${src} alt="" onClick=${open}/>`;
  return html`<span class="att-chip">${ic(a.image ? "image" : "file", 14)} ${a.name.split("/").pop() || t("att.file")}</span>`;
}

// the model of a session from Telegram: aliases Claude Code accepts, plus whatever the settings say
const MODELS = [["", "model.default"], ["fable", "Fable"], ["opus", "Opus"], ["sonnet", "Sonnet"], ["haiku", "Haiku"]];
const EFFORTS = ["", "low", "medium", "high", "xhigh", "max"];
// the model and the effort for a new session, in words: what is picked, the rest from Pult's default (Settings);
// nothing in either — as Claude Code's own settings say
const choiceText = (model, effort, def) => {
  const m = model || (def && def.model), e = effort || (def && def.effort);
  return !m && !e ? t("pick.as.cc") : [m ? modelName(m) : t("pick.model.def"), e ? effortName(e) : t("pick.effort.def")].join(" · ");
};
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
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick"><div class="q-t pick-h">${title}<button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></div>
    ${lines.map((l, i) => html`<p class="sheet-p" key=${i}>${l}</p>`)}</div>`;
}

// the model and the effort of a session, side by side; each tap switches one of them and the menu stays open
function ModelPick({ sid, choice, now, driven, tab, dflt, canModel, canEffort, onDone, onClose }) {
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
  const notes = [driven ? t("model.next") : tab ? t("model.next") + " " + t("model.tab") : t("model.later"),
    t(dflt && (dflt.model || dflt.effort) ? "pick.default.pult" : "pick.default.note"),
    tab && canEffort ? t("effort.tab") : ""];
  const why = tab && !canModel ? t("model.reload") : tab && !canEffort ? t("effort.reload") : "";
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick"><div class="q-t pick-h">${t("model.pick")}<button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></div>
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
  if (stack[stack.length - 1] === location.hash) return;      // replaced in place (go with replace, back to home)
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
    : start === "new" ? "#/new" : start === "usage" ? "#/usage" : start === "settings" ? "#/settings" : start === "projects" ? "#/projects"
    : start === "load" ? "#/load" : start === "newproject" ? "#/newproject"
    : /^f_[0-9a-f-]{36}_\d+$/.test(start) ? "#/f/" + start.slice(2, 38) + "?t=" + start.slice(39) : null;
  if (h) { history.replaceState(null, "", h); stack[0] = h; }
}

// ---------- cards: question, permission request, plan ----------

// a card answered here keeps "✓ Answer sent" RCPT_MS, a bar running out under it, though the computer drops the
// request at once (the owner didn't see the line at all, 2026-10-24)
const RCPT_MS = 3000;
const answeredAt = new Map();        // rid → when it was answered here
// what to show: the computer's list, and the requests answered here less than RCPT_MS ago in their old places;
// key — a row's request id (other rows never linger)
function useRcpt(list, key = (r) => r.rid) {
  const prev = useRef([]);
  const [, bump] = useState(0);
  const now = Date.now(), ids = new Set(list.map(key)), out = list.slice();
  prev.current.forEach((r, i) => { if (!ids.has(key(r)) && now - (answeredAt.get(key(r)) || 0) < RCPT_MS) out.splice(Math.min(i, out.length), 0, r); });
  prev.current = out;
  const left = out.filter((r) => !ids.has(key(r))).map((r) => answeredAt.get(key(r)) + RCPT_MS - now);
  useEffect(() => {
    if (!left.length) return;
    const tm = setTimeout(() => bump((x) => x + 1), Math.max(0, Math.min(...left)) + 20);
    return () => clearTimeout(tm);
  });
  return out;
}

function Req({ r, onDone, showWhere = true, showProject = true }) {
  const [busy, setBusy] = useState(false);
  const [why, setWhy] = useState(null);
  const [picks, setPicks] = useState({});
  const [own, setOwn] = useState({});
  const [done, setDone] = useState(null);      // the answer went: "✓ Allowed" in place of the card, until the list drops it
  const [mine, setMine] = useState({});        // questions answered here, shown as answered before the list brings them back
  const chosen = Object.assign({}, r.chosen, mine);
  const send = async (args) => {
    setBusy(true);
    try {
      const res = await api("answer", Object.assign({ rid: r.rid }, args));
      if (res && res.ok === false) alertBox(res.note || t("failed"));
      else if (r.kind === "ask" && Object.keys(Object.assign({}, chosen, args.answers)).length < r.questions.length) {
        haptic("success");           // one of several questions: Claude waits for the rest, the card stays
        setMine(Object.assign({}, mine, args.answers));
      } else {
        haptic("success");
        const k = r.kind === "ask" ? "rcpt.ask" : r.kind === "plan" ? (args.act === "y" ? "rcpt.plan.y" : "rcpt.plan.n")
          : args.act === "a" ? "rcpt.always" : args.act === "y" ? "rcpt.allow" : "rcpt.deny";
        answeredAt.set(r.rid, Date.now());
        setDone(k);
      }
      onDone && onDone();
    } catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  // how long it waits, as a session's card says: "your move" puts them all in one line by time
  const waits = r.since && !done ? html`<span class="c-wait">${t("mine.waits", { dur: nb(dur(Date.now() / 1000 - r.since)) })}</span>` : "";
  const where = showWhere && html`<div class="card-h">${showProject && r.project || waits ? html`<div class="c-proj">${showProject && r.project ? html`${avatar(r.project, 18)}<span>${r.project}</span>` : ""}${waits}</div>` : ""}${r.project !== r.title || !showProject ? html`<b class="c-title">${r.title}</b>` : ""}</div>`;
  if (done) {
    const no = done === "rcpt.deny" || done === "rcpt.plan.n" ? " no" : "";
    return html`<div class="card rcpt" role="status">${where}<div class=${"rcpt-l" + no}>${t(done)}</div>
      <div class=${"rcpt-bar" + no} style=${{ animationDuration: RCPT_MS + "ms" }}></div></div>`;
  }
  if (r.kind === "ask") {
    return html`<div class="card ask">${where}
      ${r.questions.map((qn, i) => chosen[i] ? html`<div class="q done"><div class="q-t">${qn.question}</div>→ <b>${chosen[i].join(", ")}</b></div>` : html`
        <div class="q"><div class="kind">${ic("help", 16)} ${t("kind.q")}</div><div class="q-t">${qn.question}</div>
          ${(qn.options || []).map((o) => {
            const on_ = (picks[i] || []).includes(o.label);
            return html`<button class=${"opt" + (on_ ? " on" : "")} disabled=${busy} onClick=${() => {
              if (qn.multiSelect) setPicks(Object.assign({}, picks, { [i]: on_ ? picks[i].filter((x) => x !== o.label) : [...(picks[i] || []), o.label] }));
              else send({ answers: { [i]: [o.label] } });
            }}><b>${qn.multiSelect ? html`${ic(on_ ? "boxon" : "box", 16)} ` : ""}${o.label}</b>${o.description ? html`<span class="dim">${o.description}</span>` : ""}</button>`;
          })}
          ${qn.multiSelect && html`<button class="btn" disabled=${busy || !(picks[i] || []).length} onClick=${() => send({ answers: { [i]: picks[i] } })}>${t("done")}</button>`}
          <div class="own"><input placeholder=${t("ask.own")} value=${own[i] || ""} onInput=${(e) => setOwn(Object.assign({}, own, { [i]: e.target.value }))}/>
            <button class="btn ghost" disabled=${busy || !(own[i] || "").trim()} onClick=${() => send({ answers: { [i]: [own[i].trim()] } })}>${t("ask.answer")}</button></div>
        </div>`)}
    </div>`;
  }
  const isPlan = r.kind === "plan";
  return html`<div class="card perm">${where}
    <div class="kind">${ic(isPlan ? "plan" : "shield", 16)} ${isPlan ? t("req.plan") : t("req.perm")}</div>
    ${isPlan ? html`<details class="plan"><summary>${t("plan")}</summary><div class="md" data-sid=${r.sid} dangerouslySetInnerHTML=${{ __html: md(r.plan) }}/></details>`
      : html`<div class="perm-b" dangerouslySetInnerHTML=${{ __html: r.html }}/>`}
    <div class="row">
      <button class="btn" disabled=${busy} onClick=${() => send({ act: "y" })}>${isPlan ? t("approve") : t("allow")}</button>
      <button class="btn danger" disabled=${busy} onClick=${() => send({ act: "n" })}>${isPlan ? t("reject.plan") : t("deny")}</button>
    </div>
    <div class="foot quiet">${r.suggest ? html`<button class="link" disabled=${busy} onClick=${() => send({ act: "a" })}>${t("always.short")}</button>` : html`<span></span>`}
    ${why === null ? html`<button class="link" onClick=${() => setWhy("")}>${isPlan ? t("plan.notes") : t("deny.note.short")}</button>` : ""}</div>
    ${why === null ? "" : html`
      <div class="own"><input placeholder=${t("tell.claude")} value=${why} onInput=${(e) => setWhy(e.target.value)}/>
        <button class="btn ghost" disabled=${busy || !why.trim()} onClick=${() => send({ act: "n", text: why.trim() })}>${t("send")}</button></div>`}
  </div>`;
}

// ---------- screens ----------

// Claude's background tasks still running after a turn; when one ends, Claude starts a new turn by itself
const bgLine = (bg) => html`${ic("bg", 14)} ${t("bg", { list: bg.map(q).join(", ") })}`;

// ---------- the load on the computer ----------

// cores a process keeps busy: "1 core", "0.3 cores" — "1 ядро", "0,3 ядра", "5 ядер"
const coresText = (c) => (c >= 0.95 && Math.abs(c - Math.round(c)) < 0.05 ? Math.round(c) + " " + plural(Math.round(c), "core") : num(c, 1) + " " + t("cores.frac"));
const memPct = (l) => (l.mem_total && l.mem_used != null ? Math.round(l.mem_used * 100 / l.mem_total) : null);
const stateWord = (st) => (st === "work" ? t("load.st.work") : st === "ask" ? t("st.ask") : st === "bg" ? t("st.bg") : "");

// what runs under a session: Claude's command in the background (the cog) or in a turn (▶), another program (·)
function Cmds({ cmds, now }) {
  return cmds.length ? html`<div class="cmds">${cmds.map((c, i) => html`<div class="cmd" key=${i}>
    <div class="mono">${c.bg ? ic("bg", 13) : c.claude ? ic("play", 12) : "·"} ${c.text}</div>
    <div class="dim">${[pct(c.cpu), bytes(c.mem), t("load.runs", { dur: nb(dur(now - c.started)) })].join(" · ")}</div></div>`)}</div>` : "";
}

function LoadRow({ s, now }) {
  return html`<button class="item" onClick=${() => go("#/s/" + s.sid)}>
    <div class="item-h"><b>${s.driven ? html`<span class="st-ic">${ic("phone", 14)}</span>` : ""}${s.title}</b><b class=${"pct " + level(s.cpu)}>${pct(s.cpu)}</b></div>
    <div class="dim">${[s.project !== s.title ? s.project : "", stateWord(s.state), bytes(s.mem),
      s.cpu_time != null ? t("load.total", { dur: nb(dur(s.cpu_time)) }) : "", t("load.opened", { when: ago(s.started) })].filter(Boolean).join(" · ")}</div>
    <${Cmds} cmds=${s.cmds} now=${now}/>
  </button>`;
}

// the computer: processor and memory now, then every Claude session on it, the busiest first; resting ones folded
function Load({ embedded }) {
  const now = useNow(5000);
  const [d, err] = useLive(() => api("load"), [], () => false, 5000);
  const [rest, setRest] = useState(false);
  if (!d) return html`<${Loading} err=${err}/>`;
  if (!d.ok) return embedded ? "" : html`<div><h2>${t("load.title")}</h2><div class="empty">${t("load.none")}</div></div>`;
  const l = d.mac, m = memPct(l);
  const busy = d.sessions.filter((s) => !s.idle), idle = d.sessions.filter((s) => s.idle);
  return html`<div>${embedded ? "" : html`<h2>${t("load.title")}</h2>`}
    <div class="list">
      <div class="lim"><div class="item-h"><b>${t("load.cpu")}</b><b class=${"pct " + level(l.cpu)}>${pct(l.cpu)}</b></div>
        <div class="meter"><i class=${level(l.cpu)} style=${"width:" + Math.min(100, l.cpu) + "%"}></i></div>
        <div class="dim">${t("load.cpu.about", { n: l.cores, cores: plural(l.cores, "core"), load: num(l.load, 1) })}</div></div>
      ${m !== null && html`<div class="lim"><div class="item-h"><b>${t("load.mem")}</b><b class=${"pct " + level(m)}>${m} %</b></div>
        <div class="meter"><i class=${level(m)} style=${"width:" + Math.min(100, m) + "%"}></i></div>
        <div class="dim">${t("load.mem.about", { used: bytes(l.mem_used), total: bytes(l.mem_total), free: bytes(l.mem_total - l.mem_used) })}</div></div>`}
    </div>
    <h3>${t("load.sessions", { n: l.claude.n, sessions: plural(l.claude.n, "session"), cpu: pct(l.claude.cpu), mem: bytes(l.claude.mem) })}</h3>
    ${!d.sessions.length && html`<div class="empty">${t("load.nosessions")}</div>`}
    ${busy.length > 0 && html`<div class="list">${busy.map((s) => html`<${LoadRow} key=${s.sid} s=${s} now=${now}/>`)}</div>`}
    ${idle.length > 0 && html`<h3 class="toggle" onClick=${() => setRest(!rest)}>${t("load.resting", { n: idle.length, mem: bytes(idle.reduce((a, s) => a + s.mem, 0)) })} <span class=${"chev" + (rest ? " open" : "")}>${ic("chev", 14)}</span></h3>
      ${rest && html`<div class="list">${idle.map((s) => html`<${LoadRow} key=${s.sid} s=${s} now=${now}/>`)}</div>`}`}
    <${About} text=${t("load.about")}/>
  </div>`;
}

// a tap on "in the background": each task and what it costs the computer — now, in total and at its peak
const TASK_TYPES = { shell: "bgs.shell", monitor: "bgs.monitor", subagent: "bgs.subagent", workflow: "bgs.workflow" };
function BgSheet({ sid, onClose, fixed }) {
  const now = useNow(5000);
  const [d, err] = useLive(() => api("load", { sid }), [sid], (m) => !m.sid || m.sid === sid, 5000);
  const more = () => { onClose(); setTimeout(() => go("#/load"), 60); };
  const one = (x) => html`<div class="task" key=${x.id}>
    <div class="item-h"><b>${x.what}</b><span class="chip">${t(TASK_TYPES[x.type] || "bgs.shell")}</span></div>
    ${x.cmd && html`<pre class="cmdline">${x.cmd}</pre>`}
    ${x.remote ? html`<div class="dim">${x.since ? t("bgs.atleast", { dur: dur(now - x.since), hm: hhmm(toDate(x.since)) }) + " · " : ""}${t("bgs.remote")}</div>`
      : x.found === false ? html`<div class="dim">${t("bgs.gone")}</div>`
      : html`<div class="kv">
          <span>${t("bgs.runs")}</span><b>${dur(now - x.since)} <span class="dim">${t("bgs.since", { hm: hhmm(toDate(x.since)) })}</span></b>
          <span>${t("bgs.cpu")}</span><b>${pct(x.cpu)}${x.cores >= 0.1 ? html` <span class="dim">· ≈ ${coresText(x.cores)}</span>` : ""}</b>
          ${x.cpu_time != null && html`<span>${t("bgs.cputime")}</span><b>${dur(x.cpu_time)}</b>`}
          <span>${t("bgs.mem")}</span><b>${bytes(x.mem)}${x.peak ? html` <span class="dim">· ${t("bgs.peak", { mem: bytes(x.peak) })}</span>` : ""}</b>
        </div>`}</div>`;
  return html`<div class="backdrop" onClick=${onClose}></div><div class=${"card pick tall" + (fixed ? " fixed" : "")}>
    <div class="q-t pick-h"><span>${ic("bg", 17)} ${t("bgs.title")}</span><button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></div>
    ${!d ? html`<div class="dim">${err || t("loading")}</div>` : !d.ok ? html`<div class="dim">${t("load.none")}</div>` : html`
      ${!d.tasks.length && html`<div class="dim">${t("bgs.none")}</div>`}${d.tasks.map(one)}
      ${d.session && html`<div class="dim small">${t("bgs.session", { cpu: pct(d.session.cpu), mem: bytes(d.session.mem) })}</div>`}`}
    <button class="link" onClick=${more}>${t("bgs.more")}</button></div>`;
}

// where the owner is: it only changes the sound, messages always arrive
const MODES = ["auto", "mac", "phone"];
function ModePick({ mode, onSet, pager }) {
  const pick = async (m) => {
    if (m === mode) return;
    try { await api("prefs", { mode: m }); onSet(m); haptic("success"); } catch (e) { alertBox(e.message); }
  };
  const cur = MODES.includes(mode) ? mode : "auto";
  return html`<div class="modes"><div class="seg">${MODES.map((k) =>
    html`<button key=${k} class=${k === cur ? "on" : ""} onClick=${() => pick(k)}>${ic({ auto: "auto", mac: "monitor", phone: "phone" }[k], 16)} ${t("mode." + k + ".btn")}</button>`)}</div>
    <div class="dim small">${t("mode." + cur + (pager ? ".pager" : ".about"))}</div></div>`;
}

// one line-icon set for the whole app (stroke, 24 grid): the same meaning — the same picture on every screen
const IC = {
  check: '<path d="M20 6 9 17l-5-5"/>',
  checks: '<path d="M18 6 7 17l-5-5"/><path d="m22 10-7.5 7.5L13 16"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
  help: '<circle cx="12" cy="12" r="9.5"/><path d="M9.2 9.2a3 3 0 0 1 5.7 1.1c0 2-2.9 2.7-2.9 2.7"/><path d="M12 17h.01"/>',
  plan: '<rect x="8" y="2.5" width="8" height="4" rx="1"/><path d="M16 4.5h2a2 2 0 0 1 2 2V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6.5a2 2 0 0 1 2-2h2"/><path d="M9 12h6M9 16h4"/>',
  alert: '<path d="m21.7 18-8-14a2 2 0 0 0-3.5 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3"/><path d="M12 9v4M12 17h.01"/>',
  bg: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.5v3M12 18.5v3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M2.5 12h3M18.5 12h3M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
  phone: '<rect x="6" y="2" width="12" height="20" rx="2.6"/><path d="M11 18h2"/>',
  monitor: '<rect x="2.5" y="3.5" width="19" height="13" rx="2"/><path d="M8 21h8M12 16.5V21"/>',
  auto: '<path d="M20.5 12a8.5 8.5 0 0 1-14.6 5.9L3.5 15.5"/><path d="M3.5 12a8.5 8.5 0 0 1 14.6-5.9l2.4 2.4"/><path d="M20.5 3.5v5h-5M3.5 20.5v-5h5"/>',
  msg: '<path d="M20.5 14.5a2 2 0 0 1-2 2H8l-4.5 4v-15a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2z"/>',
  term: '<path d="m4.5 17 5.5-5-5.5-5M12.5 18.5h7"/>',
  home: '<path d="M3.5 10.5 12 3.5l8.5 7"/><path d="M5.5 9v11a1 1 0 0 0 1 1h3.5v-6h4v6h3.5a1 1 0 0 0 1-1V9"/>',
  folder: '<path d="M3 7.5V18a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9.5a2 2 0 0 0-2-2h-7l-2-3H5a2 2 0 0 0-2 2z"/>',
  gauge: '<path d="M4.2 18.5a9 9 0 1 1 15.6 0"/><path d="m12 13.5 4-4.5"/><circle cx="12" cy="13.5" r="1.2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  chev: '<path d="m9 6 6 6-6 6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  up: '<path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  file: '<path d="M14 2.5H6.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8z"/><path d="M14 2.5V8h5.5"/>',
  image: '<rect x="3" y="3.5" width="18" height="17" rx="2.5"/><circle cx="9" cy="9.5" r="1.8"/><path d="m21 15.5-5-5-11 10"/>',
  mic: '<rect x="9" y="2.5" width="6" height="12" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5v4"/>',
  play: '<path d="M7 4.5v15l12-7.5z"/>',
  box: '<rect x="4" y="4" width="16" height="16" rx="3.5"/>',
  boxon: '<rect x="4" y="4" width="16" height="16" rx="3.5"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
  copy: '<rect x="8.5" y="8.5" width="12" height="12" rx="2.2"/><path d="M15.5 8.5V5.7a2.2 2.2 0 0 0-2.2-2.2H5.7a2.2 2.2 0 0 0-2.2 2.2v7.6a2.2 2.2 0 0 0 2.2 2.2h2.8"/>',
  clip: '<path d="m20.5 11.5-8.6 8.6a5.3 5.3 0 0 1-7.5-7.5l8.6-8.6a3.5 3.5 0 0 1 5 5l-8.6 8.6a1.8 1.8 0 0 1-2.5-2.5l7.9-7.9"/>',
  info: '<circle cx="12" cy="12" r="9.5"/><path d="M12 16.5v-5M12 7.8h.01"/>',
  clock: '<circle cx="12" cy="12" r="9.5"/><path d="M12 7v5l3.2 2"/>',
  back: '<path d="m15 6-6 6 6 6"/>',
  send: '<path d="M21.5 2.5 10.5 13.5"/><path d="m21.5 2.5-7 19-4-8-8-4z"/>',
  server: '<rect x="3" y="3.5" width="18" height="7" rx="2"/><rect x="3" y="13.5" width="18" height="7" rx="2"/><path d="M7 7h.01M7 17h.01"/>',
  relay: '<path d="M4 12h5M15 12h5"/><circle cx="12" cy="12" r="3"/><path d="M6.5 8.5 4 12l2.5 3.5M17.5 8.5 20 12l-2.5 3.5"/>',
  tabs: '<rect x="2.5" y="4" width="19" height="16" rx="2.5"/><path d="M2.5 9h19M9 4v5"/>',
  hook: '<path d="M8 3v7a4 4 0 0 0 8 0V8"/><path d="m13 11 3-3 3 3"/><path d="M8 21v-4"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8"/>',
  tag: '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z"/><path d="M7.5 7.5h.01"/>',
  lock: '<rect x="4.5" y="10.5" width="15" height="11" rx="2"/><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5"/>',
};
const ic = (n, s = 18) => html`<svg class=${"ic ic-" + n} viewBox="0 0 24 24" width=${s} height=${s} fill="none" stroke="currentColor"
  stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" dangerouslySetInnerHTML=${{ __html: IC[n] }}></svg>`;
const dot = (k) => html`<i class=${"dot " + k}></i>`;
const dotted = (xs) => xs.filter(Boolean).map((m, i) => html`${i ? html`<span class="sep">·</span>` : ""}${m}`);
// a project's own colour, the same on Home, its screen, Resources and its new topic's icon: Telegram's six topic
// colours, picked by the name's UTF-8 bytes — pult_render.topic_color does the same sum, keep them in step
const HUES = ["#6fb9f0", "#ffd67e", "#cb86db", "#8eee98", "#ff93b2", "#fb6f5f"];
const hue = (s) => { let h = 0; for (const b of new TextEncoder().encode(String(s))) h = (h * 31 + b) >>> 0; return HUES[h % HUES.length]; };
// a task's two tags (stage T): the section of its project and the topic in it, in plain words — Claude keeps them, the
// owner only corrects. The colour is the section's place in its project's list, the same on every screen; the topic
// wears its section's colour, outlined. A tag Claude has just made is dashed only in the sheet that corrects a task's
// tags: in the lists, in its first day almost every tag is new, and the dashes were noise (2026-10-26)
const TAG_H = [212, 28, 150, 280, 340, 190, 45, 95];
const tagSt = (c) => "--th:" + TAG_H[(c || 0) % TAG_H.length];
const tagChip = (g) => html`<span key=${g.k + g.n} class=${"tagc" + (g.k === "topic" ? " topic" : "")} style=${tagSt(g.c)}>${g.n}</span>`;
const tagChips = (tags) => (tags && tags.length ? tags.slice(0, 2).map(tagChip) : "");
// a session has no tab bar (the composer is there): its way straight home, the tab's own icon
const home = (size) => html`<a class="home-l" href="#/" aria-label=${t("tab.home")}>${ic("home", size)}</a>`;
const avatar = (name, size = 28) => html`<span class="av" aria-hidden="true" style=${"background:" + hue(name) + ";width:" + size + "px;height:" + size + "px;font-size:" + Math.round(size * .5) + "px"}>${String(name).replace(/[^\p{L}\p{N}]/gu, "").charAt(0).toUpperCase()}</span>`;

// the Home strip: two small tiles and the way to the settings — where you are (tap — the mode picker) and the limit
// with the load (tap — Resources). A label over a value, so nothing is cut on a narrow phone. The strip is a setting,
// not the news: what waits for an answer comes right under it
const GEAR = html`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`;
// the top line stays grey while all is well: a colour means look here
const quiet = (v, bad) => (v >= bad ? "bad" : v >= bad - 10 ? "warn" : "dim");
const GLYPH = { pace: "●", under: "▼", over: "▲" };
function Top({ mac, load, usagePct, usageTop, pager, onSet }) {
  const [open, setOpen] = useState(false);
  const cur = MODES.includes(mac.mode) ? mac.mode : "auto";
  const line = cur === "auto" ? (mac.away ? t("mac.away.short", { dur: durShort(mac.idle) }) : t("mac.here.short")) : t("mode." + cur + ".short");
  const m = load ? memPct(load) : null;
  // the limit: the one that runs out first (stage R), grey unless it does; an older Pult sends only the 5-hour window
  const lim = usageTop ? Math.round(usageTop.pct) : usagePct;
  const limCls = !usageTop || usageTop.state === "none" ? quiet(lim, 80) : usageTop.state === "over" ? "bad" : "dim";
  const limText = lim + "\u00a0%" + (usageTop && GLYPH[usageTop.state] ? "\u00a0" + GLYPH[usageTop.state] : "");
  const stat = (k, v, cls, label) => html`<span class="tl-c"><span class="tl-l">${label || t(k)}</span><span class=${"tl-v " + cls}>${v}</span></span>`;
  return html`<div class="where">
    <div class="where-h">
      <button class="where-b" aria-expanded=${open} onClick=${() => setOpen(!open)}><span class="tl-l">${ic({ auto: "auto", mac: "monitor", phone: "phone" }[cur], 14)} ${t("mode." + cur + ".btn")}</span><span class="tl-v">${line}</span></button>
      ${(load || lim != null) && html`<button class="where-b top-load" onClick=${() => go("#/usage")}>${lim != null && stat("top.lim", limText, limCls, usageTop && t("sp.short." + usageTop.key))}${load && stat("top.cpu", pct(load.cpu), quiet(load.cpu, 90))}${m !== null && m >= 90 && stat("top.mem", m + "\u00a0%", "bad")}</button>`}
      <a class="gear" href="#/settings" aria-label=${t("settings")}>${GEAR}</a>
    </div>
    ${open && html`<${ModePick} mode=${cur} onSet=${onSet} pager=${pager}/>`}
  </div>`;
}

// a message from a card or a ready reply into the session: the same ways as the session's own field — straight in,
// into the tab, or a copy when it is open on the computer without Pult (asked first)
async function sendTo(sid, text) {
  let r = await api("send", { sid, text });
  if (r.need === "fork") {
    if (!(await confirmBox(t("fork.ask")))) return false;
    r = await api("send", { sid, text, fork: true });
    if (r.how === "fork") alertBox(t("fork.started"));
  }
  haptic("success");
  return true;
}

// ready replies the model took from Claude's message: one tap sends, with three seconds to change your mind
const UNDO = 3;
function Replies({ sid, replies, onSent }) {
  const [wait, setWait] = useState(null);         // {text, left}
  const timer = useRef(0);
  useEffect(() => () => clearInterval(timer.current), []);
  if (!replies || !replies.length) return "";
  const pick = (text, e) => {
    e && e.stopPropagation();
    clearInterval(timer.current);
    setWait({ text, left: UNDO });
    timer.current = setInterval(() => setWait((w) => {
      if (!w) return w;
      if (w.left > 1) return Object.assign({}, w, { left: w.left - 1 });
      clearInterval(timer.current);
      sendTo(sid, w.text).then((ok) => ok && onSent && onSent(w.text)).catch((err) => alertBox(err.message));
      return null;
    }), 1000);
  };
  const undo = (e) => { e.stopPropagation(); clearInterval(timer.current); setWait(null); };
  return wait ? html`<div class="qr wait"><span>${t("reply.will", { text: wait.text })} · ${wait.left}</span><button class="link" onClick=${undo}>${t("undo")}</button></div>`
    : html`<div class="qr">${replies.map((x) => html`<button key=${x} onClick=${(e) => pick(x, e)}>${x}</button>`)}</div>`;
}

// your own words right in the card: a line and the microphone, Enter or the arrow sends
function QuickReply({ sid, stt, onSent }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const v = useRecorder((w) => setText((c) => (c ? c.replace(/\s+$/, "") + " " : "") + w));
  const send = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    try { if (await sendTo(sid, text.trim())) { setText(""); onSent && onSent(text.trim()); } } catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  return html`<div class="reply" onClick=${(e) => e.stopPropagation()}>
    <input ref=${plainField} placeholder=${t("reply.own")} value=${text} onInput=${(e) => setText(e.target.value)}
      onKeyDown=${(e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); send(); } }}/>
    ${stt ? html`<${Mic} v=${v} disabled=${busy}/>` : ""}
    ${text.trim() ? html`<button class="btn send" aria-label=${t("send")} disabled=${busy} onClick=${send}>${ic("up", 18)}</button>` : ""}</div>`;
}

// "continue when the usage limit resets": Pult says "continue" in the session itself at that time
function ResumeAt({ sid, resume, reset, onSet }) {
  const set = async (at) => {
    try { const r = await api("resume_at", { sid, at }); haptic("success"); onSet && onSet(r.at); } catch (e) { alertBox(e.message); }
  };
  if (resume) return html`<div class="qr wait"><span>${t("resume.set", { hm: hhmm(toDate(resume)) })}</span><button class="link" onClick=${(e) => { e.stopPropagation(); set(null); }}>${t("resume.cancel")}</button></div>`;
  return html`<div class="qr"><button onClick=${(e) => { e.stopPropagation(); set(reset || 0); }}>${reset ? t("resume.at", { hm: hhmm(toDate(reset)) }) : t("resume.after")}</button></div>`;
}

// "your move" in one line by time: questions and permissions with the sessions that wait, the freshest on top, the
// longest waiting at the bottom (the owner, 2026-10-24); a computer before 0.15.1 gives a request no time — on top
const moves = (pending, mine) => [...pending.map((r) => ({ key: r.rid, req: r, at: r.since || 1e12 })),
  ...mine.map((r) => ({ key: "m" + r.sid, mine: r, at: r.since || 0 }))].sort((a, b) => b.at - a.at);
const moveKey = (e) => e.key;

// "Your move": a session that ended and waits for you — how long, what came out, what is needed; ready replies,
// your own words, "Got it" to put it to rest; the title opens the session
function Mine({ r, now, onGot, stt, showProject = true }) {
  const [busy, setBusy] = useState(false);
  const [resume, setResume] = useState(r.resume);
  const got = async (e) => {
    e && e.stopPropagation();
    setBusy(true);
    try { await api("seen", { sid: r.sid }); haptic("success"); onGot && onGot(r.sid); } catch (err) { alertBox(err.message); }
    setBusy(false);
  };
  const open = () => go("#/s/" + r.sid);
  const sent = () => onGot && onGot(r.sid);
  return html`<div class=${"card mine" + (r.state === "fail" ? " fail" : "")}>
    <div class="card-h tap" onClick=${open}><div class="c-proj">${showProject && r.project ? html`${avatar(r.project, 18)}<span class="c-name">${r.project}</span>` : ""}<span class="c-wait">${t("mine.waits", { dur: nb(dur(now - r.since)) })}</span></div>
      <b class="c-title">${r.state === "fail" ? ic("alert", 16) : ""}${r.title}</b></div>
    ${r.need ? html`<div class="ln dim tap" onClick=${open}>${tagChips(r.tags)}${r.line}</div><div class="now tap" onClick=${open}>${r.need}</div>` : html`<div class="now tap" onClick=${open}>${tagChips(r.tags)}${r.line}</div>`}
    ${r.fail === "rate_limit" ? html`<${ResumeAt} sid=${r.sid} resume=${resume} reset=${r.reset} onSet=${setResume}/>` : html`<${Replies} sid=${r.sid} replies=${r.replies} onSent=${sent}/>`}
    <${QuickReply} sid=${r.sid} stt=${stt} onSent=${sent}/>
    <div class="foot quiet"><span></span><button class="link" disabled=${busy} onClick=${got}>${ic("check", 15)} ${t("mine.got")}</button></div>
  </div>`;
}

// "While you were away": what happened since you last had the app open (an hour or more ago) — turns, what is done,
// what waits; a line per project. Gone with the next long break, or with ×
function Catchup({ c, onClose }) {
  return html`<div class="card catch"><div class="item-h"><b>${t("catch.title")}</b><span class="dim nowrap">${t("catch.since", { hm: agoShort(c.from) })}
    <button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></span></div>
    <div class="dim cnts">${[t("catch.turns", { n: c.turns, turns: plural(c.turns, "turn"), p: c.projects }), c.done ? html`<span class="cnt ok">${ic("check", 14)}${c.done}</span>` : "", c.mine ? html`<span class="cnt">${dot("attn")}${c.mine}</span>` : ""].filter(Boolean).map((m, i) => html`${i ? html`<span class="sep">·</span>` : ""}${m}`)}</div>
    ${c.lines.map((x) => html`<div class="ln tap" key=${x.pkey} onClick=${() => go("#/p/" + encodeURIComponent(x.pkey))}>${x.you ? dot("attn") : x.fail ? ic("alert", 14) : ic("check", 14)} <b>${x.name}</b> — ${x.line}</div>`)}</div>`;
}

// one session on the board: what it does now or how its last turn ended, in a line or two; in "Running now" (with
// project) — its project and what it does in one grey line: the turn's line, or its background task
function BoardRow({ r, now, onBg, project }) {
  const bgTap = (e) => { e.stopPropagation(); onBg(r); };
  const right = r.state === "work" ? workChip(r.since, now)
    : r.state === "queue" ? queueChip(r.since, now)
    : r.state === "bg" ? bgChip(r.since, now, bgTap)
    : html`<span class="dim nowrap">${agoShort(r.ts)}</span>`;
  const what = project != null && [project !== r.title ? project : "",
    r.state === "bg" && r.bg && r.bg.length ? r.bg.map(q).join(", ") : r.line ? r.line : ""].filter(Boolean).join(" · ");
  const icon = r.state === "work" ? html`<span class="st st-work"></span>` : r.state === "bg" ? html`<span class="st-ic">${ic("bg", 15)}</span>`
    : r.state === "queue" ? html`<span class="st-ic">${ic("clock", 15)}</span>`
    : r.state === "done" ? html`<span class="st-ic ok">${ic("check", 15)}</span>` : r.driven ? html`<span class="st-ic">${ic("phone", 15)}</span>` : "";
  return html`<button class=${"item brow" + (r.state === "idle" ? " rest" : "") + (r.state === "done" ? " fresh" : "")} onClick=${() => go("#/s/" + r.sid)}>
    <div class="item-h"><b class="one">${icon}${r.title}</b><span class="meta">${r.ctx != null && r.ctx >= 90 ? html`<span class="pct bad">${ic("alert", 13)} ${r.ctx} %</span>` : ""}${right}</span></div>
    ${project != null ? (what || (r.tags && r.tags.length > 0)) && html`<div class="ln dim">${tagChips(r.tags)}${what}</div>` : html`
    ${(r.line || (r.tags && r.tags.length > 0)) && html`<div class="ln">${tagChips(r.tags)}${r.line}</div>`}
    ${r.bg && r.bg.length > 0 && html`<div class="bg tap" onClick=${bgTap}>${bgLine(r.bg)} ${ic("chev", 14)}</div>`}`}
  </button>`;
}

// a project on the board: who works and who waits for you, today's turns; its live sessions; the resting folded
function ProjectBlock({ p, now, onBg }) {
  const open = () => go("#/p/" + encodeURIComponent(p.pkey));
  const meta = [p.work ? html`<span class="cnt">${dot("work")}${p.work}</span>` : "", p.mine ? html`<span class="cnt">${dot("attn")}${p.mine}</span>` : "",
    p.turns ? t("proj.turns", { n: p.turns, turns: plural(p.turns, "turn") }) : "",
    !p.rows.length && p.resting ? t("proj.resting", { n: p.resting }) : ""].filter(Boolean);
  return html`<div class="list proj">
    <button class="item proj-h" onClick=${open}><span class="pname">${avatar(p.name, 34)}<span class="pn"><b>${p.name}</b><span class="dim pmeta">${meta.length ? meta.map((m, i) => html`${i ? html`<span class="sep">·</span>` : ""}${m}`) : t("proj.quiet")}</span></span>${ic("chev", 16)}</span></button>
    ${p.rows.map((r) => html`<${BoardRow} key=${r.sid} r=${r} now=${now} onBg=${onBg}/>`)}
    ${p.rows.length > 0 && p.resting > 0 && html`<button class="item more dim" onClick=${open}>${t("row.resting", { n: p.resting, rest: plural(p.resting, "rest") })}</button>`}
  </div>`;
}

// Home (stage V, "whose move"): one line on top — where you are, the computer's load, settings; then what runs right
// now (turns, background tasks, tasks without Claude); what waits for you (questions and permissions to answer right
// here, sessions that ended and need you); then every project with the rest of its sessions; finished tasks without
// Claude. Nothing repeats: a session is in "Running now", in "Your move" or on the board
function Home() {
  const now = useNow(1000);            // "working 14 s" ticks every second: a turn in progress should look alive
  const [d, err, set] = useLive(() => api("overview"), []);
  const [bgFor, setBgFor] = useState(null);
  const [openBg, closeBg] = useOverlay(!!bgFor, (v) => { if (!v) setBgFor(null); });
  const seenN = useRef(-1);
  const yours = useRcpt(d ? moves(d.pending, d.mine || []) : [], moveKey);
  if (!d) return html`<${Loading} err=${err}/>`;
  if (seenN.current < 0) seenN.current = (d.pending || []).length + (d.mine || []).length;     // no buzz on opening
  useLang(d.lang);
  const onBg = (s) => { setBgFor(s.sid); openBg(); };
  const mine = d.mine || [], board = d.board || [];
  const n = d.pending.length + mine.length;
  if (n > seenN.current) haptic("warning");             // a new "your move" while you look at Home — a buzz
  seenN.current = n;
  const gone = (sid) => set(Object.assign({}, d, { mine: mine.filter((r) => r.sid !== sid) }));
  // what runs, first: working, then in the background, then waiting in the queue, then tasks without Claude; the
  // earliest started on top in each, so new ones come in below and rows don't jump; they leave the project blocks
  const runs = (r) => r.state === "work" || r.state === "bg" || r.state === "queue";
  const live = board.flatMap((p) => p.rows.filter(runs).map((r) => Object.assign({ project: p.name }, r)));
  const early = (a, b) => (a.since || 0) - (b.since || 0);
  const running = ["work", "bg", "queue"].flatMap((st) => live.filter((r) => r.state === st).sort(early));
  const nQueue = live.filter((r) => r.state === "queue").length;
  const jobs = d.jobs || [];
  const jobsOn = jobs.filter((j) => j.ended == null).sort((a, b) => a.started - b.started), jobsDone = jobs.filter((j) => j.ended != null);
  const nRun = running.length + jobsOn.length;
  const rest = board.map((p) => Object.assign({}, p, { rows: p.rows.filter((r) => !runs(r)) }));
  return html`<div>
    <${Top} mac=${d.mac} load=${d.load} usagePct=${d.usage_pct} usageTop=${d.usage_top} pager=${d.pager} onSet=${(m) => set(Object.assign({}, d, { mac: Object.assign({}, d.mac, { mode: m }) }))}/>
    <${UpdRow} u=${d.update}/>
    ${nRun > 0 && html`<h3>${t("home.running", { n: nRun - nQueue })}${nQueue ? " · " + t("home.queued", { n: nQueue }) : ""}</h3><div class="list">
      ${running.map((r) => html`<${BoardRow} key=${r.sid} r=${r} now=${now} onBg=${onBg} project=${r.project}/>`)}
      ${jobsOn.map((j) => html`<${Job} key=${j.id} j=${j} now=${now} row=${true}/>`)}</div>`}
    ${d.catchup && html`<${Catchup} c=${d.catchup} onClose=${() => { api("catchup_off").catch(() => {}); set(Object.assign({}, d, { catchup: null })); }}/>`}
    ${(n > 0 || yours.length > 0) && html`<h3>${t("home.mine", { n })}</h3>
      ${yours.map((e) => e.req ? html`<${Req} key=${e.key} r=${e.req}/>`
        : html`<${Mine} key=${e.key} r=${Object.assign({ reset: d.reset }, e.mine)} now=${now} onGot=${gone} stt=${d.stt}/>`)}`}
    ${rest.length > 0 && html`<h3>${t("home.projects")}</h3>${rest.map((p) => html`<${ProjectBlock} key=${p.pkey} p=${p} now=${now} onBg=${onBg}/>`)}`}
    ${!n && !board.length && !nRun && html`<div class="empty">${t("home.quiet")}</div>`}
    ${jobsDone.length > 0 && html`<h3>${t("home.jobs")}</h3><div class="list">${jobsDone.map((j) => html`<${Job} key=${j.id} j=${j} now=${now}/>`)}</div>`}
    ${bgFor && html`<${BgSheet} sid=${bgFor} fixed=${true} onClose=${closeBg}/>`}
  </div>`;
}

// a task without Claude; in "Running now" (row) — two lines, like a session: the command, then project · last output
function Job({ j, now, row }) {
  const [open, setOpen] = useState(false);
  const st = j.ended == null ? html`<${TimeChip} cls="ok" text=${t("job.running", { dur: durShort(now - j.started) })}/>`
    : j.code === 0 ? html`<span class="chip okc">${ic("check", 12)} ${dur(j.ended - j.started)}</span>`
    : html`<span class="chip bad">${j.code == null ? t("job.killed") : t("job.code", { code: j.code })}</span>`;
  return html`<button class="item" onClick=${() => setOpen(!open)}>
    <div class="item-h"><b class="mono one">${row ? html`<span class="st-ic">${ic("term", 15)}</span>` : ""}${j.cmd}</b>${st}</div>
    ${row && !open ? html`<div class="ln dim">${[j.project || j.cwd, j.last].filter(Boolean).join(" · ")}</div>` : html`
    <div class="dim">${j.project || j.cwd}${j.ended ? " · " + ago(j.ended) : ""}</div>
    ${!open && j.last && j.ended == null && html`<div class="now mono">${j.last}</div>`}`}
    ${open && html`<pre class="tail">${(j.tail.length ? j.tail : [j.last || t("job.noout")]).join("\n")}</pre>`}
  </button>`;
}

// stage U: an update from the app. Pult knows the folder it was installed from; a commit there that changed its
// files is offered here. "run" — the computer restarts Pult: the banner says so instead of "offline" for a while
const updSpin = html`<span class="upd-spin" aria-hidden="true"></span>`;
const UPD_RUN_MAX = 180000;
function noteUpd(state) {
  const was = conn.updating;
  conn.updating = state === "run" ? was || Date.now() : 0;
  if (!was !== !conn.updating) emit("conn");
}
const tOr = (k, other) => { const v = t(k); return v === k ? other : v; };     // a code the app has no words for: as is
const updWhy = (w) => tOr("upd.why." + w, w || "?");
const updWho = (b, i) => html`<div class="upd-who" key=${i}>${b.turn ? html`<span class="st st-work"></span>` : html`<span class="st-ic">${ic("bg", 15)}</span>`}<span>${b.project ? html`<b>${b.project}</b>${b.title && b.title !== b.project ? " · " + b.title : ""}` : b.title} <span class="dim">— ${[b.turn ? t("upd.busy.turn") : "", b.n ? t("upd.busy.bg", { n: b.n }) : ""].filter(Boolean).join(", ")}</span></span></div>`;

// stage U2: which copy of the app this window runs — the ?v= its own link carries (the server puts the files' latest
// change there) — against the one the server hands out now, from its page. Asked when the app comes back to the
// screen and when Settings opens, at most every 5 min otherwise: a window Telegram kept open for days runs the old one
const OWN_V = (() => { try { return new URL(import.meta.url).searchParams.get("v") || ""; } catch (e) { return ""; } })();
const served = { v: "", at: 0 };
async function checkServed(force) {
  if (!force && Date.now() - served.at < 300000) return;
  served.at = Date.now();
  try {
    const r = await fetch(location.pathname, { cache: "no-store", credentials: "same-origin" });
    const m = /\/app\.js\?v=(\d+)/.exec(await r.text());
    if (m && m[1] !== served.v) { served.v = m[1]; emit("served"); }
  } catch (e) {}
}
const phoneOld = () => !!(OWN_V && served.v && served.v !== OWN_V);
on("ready", () => checkServed());
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") checkServed(); });
const useServed = () => { const [, bump] = useState(0); useEffect(() => on("served", () => bump((x) => x + 1)), []); };

// Home: a line under the strip only while there is something to do or to know; a tap — Settings. The computer's own
// install states first; then what can be done from here (the computer, this phone's copy) and what doesn't work
function UpdRow({ u }) {
  useEffect(() => noteUpd(u && u.state), [u && u.state]);
  useServed();
  const st = u ? u.state : "ok", phone = phoneOld(), broken = (u && u.broken) || [];
  const mac = st === "ready" || st === "busy";
  const row = (icon, title, sub, cls) => html`<button class=${"card upd-row " + cls} onClick=${() => go("#/settings")}>
    <span class="upd-ic">${icon}</span><span class="upd-t"><b>${title}</b><span class="dim">${sub}</span></span>${ic("chev", 16)}</button>`;
  if (st === "wait" || st === "run" || st === "fail" || mac && !phone && !broken.length) {
    const [icon, title, sub, cls] = {
      ready: [ic("up", 17), t("upd.ready", { v: u.next }), t("upd.row.ready", { v: u.have }), ""],
      busy: [ic("up", 17), t("upd.ready", { v: u.next }), t("upd.row.busy", { n: u.left }), "attn"],
      wait: [ic("auto", 17), t("upd.wait", { v: u.next }), t("upd.row.wait", { n: u.left }), "attn"],
      run: [updSpin, t("upd.run", { v: u.next }), t("upd.row.run"), ""],
      fail: [ic("alert", 17), u.back ? t("upd.row.fail", { next: u.next, v: u.have }) : t("upd.fail.kept", { v: u.next }), t("upd.row.fail.sub"), "bad"],
    }[st];
    return row(icon, title, sub, cls);
  }
  const acts = [mac ? t("pt.home.mac") : "", phone ? t("pt.home.phone") : ""].filter(Boolean);
  const probs = broken.map((b) => (b.k === "hooks" ? t("pt.home.hooks", { ev: b.missing.join(", ") }) : t("pt.home.cc", { v: b.v })));
  if (!acts.length && !probs.length) return "";
  if (!acts.length) return row(ic("alert", 17), probs[0], probs.slice(1).join(" · ") || t("pt.home.more"), "bad");
  return row(ic("up", 17), t("pt.home.upd", { what: acts.join(", ") }), probs.join(" · ") || t(mac ? "upd.row.ready" : "pt.home.phone.sub", { v: u && u.have }), probs.length ? "bad" : "");
}

// the computer's Pult: the state, the one button, the history — the "Pult" block of a computer before stage U2, and
// the computer's row in the parts table (row: the version and "up to date" are in the row already)
function UpdBody({ v, set, row }) {
  const [busy, setBusy] = useState(false);
  const act = async (op) => {
    setBusy(true);
    try { const r = await api(op); set(r); haptic("success"); }
    catch (e) { alertBox(e.message); api("update").then(set).catch(() => {}); }
    setBusy(false);
  };
  const head = (icon, title, chip, cls) => html`<div class=${"upd-h " + (cls || "")}><b>${icon}${title}</b>${chip}</div>`;
  const news = v.news && v.news.length ? html`<div class="upd-k">${t("upd.news")}</div><ul class="upd-news">${v.news.map((x, i) => html`<li key=${i}>${x}</li>`)}</ul>` : "";
  const busyList = v.busy || [];
  const order = { prepare: 0, start: 0, stop: 1, copy: 1, check: 2, back: 3 };
  const at = order[v.step] || 0;
  const mark = (n) => (at > n ? ic("check", 15) : at === n ? updSpin : html`<span class="upd-dot"></span>`);
  const body = {
    ok: html`${head(html`<span class="upd-ok">${ic("check", 17)}</span>`, t("upd.ok", { v: v.have }), html`<span class="chip ok">${t("upd.ok.chip")}</span>`)}
      ${v.dir ? html`<div class="dim">${t("upd.ok.from", { dir: v.dir, commit: v.commit })}</div>` : ""}`,
    ready: html`${head("", t("upd.ready", { v: v.next }), html`<span class="chip ok">${t("upd.ready.chip")}</span>`)}
      <div class="dim">${t("upd.have", { v: v.have })}</div>${news}
      <button class="btn wide" disabled=${busy} onClick=${() => act("update_go")}>${t("upd.go", { v: v.next })}</button>
      <div class="dim upd-note">${t("upd.go.about")}</div>`,
    busy: html`${head("", t("upd.ready", { v: v.next }), html`<span class="chip warn">${t("upd.busy.chip")}</span>`)}
      <div class="dim">${t("upd.have", { v: v.have })}</div>${news}
      <div class="upd-k attn">${t("upd.busy.cut", { n: busyList.length })}</div>${busyList.map(updWho)}
      <div class="dim upd-note">${t("upd.busy.safe")}</div>
      <button class="btn wide" disabled=${busy} onClick=${() => act("update_wait")}>${t("upd.wait.go")}</button>
      <div class="dim upd-note">${t("upd.wait.idle")}</div>`,
    wait: html`${head(html`<span class="upd-attn">${ic("auto", 17)}</span>`, t("upd.wait", { v: v.next }), html`<span class="chip warn">${t("upd.wait.chip")}</span>`)}
      ${busyList.length ? html`<div class="upd-k">${t("upd.wait.left", { n: busyList.length })}</div>${busyList.map(updWho)}` : html`<div class="dim upd-note">${t("upd.wait.none")}</div>`}
      <div class="dim upd-note">${t("upd.wait.about")}</div>
      <button class="btn ghost wide" disabled=${busy} onClick=${() => act("update_cancel")}>${t("upd.cancel")}</button>`,
    run: html`${head(updSpin, t("upd.run", { v: v.next }), "")}
      <div class="upd-steps">${at === 3 ? html`<div class="cur">${updSpin} ${t("upd.run.back", { v: v.have })}</div>` : html`
        <div class=${at === 0 ? "cur" : ""}>${mark(0)} ${t("upd.run.keep", { v: v.have })}</div>
        <div class=${at === 1 ? "cur" : ""}>${mark(1)} ${t("upd.run.files", { v: v.next })}</div>
        <div class=${at === 2 ? "cur" : ""}>${mark(2)} ${t("upd.run.check")}</div>`}</div>
      <div class="dim upd-note">${t("upd.run.about")}</div>`,
    fail: html`${head(html`<span class="upd-bad">${ic("alert", 17)}</span>`, t(v.back ? "upd.fail" : "upd.fail.kept", { v: v.next }),
        html`<span class="chip bad">${t(v.back ? "upd.fail.chip" : "upd.fail.chip.kept")}</span>`, "bad")}
      <div>${t(v.back ? "upd.fail.back" : "upd.fail.stays", { v: v.have })}</div>
      <div class="dim upd-note">${t("upd.fail.why", { why: updWhy(v.why) })}</div>
      ${v.detail ? html`<div class="upd-detail mono">${v.detail}</div>` : ""}
      <div class="dim upd-note">${t("upd.fail.again", { v: v.next })}</div>`,
    na: html`${head("", t("upd.ok", { v: v.have }), "")}<div class="dim">${t("upd.na." + (v.why === "windows" ? "windows" : "norepo"))}</div>`,
  }[v.state] || "";
  const hist = v.hist || [];
  return html`${row && v.state === "ok" ? (v.dir ? html`<div class="dim">${t("upd.ok.from", { dir: v.dir, commit: v.commit })}</div>` : "") : body}
    ${hist.length ? html`<details class="upd-hist"><summary>${t("upd.hist", { n: hist.length })}</summary>
      ${hist.map((x, i) => html`<div class="login" key=${i}><span class=${x.ok ? "ok" : "bad"}>${ic(x.ok ? "check" : "x", 14)} ${ago(x.ts)}</span>
        <span class="dim">${x.ok ? [x.from, x.to].filter(Boolean).join(" → ") : t(x.from && x.from !== x.to ? "upd.hist.failed" : "upd.hist.kept", { to: x.to, from: x.from })} · ${tOr("upd.how." + x.how, x.how)}</span></div>`)}</details>` : ""}`;
}

// Settings, a computer before stage U2: the "Pult" block alone (before stage U the computer doesn't know the request:
// no block then)
function UpdCard() {
  const [v, , set] = useLive(() => api("update"), [], null, 10000);
  useEffect(() => noteUpd(v && v.state), [v && v.state]);
  if (!v) return "";
  return html`<h3>${t("upd.h")}</h3><div class=${"card upg upd-s-" + v.state}><${UpdBody} v=${v} set=${set}/></div>`;
}

// stage U2: every part of Pult in one table — what is there, how far behind the source folder's branch (main), who
// brings it up to date. A tap opens a row: the details and who does it; the computer's row holds the install block.
// The phone's row is the app's own: only it knows which copy it runs
const PART_IC = { mac: "monitor", web: "server", relay: "relay", phone: "phone", tabs: "tabs", hooks: "hook", cc: "spark", gh: "tag" };
const ddmm = (ts) => toDate(ts).toLocaleDateString(locale(), { day: "2-digit", month: "2-digit" });
const dayOrTime = (ts) => (toDate(ts).toDateString() === new Date().toDateString() ? hhmm(toDate(ts)) : ddmm(ts));
const commits = (n) => n + "\u00a0" + plural(n, "commit");

function partChip(r, b) {
  if (r.st === "ok") return t("pt." + r.k + ".ok", { b });
  if (r.k === "mac") return r.upd.state === "run" ? t("pt.mac.run") : r.upd.state === "fail" ? t("upd.fail.chip")
    : r.upd.state === "na" ? t(r.upd.why === "windows" ? "pt.mac.win" : "pt.unknown") : r.n ? "\u2212" + commits(r.n) : t("upd.ready.chip");
  if (r.k === "web" || r.k === "relay") return r.st === "warn" ? "\u2212" + commits(r.n) : t(r.why === "other" ? "pt.other" : "pt.unknown", { b });
  if (r.k === "phone") return t(r.st === "warn" ? "pt.phone.old" : "pt.unknown");
  if (r.k === "tabs") return t("pt.tabs.old", { n: r.n_old });
  if (r.k === "hooks") return r.have ? t("pt.hooks.missing", { n: r.missing.length }) : t("pt.hooks.off");
  if (r.k === "cc") return t(r.st === "bad" ? "pt.cc.off" : r.st === "attn" ? "pt.cc.fresh" : "pt.cc.nowrap");
  if (r.k === "gh") return t("pt.gh.waiting", { n: r.waiting });
  return "";
}

function partHave(r) {
  if (r.have == null) return "\u2014";
  if (r.k === "web" || r.k === "relay") return ddmm(r.have);
  if (r.k === "phone") return dayOrTime(+r.have);
  if (r.k === "hooks") return t("pt.hooks.have", { n: r.have, all: r.all });
  return String(r.have);
}

const who = (icon, text) => html`<div class="who">${ic(icon, 14)}<span>${text}</span></div>`;
const newsList = (xs) => (xs && xs.length ? html`<ul class="upd-news">${xs.map((x, i) => html`<li key=${i}>${x}</li>`)}</ul>` : "");

function PartMore({ r, set, b }) {
  if (r.k === "mac") return html`${r.n ? html`<div class="dim">${t("pt.lag.short", { n: commits(r.n), since: ddmm(r.since), b })}</div>` : ""}
    <${UpdBody} v=${r.upd} set=${set} row=${true}/>`;
  if (r.k === "web" || r.k === "relay") {
    if (r.st === "info") return html`<div class="dim">${t("pt.why." + r.why, { b })}</div>`;
    return html`<div class="dim">${t("pt." + r.k + ".from", { commit: r.commit, d: ddmm(r.have) })}</div>
      ${r.n ? html`<div class="dim upd-note">${t("pt.lag", { n: commits(r.n), since: ddmm(r.since), b })}</div>${newsList(r.news)}
      ${who("server", t("pt.web.who"))}` : ""}`;
  }
  if (r.k === "phone") {
    if (r.st === "ok") return html`<div class="dim">${t("pt.phone.same")}</div>`;
    if (r.st === "info") return html`<div class="dim">${t("pt.phone.unknown")}</div>`;
    return html`<div class="dim">${t("pt.phone.diff", { mine: dayOrTime(+r.have), srv: dayOrTime(+r.srv) })}</div>
      <button class="btn wide" onClick=${() => location.reload()}>${t("pt.phone.reload")}</button>`;
  }
  if (r.k === "tabs") {
    if (!r.have) return html`<div class="dim">${t("pt.tabs.none")}</div>`;
    return html`<div class="dim">${t(r.old.length || r.unknown ? "pt.tabs.some" : "pt.tabs.all", { n: r.have })}</div>
      ${r.old.length ? html`<div class="upd-note">${t("pt.tabs.oldin", { list: r.old.join(", ") })}</div>
      <div class="dim upd-note">${t("pt.tabs.works")}</div>${who("monitor", t("pt.tabs.who"))}` : ""}
      ${r.unknown ? html`<div class="dim upd-note">${t("pt.tabs.unknown", { n: r.unknown })}</div>` : ""}`;
  }
  if (r.k === "hooks") {
    if (r.st === "ok") return html`<div class="dim">${t("pt.hooks.all", { n: r.all })}</div>`;
    return html`<div>${r.have ? t("pt.hooks.no", { list: r.missing.join(", ") }) : t("pt.hooks.none")}</div>
      ${who("monitor", t("pt.hooks.who"))}`;
  }
  if (r.k === "cc") {
    if (!r.wrapped) return html`<div class="dim">${t("pt.cc.nowrap.about")}</div>${r.cli ? html`<div class="dim upd-note">${t("pt.cc.app", { cli: r.cli, sdk: r.sdk })}</div>` : ""}`;
    return html`${r.off.length ? html`<div>${t("pt.cc.offin", { v: r.off.join(", "), ok: r.verified || "?" })}</div>`
        : html`<div>${t("pt.cc.runs", { v: r.have, ok: r.verified || "?" })}</div>`}
      ${r.fresh ? html`<div class="dim upd-note">${t("pt.cc.next", { v: r.fresh })}</div>` : ""}
      ${r.cli ? html`<div class="dim upd-note">${t("pt.cc.app", { cli: r.cli, sdk: r.sdk })}</div>` : ""}
      ${r.off.length || r.fresh ? who("term", t("pt.cc.who", { v: r.off[r.off.length - 1] || r.fresh })) : ""}`;
  }
  if (r.k === "gh") return html`<div class="dim">${t("pt.gh.last", { v: r.have, d: r.date })}</div>
    ${r.waiting ? html`<div class="dim upd-note">${t("pt.gh.todo", { n: r.waiting })}</div>${who("term", t("pt.gh.who"))}` : ""}`;
  return "";
}

function Parts() {
  const [d, err, set] = useLive(() => api("parts"), [], (m) => m.kind === "update", 10000);
  const [open, setOpen] = useState(undefined);       // undefined — nothing tapped yet
  useServed();
  useEffect(() => { checkServed(true); }, []);
  const mac = d && d.rows.find((r) => r.k === "mac");
  useEffect(() => noteUpd(mac && mac.upd.state), [mac && mac.upd.state]);
  // the computer's row stands open while there is something to do with it — Home's line about it leads here
  const shown = open !== undefined ? open : mac && mac.upd.state !== "ok" && mac.upd.state !== "na" ? "mac" : null;
  if (err && !d) return html`<${UpdCard}/>`;      // a computer before stage U2 ("no such request: parts"), or a failure
  if (!d) return "";
  const reload = () => api("parts").then(set).catch(() => {});
  const rows = d.rows.slice();
  if (OWN_V) {
    const ph = { k: "phone", have: OWN_V, srv: served.v, st: !served.v ? "info" : phoneOld() ? "warn" : "ok" };
    const at = rows.findIndex((r) => r.k === "tabs" || r.k === "hooks");
    rows.splice(at < 0 ? rows.length : at, 0, ph);
  }
  const b = d.branch || "main";
  const late = rows.filter((r) => r.st === "warn" || r.st === "bad").length, note = rows.filter((r) => r.st === "attn").length;
  return html`<h3>${t("pt.h")}</h3><div class=${"card upg parts upd-s-" + mac.upd.state}>
    <div class="upd-h"><b>${late ? html`<span class="upd-attn">${ic("up", 17)}</span>` : html`<span class="upd-ok">${ic("check", 17)}</span>`}
      ${late ? t("pt.late", { n: late, all: rows.length }) : t("pt.allok", { b })}</b>
      <span class=${"chip " + (late || note ? "warn" : "ok")}>${late ? t("pt.chip.late") : note ? t("pt.chip.note", { n: note }) : t("upd.ok.chip")}</span></div>
    <div class="parts-t">
      <div class="parts-hd"><span>${t("pt.col.part")}</span><span>${t("pt.col.have")}</span><span>${t("pt.col.lag", { b })}</span></div>
      ${rows.map((r) => html`<div class=${"part st-" + r.st + (shown === r.k ? " open" : "")} key=${r.k} data-k=${r.k}>
        <button class="part-r" aria-expanded=${shown === r.k} onClick=${() => setOpen(shown === r.k ? null : r.k)}>
          <span class="part-ic">${ic(PART_IC[r.k], 18)}</span>
          <span class="part-n"><b>${t("pt." + r.k)}</b><span class="dim">${t("pt." + r.k + ".sub")}</span></span>
          <span class="part-v mono">${partHave(r)}</span>
          <span class=${"pchip " + r.st}>${r.st === "ok" ? ic("check", 13) : ""}${partChip(r, b)}</span>
        </button>
        ${shown === r.k ? html`<div class="part-x"><${PartMore} r=${r} set=${reload} b=${b}/></div>` : ""}
      </div>`)}
    </div>
    ${d.head ? html`<div class="dim parts-f">${t("pt.foot", { b, head: d.head, hm: hhmm(toDate(d.at)) })}</div>` : ""}
  </div>`;
}

function Settings() {
  const [d, err, set] = useLive(() => api("settings"), [], () => false);
  const [key, setKey] = useState("");
  const [kbusy, setKbusy] = useState(false);
  const [words, setWords] = useState(null);        // null — as saved on the computer
  const [pick, setPick] = useState(false);          // the default model and effort, in the same menu as a new task's
  const [openPick, closePick] = useOverlay(pick, setPick);
  if (!d) return html`<${Loading} err=${err}/>`;
  useLang(d.prefs.lang);
  const toggle = async (k) => {
    try { const p = await api("prefs", { [k]: !d.prefs[k] }); set(Object.assign({}, d, { prefs: Object.assign({}, d.prefs, p) })); haptic("success"); }
    catch (e) { alertBox(e.message); }
  };
  // a switch: one line under it, the rest behind "More"
  const sw = (k, label, hint, more) => html`<div class="item sw-row">
    <button class="sw-h" role="switch" aria-checked=${!!d.prefs[k]} onClick=${() => toggle(k)}><b>${label}</b><span class=${"sw" + (d.prefs[k] ? " on" : "")}></span></button>
    <div class="dim">${hint}</div>${more ? html`<${About} text=${more} label=${t("more")}/>` : ""}</div>`;
  const setLangPref = async (k) => {
    try { await api("prefs", { lang: k }); set(Object.assign({}, d, { prefs: Object.assign({}, d.prefs, { lang: k }) })); useLang(k); haptic("success"); }
    catch (e) { alertBox(e.message); }
  };
  const setPace = async (n) => {
    try { const p = await api("prefs", { pace: n }); set(Object.assign({}, d, { prefs: Object.assign({}, d.prefs, p) })); haptic("success"); }
    catch (e) { alertBox(e.message); }
  };
  const setChoice = async (c) => {
    try { const p = await api("prefs", c); set(Object.assign({}, d, { prefs: Object.assign({}, d.prefs, p) })); haptic("success"); }
    catch (e) { alertBox(e.message); }
  };
  const saveKey = async (k) => {
    setKbusy(true);
    try { const r = await api("stt_key", { key: k.trim() }); set(Object.assign({}, d, { stt: Object.assign({}, d.stt || {}, { on: r.on }) })); setKey(""); haptic("success"); alertBox(t(r.on ? "voice.saved" : "voice.removed")); }
    catch (e) { alertBox(e.message); }
    setKbusy(false);
  };
  const saveWords = async () => {
    setKbusy(true);
    try { const r = await api("stt_words", { words }); set(Object.assign({}, d, { stt: Object.assign({}, d.stt, { words: r.words }) })); setWords(null); haptic("success"); }
    catch (e) { alertBox(e.message); }
    setKbusy(false);
  };
  return html`<div><h2>${t("settings")}</h2>
    <${Parts}/>
    ${"model" in d.prefs ? html`<h3>${t("model.pick")}</h3>
    <button class="field" onClick=${openPick}><span>${choiceText(d.prefs.model, d.prefs.effort)}</span><span class="dim">${ic("down", 18)}</span></button>
    <div class="dim small">${t("def.about")}</div>
    ${pick && html`<${ChoicePick} model=${d.prefs.model} effort=${d.prefs.effort} def=${d.cc} top=${t("pick.as.cc.short")}
      note=${t("def.cc.note")} onClose=${closePick} onPick=${setChoice}/>`}` : ""}
    <h3>${t("notifications")}</h3><div class="list">${sw("pager", t("pager"), t("pager.short"), t("pager.about"))}${d.prefs.pager ? "" : sw("vehi", t("vehi"), t("vehi.about"))}${sw("brief", t("brief"), t("brief.short"), t("brief.about"))}</div>
    <h3>${t("where")}</h3>
    <${ModePick} mode=${d.prefs.mode} pager=${d.prefs.pager} onSet=${(m) => set(Object.assign({}, d, { prefs: Object.assign({}, d.prefs, { mode: m }) }))}/>
    ${d.prefs.pace ? html`<h3>${t("pace")}</h3>
    <div class="seg">${[85, 90, 95].map((n) => html`<button key=${n} class=${d.prefs.pace === n ? "on" : ""} onClick=${() => setPace(n)}>${n}\u00a0%</button>`)}</div>
    <div class="dim small">${t("pace.about", { n: d.prefs.pace })}</div>` : ""}
    <h3>${t("language")}</h3>
    <div class="seg">${[["en", "English"], ["ru", "Русский"]].map(([k, label]) => html`<button key=${k}
      class=${d.prefs.lang === k ? "on" : ""} onClick=${() => setLangPref(k)}>${label}</button>`)}</div>
    <h3>${t("voice")}</h3><div class="list"><div class="item static">
      <div>${d.stt && d.stt.on ? t("voice.on") : t("voice.off")}</div>
      <div class="dim">${t("voice.privacy", { lang: (d.stt && d.stt.lang) || "auto" })}</div>
      <div class="keyrow"><input type="password" ref=${plainField} placeholder=${t("voice.key")} value=${key} onInput=${(e) => setKey(e.target.value)}/>
        <button class="btn" disabled=${!key.trim() || kbusy} onClick=${() => saveKey(key)}>${t("voice.save")}</button></div>
      ${d.stt && d.stt.on ? html`<button class="link" disabled=${kbusy} onClick=${() => saveKey("")}>${t("voice.remove")}</button>` : ""}
    </div>
    ${d.stt && d.stt.on && typeof d.stt.words === "string" ? html`<div class="item static">
      <div>${t("voice.words")}</div><div class="dim">${t("voice.words.about")}</div>
      <div class="keyrow"><input ref=${plainField} maxlength="280" placeholder=${t("voice.words.ph")} value=${words === null ? d.stt.words : words} onInput=${(e) => setWords(e.target.value)}/>
        <button class="btn" disabled=${words === null || words.trim() === d.stt.words || kbusy} onClick=${saveWords}>${t("voice.save")}</button></div>
    </div>` : ""}</div>
    <${Logins}/>
    <h3>${t("status")}</h3><div class="list"><div class="item static">
      <div>${t("status.pult", { v: d.version, mac: d.mac.away ? t("mac.away", { dur: dur(d.mac.idle) }) : t("mac.here") })}</div>
      <div class="dim">${t("status.tg", { how: t("tg." + (d.telegram === "proxy" ? "proxy" : "direct")) })}</div>
    </div></div>
    <details class="logbox"><summary>${t("log", { n: d.log.length })}</summary>
      <pre class="log">${d.log.slice().reverse().join("\n")}</pre></details>
  </div>`;
}

// the app's recent logins: when, from which network and device, how — and a way to log every window out
// logins in a row from the same window, network and device read as one line: "8 times", the latest time
const runs = (xs) => xs.reduce((out, x) => {
  const last = out[out.length - 1];
  if (last && last.ok === x.ok && last.how === x.how && last.net === x.net && last.dev === x.dev) last.n += 1;
  else out.push(Object.assign({ n: 1 }, x));
  return out;
}, []);
function Logins() {
  const [d] = useLive(() => api("logins"), [], () => false);
  if (!d) return "";
  const out = async () => {
    if (!(await confirmBox(t("logins.confirm")))) return;
    try { await api("logout_all"); haptic("success"); } catch (e) { alertBox(e.message); }
  };
  return html`<h3>${t("logins")}</h3><div class="list"><div class="item static">
    ${d.locked ? html`<div class="warn">${t("logins.locked", { files: d.locked })}</div>` : ""}
    ${runs(d.logins).slice(0, 8).map((x, i) => html`<div class="login" key=${i}>
      <span class=${x.ok ? "ok" : "bad"}>${ic(x.ok ? "check" : "x", 14)} ${ago(x.ts)}</span>
      <span class="dim">${[t("logins.how." + x.how), x.net, x.dev, x.n > 1 ? t("logins.times", { n: x.n, times: plural(x.n, "time") }) : ""].filter(Boolean).join(" · ")}</span></div>`)}
    ${d.logins.length ? "" : html`<div class="dim">${t("logins.none")}</div>`}
    <button class="link danger" onClick=${out}>${t("logins.out")}</button>
  </div></div>`;
}

// every project in one list, in the same grammar as the board: who waits, who works, the latest outcome; quiet ones last
function Projects() {
  const [d, err] = useLive(() => api("projects"), []);          // live: the counts change with every turn
  if (!d) return html`<${Loading} err=${err}/>`;
  const add = d.create && html`<div class="stick"><button class="btn wide" onClick=${() => go("#/newproject")}>${t("np.create")}</button></div>`;
  if (!d.projects.length) return html`<div><h2>${t("projects")}</h2><div class="empty">${t("projects.none")}</div>${add}</div>`;
  return html`<div><h2>${t("projects")}</h2><div class="list">${d.projects.map((p) => html`
    <button class=${"item proj-h" + (p.mine || p.work || p.open ? "" : " rest")} key=${p.pkey} onClick=${() => go("#/p/" + encodeURIComponent(p.pkey))}>
      <span class="pname">${avatar(p.name, 34)}<span class="pn"><b>${p.name}</b><span class="dim pmeta">${dotted([
        p.work ? html`<span class="cnt">${dot("work")}${p.work}</span>` : "", p.mine ? html`<span class="cnt">${dot("attn")}${p.mine}</span>` : "",
        p.turns ? t("proj.turns", { n: p.turns, turns: plural(p.turns, "turn") }) : agoShort(p.last)])}</span>
        <span class="ln pline">${p.line || html`<span class="path">${p.path}</span>`}</span></span>${ic("chev", 16)}</span></button>`)}</div>${add}</div>`;
}

// a project's screen — its board, large: what waits for you (answer right here), what runs, today's outcomes, then
// the earlier sessions folded; a new task at the bottom, under the thumb. A red mark anywhere leads here or deeper
// the project's sections with how many of the screen's tasks each has (stage T); a tap narrows every list on the
// screen to that section and shows its topics in a second row; a second tap or "All" brings everything back
function TagBar({ set, sel, top, all, onSel, onTop }) {
  const sec = sel && set.find((g) => g.n === sel);
  return html`<div class="tagbar" role="toolbar">
    <button class=${"tagf" + (sel ? "" : " on")} onClick=${() => onSel(null)}>${t("tags.all")}<span>${all}</span></button>
    ${set.map((g) => html`<button key=${g.n} class=${"tagf" + (sel === g.n ? " on" : "")} style=${tagSt(g.c)}
      onClick=${() => onSel(sel === g.n ? null : g.n)}><i></i>${g.n}<span>${g.cnt}</span></button>`)}
  </div>
  ${sec && sec.topics.length > 1 && html`<div class="tagbar sub" style=${tagSt(sec.c)}>
    <button class=${"tagf" + (top ? "" : " on")} onClick=${() => onTop(null)}>${t("tags.topics.all")}<span>${sec.cnt}</span></button>
    ${sec.topics.map((x) => html`<button key=${x.n} class=${"tagf" + (top === x.n ? " on" : "")} onClick=${() => onTop(top === x.n ? null : x.n)}>${x.n}<span>${x.cnt}</span></button>`)}
  </div>`}`;
}

function Project({ pkey, tag, topic }) {
  const now = useNow(1000);
  const [d, err, set] = useLive(() => api("project", { pkey }), [pkey]);
  const [more, setMore] = useState(false);
  const [sel, setSel0] = useState(tag || null);           // stage T: the section the lists are narrowed to, and its topic
  const [top, setTop] = useState(topic || null);
  const setSel = (v) => { setSel0(v); setTop(null); };
  const [bgFor, setBgFor] = useState(null);
  const [openBg, closeBg] = useOverlay(!!bgFor, (v) => { if (!v) setBgFor(null); });
  const yours = useRcpt(d ? moves(d.pending, d.mine) : [], moveKey);           // as on Home: one line by time
  if (!d) return html`<${Loading} err=${err}/>`;
  const onBg = (s) => { setBgFor(s.sid); openBg(); };
  const gone = (sid) => set(Object.assign({}, d, { mine: d.mine.filter((r) => r.sid !== sid) }));
  const tagsOf = new Map([...d.mine, ...d.live, ...d.today, ...d.earlier].map((r) => [r.sid, r.tags || []]));
  const has = (sid) => { const g = tagsOf.get(sid) || []; return !sel || (g[0] && g[0].n === sel && (!top || (g[1] && g[1].n === top))); };
  const mineF = yours.filter((e) => has(e.req ? e.req.sid : e.mine.sid));
  const liveF = d.live.filter((r) => has(r.sid)), todayF = d.today.filter((r) => has(r.sid)), earlierF = d.earlier.filter((r) => has(r.sid));
  const waits = sel ? mineF.length : d.pending.length + d.mine.length;
  const sum = d.turns ? t("sum.today", { n: d.turns, turns: plural(d.turns, "turn"), dur: dur(d.secs) }) : t("proj.quiet");
  return html`<div class="project">
    <div class="ph">${avatar(d.name, 44)}<div><h2>${d.name}</h2><div class="sum dim">${sum}</div></div></div>
    ${d.tagset && d.tagset.length > 0 && html`<${TagBar} set=${d.tagset} sel=${sel} top=${top} all=${tagsOf.size} onSel=${setSel} onTop=${setTop}/>`}
    ${(waits > 0 || mineF.length > 0) && html`<h3>${t("proj.waits", { n: waits })}</h3>
      ${mineF.map((e) => e.req ? html`<${Req} key=${e.key} r=${e.req} showProject=${false}/>`
        : html`<${Mine} key=${e.key} r=${Object.assign({ reset: d.reset }, e.mine)} now=${now} onGot=${gone} stt=${d.stt} showProject=${false}/>`)}`}
    ${liveF.length > 0 && html`<h3>${t("proj.live", { n: liveF.length })}</h3><div class="list">${liveF.map((r) => html`<${BoardRow} key=${r.sid} r=${r} now=${now} onBg=${onBg}/>`)}</div>`}
    ${todayF.length > 0 && html`<h3>${t("proj.today")}</h3><div class="list">${todayF.map((r) => html`<${BoardRow} key=${r.sid} r=${r} now=${now} onBg=${onBg}/>`)}</div>`}
    ${!waits && !mineF.length && !liveF.length && !todayF.length && !(sel && earlierF.length) && html`<div class="empty small">${t("proj.nothing")}</div>`}
    ${earlierF.length > 0 && html`<h3 class="toggle" onClick=${() => setMore(!more)}>${t("proj.earlier", { n: earlierF.length })} <span class=${"chev" + (more || sel ? " open" : "")}>${ic("chev", 14)}</span></h3>
      ${(more || sel) && html`<div class="list">${earlierF.map((x) => html`<button class="item brow rest" key=${x.sid} onClick=${() => go("#/s/" + x.sid)}>
        <div class="item-h"><b>${x.driven ? html`<span class="st-ic">${ic("phone", 14)}</span>` : ""}${x.title}</b><span class="meta"><span class="dim nowrap">${agoShort(x.last)}</span></span></div>
        ${x.line || x.open || (x.tags && x.tags.length > 0) ? html`<div class="ln">${tagChips(x.tags)}${x.line || (x.open ? t("open.mac") : "")}</div>` : ""}</button>`)}</div>`}`}
    <div class="stick"><button class="btn wide" onClick=${() => go("#/new?pkey=" + encodeURIComponent(pkey))}>${t("project.new")}</button></div>
    ${bgFor && html`<${BgSheet} sid=${bgFor} fixed=${true} onClose=${closeBg}/>`}
  </div>`;
}

// a task's tags (stage T): its section, then a topic in it. "Claude picks them" leaves both to Claude; a tap on another
// section or on a topic makes the choice the owner's, and Claude never changes it again. Each tap is saved at once,
// as in the model menu; a new section or topic by name, right here
function TagPick({ sid, info, onDone, onClose }) {
  const [tags, setTags] = useState(info.tags || []);
  const [set, setSet] = useState(info.tagset || []);
  const [auto, setAuto] = useState(info.tag_auto !== false);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(null);          // "sec" | "topic": the field for a new name is open
  const [name, setName] = useState("");
  const sec = tags[0] ? tags[0].n : null, top = tags[1] ? tags[1].n : null;
  const cur = set.find((g) => g.n === sec);
  const pick = async (args) => {
    setBusy(true);
    try { const r = await api("tag", Object.assign({ sid }, args)); haptic("success"); setTags(r.tags || []); setSet(r.tagset || []); setAuto(!!r.auto); onDone(); }
    catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  const add = (e) => {
    e.preventDefault();
    const v = name.trim();
    if (!v) return;
    const kind = adding;
    setAdding(null); setName("");
    pick(kind === "sec" ? { sec: v } : { sec, topic: v });
  };
  const field = (kind) => (adding === kind ? html`<form class="tagnew" onSubmit=${add}><input value=${name} placeholder=${t("tags.name")} maxlength="32"
      autocomplete="off" onInput=${(e) => setName(e.target.value)} ref=${(el) => el && !el.dataset.on && ((el.dataset.on = "1"), el.focus())}/>
      <button class="btn" disabled=${busy || !name.trim()}>${t("tags.add")}</button></form>`
    : html`<button class="tagf add" disabled=${busy} onClick=${() => { setAdding(kind); setName(""); }}>${ic("plus", 14)} ${t(kind === "sec" ? "tags.sec.new" : "tags.topic.new")}</button>`);
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick tall tagpick"><div class="q-t pick-h">${t("tags.task")}<button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></div>
    <button class=${"opt auto" + (auto ? " on" : "")} disabled=${busy} onClick=${() => { if (!auto) pick({ auto: true }); }}>${ic("auto", 16)}<span class="tn">${t("tags.auto")}</span>${auto ? ic("check", 16) : ""}<span class="dim">${t("tags.auto.about")}</span></button>
    <div class="pick-t">${t("tags.sec")}</div>
    <div class="pills">${set.map((g) => html`<button key=${g.n} class=${"tagf" + (sec === g.n ? " on" : "") + (g.fresh ? " fresh" : "")} style=${tagSt(g.c)} disabled=${busy}
      onClick=${() => { if (sec !== g.n) pick({ sec: g.n }); }}><i></i>${g.n}</button>`)}${field("sec")}</div>
    ${sec && html`<div class="pick-t">${t("tags.topic")}</div>
    <div class="pills" style=${cur ? tagSt(cur.c) : ""}>${(cur ? cur.topics : []).map((x) => html`<button key=${x.n} class=${"tagf topic" + (top === x.n ? " on" : "") + (x.fresh ? " fresh" : "")} disabled=${busy}
      onClick=${() => pick({ sec, topic: top === x.n ? "" : x.n })}>${x.n}</button>`)}${field("topic")}</div>`}
    <div class="dim small">${t("tags.mine")}</div></div>`;
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
    <button class="steps-h" onClick=${() => setOpen(!open)}><span class=${"chev" + (open ? " open" : "")}>${ic("chev", 14)}</span>${label}${bad ? html` · <span class="bad">${t("steps.bad", { n: bad })}</span>` : ""}
      <span class="dim">${open ? "" : " · " + (last.k === "update" ? brief(last.text, 90) : last.step)}</span></button>
    ${open && steps.map((s, n) => s.k === "update" ? html`<div class="upd" key=${"u" + n}>${s.text}</div>` : html`<div class="step" key=${s.id}>
      <button class="step-h" onClick=${() => setOne(one === s.id ? null : s.id)}><span class="dim">${s.ts ? hhmm(toDate(s.ts)) + " " : ""}</span>${s.ok === false ? html`<span class="bad">${ic("alert", 13)} </span>` : ""}${s.step}</button>
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
// your message's ticks (Q56), as in a messenger: the clock — on its way to the computer; ✓ — the computer has it, Claude
// reads it after the step it is on; ✓✓ — Claude read it (every message of yours in the chat); ✕ — it didn't reach Claude
const TICKS = { sending: "clock", sent: "check", read: "checks", gone: "x" };
const tickMark = (st) => html`<span class=${"tick " + st} role="img" aria-label=${t("out." + st)}>${ic(TICKS[st], 14)}</span>`;
const At = ({ ts, mid, st }) => (ts ? html`<span class="t">${mid ? t("mid.turn") : ""}${hhmm(toDate(ts))}${st ? tickMark(st) : ""}</span>` : "");

// your messages on their way (Q56), oldest first: the computer's outbox (info.out) wins over what this screen has just
// sent (by id); one the chat already has — the same words, written no earlier than it was sent — is not shown twice. They
// come before the session's state ("working…", the queue): the state stays under the message you just sent instead of
// standing above it until the chat has it, then jumping below (2026-10-25)
function onTheWay(items, server, local) {
  const ids = new Set(server.map((o) => o.id));
  // before the answer brings its id, the outbox may already have it: the same words, sent about then
  const all = [...server, ...local.filter((x) => (x.id ? !ids.has(x.id) : !server.some((o) => o.text === x.text && o.ts >= x.ts - 120)))];
  const own = items.slice(-80).filter((i) => i.k === "user"), used = new Set();
  return all.filter((o) => {
    const k = own.findIndex((i, n) => !used.has(n) && i.text === o.text
      && (!i.ts || toDate(i.ts).getTime() / 1000 >= o.ts - (o.key ? 120 : 5)));     // the phone's clock may be off
    if (k < 0) return true;
    used.add(k);
    return false;
  });
}

// one of Claude's messages; a long one that is not the last is folded to a few lines — "Show all" opens it
const LONG = 900;
function TextMsg({ i, fold }) {
  const [open, setOpen] = useState(false);
  const folded = fold && !open;
  return html`<div class="msg"><div class=${"md" + (folded ? " fold" : "")} dangerouslySetInnerHTML=${{ __html: md(i.text) }}/>
    ${fold ? html`<button class="link more2" onClick=${() => setOpen(!open)}>${t(open ? "msg.less" : "msg.more")}</button>` : ""}
    ${i.att && i.att.length ? html`<div class="atts shown">${i.att.map((a, k) => html`<${Pic} key=${k} a=${a} all=${i.att}/>`)}</div>` : ""}<${At} ts=${i.ts}/></div>`;
}

// how the session's last turn ended, at the end of the chat right above the field: what came out, what is needed,
// ready replies (or "continue after the reset"). Red while it waited for you when you opened it; a plain report gets
// no card — the whole answer is right above
// the session's last outcome at the end of the chat; one that waits for a decision stays "your move" on Home after
// reading — "Got it" here puts it to rest without an answer
// the files the turn made or changed in the project (stage F4): one line in the outcome, a tap opens their screen
const fsize = (b) => (b >= 1048576 ? t("size.mb", { n: num(b / 1048576, 1) }) : t("size.kb", { n: Math.max(1, Math.round(b / 1024)) }));
function TurnLine({ sid, tf }) {
  return html`<a class="tfline" href=${"#/f/" + sid + "?t=" + tf.id}><span>${ic("clip", 17)} ${t("files.line", { n: tf.n, size: fsize(tf.size) })}</span><span class="dim">${ic("chev", 16)}</span></a>`;
}

// the screen of a turn's files: ‹ › through the session's turns that had files; nothing ticked at first, since the
// list is everything the turn touched, side files too (decision Q43); more than ZIP_FROM go only as one archive (Q44)
const ZIP_FROM = 10;
function turnWhen(ts) {
  const d = toDate(ts);
  return d.toDateString() === new Date().toDateString() ? hhmm(d) : d.toLocaleDateString(locale(), { day: "numeric", month: "short" }) + " " + hhmm(d);
}
function TurnFilesScreen({ sid, turn }) {
  const [cur, setCur] = useState(turn);
  useEffect(() => setCur(turn), [turn]);
  const [d, err] = useLive(() => api("turn_files", { sid, turn: cur }), [sid, cur], () => false, 600000);
  const [pick, setPick] = useState({});
  const [sent, setSent] = useState({});
  const [zip, setZip] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  useEffect(() => { setPick({}); setSent({}); setZip(false); setNote(""); }, [cur]);
  if (!d) return html`<${Loading} err=${err}/>`;
  if (!d.id) return html`<div><h2>${t("files.turn")}</h2><div class="empty">${t("files.none")}</div></div>`;
  const can = d.files.filter((f) => !f.gone);
  const chosen = can.filter((f) => pick[f.p]).map((f) => f.p);
  const all = can.length > 0 && chosen.length === can.length;
  const forced = chosen.length > ZIP_FROM;
  const asZip = forced || zip;
  const toggle = (p) => setPick((x) => Object.assign({}, x, { [p]: !x[p] }));
  const toggleAll = () => setPick(all ? {} : Object.fromEntries(can.map((f) => [f.p, true])));
  const send = async () => {
    setBusy(true);
    setNote("");
    try {
      const r = await api("send_files", { sid, paths: chosen, zip: asZip });
      haptic("success");
      setSent((x) => Object.assign({}, x, ...r.sent.map((p) => ({ [p]: true }))));
      setPick({});
      setNote(r.zip ? t("files.zip_sent", { name: r.zip }) : t("files.n_sent", { n: r.sent.length }));
      if (r.refused && r.refused.length) alertBox(r.refused.map(([n, w]) => n + " — " + w).join("\n"));
    } catch (e) { alertBox(e.message); } finally { setBusy(false); }
  };
  return html`<div class="tfs">
    <div class="tf-nav">
      <button class="nv" aria-label=${t("files.prev")} disabled=${d.prev == null} onClick=${() => setCur(d.prev)}>‹</button>
      <div class="tf-h"><b>${t("files.turn_at", { at: turnWhen(d.start) })}${d.dur ? " · " + t("home.took", { dur: dur(d.dur) }) : ""}</b>
        <a class="dim" href=${"#/s/" + sid}>${d.project}${d.title ? " · " + d.title : ""}</a></div>
      <button class="nv" aria-label=${t("files.next")} disabled=${d.next == null} onClick=${() => setCur(d.next)}>›</button>
    </div>
    <div class="list">
      <label class="tf-row tf-all"><input type="checkbox" checked=${all} disabled=${!can.length || busy} onChange=${toggleAll}/>
        <span class="tf-n"><b>${t("files.all_pick")}</b></span><span class="dim nowrap">${t("files.count", { n: chosen.length, of: can.length })}</span></label>
      ${d.files.map((f) => { const cut = Math.max(f.p.lastIndexOf("/"), f.p.lastIndexOf("\\")); return html`<label class=${"tf-row" + (f.gone ? " gone" : "")} key=${f.p}>
        <input type="checkbox" checked=${!!pick[f.p]} disabled=${f.gone || busy} onChange=${() => toggle(f.p)}/>
        <span class="tf-n">${f.p.slice(cut + 1)}<span class="dim"> · ${f.gone ? t("files.gone") : fsize(f.size)}${cut > 0 ? " · " + f.p.slice(0, cut) : ""}</span>${sent[f.p] ? html`<span class="tf-ok"> · ✓ ${t("files.sent")}</span>` : ""}</span>
      </label>`; })}
    </div>
    ${d.n > d.files.length && html`<div class="dim small">${t("files.cut", { n: d.files.length, total: d.n })}</div>`}
    <div class="stick tf-go">
      <label class="tf-zip"><input type="checkbox" checked=${asZip} disabled=${forced || busy} onChange=${() => setZip(!zip)}/>
        <span>${t("files.zip")}${forced ? html`<span class="dim"> · ${t("files.zip_forced", { n: ZIP_FROM })}</span>` : ""}</span></label>
      <button class="btn wide" disabled=${!chosen.length || busy} onClick=${send}>${busy ? "…" : t("files.send_n", { n: chosen.length })}</button>
      ${note && html`<div class="dim tf-note">${ic("check", 14)} ${note}</div>`}
    </div>
  </div>`;
}

// ---------- a project's file from a link in Claude's words (stage F5) ----------

// the tap opens it over the screen, the chat stays where it was underneath; a folder lists its files, and the folder
// in a file's header lists that folder — each step one more in the history, Back goes one down. What may be opened is
// the computer's call, by Telegram's rule: inside the project, nothing like keys or settings
const FV_LINES = 2000;                    // lines put on the screen at once, "More lines" adds as many
const PIC_EXT = /\.(png|jpe?g|gif|webp)$/i;
const lit = (s) => s.replace(/[%#]/g, encodeURIComponent);     // a real name as a link: % and # stay themselves
function FileHost() {
  const [trail, setTrail] = useState([]);
  useEffect(() => on("file", (x) => { overlays++; history.pushState({ overlay: true }, ""); setTrail((tr) => tr.concat([x])); }), []);
  const open = trail.length > 0;
  useEffect(() => {
    if (!open) return undefined;
    const onPop = () => { overlays = Math.max(0, overlays - 1); setTrail((tr) => tr.slice(0, -1)); };
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, [open]);
  useNoFold(open);
  useEffect(() => {                     // a link in a plan on Home: Telegram's Back closes the file, not the app
    if (!open || !tg || !tg.BackButton) return undefined;
    tg.BackButton.show();
    return () => { if (parse().name === "home") tg.BackButton.hide(); };
  }, [open]);
  // every step stays mounted under the next one: Back finds the folder or the page scrolled where it was
  return trail.map((x, k) => html`<${FileView} key=${k} job=${x}/>`);
}
function FileView({ job }) {
  const cut = job.p.indexOf("#");
  const path = cut < 0 ? job.p : job.p.slice(0, cut);
  const line = +((/^L(\d+)/.exec(cut < 0 ? "" : job.p.slice(cut + 1)) || [])[1] || 0);
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const [asText, setAsText] = useState(!!line);       // a page (md, html) as its text: a link to a line wants the text
  const [upto, setUpto] = useState(Math.max(FV_LINES, line + 200));
  const [busy, setBusy] = useState(false);
  const body = useRef(null);
  // a computer before stage F5 doesn't know the request: say what to do, not "no such request"
  useEffect(() => { api("file", { sid: job.sid, p: path, base: job.base || "" })
    .then(setD, (e) => setErr(/: file$/.test(e.message) ? t("fv.old") : e.message)); }, []);
  const lines = useMemo(() => {
    if (!d || d.text == null) return null;
    const ls = d.text.split("\n");
    if (ls.length > 1 && ls[ls.length - 1] === "") ls.pop();
    return ls;
  }, [d]);
  useEffect(() => {                                     // a link to a line: that line in the middle, marked
    const el = line && body.current && body.current.querySelector("#L" + line);
    if (el) el.scrollIntoView({ block: "center" });
  }, [d, asText]);
  const close = () => history.back();
  const openAt = (p) => emit("file", { sid: job.sid, p: lit(p), base: "" });
  const send = async () => {
    setBusy(true);
    try { await api("send_files", { sid: job.sid, paths: [d.p] }); haptic("success"); emit("toast", t("fv.sent")); }
    catch (e) { alertBox(e.message); } finally { setBusy(false); }
  };
  if ((d && d.kind === "pic") || (!d && !err && PIC_EXT.test(path))) {
    const item = d ? { src: "data:image/" + (d.pic === "jpg" ? "jpeg" : d.pic) + ";base64," + d.data } : {};
    return html`<${Viewer} key=${d ? "pic" : "wait"} job=${{ items: [item], send: d && !busy ? send : null }} onClose=${close} then=${() => {}}/>`;
  }
  const last = (x) => x.slice(x.lastIndexOf("/") + 1);
  const folderOf = (x) => x.slice(0, Math.max(0, x.lastIndexOf("/")));
  const name = d ? (d.p ? last(d.p) : d.project) : last(path.replace(/\/+$/, "")) || path;
  const isDir = d && d.kind === "dir";
  const page = d && (d.kind === "md" || d.kind === "html") && d.size > 0;
  // a file's folder, or a folder's own folder: a tap lists it (the project's name stands for its top folder)
  const up = d && (d.p || !isDir) ? html`<button class="link fv-dir" onClick=${() => openAt(folderOf(d.p))}>${ic("folder", 14)} ${folderOf(d.p) || d.project}</button>` : null;
  const sub = !d ? null : isDir ? dotted([up, t("fv.items", { n: d.n, items: plural(d.n, "item") })])
    : dotted([up, fsize(d.size), t("fv.changed", { at: turnWhen(d.mt) })]);
  let view;
  if (err) view = html`<div class="empty">${err}</div>`;
  else if (!d) view = html`<div class="empty">${t("loading")}</div>`;
  else if (isDir) {
    view = html`${d.entries.length ? html`<div class="list fv-list">${d.entries.map((x) => html`<button key=${x.n} class=${"fv-row" + (x.lock ? " lock" : "")}
        disabled=${x.lock} onClick=${() => openAt((d.p ? d.p + "/" : "") + x.n)}>
        ${ic(x.lock ? "lock" : x.dir ? "folder" : PIC_EXT.test(x.n) ? "image" : "file", 18)}<span class="fv-n">${x.n}</span>
        ${x.dir ? html`<span class="dim">${ic("chev", 16)}</span>` : html`<span class="dim nowrap">${fsize(x.size)}</span>`}</button>`)}</div>`
      : html`<div class="empty">${t("fv.dir_empty")}</div>`}
      ${d.n > d.entries.length && html`<div class="dim small">${t("fv.dir_cut", { n: d.entries.length, total: d.n })}</div>`}`;
  } else if (d.kind === "other") view = html`<div class="empty">${t("fv.other")}</div>`;
  else if (!d.size) view = html`<div class="empty">${t("fv.empty")}</div>`;
  else if (page && !asText && d.kind === "md") {
    view = html`<div class="md fv-md" data-sid=${job.sid} data-base=${folderOf(d.p)} dangerouslySetInnerHTML=${{ __html: md(d.text) }}/>`;
  } else if (page && !asText) {
    // the project's own page, drawn but dead: no script runs in it (no allow-scripts, and the app's own rules hold in it),
    // nothing in it reaches the app or the network
    view = html`<iframe class="fv-page" sandbox="" srcdoc=${d.text} title=${name}></iframe>`;
  } else {
    view = html`<div class="fv-code">${lines.slice(0, upto).map((l, k) => html`<div class=${"ln" + (k + 1 === line ? " hit" : "")} id=${"L" + (k + 1)}>
        <span class="n">${k + 1}</span><span class="c">${l || " "}</span></div>`)}</div>
      ${lines.length > upto && html`<button class="link more2" onClick=${() => setUpto(upto + FV_LINES)}>${t("fv.more_lines", { n: lines.length - upto })}</button>`}`;
  }
  return html`<div class="fv" role="dialog" aria-label=${name}>
    <div class="fv-top">
      <button class="fv-b" aria-label=${t("fv.back")} onClick=${close}>${ic("back", 24)}</button>
      <div class="fv-h"><b>${name}</b>${sub && html`<div class="dim">${sub}</div>`}</div>
      ${page && html`<button class="chip fv-t" onClick=${() => setAsText(!asText)}>${t(asText ? "fv.page" : "fv.text")}</button>`}
    </div>
    <div ref=${body} class=${"fv-body" + (page && !asText && d.kind === "html" ? " full" : "")}>${view}
      ${d && d.cut && html`<div class="dim small fv-cut">${t("fv.cut", { total: fsize(d.size) })}</div>`}</div>
    ${d && !isDir && d.size > 0 && html`<div class="fv-bar"><button class="btn wide" disabled=${busy} onClick=${send}>${ic("send", 18)} ${busy ? "…" : t("fv.send")}</button></div>`}
  </div>`;
}

function Outcome({ sid, out, state, now }) {
  const [resume, setResume] = useState(out.resume);
  const [got, setGot] = useState(false);
  const mine = state === "you" || state === "fail";
  const gotIt = async () => {
    try { await api("seen", { sid }); haptic("success"); setGot(true); } catch (err) { alertBox(err.message); }
  };
  const head = state === "fail" ? html`${ic("alert", 14)} ${out.line || t("out.failed")}` : state === "you" ? html`${dot("attn")}${t("out.waits", { dur: dur(now - out.ts) })}` : html`${ic("check", 14)} ${t("out.done")}`;
  return html`<div class=${"card outcome" + (mine ? " mine" : "") + (state === "fail" ? " fail" : "")}>
    <div class="k">${head}${out.dur ? " · " + t("home.took", { dur: dur(out.dur) }) : ""}</div>
    ${state !== "fail" && out.line && html`<div class="o-l"><b>${t("out.line")}</b> ${out.line}</div>`}
    ${out.need && html`<div class="o-l"><b>${t("out.need")}</b> ${out.need}</div>`}
    ${out.fail === "rate_limit" ? html`<${ResumeAt} sid=${sid} resume=${resume} reset=${out.reset} onSet=${setResume}/>` : html`<${Replies} sid=${sid} replies=${out.replies}/>`}
    ${out.turn_files && html`<${TurnLine} sid=${sid} tf=${out.turn_files}/>`}
    ${mine && (out.need || state === "fail") && html`<div class="foot quiet"><span></span>${got ? html`<span class="dim">${ic("check", 14)} ${t("mine.got")}</span>` : html`<button class="link" onClick=${gotIt}>${ic("check", 15)} ${t("mine.got")}</button>`}</div>`}
  </div>`;
}

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
  // what this screen has just sent, until the computer's outbox has it (Q56): the clock at once, ✓ on the answer
  const [sending, setSending] = useState([]);
  const [putBack, setPutBack] = useState([]);       // messages that didn't reach Claude, their words back in the field
  const [pick, setPick] = useState(false);
  const [openPick, closePick] = useOverlay(pick, setPick);
  const [note, setNote] = useState(null);
  const [openNote, closeNote] = useOverlay(!!note, (v) => { if (!v) setNote(null); });
  const [bgs, setBgs] = useState(false);
  const [openBgs, closeBgs] = useOverlay(bgs, setBgs);
  const [tagPick, setTagPick] = useState(false);
  const [openTagPick, closeTagPick] = useOverlay(tagPick, setTagPick);
  const [unread, setUnread] = useState(false);
  const [far, setFar] = useState(false);          // scrolled up more than a screen: a way straight to the bottom
  // your own message that went up past the top of the screen: pinned there, like a pinned message in Telegram;
  // a tap shows it in full. "Your message" is the nearest one above what is on screen — the one being answered
  const [pin, setPin] = useState(null);
  // the header went up past the top — and a session opens at its last message, so mostly it has: a bar at the top
  // keeps the project, the session and its state in sight (the owner couldn't tell which ones were open, 2026-10-23)
  const [away, setAway] = useState(false);
  const [full, setFull] = useState(null);
  const [openFull, closeFull] = useOverlay(!!full, (v) => { if (!v) setFull(null); });
  const pending = useRcpt(s.info ? s.info.pending : []);       // in the chat's order: the latest at the bottom
  const shown = useRef([]);
  const firstOut = useRef(null);       // the outcome as you found it: opening the session marks it seen, the card stays red
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
      const head = document.querySelector(".sess-h");
      setAway(!!head && head.getBoundingClientRect().bottom < 0);
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
    firstOut.current = null;
    let timer;
    if (conn.ready) load("full");
    const offs = [on("ready", () => load("full")),
      on("event", (m) => { if (!m.sid || m.sid === sid) { clearTimeout(timer); timer = setTimeout(() => load("after"), 400); } })];
    return () => { offs.forEach((f) => f()); clearTimeout(timer); };
  }, [sid]);

  // the field fits its words: one line when empty, up to 160 px with a long message
  const fit = () => setTimeout(() => { const el = ta.current; if (el) { el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 160) + "px"; } }, 0);
  // the message goes into the chat at once, as in a messenger (Q56); if it can't go, the words come back to the field
  const sendText = async (fork) => {
    const words = text;
    if (!words.trim() && !a.files.length) return;
    setBusy(true);
    const key = "l" + Date.now();
    setSending((m) => [...m, { key, text: words.trim(), n: a.files.length, ts: Date.now() / 1000, st: "sending" }]);
    setText("");
    fit();
    const back = () => { setSending((m) => m.filter((x) => x.key !== key)); setText(words); fit(); };
    try {
      const r = await api("send", { sid, text: words, fork: !!fork, files: a.payload() });
      if (r.need === "fork") {
        back();
        setBusy(false);
        if (await confirmBox(t("fork.ask"))) return sendText(true);
        return;
      }
      haptic("success");
      a.clear();
      // a copy is a new session: its message is not this chat's; a computer before 0.15.2 keeps no outbox — the
      // message then leaves the chat until Claude reads it, as it did before the ticks
      setSending((m) => (r.out ? m.map((x) => (x.key === key ? Object.assign({}, x, { id: r.out, st: "sent" }) : x)) : m.filter((x) => x.key !== key)));
      if (r.how === "fork") alertBox(t("fork.started"));
    } catch (e) { back(); alertBox(e.message); }
    setBusy(false);
  };
  // once the computer's outbox has a message, it speaks for it
  useEffect(() => {
    const ids = new Set(((s.info && s.info.out) || []).map((o) => o.id));
    setSending((m) => (m.some((x) => x.id && ids.has(x.id)) ? m.filter((x) => !(x.id && ids.has(x.id))) : m));
  }, [s.info, sending]);
  const stop = async () => {
    const r = await api("stop", { sid }).catch((e) => ({ note: e.message }));
    r.ok ? haptic("success") : alertBox(r.note || t("failed"));
  };
  // "Start now": the turn waiting in the queue goes over the limit, once
  const jump = async () => {
    const r = await api("jump", { sid }).catch((e) => ({ note: e.message }));
    r.ok ? haptic("success") : alertBox(r.note || t("failed"));
  };

  const info = s.info;
  if (!info) return html`<${Loading} err=${s.err && (/not found|не найден/.test(s.err) ? t("sess.starting") : s.err)}/>`;
  const lv = info.live;
  const out = info.outcome;
  if (out && (!firstOut.current || firstOut.current.ts !== out.ts)) firstOut.current = { ts: out.ts, state: out.state };
  const outState = out ? (["you", "fail"].includes(firstOut.current.state) ? firstOut.current.state : out.state) : null;
  const st = lv.state === "ask" ? html`<span class="chip warn">${t("st.ask")}</span>`
    : lv.state === "work" ? workChip(lv.run || lv.started, now)
    : lv.state === "queue" ? queueChip(lv.queued, now)
    : lv.bg && lv.bg.length > 0 ? bgChip(lv.bg_since || (out && out.ts), now, openBgs) : "";
  const ts = info.stats && info.stats.turn;
  // the context gauge, the same number VS Code shows: used ÷ (window − the reserve for the answer)
  const pct = info.ctx && info.stats ? Math.min(100, Math.round(info.stats.context * 100 / info.ctx.usable)) : null;
  // the status under the message field: where the text goes (a tab, a copy), the model, the context gauge
  const dest = lv.tab ? html`${ic("monitor", 13)} ${t("dest.tab")}` : lv.open ? html`${ic("copy", 13)} ${t("dest.copy")}` : "";
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
    info.stats && info.stats.model ? t("ex.ctx", { n: kilo(info.stats.context), win: pct !== null ? t("ex.ctx.win", { w: kilo(info.ctx.window), pct }) : "" }) : "",
    // the last turn's figures — once in the session's header, now here: the header keeps the title and the state
    ts ? t("turn.stats", { n: ts.req, requests: plural(ts.req, "request"), out: kilo(ts.out) }) + (ts.think ? t("turn.think", { n: kilo(ts.think) }) : "") : ""
  ].filter(Boolean)); openNote(); };
  const line1 = (modelText || canPick) && html`<button class=${"mchip" + (canPick ? " on" : "")} onClick=${canPick ? () => (pick ? closePick() : openPick()) : explain}>
    <span>${modelText || t("model")}</span>${effortNow && html`<${Dots} e=${effortNow}/>`}${canPick ? html`<span class="caret">${ic("down", 13)}</span>` : ""}</button>`;
  const line2 = (dest || ctxText) && html`<button class="where" onClick=${explain}>${dest}${dest && ctxText ? " · " : ""}<span class=${pct >= 90 ? "bad" : pct >= 70 ? "warn" : ""}>${ctxText}</span></button>`;
  return html`<div class="session">
    <div class="sess-h"><h2>${info.title}</h2>
      ${info.tagset && html`<button class="sess-tags" onClick=${() => (tagPick ? closeTagPick() : openTagPick())}>${(info.tags || []).length ? tagChips(info.tags) : html`<span class="dim">${t("tags.none")}</span>`}<span class="caret">${ic("down", 14)}</span></button>`}
      <div class="dim">${home(20)}${info.project !== info.title ? html`<span class="sep">›</span><a class="crumb" href=${"#/p/" + encodeURIComponent(info.pkey)}>${info.project}</a>` : ""} ${st}</div>
      ${lv.bg && lv.bg.length > 0 && html`<button class="bg tap plain" onClick=${openBgs}>${bgLine(lv.bg)} ${ic("chev", 14)}</button>`}</div>
    ${s.before != null && html`<button class="link center earlier" disabled=${early} onClick=${earlier}>${t(early ? "earlier.loading" : "earlier")}</button>`}
    ${(away || pin) && html`<div class="sess-top">
      ${away && html`<div class="where-bar">${home(22)}${avatar(info.project, 30)}<span class="wb-body">
        <a class="wb-p" href=${"#/p/" + encodeURIComponent(info.pkey)}>${info.project}</a>
        ${info.title !== info.project && html`<span class="wb-t">${tagChips(info.tags)}${info.title}</span>`}</span>${st}</div>`}
      ${pin && html`<button class="pinned" onClick=${() => { setFull(pin); openFull(); }}><span class="pin-in"><span class="pin-bar"></span>
      <span class="pin-body"><span class="pin-h">${t("pin.you")}${pin.ts ? " · " + hhmm(toDate(pin.ts)) : ""}${pin.att && pin.att.length ? html` · ${ic("clip", 12)} ${pin.att.length}` : ""}</span>
      <span class="pin-tx">${pin.text}</span></span></span></button>`}</div>`}
    ${(shown.current = group(s.items)).map((i, n, all) => i.k === "day" ? html`<div class="day" key=${i.key}>${i.label}</div>`
      : i.k === "steps" ? html`<${Steps} key=${i.key} steps=${i.steps}/>`
      : i.k === "user" ? html`<div class="msg me" key=${n} data-n=${n}>${i.voice ? html`<span class="mic-i">${ic("mic", 14)}</span>` : ""}${i.text}${i.att && i.att.length ? html`<div class="atts">${i.att.map((a, k) => html`<${Pic} key=${k} a=${a} all=${i.att}/>`)}</div>` : ""}<${At} ts=${i.ts} mid=${i.mid} st="read"/></div>`
      : i.k === "note" ? html`<div class="note" key=${n}>${i.text}${i.ts ? " · " + hhmm(toDate(i.ts)) : ""}</div>`
      : i.k === "update" ? html`<div class="upd solo" key=${n}>${i.text}</div>`
      : html`<${TextMsg} key=${n} i=${i} fold=${i.text.length > LONG && all.slice(n + 1).some((x) => x.k === "text")}/>`)}
    ${onTheWay(s.items, info.out || [], sending).filter((o) => !putBack.includes(o.id)).map((o) => html`<div key=${"o" + (o.id || o.key)} class=${"msg me out " + o.st}
        onClick=${o.st === "gone" ? () => { setText(o.text); fit(); setPutBack((x) => [...x, o.id]); } : null}>${o.voice ? html`<span class="mic-i">${ic("mic", 14)}</span>` : ""}${o.text}${o.att && o.att.length
        ? html`<div class="atts">${o.att.map((x, k) => html`<${Pic} key=${k} a=${x} all=${o.att}/>`)}</div>`
        : o.n ? html`<div class="out-n">${ic("clip", 13)} ${o.n}</div>` : ""}<${At} ts=${o.ts} st=${o.st}/></div>
      ${o.st === "sent" && (lv.state === "work" || lv.state === "ask") ? html`<div class="out-hint">${t("out.after_step")}</div>`
        : o.st === "gone" ? html`<div class="out-hint bad">${t("out.gone.why")}</div>` : ""}`)}
    ${lv.state === "work" && html`<div class="working">${t("working")}</div>`}
    ${lv.state === "queue" && html`<div class="card queue"><div class="q-t">${ic("clock", 16)} ${t("queue.title")}</div>
      <div class="dim small">${t("queue.why", { n: lv.slots })}</div>
      <div class="foot"><span></span><button class="btn" onClick=${jump}>${t("queue.jump")}</button></div></div>`}
    ${out && lv.state !== "work" && lv.state !== "queue" && !info.pending.length && (outState === "you" || outState === "fail" || out.need || (out.replies && out.replies.length) || out.resume || out.turn_files)
      && html`<${Outcome} key=${out.ts} sid=${sid} out=${out} state=${outState} now=${now}/>`}
    ${pending.map((r) => html`<${Req} key=${r.rid} r=${r} showWhere=${false}/>`)}
    <div ref=${bottom}></div>
    ${(unread || far) && html`<button class=${"tobottom" + (unread ? " fresh" : "")} aria-label=${t("to.bottom")} onClick=${() => { toBottom(); setUnread(false); }}>${unread ? t("new.msgs") : "↓"}</button>`}
    <div class="composer" ref=${comp}>
      ${pick && html`<${ModelPick} sid=${sid} choice=${info.choice} now=${info.stats || {}} driven=${lv.driven} tab=${lv.tab} dflt=${info.default} canModel=${info.switch} canEffort=${info.switch_effort} onClose=${closePick} onDone=${() => load("after")}/>`}
      ${note && html`<${Sheet} title=${info.title} lines=${note} onClose=${closeNote}/>`}
      ${bgs && html`<${BgSheet} sid=${sid} onClose=${closeBgs}/>`}
      ${tagPick && html`<${TagPick} sid=${sid} info=${info} onDone=${() => load("after")} onClose=${closeTagPick}/>`}
      ${full && html`<div class="backdrop" onClick=${closeFull}></div><div class="card pick"><div class="q-t pick-h">${t("pin.you")}${full.ts ? " · " + hhmm(toDate(full.ts)) : ""}<button class="x" aria-label=${t("close")} onClick=${closeFull}>×</button></div>
        <div class="full-tx">${full.text}</div>
        ${full.att && full.att.length ? html`<div class="atts">${full.att.map((x, k) => html`<${Pic} key=${k} a=${x} all=${full.att}/>`)}</div>` : ""}
        <button class="link" onClick=${() => { const el = document.querySelector('.msg.me[data-n="' + full.n + '"]'); closeFull();
          if (el) setTimeout(() => el.scrollIntoView({ block: "start" }), 60); }}>${t("pin.goto")}</button></div>`}
      <${Thumbs} a=${a}/>
      <textarea ref=${taRef} rows="1" placeholder=${t("write")} value=${text} onKeyDown=${sendKey(() => { if (!busy) sendText(false); }, setText)} onInput=${(e) => { setText(e.target.value); e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px"; }}/>
      <div class="ctl"><${Attach} a=${a} disabled=${busy}/>${info.stt ? html`<${Mic} v=${v} disabled=${busy}/>` : ""}
        <div class="status">${line1}${line2}</div>
        ${lv.driven && (lv.state === "work" || lv.state === "queue") ? html`<button class="btn danger" onClick=${stop}>${t("stop")}</button>` : ""}
        <button class="btn send" aria-label=${t("send")} disabled=${busy || (!text.trim() && !a.files.length)} onClick=${() => sendText(false)}><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="M5 12l7-7 7 7"/></svg></button></div>
    </div>
  </div>`;
}

// the new-task form picks with the app's own lists, not native <select>s: in Telegram on Android the project list
// would not let the owner pick (2026-10-21), and the 30-s poll reorders projects (what needs you first), so the rows
// could move under the finger — a list is frozen while it is open. The form starts on the project last started here,
// never on whatever needs you first: that is how a "have a look" went to the wrong project (2026-10-21)
const LAST_NEW = {
  get() { try { return localStorage.getItem("pult.newPkey") || ""; } catch (e) { return ""; } },
  set(k) { try { localStorage.setItem("pult.newPkey", k); } catch (e) {} },
};

function ProjectPick({ projects, cur, onPick, onClose, create }) {
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick tall fixed">
    <div class="q-t pick-h">${t("new.pick.title")}<button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></div>
    ${create && html`<button class="opt add" onClick=${() => { onClose(); go("#/newproject"); }}>${t("np.create")}</button>`}
    ${projects.map((x) => html`<button key=${x.pkey} class=${"opt" + (x.pkey === cur ? " on" : "")} onClick=${() => onPick(x.pkey)}>${x.name}</button>`)}</div>`;
}

// the "Default" line says in grey what it stands for now (def); Settings names it "As in Claude Code" (top)
function ChoicePick({ model, effort, def, top, note, onPick, onClose }) {
  const col = (title, items, on, key, cur) => html`<div class="pick-col"><div class="pick-t">${title}</div>
    ${items.map(([v, label]) => html`<button key=${v} class=${"opt" + (v === on ? " on" : "")} onClick=${() => onPick({ [key]: v })}>${label}${!v && cur ? html`<span class="dim">${cur}</span>` : ""}</button>`)}</div>`;
  const d = def || {};
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick tall fixed">
    <div class="q-t pick-h">${t("model.pick")}<button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></div>
    <div class="pick-cols">
      ${col(t("model"), MODELS.map(([m, label]) => [m, m ? label : top || t("pick.default")]), model || "", "model", d.model && modelName(d.model))}
      ${col(t("effort"), EFFORTS.map((e) => [e, e ? effortName(e) : top || t("pick.default")]), effort || "", "effort", d.effort && effortName(d.effort))}
    </div>${note ? html`<div class="dim small">${note}</div>` : ""}</div>`;
}

function NewTask({ pkey }) {
  const [d, err] = useLive(() => api("projects"), [], () => false);
  const [p, setP] = useState(pkey || "");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const [sheet, setSheet] = useState(null);         // {k: "project", list} — the list as it was when opened — or {k: "model"}
  const a = useAttach();
  const v = useRecorder((w) => setText((c) => (c ? c.replace(/\s+$/, "") + " " : "") + w));
  useEffect(() => {
    const last = LAST_NEW.get();
    if (d && !p && last && d.projects.some((x) => x.pkey === last)) setP(last);
  }, [d]);
  if (!d) return html`<${Loading} err=${err}/>`;
  const send = async () => {
    setBusy(true);
    try {
      const r = await api("new", { pkey: p, text, files: a.payload(), model, effort });
      LAST_NEW.set(p); haptic("success"); go("#/s/" + r.sid, true);
    }
    catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  const cur = d.projects.find((x) => x.pkey === p);
  const close = () => setSheet(null);
  return html`<div class="form"><h2>${t("new.title")}</h2>
    <label class="lbl">${t("new.project")}</label>
    <button class=${"field" + (p ? "" : " empty")} onClick=${() => setSheet({ k: "project", list: d.projects })}>
      <span>${p ? (cur ? cur.name : p) : t("new.pick")}</span><span class="dim">${ic("down", 18)}</span></button>
    <label class="lbl">${t("new.what")}</label>
    <textarea ref=${plainField} rows="6" placeholder=${t("new.placeholder")} value=${text} onKeyDown=${sendKey(() => { if (!busy && p && (text.trim() || a.files.length)) send(); }, setText)} onInput=${(e) => setText(e.target.value)}/>
    <${Thumbs} a=${a}/>
    <${Attach} a=${a} disabled=${busy} wide=${true}/>
    ${d.stt ? html`<${Mic} v=${v} disabled=${busy} wide=${true}/>` : ""}
    <label class="lbl">${t("model.pick")}</label>
    <button class="field" onClick=${() => setSheet({ k: "model" })}>
      <span>${choiceText(model, effort, d.choice)}</span><span class="dim">${ic("down", 18)}</span></button>
    <button class="btn wide" disabled=${busy || !p || (!text.trim() && !a.files.length)} onClick=${send}>${t("new.start")}</button>
    <div class="dim small">${t("new.about")}</div>
    ${sheet && sheet.k === "project" && html`<${ProjectPick} projects=${sheet.list} cur=${p} create=${d.create} onClose=${close} onPick=${(k) => { setP(k); haptic("success"); close(); }}/>`}
    ${sheet && sheet.k === "model" && html`<${ChoicePick} model=${model} effort=${effort} def=${d.choice} onClose=${close}
      onPick=${(c) => { if ("model" in c) setModel(c.model); if ("effort" in c) setEffort(c.effort); haptic("success"); }}/>`}
  </div>`;
}

// ---------- a new project (stage S) ----------
// A folder on the computer for something Claude hasn't worked on yet. The folder's name follows the title (the
// computer turns it into Latin — one rule for the app and the daemon) until the owner edits it; the place is picked
// level by level inside the home folder; three ways to begin. The computer checks everything again on "Create".

const HOWS = ["empty", "describe", "clone"];
const STEPS = { receive: "np.step.receive", resolve: "np.step.resolve", files: "np.step.files" };

function FolderPick({ start, onPick, onClose }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const load = (args) => api("dirs", args).then((x) => { setD(x); setErr(null); }).catch((e) => setErr(e.message));
  useEffect(() => { load(start ? { path: start } : {}); }, []);
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick tall fixed">
    <div class="q-t pick-h"><span class="path">${d ? d.show : "…"}</span><button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></div>
    ${err && html`<div class="pick-why">${err}</div>`}
    ${d && html`<button class="btn wide" onClick=${() => onPick(d)}>${t("np.pick.here")}</button>
      ${d.up && html`<button class="opt up" onClick=${() => load({ path: d.up })}>${ic("up", 16)} ${t("np.pick.up")}</button>`}
      ${d.dirs.map((n) => html`<button key=${n} class="opt" onClick=${() => load({ path: d.path, into: n })}>${ic("folder", 16)} ${n}</button>`)}
      ${!d.dirs.length && html`<div class="dim small">${t("np.pick.none")}</div>`}`}
  </div>`;
}

function NewProject() {
  const [d] = useLive(() => api("projects"), [], () => false);       // only for the microphone: shown with a key
  const [title, setTitle] = useState("");
  const [name, setName] = useState("");
  const [edited, setEdited] = useState(false);       // the owner typed the folder's name: it no longer follows the title
  const [place, setPlace] = useState(null);           // {path, show, tabs}
  const [how, setHow] = useState("empty");
  const [about, setAbout] = useState("");
  const [link, setLink] = useState("");
  const [text, setText] = useState("");
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const [sheet, setSheet] = useState(null);           // "dir" | "model"
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState(null);               // a clone in progress: {step, sec}
  const a = useAttach();
  const howRef = useRef(how);
  howRef.current = how;
  const add = (set) => (w) => set((c) => (c ? c.replace(/\s+$/, "") + " " : "") + w);
  const v = useRecorder((w) => (howRef.current === "describe" ? add(setAbout) : add(setText))(w));
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  useEffect(() => { if (conn.ready) api("dirs").then(setPlace).catch(() => {}); return on("ready", () => !place && api("dirs").then(setPlace).catch(() => {})); }, []);
  useEffect(() => {                                    // the folder's name, as the computer will make it
    if (edited) return;
    const src = how === "clone" ? link : "";
    if (!title.trim() && !src.trim()) { setName(""); return; }
    const timer = setTimeout(() => api("folder", { title, link: src }).then((r) => alive.current && !edited && setName(r.name)).catch(() => {}), 300);
    return () => clearTimeout(timer);
  }, [title, link, how, edited]);
  const finish = (r) => {
    haptic("success");
    if (r.git === false) alertBox(t("np.nogit"));
    go(r.sid ? "#/s/" + r.sid : "#/p/" + encodeURIComponent(r.pkey), true);
  };
  const watch = (job) => new Promise((ok, no) => {
    const tick = () => api("job", { job }).then((j) => {
      if (!alive.current) return ok(null);
      if (j.state === "run") { setJob(j); setTimeout(tick, 1000); }
      else if (j.state === "done") ok(j);
      else no(new Error(j.error));
    }).catch(no);
    tick();
  });
  const create = async (big = false) => {
    setBusy(true);
    try {
      let r = await api("create", { title, name, parent: place && place.path, how, about, link, text, files: a.payload(), model, effort, big });
      if (r.big) {
        setBusy(false);
        if (await confirmBox(t("np.big", { mb: r.big }))) return create(true);
        return;
      }
      if (r.job) r = await watch(r.job);
      if (r) finish(r);
    }
    catch (e) { alertBox(e.message); }
    if (alive.current) { setBusy(false); setJob(null); }
  };
  const ready = !busy && place && name.trim() && (title.trim() || how === "clone") && (how !== "describe" || about.trim()) && (how !== "clone" || link.trim());
  const step = job && job.step ? t(STEPS[job.step[0]], { p: job.step[1] }) : "";
  const close = () => setSheet(null);
  return html`<div class="form"><h2>${t("np.title")}</h2>
    <label class="lbl">${t("np.name")}</label>
    <input ref=${plainField} value=${title} placeholder=${t("np.name.ph")} onInput=${(e) => setTitle(e.target.value)}/>
    <label class="lbl">${t("np.folder")}</label>
    <input ref=${plainField} class="mono" value=${name} placeholder=${t("np.folder.ph")} onInput=${(e) => { setEdited(true); setName(e.target.value.trim()); }}/>
    <label class="lbl">${t("np.where")}</label>
    <button class="field" onClick=${() => setSheet("dir")}><span class="path">${place ? place.show : "…"}</span><span class="dim">${ic("down", 18)}</span></button>
    ${place && place.tabs === false && html`<div class="dim small np-hint">${t("np.notabs")}</div>`}
    <label class="lbl">${t("np.how")}</label>
    ${HOWS.map((h) => html`<button key=${h} class=${"opt" + (how === h ? " on" : "")} onClick=${() => setHow(h)}>${t("np." + h)}<span class="dim">${t("np." + h + ".about")}</span></button>`)}
    ${how === "clone" && html`<label class="lbl">${t("np.link")}</label>
      <input ref=${plainField} type="url" inputmode="url" value=${link} placeholder="https://github.com/…" onInput=${(e) => setLink(e.target.value)}/>`}
    ${how === "describe" ? html`<label class="lbl">${t("np.about")}</label>
      <textarea ref=${plainField} rows="5" placeholder=${t("np.about.ph")} value=${about} onInput=${(e) => setAbout(e.target.value)}/>`
    : html`<label class="lbl">${t("np.task")}</label>
      <textarea ref=${plainField} rows="4" placeholder=${t("new.placeholder")} value=${text} onInput=${(e) => setText(e.target.value)}/>
      <${Thumbs} a=${a}/><${Attach} a=${a} disabled=${busy} wide=${true}/>`}
    ${d && d.stt && html`<${Mic} v=${v} disabled=${busy} wide=${true}/>`}
    ${(how === "describe" || text.trim() || a.files.length > 0) && html`<label class="lbl">${t("model.pick")}</label>
      <button class="field" onClick=${() => setSheet("model")}>
        <span>${choiceText(model, effort, d && d.choice)}</span><span class="dim">${ic("down", 18)}</span></button>`}
    <button class="btn wide" disabled=${!ready} onClick=${() => create()}>${busy ? (job ? t("np.cloning") + (step ? " · " + step : "") + " · " + dur(job.sec) : "…") : t("np.go")}</button>
    <div class="dim small">${t("np.help")}</div>
    ${sheet === "dir" && html`<${FolderPick} start=${place && place.path} onClose=${close} onPick=${(x) => { setPlace(x); haptic("success"); close(); }}/>`}
    ${sheet === "model" && html`<${ChoicePick} model=${model} effort=${effort} def=${d && d.choice} onClose=${close}
      onPick=${(c) => { if ("model" in c) setModel(c.model); if ("effort" in c) setEffort(c.effort); haptic("success"); }}/>`}
  </div>`;
}

// ---------- Resources: how the plan's limits are spent (stage R) ----------
// For each limit: the curve from its start to its reset against the even pace, the forecast at the current pace, how
// many sessions worked at once, what spent it. The computer counts (pult_spend.py), the app only draws — SVG by hand,
// no chart library. The data is the only loud thing: thin marks, hairline grid; red only when a limit runs out early.

// hours of one session's work, as precise as it is worth: 35 h · 5.9 h · 25 min
const shours = (h) => nb(h >= 10 ? t("dur.h", { n: Math.round(h) }) : h >= 1 ? t("dur.h", { n: num(h, 1) }) : t("dur.m", { n: Math.max(5, Math.round(h * 12) * 5) }));
const sameDay = (a, b) => a.toDateString() === b.toDateString();
const spWhen = (ts) => { const d = toDate(ts); return (sameDay(d, new Date()) ? "" : t("weekdays").split(" ")[d.getDay()] + " ") + hhmm(d); };
const durLong = (sec) => (sec >= 86400 ? t("dur.d", { n: Math.floor(sec / 86400) }) + (Math.floor(sec % 86400 / 3600) ? " " + t("dur.h", { n: Math.floor(sec % 86400 / 3600) }) : "") : dur(sec));
// a project in the spend: its own colour (the tile's); the rest, grouped, grey
const spColor = (p) => (!p || p.color == null ? "var(--c0)" : hue(p.name));

function verdict(L) {
  const left = Math.max(0, L.t1 - L.now);
  if (L.used >= 100) return [t("sp.out", { left: durLong(left) })];
  if (L.state === "none") return [t("sp.none")];
  if (L.state === "over") {
    const slow = (100 - L.used) / Math.max(1e-9, L.rate * left / 3600);
    return [t("sp.over.v", { left: durLong(left), hit: spWhen(L.hit), gap: durLong(L.t1 - L.hit) }),
      t(slow > 0.66 ? "sp.slow.3" : slow > 0.4 ? "sp.slow.2" : "sp.slow.1")];
  }
  const out = [t("sp.at", { left: durLong(left), proj: "~" + pct(L.proj) })];
  let s = t(L.state === "under" ? "sp.burn" : "sp.free", { spare: "~" + pct(L.spare) });
  if (L.sh_left != null) s += t("sp.sh", { sh: shours(L.sh_left) });
  if (L.par != null && L.par >= 1) {
    const n = Math.round(L.par);
    s += t("sp.par", { n, sessions: plural(n, "session"), hm: hhmm(toDate(L.t1)) });
  }
  out.push(s + ".");
  if (L.tighter) out.push(t("sp.tighter", { sh: L.tighter.sh != null ? shours(L.tighter.sh) : "—" }));
  return out;
}

function PaceChart({ L }) {
  const box = useRef(null);
  const [w, setW] = useState(0);
  const [hx, setHx] = useState(null);
  useEffect(() => {
    const el = box.current;
    const fit = () => setW(el.clientWidth);
    fit();
    const ro = window.ResizeObserver ? new ResizeObserver(fit) : null;
    if (ro) ro.observe(el); else window.addEventListener("resize", fit);
    const away = (e) => { if (!el.contains(e.target)) setHx(null); };       // a tap elsewhere hides the readout
    document.addEventListener("pointerdown", away);
    return () => { if (ro) ro.disconnect(); else window.removeEventListener("resize", fit); document.removeEventListener("pointerdown", away); };
  }, []);
  useEffect(() => setHx(null), [L.key]);
  if (!w) return html`<div class="chart" ref=${box}></div>`;
  const W = w, PT = 16, PH = 150, ST = PT + PH + 20, SH = 38, XB = ST + SH + 16, HT = XB + 4;
  const X = (ts) => (ts - L.t0) / (L.t1 - L.t0) * W, Y = (p) => PT + (1 - Math.min(p, 100) / 100) * PH;
  let c = 0;
  const cums = L.bars.map((b) => (c += b[0]));
  const end = (i) => Math.min(L.t0 + (i + 1) * L.step, L.now);
  const pts = [[0, Y(0)]].concat(cums.map((v, i) => [X(end(i)), Y(v)]));
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join("");
  // the axis: days for the week, hours for the window
  const ticks = [], d = toDate(L.t0);
  if (L.key === "week") { d.setHours(24, 0, 0, 0); for (; d / 1000 < L.t1; d.setDate(d.getDate() + 1)) ticks.push(d / 1000); }
  else { d.setMinutes(60, 0, 0); for (; d / 1000 < L.t1; d.setHours(d.getHours() + 1)) ticks.push(d / 1000); }
  const marks = [L.t0].concat(ticks, [L.t1]);
  const labels = L.key === "week"
    ? marks.slice(0, -1).map((a, i) => [(X(a) + X(marks[i + 1])) / 2, X(marks[i + 1]) - X(a) > 22 ? t("weekdays").split(" ")[toDate(a + 60).getDay()] : ""])
    : ticks.map((a) => [X(a), hhmm(toDate(a))]);
  const ink = { "text-anchor": "end", class: "ink" };
  const hitX = L.hit ? X(L.hit) : null, endP = L.proj == null ? null : L.hit ? 100 : L.proj;
  const short = W - X(L.now) < 70;                                  // a short forecast: one label "82 % → ~88 %"
  const nBars = Math.round((L.t1 - L.t0) / L.step), bw = W / nBars, gap = bw >= 4 ? 1 : 0;
  const maxN = Math.max(4, ...L.bars.map((b) => b[1] + b[2]));
  // the readout under the finger: the bar's spend, sessions at once and projects; past now — the forecast
  let tip = null, cx = 0, cy = 0;
  if (hx != null) {
    const at = L.t0 + hx / W * (L.t1 - L.t0);
    if (at < L.now && L.bars.length) {
      const i = Math.min(Math.floor((at - L.t0) / L.step), L.bars.length - 1), b = L.bars[i], s = L.t0 + i * L.step;
      cx = X(Math.min(s + L.step / 2, L.now)); cy = Y(cums[i]);
      tip = html`<div class="dim">${(L.key === "week" ? t("weekdays").split(" ")[toDate(s + 60).getDay()] + " " : "") + hhmm(toDate(s))}–${hhmm(toDate(end(i)))}</div>
        <div class="v">${t("sp.tip.spent", { d: "+" + pct(b[0]), c: pct(cums[i]) })}</div>
        <div>${b[1] || b[2] ? t("sp.tip.at", { who: (b[1] ? t("sp.tip.n", { n: b[1], sessions: plural(b[1], "session") }) : "")
          + (b[1] && b[2] ? t("sp.tip.and") : "") + (b[2] ? t("sp.tip.n", { n: b[2], sessions: plural(b[2], "agent") }) : "") }) : t("sp.tip.idle")}</div>
        ${b[3].map(([j, v]) => html`<div><i class="k" style=${"background:" + spColor(L.projects[j])}></i>${(L.projects[j] || {}).name} · ${pct(v)}</div>`)}
        ${b[4] ? html`<div><i class="k" style="background:var(--pace)"></i>${t("sp.elsewhere")} · ${pct(b[4])}</div>` : ""}`;
    } else if (L.rate != null) {
      cx = hx;
      const p = Math.min(100, L.used + L.rate * (at - L.now) / 3600);
      cy = Y(p);
      tip = html`<div class="dim">${t("sp.tip.fc", { when: spWhen(at) })}</div><div class="v">~${pct(p)}</div>
        <div>${t("sp.tip.rate", { r: pct(L.rate) })}</div>`;
    }
  }
  const pick = (e) => { const r = e.currentTarget.getBoundingClientRect(); setHx(Math.max(0, Math.min(W, (e.clientX - r.left) / r.width * W))); };
  return html`<div class="chart" ref=${box}>
    <svg viewBox=${"0 0 " + W + " " + HT} height=${HT} role="img" aria-label=${L.name + ": " + pct(L.used) + (endP != null ? " → ~" + pct(endP) : "")}
      onPointerMove=${pick} onPointerDown=${pick} onPointerLeave=${(e) => e.pointerType === "mouse" && setHx(null)}>
      <line x1="0" x2=${W} y1=${Y(0)} y2=${Y(0)} stroke="var(--grid)"/><line x1="0" x2=${W} y1=${Y(50)} y2=${Y(50)} stroke="var(--grid)"/>
      <line x1="0" x2=${W} y1=${Y(100)} y2=${Y(100)} stroke="var(--axis)"/>
      <text x="0" y=${Y(100) - 4}>100 %</text><text x="0" y=${Y(50) - 4}>50 %</text>
      ${ticks.map((a) => html`<line x1=${X(a)} x2=${X(a)} y1=${PT} y2=${ST + SH} stroke="var(--grid)"/>`)}
      ${labels.map(([x, s]) => s && html`<text x=${x} y=${XB} text-anchor="middle">${s}</text>`)}
      <line x1="0" y1=${Y(0)} x2=${W} y2=${Y(100)} stroke="var(--pace)" stroke-width="1.5"/>
      <path d=${line + "L" + X(L.now).toFixed(1) + " " + Y(0) + "L0 " + Y(0) + "Z"} fill="var(--s1)" opacity="0.1"/>
      <path d=${line} fill="none" stroke="var(--s1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
      ${endP != null && html`<line x1=${X(L.now)} y1=${Y(L.used)} x2=${L.hit ? hitX : W} y2=${Y(endP)} stroke=${L.hit ? "var(--danger)" : "var(--s1)"} stroke-width="2" stroke-dasharray="4 4" stroke-linecap="round"/>`}
      ${L.hit && L.used < 100 ? html`<rect x=${hitX} y=${Y(100) - 3} width=${Math.max(0, W - hitX)} height="6" rx="3" fill="var(--danger)" opacity="0.25"/>
        <circle cx=${hitX} cy=${Y(100)} r="4.5" fill="var(--danger)" stroke="var(--card)" stroke-width="2"/>
        <text x=${hitX > W * 0.6 ? W : hitX} y=${Y(100) - 6} text-anchor=${hitX > W * 0.6 ? "end" : "start"} class="ink">${t("sp.runs.out", { when: spWhen(L.hit) })}</text>` : ""}
      ${endP != null && !L.hit ? html`<circle cx=${W - 4} cy=${Y(endP)} r="4" fill="var(--card)" stroke="var(--s1)" stroke-width="2"/>
        ${!short && html`<text x=${W - 12} y=${Y(endP) - 8} ...${ink}>~${pct(endP)}</text>`}` : ""}
      <circle cx=${X(L.now)} cy=${Y(L.used)} r="4.5" fill="var(--s1)" stroke="var(--card)" stroke-width="2"/>
      <text x=${X(L.now) - 8} y=${Y(L.used) - 9} ...${ink}>${pct(L.used) + (short && endP != null && !L.hit ? " → ~" + pct(endP) : "")}</text>
      <text x="0" y=${ST - 2}>${t("sp.at.once", { n: maxN })}</text>
      ${L.bars.map((b, i) => {
        if (!b[1] && !b[2]) return "";
        const x = i * bw, bwid = Math.max(1, bw - gap), hs = b[1] / maxN * SH, ha = b[2] / maxN * SH;
        return html`<rect x=${x} y=${ST + SH - hs} width=${bwid} height=${hs} fill="var(--s1)"/>${ha ? html`<rect x=${x} y=${ST + SH - hs - ha - (hs ? 1 : 0)} width=${bwid} height=${ha} fill="var(--s1-soft)"/>` : ""}`;
      })}
      <line x1="0" x2=${W} y1=${ST + SH + 0.5} y2=${ST + SH + 0.5} stroke="var(--axis)"/>
      ${tip && html`<line x1=${cx} x2=${cx} y1=${PT - 6} y2=${ST + SH} stroke="var(--ink)" stroke-opacity="0.35"/>
        <circle cx=${cx} cy=${cy} r="4" fill="var(--s1)" stroke="var(--card)" stroke-width="2"/>`}
    </svg>
    ${tip && html`<div class=${"tip" + (cy < PT + 70 ? " below" : "")} style=${"left:" + Math.max(100, Math.min(W - 100, cx)) + "px;top:" + (cy < PT + 70 ? cy + 14 : cy - 12) + "px"}>${tip}</div>`}
  </div>`;
}

// the same as a table: a row a day (the week) or half an hour (the window)
function SpendTable({ L }) {
  const per = L.key === "week" ? 24 : 6, rows = [];
  let c = 0;
  for (let i = 0; i < L.bars.length; i += per) {
    const part = L.bars.slice(i, i + per), s = L.t0 + i * L.step;
    const add = part.reduce((a, b) => a + b[0], 0);
    c += add;
    rows.push(html`<tr><td>${(L.key === "week" ? t("weekdays").split(" ")[toDate(s + 60).getDay()] + " " : "") + hhmm(toDate(s))}</td>
      <td>+${pct(add)}</td><td>${pct(c)}</td><td>${Math.max(...part.map((b) => b[1]))}</td></tr>`);
  }
  return html`<table class="tv"><thead><tr><th>${t("sp.t.from")}</th><th>+ %</th><th>${t("sp.t.total")}</th><th>${t("sp.t.peak")}</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// what spent the limit: a project keeps its colour, the five biggest have one, the rest are "other"
function Spent({ L }) {
  const parts = L.projects.filter((p) => p.color != null).map((p) => [p.name, p.pct, spColor(p), p.sh]);
  const rest = L.projects.filter((p) => p.color == null);
  const restPct = rest.reduce((a, p) => a + p.pct, 0);
  if (restPct >= 0.3) parts.push([t("sp.other"), restPct, "var(--c0)", L.per_sh ? restPct / L.per_sh : null]);
  if (L.ext >= 0.3) parts.push([t("sp.elsewhere"), L.ext, "var(--pace)", null]);
  if (!parts.length) return "";
  return html`<h3>${t("sp.ate." + L.key)}</h3><div class="card spent">
    <div class="stack">${parts.map(([, v, col], i) => html`<i key=${i} style=${"flex:" + v + ";background:" + col}></i>`)}</div>
    ${parts.map(([n, v, col, sh], i) => html`<div class="prow" key=${i}><span><i class="swatch" style=${"background:" + col}></i>${n}</span>
      <span class="dim">${pct(v)}${sh != null ? " · ≈ " + shours(sh) : ""}</span></div>`)}</div>`;
}

function Spend() {
  const [d, err, set] = useLive(() => api("spend"), [], () => false, 60000);
  const [key, setKey] = useState(null);
  const [table, setTable] = useState(false);
  const [busy, setBusy] = useState(false);
  useNow(30000);
  if (!d && err) return html`<${Usage}/>`;          // an older Pult on the computer, or no reading: the old screen says why
  if (!d) return html`<${Loading}/>`;
  if (!d.limits.length) return html`<${Usage}/>`;
  const by = Object.fromEntries(d.limits.map((x) => [x.key, x]));
  // the week opens first — the budget that has to last; the window only when it runs out first and the week doesn't
  const auto = by.h5 && by.h5.hit && !(by.week && by.week.hit) ? "h5" : by.week ? "week" : "h5";
  const L = by[key] || by[auto];
  const other = d.limits.find((x) => x !== L);
  const refresh = async () => {
    setBusy(true);
    try { set(await api("spend", { force: true })); haptic("success"); } catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  const share = (name) => (d.shares || []).find((x) => name.indexOf(x.name) >= 0);
  const chip = { pace: "ok", under: "info", over: "bad" }[L.state];
  return html`<div>
    ${d.limits.length > 1 && html`<div class="seg spend-seg">${d.limits.map((x) => html`<button key=${x.key} class=${x === L ? "on" : ""}
      onClick=${() => setKey(x.key)}>${t("sp.short." + x.key)}</button>`)}</div>`}
    <div class="card spend">
      <div class="sp-h"><span>${t("sp.name." + L.key)}${d.plan ? " · " + d.plan.charAt(0).toUpperCase() + d.plan.slice(1) : ""}</span><span>${t("usage.reset", { when: spWhen(L.t1) })}</span></div>
      <div class="sp-hero"><span class="big">${pct(L.used)}</span>${chip && html`<span class=${"vchip " + chip}>${t("sp.chip." + L.state)}</span>`}</div>
      <div class="verdict">${verdict(L).join(" ")}</div>
      <${PaceChart} L=${L}/>
      <div class="sp-leg"><span><i class="swatch" style="background:var(--s1)"></i>${t("sp.sessions")}</span><span><i class="swatch" style="background:var(--s1-soft)"></i>${t("sp.agents")}</span>
        <span><i class="swatch line" style="background:var(--pace)"></i>${t("sp.even")}</span>
        <button class="link" onClick=${() => setTable(!table)}>${t(table ? "sp.chart" : "sp.table")}</button></div>
      ${table && html`<${SpendTable} L=${L}/>`}
    </div>
    <div class="list">
      ${other && html`<button class="lim" onClick=${() => setKey(other.key)}>
        <div class="item-h"><b>${t("sp.short." + other.key)}</b><b class="pct">${pct(other.used)}</b></div>
        <div class="meter"><i class=${other.state === "over" ? "bad" : "spend"} style=${"width:" + Math.min(100, other.used) + "%"}></i></div>
        <div class="dim">${t("usage.reset", { when: spWhen(other.t1) })}${other.hit ? " · " + t("sp.runs.out", { when: spWhen(other.hit) }) : other.proj != null ? " · " + t("sp.other.at", { proj: "~" + pct(other.proj) }) : ""}</div></button>`}
      ${(d.others || []).map((x) => { const sh = share(x.name); return html`<div class="lim" key=${x.name}>
        <div class="item-h"><b>${x.name}</b><b class=${"pct " + level(x.percent)}>${pct(x.percent)}</b></div>
        <div class="meter"><i class=${level(x.percent) || "spend"} style=${"width:" + Math.min(100, x.percent) + "%"}></i></div>
        <div class="dim">${sh ? t("sp.share", { used: sh.used, allow: sh.allow }) + " · " : ""}${t("usage.reset", { when: spWhen(x.resets_at) })}</div></div>`; })}
    </div>
    <${Spent} L=${L}/>
    ${d.extra && d.extra.enabled && html`<div class="dim small">${t("usage.extra", { used: d.extra.used ?? 0, limit: d.extra.limit ?? "—", cur: d.extra.currency || "" })}</div>`}
    <div class="res-foot"><span class="dim">${t("usage.updated", { ago: ago(d.ts) })}</span>
      <button class="link" disabled=${busy} onClick=${refresh}>${busy ? t("refreshing") : t("refresh")}</button></div>
    <${About} text=${t("sp.about") + (L.per_sh ? " " + t("sp.about.sh", { per: pct(L.per_sh), limit: t("sp.of." + L.key) }) : "")
      + (d.fable_x >= 1.5 ? " " + t("sp.about.fable", { x: num(d.fable_x, 1) }) : "") + " " + t("usage.alerts")}/>
  </div>`;
}

// Resources: can I keep working — the plan's limits, or the computer's load; two sections, not five screens of one
const RES = ["lim", "pc"];
const resStore = {
  get() { try { const k = sessionStorage.getItem("pult.res"); return RES.includes(k) ? k : "lim"; } catch (e) { return "lim"; } },
  set(k) { try { sessionStorage.setItem("pult.res", k); } catch (e) {} },
};
function Resources() {
  const [sec, setSec] = useState(resStore.get);
  const pick = (k) => { setSec(k); resStore.set(k); };
  return html`<div><h2>${t("res.title")}</h2>
    <div class="subtabs" role="tablist">${RES.map((k) => html`<button key=${k} role="tab" aria-selected=${sec === k} class=${sec === k ? "on" : ""}
      onClick=${() => pick(k)}>${t("res." + k)}</button>`)}</div>
    ${sec === "pc" ? html`<${Load} embedded=${true}/>` : html`<${Spend}/>`}
  </div>`;
}

// "how it's counted": behind ⓘ, not on the screen all the time
function About({ text, label }) {
  const [open, setOpen] = useState(false);
  return html`<button class="about-b" aria-expanded=${open} onClick=${() => setOpen(!open)}>${ic("info", 15)} ${label || t("about.how")}</button>
    ${open && html`<div class="dim small about-t">${text}</div>`}`;
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
  return html`<div><h3>${t("usage")}</h3>
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

// nothing to show yet: loading — or, with the Mac away, why nothing comes (the data lives only on the Mac, nothing is kept
// in the phone), instead of "Loading…" for ever under the banner
function Loading({ err }) {
  const c = useConn();
  return html`<div class="empty">${err || (c.state === "nomac" ? t("loading.nomac") : c.state === "denied" ? "" : t("loading"))}</div>`;
}

// a short note at the bottom of the screen for a moment — an answer went — outliving the card it came from
function Toast() {
  const [m, setM] = useState(null);
  useEffect(() => on("toast", (text) => setM({ text, k: Date.now() })), []);
  useEffect(() => { if (!m) return undefined; const id = setTimeout(() => setM(null), 1800); return () => clearTimeout(id); }, [m]);
  return m ? html`<div class="toast" role="status" key=${m.k}>${m.text}</div>` : "";
}

function Banner() {
  const c = useConn();
  const upd = c.updating && Date.now() - c.updating < UPD_RUN_MAX && ["connecting", "offline", "auth", "nomac"].includes(c.state);
  const text = c.state === "denied" ? t(["expired", "out", "locked"].includes(c.why) ? "banner.denied." + c.why : "banner.denied")
    : upd ? t("banner.updating")
    : ["connecting", "offline", "auth", "nomac"].includes(c.state) ? t("banner." + c.state) : "";
  const stale = c.fresh && ["offline", "nomac"].includes(c.state) ? " " + t("banner.stale", { hm: hhmm(new Date(c.fresh)) }) : "";
  return text ? html`<div class=${"banner " + c.state} role="status">${text}${stale}</div>` : "";
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
    : r.name === "f" ? html`<${TurnFilesScreen} sid=${r.id} turn=${r.q.get("t")}/>`
    : r.name === "p" ? html`<${Project} key=${r.id + "?" + (r.q.get("tag") || "") + "/" + (r.q.get("topic") || "")} pkey=${r.id} tag=${r.q.get("tag")} topic=${r.q.get("topic")}/>`
    : r.name === "projects" ? html`<${Projects}/>`
    : r.name === "new" ? html`<${NewTask} pkey=${r.q.get("pkey")}/>`
    : r.name === "newproject" ? html`<${NewProject}/>`
    : r.name === "usage" ? html`<${Resources}/>`
    : r.name === "load" ? html`<${Load}/>`
    : r.name === "settings" ? html`<${Settings}/>`
    : html`<${Home}/>`;
  const tab = (name, h, label, icon) => html`<a class=${(r.name === name ? "on" : "") + (name === "new" ? " new" : "")} href=${h}><span class="ti">${ic(icon, name === "new" ? 22 : 22)}</span><span class="tl">${label}</span></a>`;
  return html`<${Banner}/><main class=${r.name === "s" ? "with-composer" : ""}>${screen}</main>
    ${r.name !== "s" && html`<nav class="tabs">${tab("home", "#/", t("tab.home"), "home")}${tab("projects", "#/projects", t("tab.projects"), "folder")}${tab("usage", "#/usage", t("tab.res"), "gauge")}${tab("new", "#/new", t("tab.new"), "plus")}</nav>`}
    <${EditHost}/><${ViewHost}/><${FileHost}/><${Toast}/>`;
}

render(html`<${App}/>`, document.getElementById("app"));
