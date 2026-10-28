// Pult app — where you are: routes, our own history, layers over the screen, Back; links out and to files.
// Moved from app.js as it was (review 2026-10-27, 6.4).
import { t } from "../i18n.js";
import { useEffect, useRef, useState } from "../vendor/htm-preact-3.1.1.js";
import { emit } from "./conn.js";
import { tg } from "./tg.js";

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
// what the page's own reload must not cut (the copy following the server, stage U3): a recording from the tap on (the
// microphone's question included), a countdown to send a ready reply, answers ticked by hand — counted here (0.18.6;
// before, the page could reload under Telegram's microphone question or a ticked question — review 2026-10-27)
let holds = 0;
const holdBy = (n) => { holds += n; };      // a module's `let` is read-only to the others: they count through here
function useHold(on) {
  useEffect(() => { if (!on) return undefined; holds++; return () => { holds--; }; }, [on]);
}
// words that would be lost with the screen they belonged to — dictated after the screen was left — kept for this
// window's life by their place, and given back when it opens again
const drafts = {
  take(k) { try { const v = sessionStorage.getItem("pult.draft." + k) || ""; sessionStorage.removeItem("pult.draft." + k); return v; } catch (e) { return ""; } },
  put(k, v) { try { const old = sessionStorage.getItem("pult.draft." + k); sessionStorage.setItem("pult.draft." + k, old ? old + " " + v : v); } catch (e) { /* lost */ } },
};
// the overlays open now, the newest last — a picture full screen, the model menu, a file: each a step in the history,
// so Back closes the top one, not the screen. Each used to listen for Back itself: one Back closed a file and the sheet
// under it, and the sheet's step stayed — the next Back did nothing (review 2026-10-27, П8)
const layers = [];
addEventListener("popstate", () => { const top = layers.pop(); if (top) top(); });
const openLayer = (close) => { layers.push(close); history.pushState({ overlay: true }, ""); };
// on Home Telegram's Back is hidden, and the phone's own Back then closes the whole app: shown while a layer is open
function useBackFor(open) {
  useEffect(() => {
    if (!open || !tg || !tg.BackButton) return undefined;
    tg.BackButton.show();
    return () => { if (parse().name === "home" && !layers.length) tg.BackButton.hide(); };
  }, [open]);
}
function back() {
  if (layers.length > 0 || stack.length > 1) history.back(); else { history.replaceState(null, "", "#/"); stack[0] = "#/"; dispatchEvent(new HashChangeEvent("hashchange")); }
}
// an overlay's open/close go through the history: the system back gesture, Telegram's Back, a tap outside — all the
// same. Two quick taps on ✕ go back once: the second went on to the screen before
function useOverlay(open, setOpen) {
  const me = useRef(null);
  useEffect(() => () => {                       // its screen went with it open: no longer a layer
    const i = layers.indexOf(me.current);
    if (i >= 0) layers.splice(i, 1);
  }, []);
  useBackFor(open);
  return [() => { if (!open && !me.current) { const close = () => { me.current = null; setOpen(false); }; me.current = close; openLayer(close); setOpen(true); } },
          () => { const c = me.current; if (open && c && !c.closing) { c.closing = true; history.back(); } }];
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
// the window closed to get the file picker back (ui/pics.js): the next start without a link of its own, within a
// quarter of an hour, comes back to that screen with the words typed there
const REOPEN_MS = 15 * 60000;
try {
  const re = JSON.parse(localStorage.getItem("pult.reopen") || "null");
  localStorage.removeItem("pult.reopen");
  if (re && !start && (!location.hash || tgHash(location.hash)) && Date.now() - re.at < REOPEN_MS && /^#\/[\w/?=&%.-]*$/.test(re.h || "")) {
    if (re.k && re.text) drafts.put(re.k, re.text);
    history.replaceState(null, "", re.h); stack[0] = re.h;
    setTimeout(() => emit("toast", t("pick.again")), 1000);      // the toast listens once the app is on the screen
  }
} catch (e) { /* no storage: the start screen as always */ }

export { back, drafts, go, holdBy, holds, layers, openLayer, parse, stack, useBackFor, useHold, useOverlay, useRoute };
