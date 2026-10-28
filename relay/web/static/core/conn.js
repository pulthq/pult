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
  key: keyStore.get(), why: null, fresh: 0, updating: 0, gone: 0 };   // gone: since when the computer is away (ms, this phone's clock)
// the relay says how many seconds ago the computer went away (0.18.5): a computer silent for hours is one whose Pult
// doesn't start, and the banner says since when
const noteGone = (m) => { conn.gone = typeof m.away === "number" ? Date.now() - m.away * 1000 : conn.gone; };   // updating: since when Pult installs an update (stage U)       // fresh: when the Mac last answered — what's on screen is from then
const setState = (s) => { conn.state = s; emit("conn"); };
const setKey = (k) => { conn.key = k || null; keyStore.set(k); };

// calls made on a socket that is gone, or sent to a computer that is gone, get no answer: they fail now, not in 30 s
// (2026-10-27: a reload sent as an install stopped Pult held the table's next one back — a stale Install was tapped
// twice); `lost` — the call may have reached the computer before it went
const dropWaits = () => { for (const w of conn.wait.values()) { clearTimeout(w.timer); w.reject(Object.assign(new Error(t("conn.lost")), { lost: true })); } conn.wait.clear(); };
function connect() {
  if (conn.ws && conn.ws.readyState <= 1) return;
  conn.ready = false;
  dropWaits();
  const ws = (conn.ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/pult/ws"));
  setState("connecting");
  ws.onopen = () => ws.send(JSON.stringify({ t: "hello", init: (tg && tg.initData) || "", resume: conn.key,
    client: { platform: tg && tg.platform, version: tg && tg.version } }));
  // a socket replaced while it was closing says nothing more: its late end failed the new one's calls and planned an
  // extra reconnect (review 2026-10-27, П8); a frame that isn't JSON is no message
  ws.onmessage = (ev) => {
    if (ws !== conn.ws) return;
    let m;
    try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (!m || typeof m !== "object") return;
    if (m.t === "hello") { conn.mac = m.mac; conn.gone = 0; if (!m.mac) noteGone(m); setState(m.mac ? "auth" : "nomac"); }
    else if (m.t === "ready") {
      if (m.resume) setKey(m.resume);
      conn.ready = true; conn.retry = 0; setState("ok"); emit("ready"); api("lang").then(useLang).catch(() => {});
    }
    else if (m.t === "denied") { conn.ready = false; conn.why = m.why || null; if (m.why === "out") setKey(null); setState("denied"); }
    else if (m.t === "mac") { conn.mac = m.on; if (!m.on) { noteGone(m); conn.ready = false; dropWaits(); setState("nomac"); } else { conn.gone = 0; if (!conn.ready) setState("auth"); } }
    else if (m.t === "res") {
      const w = conn.wait.get(m.id);
      if (w) { conn.wait.delete(m.id); clearTimeout(w.timer); if (!m.error) conn.fresh = Date.now(); m.error ? w.reject(new Error(m.error)) : w.resolve(m.data); }
    } else if (m.t === "event") emit("event", m);
  };
  ws.onclose = (ev) => {
    if (ws !== conn.ws) return;
    conn.ready = false;
    dropWaits();
    if (conn.state === "denied") return;
    setState("offline");
    // "too many windows" (4429): the relay holds this phone's dead sockets up to its 25-s heartbeat — wait them out
    // instead of knocking again every few seconds
    setTimeout(connect, ev && ev.code === 4429 ? 15000 + Math.random() * 15000 : [500, 1000, 2000, 5000, 10000][Math.min(conn.retry++, 4)]);
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
function useLive(load, deps, match, every = 30000) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    let alive = true;
    const kick = pacer(() => load().then((d) => { if (alive) { setData(d); setErr(null); } })
      .catch((e) => alive && setErr(e.message)));
    if (conn.ready) kick();
    const offs = [on("ready", kick), on("event", (m) => (!match || match(m)) && kick())];
    const tick = setInterval(() => conn.ready && kick(), every);
    return () => { alive = false; offs.forEach((f) => f()); clearInterval(tick); kick.stop(); };
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

export { api, conn, emit, on, pacer, useConn, useLang, useLive };
