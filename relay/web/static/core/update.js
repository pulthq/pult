// Pult app — an update: the computer installing, and this phone's copy of the app following the server.
// Moved from app.js as it was (review 2026-10-27, 6.4).
import { useEffect, useState } from "../vendor/htm-preact-3.1.1.js";
import { conn, emit, on } from "./conn.js";
import { holds, layers } from "./nav.js";
import { mic } from "./voice.js";

// stage U: an update from the app. Pult knows the folder it was installed from; a commit there that changed its
// files is offered here. "run" — the computer restarts Pult: the banner says so instead of "offline" for a while
const UPD_RUN_MAX = 180000;
function noteUpd(state) {
  const was = conn.updating;
  conn.updating = state === "run" || state === "srv_run" ? was || Date.now() : 0;
  conn.updSrv = state === "srv_run";         // stage U3: the app's server restarts — seconds, not the computer's 15
  if (!was !== !conn.updating) emit("conn");
}
// on any screen: an install started while the owner reads a session was "the computer is offline" (review 2026-10-27, П8)
on("event", (m) => { if (m.kind === "update" && m.state) noteUpd(m.state); });
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
on("ready", () => checkServed(true));
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") checkServed(); });
const useServed = () => { const [, bump] = useState(0); useEffect(() => on("served", () => bump((x) => x + 1)), []); };

// stage U3: the copy follows the server by itself — a few seconds after the server hands out a newer one (a deploy
// writes its files one by one), and only when nothing would be lost: no words typed anywhere, no menu or picture
// open, no recording, no request on its way. Until then: Settings → "Refresh the app"
function idleHere() {
  if (layers.length > 0 || holds > 0 || conn.wait.size) return false;
  // a session read away from its end: a reload would open it at the end and lose the place — on Home, or at the end
  if (/^#\/s\//.test(location.hash) && window.innerHeight + window.scrollY < document.body.scrollHeight - 200) return false;
  if (mic && mic.getTracks().some((tr) => tr.enabled && tr.readyState === "live")) return false;
  const a = document.activeElement;
  if (a && /^(TEXTAREA|INPUT|SELECT)$/.test(a.tagName)) return false;
  // a field that shows what is saved — Settings' list of a vendor's models, the voice's own words — isn't words typed
  // (with one of them on the screen the copy never followed the server, 2026-10-30): data-saved holds that value
  return ![...document.querySelectorAll("textarea, input")].some((el) => !/^(checkbox|radio|file|button|submit)$/.test(el.type) && el.value.trim()
    && !(el.dataset && el.dataset.saved !== undefined && el.value === el.dataset.saved));
}
let follow = 0;
function followServer() {
  clearTimeout(follow);
  if (!phoneOld()) return;
  follow = setTimeout(async () => {
    const v = served.v;
    await checkServed(true);
    if (!phoneOld()) return;
    if (served.v !== v) { followServer(); return; }        // still changing: a deploy in progress
    const now = () => { if (!phoneOld()) return; if (idleHere()) location.reload(); else follow = setTimeout(now, 5000); };
    now();
  }, 8000);
}
on("served", followServer);

export { OWN_V, UPD_RUN_MAX, checkServed, followServer, idleHere, noteUpd, phoneOld, served, useServed };
