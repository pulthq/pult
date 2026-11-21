// Pult app — voice from the phone: the microphone, its loudness, a recording into words.
// Moved from app.js as it was (review 2026-10-27, 6.4).
import { t } from "../i18n.js";
import { html, useEffect, useRef, useState } from "../vendor/htm-preact-3.1.1.js";
import { api } from "./conn.js";
import { drafts, holdBy } from "./nav.js";
import { alertBox, haptic, tg } from "./tg.js";

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
// A long recording goes to Whisper in pieces cut at pauses. Whole, it is read 30 s at a time, each window after the
// words of the one before, and after a pause of several seconds a window may come back with a few made-up words in
// place of its speech: the owner's 125-s recording came back right for its first 36 s and made up after (2026-11-21;
// fact 5 of tests/probe_stt.py — with either model, with the prompt or without). A piece within one window and with
// no long silence in it is read right. So the recorder starts anew at a pause — a shorter one the longer the piece
// already is — and at 28 s whatever comes; silence alone is dropped every 2 s and never sent (over it Whisper makes
// up credits). A piece goes to the computer the moment it is cut; the words land in the field together after "Stop",
// in order
const PIECE_MAX = 28;                    // s: within Whisper's window of 30
const PIECE_DROP = 2;                    // s of a piece with no voice yet: dropped, a new one starts
const PIECE_PAUSE = [[5, 3], [12, 1.2], [22, 0.6], [PIECE_MAX, 0.25]];   // [a piece shorter than s, the pause that ends it]
const PAUSE_DB = 30;                     // this far under the piece's loudest is a pause too: a street has no silence
// what the piece being recorded asks for: "" — go on, "cut" — it ends here, "drop" — silence only, start anew. len — s
// since it began, quiet — s since its voice was last heard, voiced — whether it was heard at all
function pieceCut(len, quiet, voiced) {
  if (!voiced) return len >= PIECE_DROP ? "drop" : "";
  if (len >= PIECE_MAX) return "cut";
  const p = PIECE_PAUSE.find(([upTo]) => len < upTo);
  return p && quiet >= p[1] ? "cut" : "";
}
const MIC_AUDIO = { echoCancellation: false, noiseSuppression: false, autoGainControl: false };
// The microphone and the page's sound are let go the moment a recording ends. A page that captures sound makes the
// phone's headphones its "communication device" (Chromium's AudioManagerAndroid: wired, then USB, then Bluetooth —
// whose call profile is mono and muffled), and Android (14 QPR3 on, AudioDeviceBroker) keeps that route while the app
// records or plays anything — the level meter's AudioContext too — and 6 s more. Until 0.18.48 the stream was kept,
// muted, 10 min after a recording so that Telegram wouldn't ask again: the owner heard YouTube go bad in their
// headphones after every recording (2026-11-06) and chose to have them let go at once (Q155). Telegram on Android asks
// "allow the microphone?" at every getUserMedia and keeps nothing (DrKLO/Telegram 12.10.4,
// BotWebViewContainer.onPermissionRequest), so it asks before every recording now
const mics = new Set();      // the streams of the recordings going on: one, two only if two fields record at once
// → [the stream, ms the phone took to give it: the owner's answer to Telegram's question is in it]
async function getMic() {
  const t0 = Date.now();
  const s = await navigator.mediaDevices.getUserMedia({ audio: MIC_AUDIO });
  mics.add(s);
  return [s, Date.now() - t0];
}
// lets go of these streams; with none left, the page's sound stops too
function dropMic(...streams) {
  for (const s of streams) { s.getTracks().forEach((tr) => tr.stop()); mics.delete(s); }
  if (!mics.size && actx && actx.state === "running") actx.suspend().catch(() => {});
}
const micLive = () => [...mics].some((s) => s.getTracks().some((tr) => tr.readyState === "live"));
document.addEventListener("visibilitychange", () => { if (document.hidden) dropMic(...mics); });
// the level meter: one AudioContext for the page, an analyser on each recording's microphone. Nothing is played — the
// meter only tells when sound starts to flow, whether there was a voice, and how loud (for the computer's log)
let actx = null;
function audioCtx() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!actx && AC) { try { actx = new AC(); } catch (e) { actx = null; } }
  // even while it reads "running": a suspend still on its way would otherwise leave this recording without sound
  if (actx && actx.state !== "closed") actx.resume().catch(() => {});
  return actx;
}
function meterOn(stream) {
  const ac = audioCtx();
  if (!ac) return null;
  try {
    const src = ac.createMediaStreamSource(stream), an = ac.createAnalyser();
    an.fftSize = 2048;
    src.connect(an);
    return { src, an, buf: new Float32Array(an.fftSize) };
  } catch (e) { return null; }
}
const meterOff = (m) => { if (m) { try { m.src.disconnect(); } catch (e) { /* already gone */ } } };
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
function useRecorder(onText, draft) {
  const [st, setSt] = useState("idle");           // idle | wait (the microphone wakes up) | rec | busy
  const [secs, setSecs] = useState(0);
  const cur = useRef(null);
  const alive = useRef(true);                     // the screen is still here: words go to its field, else to its draft
  const held = useRef(false);
  const hold = (on) => { if (on !== held.current) { held.current = on; holdBy(on ? 1 : -1); } };
  const idle = () => { hold(false); if (alive.current) { setSt("idle"); setSecs(0); } };
  const say = (k) => { if (alive.current) alertBox(t(k)); };
  const dot = useRef(null);                       // the red dot: it breathes with the voice
  const stop = () => {
    const x = cur.current;
    if (!x || x.stopping || x.cur.rec.state === "inactive") return;
    x.stopping = true;
    if (!x.live) return x.cur.rec.stop();
    setSt("busy");
    setTimeout(() => { if (x.cur.rec.state !== "inactive") x.cur.rec.stop(); }, REC_TAIL);
  };
  const toggle = async () => {
    if (st !== "idle") return stop();
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder)) return alertBox(t("rec.unsupported"));
    audioCtx();                                   // within the tap itself: a browser lets audio start only from one
    hold(true);
    setSt("wait");
    let stream, asked;
    try { [stream, asked] = await getMic(); } catch (e) { dropMic(); idle(); return say("rec.denied"); }
    // the screen went while Telegram asked: nobody is left to tap "Stop"
    if (!alive.current) { dropMic(stream); return idle(); }
    // the wait for sound counts from the microphone given, not from the tap: Telegram's question took its own time,
    // and "speak" right after it, before sound flows, was what lost the first syllable
    const t0 = Date.now();
    const mime = REC_MIME.find((m) => MediaRecorder.isTypeSupported(m)) || "";
    const opts = Object.assign({ audioBitsPerSecond: 32000 }, mime ? { mimeType: mime } : {});
    const r1 = (v) => Math.round(v * 10) / 10;
    let m = null;                                 // the level meter, once the first piece records
    // cur — the piece being recorded; sent — the pieces gone to the computer, in order; whole — no second recorder
    // here (the phone refused one): the rest goes as one piece, the way every recording went before 2026-11-21
    const x = (cur.current = { cur: null, sent: [], whole: false, timer: 0, started: false, stopping: false, live: 0,
                               heard: false, secs: 0, loud: 0, voice: null, first: -200, peak: -200 });
    // a piece: a recorder of its own on the same microphone, its sound in its blob once it stops. One that stops while
    // it is still the piece being recorded — "Stop", 5 minutes, the screen gone, the microphone lost — ends it all
    const piece = () => {
      const rec = new MediaRecorder(stream, opts);
      const p = { rec, chunks: [], at: Date.now(), end: 0, loud: 0, last: 0, peak: -200, words: null, err: null };
      p.blob = new Promise((ok) => {
        rec.onstop = () => {
          p.end = p.end || Date.now();
          ok(new Blob(p.chunks, { type: rec.mimeType || mime || "audio/webm" }));
          if (x.cur === p) end();
        };
      });
      rec.ondataavailable = (e) => { if (e.data && e.data.size) p.chunks.push(e.data); };
      rec.start(1000);
      return p;
    };
    // a piece to the computer at once, with its figures for the log (the first one with the recording's own): its
    // words come back while the recording goes on
    const ask = (p) => p.blob
      .then((blob) => new Promise((ok, no) => { const f = new FileReader(); f.onload = () => ok([f.result, blob.type]); f.onerror = no; f.readAsDataURL(blob); }))
      .then(([url, type]) => sttSend(url.split(",")[1], type, p.notes))
      .then((res) => { p.err = null; return (res && res.text) || ""; }, (e) => { p.err = e; return ""; });
    const send = (p) => {
      const from = Math.max(p.at, x.live);
      p.notes = { secs: r1((p.end - from) / 1000), part: x.sent.length + 1, at: r1((from - x.live) / 1000) };
      if (!x.sent.length) {
        p.notes.asked = asked;
        if (x.heard) Object.assign(p.notes, { ready: x.live - t0, voice: x.voice, first: r1(x.first) });
      }
      if (x.heard) p.notes.peak = r1(p.peak);
      p.words = ask(p);
      x.sent.push(p);
    };
    // the piece being recorded ends here; the next one starts before it stops, so no sound falls between the two
    const next = (cut) => {
      const old = x.cur;
      try { x.cur = piece(); } catch (e) { x.whole = true; return; }
      old.end = Date.now();
      if (cut && old.loud >= VOICE_MIN) send(old);
      old.rec.stop();
    };
    // the recording is over: the last piece goes too, and the words of all land together, in order
    const end = async () => {
      clearInterval(x.timer); meterOff(m); dropMic(stream); cur.current = null;
      if (dot.current) { dot.current.style.transform = ""; dot.current.style.animation = ""; }
      const last = x.cur, blob = await last.blob;
      if (!x.live || (!x.sent.length && blob.size < 1000)) { idle(); return say("rec.empty"); }
      if (x.heard ? last.loud >= VOICE_MIN : blob.size >= 1000) send(last);
      if (!x.sent.length) { idle(); return say("rec.silent"); }
      if (alive.current) setSt("busy");
      // a piece the link let down — it never left, the socket dropped, no answer in 30 s: once more as soon as that is
      // known and the recording is over, the way the whole recording went at the end before
      const land = (p) => p.words.then((w) => (p.err && (p.err.unsent || p.err.lost || p.err.late) && !p.again
        ? ((p.again = true), ask(p)) : w));
      const text = (await Promise.all(x.sent.map(land))).filter(Boolean).join(" ");
      const err = (x.sent.find((p) => p.err) || {}).err;
      if (text && alive.current) { onText(text); haptic("success"); }
      else if (text && draft) drafts.put(draft, text);      // the screen went meanwhile: its field gets them back
      if (alive.current && err) alertBox(text ? t("rec.part", { err: err.message }) : err.message);
      else if (alive.current && !text) alertBox(t("rec.none"));
      idle();
    };
    try { x.cur = piece(); } catch (e) { cur.current = null; dropMic(stream); idle(); return say("rec.unsupported"); }
    x.cur.rec.onstart = () => { x.started = true; };
    m = meterOn(stream);
    const goLive = (heard) => {
      x.live = Date.now(); x.heard = heard;
      setSt("rec"); setSecs(0);
      if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("medium");
    };
    x.timer = setInterval(() => {
      const now = Date.now(), p = x.cur;
      if (m) {
        const { peak, db } = loudness(m);
        if (!x.live && x.started && peak > 1e-5) goLive(true);
        if (x.heard) {
          if (db > x.peak) x.peak = db;
          if (db > p.peak) p.peak = db;
          if (now - x.live <= 1000 && db > x.first) x.first = db;
          if (db > VOICE_DB) {
            x.loud++; p.loud++;
            if (x.voice === null) x.voice = Math.max(0, now - x.live);   // live may be set a millisecond after `now`
            if (db >= p.peak - PAUSE_DB) p.last = now;
          }
          if (dot.current) {                      // breathes with the voice instead of blinking
            dot.current.style.animation = "none";
            dot.current.style.transform = "scale(" + (1 + Math.min(0.8, Math.max(0, db - VOICE_DB) / 40)).toFixed(2) + ")";
          }
          if (!x.stopping && !x.whole) {
            const what = pieceCut((now - p.at) / 1000, (now - (p.last || Math.max(p.at, x.live))) / 1000, p.loud > 0);
            if (what) next(what === "cut");
          }
        }
      }
      if (!x.live && now - t0 > REC_WAIT) goLive(false);
      if (!x.live) return;
      const s = Math.floor((now - x.live) / 1000);
      if (s !== x.secs) { x.secs = s; setSecs(s); }
      if (s >= REC_MAX) stop();
    }, 50);
  };
  // the screen goes: the recording stops and its words, once heard, go to the draft (the hold lasts until then)
  useEffect(() => () => {
    alive.current = false;
    const x = cur.current;
    if (x) { clearInterval(x.timer); try { x.cur.rec.stop(); } catch (e) { hold(false); } } else hold(false);
  }, []);
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

export { Mic, PIECE_MAX, REC_MAX, VOICE_DB, VOICE_MIN, dropMic, getMic, loudness, micLive, pieceCut, sttSend, useRecorder };
