// Pult app — the connection: phone ↔ relay ↔ Mac, requests and their answers, screens that stay live.
// Moved from app.js as it was (review 2026-10-27, 6.4).
import { LANG, setLang, t } from "../i18n.js";
import { useEffect, useState } from "../vendor/htm-preact-3.1.1.js";
import { tg } from "./tg.js";

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
  key: keyStore.get(), why: null, fresh: 0, updating: 0, gone: 0,   // gone: since when the computer is away (ms, this phone's clock)
  pong: false, heard: 0,     // pong: the relay answers a ping itself (0.18.40); heard: the socket's last word (ms)
  caps: [] };                // what this computer says it can do: "once" — a request with a key is done once
// the relay says how many seconds ago the computer went away (0.18.5): a computer silent for hours is one whose Pult
// doesn't start, and the banner says since when
const noteGone = (m) => { conn.gone = typeof m.away === "number" ? Date.now() - m.away * 1000 : conn.gone; };   // updating: since when Pult installs an update (stage U)       // fresh: when the Mac last answered — what's on screen is from then
const setState = (s) => { conn.state = s; emit("conn"); };
const setKey = (k) => { conn.key = k || null; keyStore.set(k); };

// calls made on a socket that is gone, or sent to a computer that is gone, get no answer: they fail now, not in 30 s
// (2026-10-27: a reload sent as an install stopped Pult held the table's next one back — a stale Install was tapped
// twice); `lost` — the call may have reached the computer before it went
const dropWaits = () => { for (const w of conn.wait.values()) { clearTimeout(w.timer); w.reject(Object.assign(new Error(t("conn.lost")), { lost: true })); } conn.wait.clear(); };
let retryTimer = 0, dialTimer = 0, pingTimer = 0;
// A network switch can leave WebSocket CONNECTING (or OPEN but silent, see ping) forever. Retire that socket before
// replacing it; its late callbacks must not change the new connection or replay any request.
function reconnect() {
  clearTimeout(retryTimer); clearTimeout(dialTimer); clearTimeout(pingTimer);
  const old = conn.ws;
  conn.ws = null; conn.ready = false;
  dropWaits();
  if (old) old.close();
  connect();
}
function connect() {
  if (conn.ws && conn.ws.readyState <= 1) return;
  clearTimeout(retryTimer); clearTimeout(dialTimer);
  conn.ready = false;
  dropWaits();
  const ws = (conn.ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/pult/ws"));
  setState("connecting");
  dialTimer = setTimeout(() => { if (ws === conn.ws) reconnect(); }, 15000);
  ws.onopen = () => { if (ws === conn.ws) ws.send(JSON.stringify({ t: "hello", init: (tg && tg.initData) || "", resume: conn.key,
    client: { platform: tg && tg.platform, version: tg && tg.version } })); };
  // a socket replaced while it was closing says nothing more: its late end failed the new one's calls and planned an
  // extra reconnect (review 2026-10-27, П8); a frame that isn't JSON is no message
  ws.onmessage = (ev) => {
    if (ws !== conn.ws) return;
    conn.heard = Date.now();
    let m;
    try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (!m || typeof m !== "object") return;
    if (m.t === "hello") {
      clearTimeout(dialTimer); conn.mac = m.mac; conn.gone = 0; conn.pong = m.pong === true; if (!m.mac) noteGone(m);
      setState(m.mac ? "auth" : "nomac"); emit("hello");
    }
    else if (m.t === "ready") {
      clearTimeout(dialTimer);
      if (m.resume) setKey(m.resume);
      conn.ready = true; conn.retry = 0; setState("ok"); emit("ready"); api("lang").then(useLang).catch(() => {});
    }
    else if (m.t === "denied") { clearTimeout(dialTimer); conn.ready = false; conn.why = m.why || null; if (m.why === "out") setKey(null); setState("denied"); }
    else if (m.t === "mac") { conn.mac = m.on; if (!m.on) { noteGone(m); conn.ready = false; dropWaits(); setState("nomac"); } else { conn.gone = 0; if (!conn.ready) setState("auth"); } }
    else if (m.t === "res") {
      const w = conn.wait.get(m.id);
      if (Array.isArray(m.caps)) conn.caps = m.caps;
      if (w) { conn.wait.delete(m.id); clearTimeout(w.timer); if (!m.error) conn.fresh = Date.now(); m.error ? w.reject(new Error(m.error)) : w.resolve(m.data); }
    } else if (m.t === "event") emit("event", m);
  };
  ws.onclose = (ev) => {
    if (ws !== conn.ws) return;
    clearTimeout(dialTimer);
    conn.ready = false;
    dropWaits();
    if (conn.state === "denied") return;
    setState(ev && ev.code === 4429 ? "busy" : "offline");
    // Background webviews may keep responding to protocol pings after the person closed the app. A full relay
    // gives their place to a new window (4001); reopen only when this window comes back on screen.
    if (ev && ev.code === 4001 && (document.hidden || tg && tg.isActive === false)) return;
    // "too many windows" (4429): every window on the relay is in use — wait for one to go instead of knocking
    // again every few seconds
    retryTimer = setTimeout(connect, ev && ev.code === 4429 ? 15000 + Math.random() * 15000 : [500, 1000, 2000, 5000, 10000][Math.min(conn.retry++, 4)]);
  };
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) connect(); });
connect();

// `once` — the request's own key: the computer does a request with a key once, however many times it is asked.
// An error says how it failed: unsent — it never left; lost, late — it may have reached the computer
function api(op, args = {}, once) {
  return new Promise((resolve, reject) => {
    if (!conn.ready) return reject(Object.assign(new Error(t("conn.nomac")), { unsent: true }));
    const id = ++conn.seq;
    const timer = setTimeout(() => { conn.wait.delete(id); reject(Object.assign(new Error(t("conn.timeout")), { late: true })); }, 30000);
    conn.wait.set(id, { resolve, reject, timer });
    conn.ws.send(JSON.stringify(once ? { t: "req", id, op, args, once } : { t: "req", id, op, args }));
  });
}
// What must be done once and must not be lost — a message, a new task: sent with a key, and when no answer came (the
// link dropped, the computer was slow or away) sent again with the same key once the link is back, for ONCE_WAIT at
// most. Before, a blink of the network said "connection lost" and gave the words back while the message had gone —
// sent again, it went twice (review 2026-11-11, FE3). A computer that doesn't know keys gets no second send: only
// what never left is tried again. The computer's own refusal comes back at once, as before
const ONCE_WAIT = 120000;
const readyBy = (until) => new Promise((ok) => {
  if (conn.ready) return ok();
  const done = () => { clearTimeout(timer); off(); ok(); };
  const off = on("ready", done), timer = setTimeout(done, Math.max(0, until - Date.now()));
});
async function apiOnce(op, args = {}) {
  const key = op + "-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 12);
  const until = Date.now() + ONCE_WAIT;
  for (;;) {
    try { return await api(op, args, key); }
    catch (e) {
      const again = e.unsent || ((e.lost || e.late) && conn.caps.includes("once"));
      if (!again || Date.now() >= until) throw e;
      await readyBy(until);
    }
  }
}

// a load that runs at most every `gap` ms, one at a time — the next right after it when asked meanwhile. While events
// came faster than 0.4 s (a turn's steps, agents side by side) the screen used to wait for a pause to update at all
function pacer(run, gap = 400) {
  let busy = false, again = false, timer = 0, last = 0, dead = false;
  const go = async () => {
    timer = 0; busy = true; last = Date.now();
    try { await run(); } catch (e) { /* the screen shows its own error */ }
    busy = false;
    if (again && !dead) { again = false; kick(); }
  };
  const kick = () => {
    if (dead) return;
    if (busy) { again = true; return; }
    if (!timer) timer = setTimeout(go, Math.max(0, last + gap - Date.now()));
  };
  kick.stop = () => { dead = true; clearTimeout(timer); };
  return kick;
}

// screen data: load when the connection is ready, on "something changed" events (at most every 0.4 s) and every
// `every` ms. What an earlier screen asked for (its deps changed meanwhile) never lands on this one
// `as` — the screen's name for what it shows ("project:<key>"): its last answer is kept for this window's life, and the
// screen opens with it at once when you come back, then catches up. Before, every way back began with "Loading…" and
// an empty page — and the place you had scrolled to had nothing to come back to (review 2026-11-11, FE12, UX3)
const shown = new Map();
const SHOWN_MAX = 24;
const keepShown = (as, d) => {
  if (!as) return;
  shown.delete(as);
  shown.set(as, d);
  if (shown.size > SHOWN_MAX) shown.delete(shown.keys().next().value);
};
function useLive(load, deps, match, every = 30000, as = null) {
  const [data, setData] = useState(as && shown.has(as) ? shown.get(as) : null);
  const [err, setErr] = useState(null);
  // what the screen itself changes in its data (a switch flipped, a project pinned) is kept too: coming back must not
  // show the switch as it was before
  const put = (d) => { keepShown(as, typeof d === "function" ? d(shown.get(as)) : d); setData(d); };
  useEffect(() => {
    let alive = true;
    if (as && shown.has(as)) setData(shown.get(as));
    const keep = (d) => keepShown(as, d);
    const kick = pacer(() => load().then((d) => { if (alive) { keep(d); setData(d); setErr(null); } })
      .catch((e) => alive && setErr(e.message)));
    if (conn.ready) kick();
    const offs = [on("ready", kick), on("event", (m) => (!match || match(m)) && kick())];
    const tick = setInterval(() => conn.ready && kick(), every);
    return () => { alive = false; offs.forEach((f) => f()); clearInterval(tick); kick.stop(); };
  }, deps);
  return [data, err, put];
}

// where you are, for Pult (stage V): the app says "on screen" while it is visible — every 20 s and at once on a change
// (the page's visibility and Telegram's own activated / deactivated). Pult then calls you in the app, not in Telegram
let shownTimer = 0;
// and the link itself, at the same pace: a network switch can leave the socket open and dead. The relay answers a ping
// on its own (its hello says "pong"), so no word in 10 s is a broken link — a computer slow to answer is not one
function ping() {
  const ws = conn.ws, sent = Date.now();
  clearTimeout(pingTimer);
  if (!conn.pong || !ws || ws.readyState !== 1) return;
  ws.send(JSON.stringify({ t: "ping" }));
  pingTimer = setTimeout(() => { if (ws === conn.ws && conn.heard < sent) reconnect(); }, 10000);
}
const sayShown = () => {
  const on_ = document.visibilityState === "visible" && !(tg && tg.isActive === false);
  if (conn.ready) api("presence", { on: on_ }).catch(() => {});
  clearInterval(shownTimer);
  clearTimeout(pingTimer);              // a page Telegram froze wakes with old timers: the link is checked anew
  if (on_) {
    ping();
    shownTimer = setInterval(() => { if (conn.ready) api("presence", { on: true }).catch(() => {}); ping(); }, 20000);
  }
};
document.addEventListener("visibilitychange", sayShown);
if (tg && tg.onEvent) { tg.onEvent("activated", () => { connect(); sayShown(); }); tg.onEvent("deactivated", sayShown); }
on("hello", sayShown);
on("ready", sayShown);

function useConn() {
  const [, set] = useState(0);
  // subscribe, then re-read once: the connection may have changed between the first render and this effect
  // (opening a session link, "ready" came first and the banner stayed on "Connecting…")
  useEffect(() => { const off = on("conn", () => set((x) => x + 1)); set((x) => x + 1); return off; }, []);
  return conn;
}

export { api, apiOnce, conn, emit, on, pacer, reconnect, shown, useConn, useLang, useLive };
