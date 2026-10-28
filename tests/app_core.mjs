// Pult — the app's four state machines (relay/web/static/core/) checked in node, inside a browser made up here: the
// connection, where you are, this phone's copy following the server, voice (review 2026-10-27, 6.4). Time moves only
// when a check moves it; no DOM, no network, no microphone.
//   node tests/app_core.mjs        (tests/test_web.py runs it; exit 1 and the failures when one fails)
import assert from "node:assert/strict";

// ---------- a clock of our own: timers run when a check moves time on ----------
const realImmediate = setImmediate;
const clock = { now: 1_800_000_000_000, timers: [], seq: 0 };
Date.now = () => clock.now;
globalThis.setTimeout = (fn, ms = 0, ...a) => { const id = ++clock.seq; clock.timers.push({ id, at: clock.now + Math.max(0, +ms || 0), fn, a, every: 0 }); return id; };
globalThis.setInterval = (fn, ms = 0, ...a) => { const id = ++clock.seq; const every = Math.max(1, +ms || 0); clock.timers.push({ id, at: clock.now + every, fn, a, every }); return id; };
globalThis.clearTimeout = globalThis.clearInterval = (id) => { clock.timers = clock.timers.filter((x) => x.id !== id); };
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => realImmediate(r)); };
async function later(ms) {
  const end = clock.now + ms;
  await settle();
  for (;;) {
    clock.timers.sort((x, y) => x.at - y.at || x.id - y.id);
    const x = clock.timers[0];
    if (!x || x.at > end) break;
    clock.now = x.at;
    if (x.every) x.at += x.every; else clock.timers.shift();
    x.fn(...x.a);
    await settle();
  }
  clock.now = end;
  await settle();
}
const newest = () => clock.timers.reduce((a, x) => (!a || x.id > a.id ? x : a), null);

// ---------- a browser of our own ----------
const win = new EventTarget();
globalThis.window = globalThis;
for (const k of ["addEventListener", "removeEventListener", "dispatchEvent"]) globalThis[k] = win[k].bind(win);
globalThis.HashChangeEvent = class extends Event {};
Object.assign(globalThis, { innerHeight: 800, scrollY: 0, scrollTo() {} });
const doc = new EventTarget();
Object.assign(doc, { documentElement: { dataset: {}, lang: "" }, hidden: false, visibilityState: "visible", activeElement: null,
  body: { scrollHeight: 600 }, fields: [], querySelectorAll() { return this.fields; } });
globalThis.document = doc;
const tabTo = (visible) => { doc.hidden = !visible; doc.visibilityState = visible ? "visible" : "hidden"; doc.dispatchEvent(new Event("visibilitychange")); };
// the address and the history: a hash moves forward, a layer is a step of its own, Back goes one step and says so later
let hash = "";
const steps = [{ hash: "", layer: false }];
let at = 0;
const loc = { protocol: "https:", host: "pult.test", pathname: "/pult/", reloads: 0, reload() { this.reloads++; },
  replace(h) { steps[at] = { hash: h, layer: false }; const was = hash; hash = h; if (was !== h) dispatchEvent(new HashChangeEvent("hashchange")); } };
Object.defineProperty(loc, "hash", { get: () => hash, set: (h) => {
  h = h.startsWith("#") ? h : "#" + h;
  if (h === hash) return;
  steps.splice(at + 1); steps.push({ hash: h, layer: false }); at++; hash = h; dispatchEvent(new HashChangeEvent("hashchange"));
} });
globalThis.location = loc;
globalThis.history = {
  pushState(st, _t, url) { steps.splice(at + 1); steps.push({ hash: url || hash, layer: !!(st && st.overlay) }); at++; if (url) hash = url; },
  replaceState(st, _t, url) { steps[at] = { hash: url || hash, layer: !!(st && st.overlay) }; if (url) hash = url; },
  back() {
    if (at === 0) return;
    at--;
    const to = steps[at].hash;
    realImmediate(() => { dispatchEvent(new Event("popstate")); if (to !== hash) { hash = to; dispatchEvent(new HashChangeEvent("hashchange")); } });
  },
};
const store = new Map();
globalThis.sessionStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) };
// the relay's socket: what the app sends, and what it is told; "on screen" every 20 s and the language at a login are
// answered at once, as the computer does — left waiting, they would count as calls on their way
class FakeWS {
  constructor(url) { this.url = url; this.readyState = 0; this.sent = []; FakeWS.all.push(this); }
  send(s) {
    const m = JSON.parse(s);
    this.sent.push(m);
    if (m.t === "req" && (m.op === "presence" || m.op === "lang")) realImmediate(() => this.onmessage({ data: JSON.stringify({ t: "res", id: m.id, data: null }) }));
  }
}
FakeWS.all = [];
globalThis.WebSocket = FakeWS;
const ws = () => FakeWS.all[FakeWS.all.length - 1];
const tell = (w, m) => w.onmessage({ data: JSON.stringify(m) });
const asked = (w, op) => w.sent.filter((m) => m.t === "req" && (!op || m.op === op));
// the server's page: which copy of the app it hands out now
const page = { v: "100" };
globalThis.fetch = async () => ({ text: async () => '<script type="module" src="/pult/static/app.js?v=' + page.v + '"></script>' });
// Telegram: opened from a session's link
const SID = "0f8fad5b-d9cb-469f-a165-70867728950e";
const alerts = [], opened = [];
window.Telegram = { WebApp: { initData: "init-data", initDataUnsafe: { user: { language_code: "en" }, start_param: "s_" + SID },
  platform: "android", version: "8.0", ready() {}, expand() {}, onEvent() {}, BackButton: { show() {}, hide() {} },
  HapticFeedback: { notificationOccurred() {}, impactOccurred() {} }, showAlert: (s) => alerts.push(s), openLink: (u) => opened.push(u) } };
// the microphone, its sound and the recorder
const audio = { level: 0 }, asks = [], recs = [];
class Track { constructor() { this.readyState = "live"; this.enabled = true; } stop() { this.readyState = "ended"; } }
class Stream { constructor() { this.tracks = [new Track()]; } getTracks() { return this.tracks; } }
Object.defineProperty(globalThis, "navigator", { configurable: true, writable: true,
  value: { mediaDevices: { getUserMedia: async (c) => { asks.push(c); return new Stream(); } } } });
globalThis.AudioContext = class { constructor() { this.state = "running"; }
  resume() { this.state = "running"; return Promise.resolve(); } suspend() { this.state = "suspended"; return Promise.resolve(); }
  createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
  createAnalyser() { return { fftSize: 2048, getFloatTimeDomainData(buf) { buf.fill(audio.level); } }; } };
globalThis.MediaRecorder = class { constructor(stream, o) { this.stream = stream; this.mimeType = (o && o.mimeType) || ""; this.state = "inactive"; recs.push(this); }
  static isTypeSupported(m) { return m === "audio/webm;codecs=opus"; }
  start(slice) { this.state = "recording"; setTimeout(() => this.onstart && this.onstart(), 30);
    this.tick = setInterval(() => this.ondataavailable({ data: new Blob([new Uint8Array(700)]) }), slice); }
  stop() { if (this.state === "inactive") return; this.state = "inactive"; clearInterval(this.tick);
    this.ondataavailable({ data: new Blob([new Uint8Array(700)]) }); setTimeout(() => this.onstop(), 0); } };
globalThis.FileReader = class { readAsDataURL(b) { b.arrayBuffer().then((x) => { this.result = "data:" + b.type + ";base64," + Buffer.from(x).toString("base64"); this.onload(); }); } };

// ---------- the modules, the way the app loads them ----------
const base = new URL("../relay/web/static/", import.meta.url);
const { t } = await import(new URL("i18n.js", base));
const C = await import(new URL("core/conn.js", base));
const N = await import(new URL("core/nav.js", base));
const V = await import(new URL("core/voice.js", base));
const U = await import(new URL("core/update.js?v=100", base));      // this window runs the copy ?v=100
const { html, render } = await import(new URL("vendor/htm-preact-3.1.1.js", base));

const results = [];
async function check(name, fn) {
  try { await fn(); results.push("ok   " + name); } catch (e) { results.push("FAIL " + name + "\n" + (e && e.stack || e)); }
}
// what is still waiting for the computer's answer gets one: the checks after it start clean
const answerAll = (w) => { for (const r of asked(w)) if (C.conn.wait.has(r.id)) tell(w, { t: "res", id: r.id, data: null }); };
async function readyOn(w) {
  w.readyState = 1; w.onopen(); tell(w, { t: "hello", mac: true }); tell(w, { t: "ready" }); await settle(); answerAll(w);
}
const close = (w, code) => { w.readyState = 3; w.onclose({ code }); };

// ---------- every module of the app loads: a name it imports that nobody exports is a white screen on the phone ----------
await check("modules: each of ui/ and screens/ loads, with what it says it exports", async () => {
  const { readdirSync } = await import("node:fs");
  const mods = ["ui", "screens"].flatMap((d) => readdirSync(new URL(d + "/", base)).filter((f) => f.endsWith(".js")).map((f) => d + "/" + f));
  assert.ok(mods.length >= 10, "found " + mods.length);
  for (const m of mods) {
    const x = await import(new URL(m, base));
    assert.ok(Object.keys(x).length > 0, m + " exports nothing");
    for (const [k, v] of Object.entries(x)) assert.notEqual(v, undefined, m + ": " + k + " is undefined");
  }
});

// ---------- the connection ----------
await check("connection: says hello with Telegram's data, and a ready login keeps its resume key", async () => {
  const w = ws();
  assert.equal(w.url, "wss://pult.test/pult/ws");
  w.readyState = 1; w.onopen();
  assert.deepEqual(w.sent[0], { t: "hello", init: "init-data", resume: null, client: { platform: "android", version: "8.0" } });
  tell(w, { t: "hello", mac: true });
  assert.equal(C.conn.state, "auth");
  tell(w, { t: "ready", resume: "K1" });
  assert.equal(C.conn.state, "ok");
  assert.equal(C.conn.ready, true);
  assert.equal(sessionStorage.getItem("pult.resume"), "K1");
  assert.ok(asked(w, "lang").length === 1, "asks the computer's language once ready");
});
await check("connection: each answer goes to its own request, an error rejects it", async () => {
  const w = ws();
  const a = C.api("one", { x: 1 }), b = C.api("two");
  const [ra, rb] = [asked(w, "one")[0], asked(w, "two")[0]];
  assert.deepEqual(ra.args, { x: 1 });
  tell(w, { t: "res", id: rb.id, data: "B" });
  tell(w, { t: "res", id: ra.id, data: "A" });
  assert.deepEqual(await Promise.all([a, b]), ["A", "B"]);
  const c = C.api("three");
  tell(w, { t: "res", id: asked(w, "three")[0].id, error: "no such thing" });
  await assert.rejects(c, /no such thing/);
  await settle();
  assert.equal(C.conn.wait.size, 0);
});
await check("connection: no answer in 30 s — the request fails, and nothing waits for it", async () => {
  const p = C.api("slow");
  const err = p.catch((e) => e);
  await later(29_000);
  assert.equal(C.conn.wait.size, 1);
  await later(1_000);
  assert.equal((await err).message, t("conn.timeout"));
  assert.equal(C.conn.wait.size, 0);
});
await check("connection: a dropped socket fails what waits at once (lost) and knocks again 0.5 → 1 → 2 → 5 → 10 → 10 s", async () => {
  const p = C.api("on-the-way").catch((e) => e);
  close(ws(), 1006);
  const e = await p;
  assert.equal(e.lost, true);
  assert.equal(C.conn.state, "offline");
  const waits = [];
  for (let i = 0; i < 6; i++) {
    const x = newest();
    waits.push(x.at - clock.now);
    const n = FakeWS.all.length;
    await later(x.at - clock.now);
    assert.equal(FakeWS.all.length, n + 1, "a new socket after the wait");
    if (i < 5) close(ws(), 1006);
  }
  assert.deepEqual(waits, [500, 1000, 2000, 5000, 10000, 10000]);
});
await check("connection: a login starts the count anew; \"too many windows\" (4429) waits 15–30 s", async () => {
  await readyOn(ws());
  close(ws(), 1006);
  assert.equal(newest().at - clock.now, 500);
  await later(500);
  await readyOn(ws());
  close(ws(), 4429);
  const wait = newest().at - clock.now;
  assert.ok(wait >= 15000 && wait <= 30000, "waited " + wait);
  await later(wait);
});
await check("connection: a replaced socket's late words change nothing", async () => {
  const old = ws();
  await readyOn(old);
  close(old, 1006);
  await later(500);
  const cur = ws();
  await readyOn(cur);
  const p = C.api("now");
  tell(old, { t: "mac", on: false });
  old.onclose({ code: 1006 });
  assert.equal(C.conn.state, "ok");
  tell(cur, { t: "res", id: asked(cur, "now")[0].id, data: 1 });
  assert.equal(await p, 1);
});
await check("connection: logged out everywhere — the key goes, no knocking again; back on the screen — a fresh start", async () => {
  const w = ws();
  tell(w, { t: "denied", why: "out" });
  assert.equal(C.conn.state, "denied");
  assert.equal(sessionStorage.getItem("pult.resume"), null);
  const n = clock.timers.length;
  close(w, 1000);
  assert.equal(clock.timers.length, n, "no reconnect planned");
  await assert.rejects(C.api("x"), new RegExp(t("conn.nomac").slice(0, 12)));
  tabTo(false); tabTo(true);
  assert.notEqual(ws(), w, "a new socket when the app comes back");
  await readyOn(ws());
});

// ---------- where you are ----------
await check("where: a session's link from Telegram opens that session", async () => {
  assert.equal(location.hash, "#/s/" + SID);
  assert.deepEqual(N.stack, ["#/s/" + SID]);
  assert.equal(N.parse().name, "s");
  assert.equal(N.parse().id, SID);
});
await check("where: Back closes the layer on top first, then goes back a screen, then home", async () => {
  N.go("#/settings");
  await settle();
  assert.deepEqual(N.stack, ["#/s/" + SID, "#/settings"]);
  let closed = 0;
  N.openLayer(() => { closed++; });
  assert.equal(N.layers.length, 1);
  N.back(); await settle();
  assert.equal(closed, 1, "the layer closed");
  assert.equal(location.hash, "#/settings", "the screen stayed");
  N.back(); await settle();
  assert.equal(location.hash, "#/s/" + SID);
  assert.deepEqual(N.stack, ["#/s/" + SID]);
  N.back(); await settle();
  assert.equal(location.hash, "#/");
  assert.equal(N.parse().name, "home");
});
await check("where: a screen left for good is replaced — Back skips it", async () => {
  N.go("#/new"); await settle();
  N.go("#/s/abc", true); await settle();
  assert.deepEqual(N.stack.slice(-2), ["#/", "#/s/abc"]);
  N.back(); await settle();
  assert.equal(location.hash, "#/");
});
await check("where: addresses — Telegram's own is home, a screen with its id and query", async () => {
  location.replace("#tgWebAppData=abc");
  assert.equal(N.parse().name, "home");
  location.replace("#/f/" + SID + "?t=3");
  const r = N.parse();
  assert.deepEqual([r.name, r.id, r.q.get("t")], ["f", SID, "3"]);
  location.replace("#/");
});
await check("where: words dictated after their screen went wait for it, once", async () => {
  N.drafts.put("s1", "first");
  N.drafts.put("s1", "second");
  assert.equal(N.drafts.take("s1"), "first second");
  assert.equal(N.drafts.take("s1"), "");
});
await check("where: a link to a project file opens over the screen; a web link — outside, through Telegram", async () => {
  const files = [];
  const off = C.on("file", (f) => files.push(f));
  const a = { dataset: { file: "src/x.py" }, closest: (s) => (s === "[data-sid]" ? { dataset: { sid: "S1", base: "docs" } } : null) };
  const click = (target) => { const e = new Event("click", { cancelable: true }); Object.defineProperty(e, "target", { value: target }); doc.dispatchEvent(e); return e; };
  const e1 = click({ closest: (s) => (s === "a[data-file]" ? a : null) });
  assert.deepEqual(files, [{ sid: "S1", p: "src/x.py", base: "docs" }]);
  assert.ok(e1.defaultPrevented);
  click({ closest: (s) => (s === "a[data-ext]" ? { href: "https://example.org/" } : null) });
  assert.deepEqual(opened, ["https://example.org/"]);
  off();
});

// ---------- an update: the computer installing; this phone's copy following the server ----------
await check("update: the computer installing shows until it's done; the app's server restarting — its own word", async () => {
  let told = 0;
  const off = C.on("conn", () => told++);
  C.emit("event", { kind: "update", state: "run" });
  assert.ok(C.conn.updating > 0);
  assert.equal(C.conn.updSrv, false);
  const since = C.conn.updating;
  await later(1000);
  U.noteUpd("srv_run");
  assert.equal(C.conn.updating, since, "still the same install");
  assert.equal(C.conn.updSrv, true);
  U.noteUpd("done");
  assert.equal(C.conn.updating, 0);
  assert.equal(told, 2, "told on the start and the end only");
  off();
});
await check("update: a newer copy on the server — the page reloads 8 s later, when nothing would be lost", async () => {
  answerAll(ws());
  assert.equal(U.OWN_V, "100");
  page.v = "200";
  await U.checkServed(true);
  assert.equal(U.phoneOld(), true);
  await later(7_900);
  assert.equal(location.reloads, 0);
  await later(200);
  assert.equal(location.reloads, 1);
});
await check("update: not under a layer, a held recording or countdown, typed words, a session read far from its end, a call on its way", async () => {
  const blockers = [
    [() => { let c; N.openLayer(() => {}); c = () => N.layers.pop(); return c; }, "a layer"],
    [() => { N.holdBy(1); return () => N.holdBy(-1); }, "a hold"],
    [() => { doc.fields = [{ type: "text", value: "half a thought" }]; return () => { doc.fields = []; }; }, "typed words"],
    [() => { doc.activeElement = { tagName: "TEXTAREA" }; return () => { doc.activeElement = null; }; }, "a field in focus"],
    [() => { location.replace("#/s/" + SID); doc.body.scrollHeight = 5000; return () => { doc.body.scrollHeight = 600; }; }, "reading far from the end"],
    [() => { C.api("slow-call").catch(() => {}); return () => answerAll(ws()); }, "a call on its way"],
  ];
  for (const [put, what] of blockers) {
    const n = location.reloads;
    page.v = String(+page.v + 1);
    const undo = put();
    await U.checkServed(true);
    await later(8_200);
    assert.equal(location.reloads, n, "reloaded under " + what);
    await later(10_000);
    assert.equal(location.reloads, n, "reloaded under " + what + " later");
    undo();
    await later(5_100);
    assert.equal(location.reloads, n + 1, "no reload once " + what + " is gone");
  }
  location.replace("#/");
});
await check("update: a copy still changing on the server (a deploy writes file by file) — 8 s more", async () => {
  const n = location.reloads;
  page.v = "500";
  await U.checkServed(true);
  await later(4_000);
  page.v = "501";
  await later(4_200);
  assert.equal(location.reloads, n, "not while it changes");
  await later(8_200);
  assert.equal(location.reloads, n + 1);
});

// ---------- voice ----------
await check("voice: the microphone is asked for once, rests muted, goes after 10 min or when the app leaves the screen", async () => {
  const before = asks.length;
  const [s1, took] = await V.getMic();
  assert.equal(asks.length, before + 1);
  assert.deepEqual(asks.at(-1), { audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
  assert.equal(typeof took, "number");
  V.restMic();
  assert.equal(s1.tracks[0].enabled, false, "muted between recordings");
  await later(V.MIC_HOLD - 1000);
  const [s2, again] = await V.getMic();
  assert.equal(s2, s1);
  assert.equal(again, null, "not asked again");
  assert.equal(s1.tracks[0].enabled, true);
  V.restMic();
  await later(V.MIC_HOLD);
  assert.equal(s1.tracks[0].readyState, "ended", "let go after 10 min");
  assert.equal(V.mic, null);
  await V.getMic();
  tabTo(false);
  assert.equal(V.mic, null, "let go when the app leaves the screen");
  tabTo(true);
  await readyOn(ws());
});
await check("voice: the level — silence far below the voice threshold, speech above", async () => {
  const m = { an: { getFloatTimeDomainData: (b) => b.fill(audio.level) }, buf: new Float32Array(2048) };
  audio.level = 0;
  assert.ok(V.loudness(m).db < -150);
  audio.level = 0.001;
  assert.ok(Math.abs(V.loudness(m).db + 60) < 0.01 && V.loudness(m).db < V.VOICE_DB, "-60 dBFS — not a voice");
  audio.level = 0.05;
  assert.ok(V.loudness(m).db > V.VOICE_DB, "-26 dBFS — a voice");
  assert.equal(V.loudness(m).peak, Math.fround(0.05));
  audio.level = 0;
});
// the recorder runs as a screen runs it: a component that draws nothing, rendered by Preact into a parent of our own
const rec = {};
function Probe() { rec.r = V.useRecorder((words) => { rec.words = words; }, "probe"); return null; }
const root = { childNodes: [], firstChild: null, appendChild() {}, insertBefore() {}, removeChild() {} };
render(html`<${Probe}/>`, root);
await later(200);
async function record(level, secs, { stopAt = true } = {}) {
  rec.words = undefined;
  audio.level = level;
  const tap = rec.r.toggle();
  await later(100);
  await tap;
  await later(secs * 1000);
  if (stopAt) { rec.r.toggle(); await later(400); }
}
await check("voice: words spoken go to the field, and the reload guard lets go when it's over", async () => {
  assert.equal(rec.r.st, "idle");
  await record(0.05, 3);
  const r = asked(ws(), "stt").at(-1);
  assert.ok(r.args.data.length > 100 && r.args.mime === "audio/webm;codecs=opus");
  assert.ok(r.args.notes.voice !== null && r.args.notes.peak > V.VOICE_DB, "the voice is in the figures");
  assert.equal(N.holds, 1, "held while the words are on their way");
  tell(ws(), { t: "res", id: r.id, data: { text: "buy milk" } });
  await later(50);
  assert.equal(rec.words, "buy milk");
  assert.equal(rec.r.st, "idle");
  assert.equal(N.holds, 0);
});
await check("voice: sound but no voice — \"nothing was heard\", nothing sent", async () => {
  const n = asked(ws(), "stt").length;
  await record(0.001, 3);
  assert.equal(asked(ws(), "stt").length, n, "silence isn't sent: over it Whisper makes up credits");
  assert.equal(alerts.at(-1), t("rec.silent"));
  assert.equal(N.holds, 0);
});
await check("voice: a recording stops by itself after 5 minutes", async () => {
  await record(0.05, V.REC_MAX + 1, { stopAt: false });
  await later(400);
  const r = asked(ws(), "stt").at(-1);
  assert.ok(r.args.notes.secs >= V.REC_MAX && r.args.notes.secs < V.REC_MAX + 2, "stopped at " + r.args.notes.secs + " s");
  tell(ws(), { t: "res", id: r.id, data: { text: "a long one" } });
  await later(50);
  assert.equal(rec.words, "a long one");
  assert.equal(rec.r.st, "idle");
});

// last: from it on, this window sends no figures
await check("voice: a computer before 0.14.2 refuses the recording's figures — sent again without them, and from then on", async () => {
  const w = ws();
  const p = V.sttSend("AAAA", "audio/webm", { secs: 2 });
  await settle();
  const r1 = asked(w, "stt").at(-1);
  assert.deepEqual(r1.args, { data: "AAAA", mime: "audio/webm", notes: { secs: 2 } });
  tell(w, { t: "res", id: r1.id, error: "TypeError: api_stt() got an unexpected keyword argument 'notes'" });
  await settle();
  const r2 = asked(w, "stt").at(-1);
  assert.deepEqual(r2.args, { data: "AAAA", mime: "audio/webm" });
  tell(w, { t: "res", id: r2.id, data: { text: "hello" } });
  assert.deepEqual(await p, { text: "hello" });
  const q = V.sttSend("BBBB", "audio/webm", { secs: 1 });
  await settle();
  const r3 = asked(w, "stt").at(-1);
  assert.equal(r3.args.notes, undefined);
  tell(w, { t: "res", id: r3.id, data: { text: "" } });
  await q;
});

// last: the entry itself — every name app.js imports exists (a missing one fails before anything runs); drawing the
// app needs a DOM node doesn't have, so its render failing for that is fine here
await check("modules: app.js links — every name it imports is there", async () => {
  doc.getElementById = () => null;
  try { await import(new URL("app.js", base)); } catch (e) {
    assert.ok(!(e instanceof SyntaxError), "app.js doesn't link: " + e.message);
  }
});

for (const r of results) console.log(r);
const failed = results.filter((r) => r.startsWith("FAIL")).length;
console.log(failed ? failed + " of " + results.length + " failed" : results.length + " checks ok");
process.exit(failed ? 1 : 0);
