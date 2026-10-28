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
    hold(true);
    setSt("wait");
    let stream, asked;
    try { [stream, asked] = await getMic(); } catch (e) { dropMic(); idle(); return say("rec.denied"); }
    // the wait for sound counts from the microphone given, not from the tap: Telegram's question took its own time,
    // and "speak" right after it, before sound flows, was what lost the first syllable
    const t0 = Date.now();
    const mime = REC_MIME.find((m) => MediaRecorder.isTypeSupported(m)) || "";
    let rec;
    try { rec = new MediaRecorder(stream, Object.assign({ audioBitsPerSecond: 32000 }, mime ? { mimeType: mime } : {})); }
    catch (e) { dropMic(); idle(); return say("rec.unsupported"); }
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
      if (blob.size < 1000 || !x.live) { idle(); return say("rec.empty"); }
      if (x.heard && x.loud < VOICE_MIN) { idle(); return say("rec.silent"); }
      if (alive.current) setSt("busy");
      const r1 = (v) => Math.round(v * 10) / 10;
      const notes = { secs: r1((Date.now() - x.live) / 1000) };
      if (asked !== null) notes.asked = asked;
      if (x.heard) Object.assign(notes, { ready: x.live - t0, voice: x.voice, first: r1(x.first), peak: r1(x.peak) });
      try {
        const url = await new Promise((ok, no) => { const f = new FileReader(); f.onload = () => ok(f.result); f.onerror = no; f.readAsDataURL(blob); });
        const res = await sttSend(url.split(",")[1], blob.type, notes);
        if (res.text && alive.current) { onText(res.text); haptic("success"); }
        else if (res.text && draft) drafts.put(draft, res.text);      // the screen went meanwhile: its field gets them back
      } catch (e) { if (alive.current) alertBox(e.message); }
      idle();
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
  // the screen goes: the recording stops and its words, once heard, go to the draft (the hold lasts until then)
  useEffect(() => () => {
    alive.current = false;
    const x = cur.current;
    if (x) { clearInterval(x.timer); try { x.rec.stop(); } catch (e) { hold(false); } } else hold(false);
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

export { MIC_HOLD, Mic, REC_MAX, VOICE_DB, VOICE_MIN, dropMic, getMic, loudness, mic, restMic, sttSend, useRecorder };
