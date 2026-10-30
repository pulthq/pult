// Pult app — small parts every screen uses: times and sizes, icons, project colours, chips, sheets, pickers.
// Moved from app.js as it was (review 2026-10-27, 6.4).
import { api, emit, useConn } from "../core/conn.js";
import { alertBox, haptic, tg, tick } from "../core/tg.js";
import { locale, t } from "../i18n.js";
import { html, useEffect, useRef, useState } from "../vendor/htm-preact-3.1.1.js";



// ---------- small helpers ----------

// a tappable thing that can't be a button — a row holding another tappable inside it, a heading that folds a list:
// reached and pressed from a keyboard too, as in Telegram Desktop (review 2026-10-27, П8)
const keyTap = (fn) => (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(e); } };

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
  return html`<span class=${"chip timer " + cls + (onClick ? " tap" : "")} role=${onClick ? "button" : undefined} tabindex=${onClick ? 0 : undefined}
    onClick=${onClick} onKeyDown=${onClick ? keyTap(onClick) : undefined}><span>${text}</span>${widest.map((w) => html`<span class="ghost" aria-hidden="true">${w}</span>`)}</span>`;
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
  const [name, ...ver] = m.replace(/^claude-/, "").replace(/-\d{8}$/, "").split("-");     // a transcript may say the date too
  return name.charAt(0).toUpperCase() + name.slice(1) + (ver.length ? " " + ver.join(".") : "");
};
// which model does a session's work, in a word or two (the owner, 2026-10-30): Claude's by its name — "Opus 5.5";
// another vendor's by the vendor, then its model without the vendor's name again — "DeepSeek · v4-pro". "[1m]" goes:
// the window is the context gauge's to say
const llmName = (l) => {
  if (!l || !l.model) return "";
  const m = String(l.model).replace(/\[1m\]$/i, "");
  if (!l.vendor) return modelName(m);
  const own = m.toLowerCase().startsWith(l.vendor.toLowerCase() + "-") ? m.slice(l.vendor.length + 1) : m;
  return l.vendor + " · " + own;
};
// a block of code — in Claude's words, a plan, a markdown file, the command a permission asks about — is copied whole
// by a tap: the commands Claude gives to run, with no selecting by hand on the phone (the owner, 2026-10-27). Text
// selected by hand in it is left alone; a swipe that scrolls it is no tap; without the clipboard API — the old way
const COPY_BLOCKS = ".md pre, .perm-b pre";
async function copyText(s) {
  try { await navigator.clipboard.writeText(s); return; } catch (e) { /* some webviews have no clipboard API */ }
  const ta = document.createElement("textarea");
  ta.value = s;
  ta.setAttribute("readonly", "");
  ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  const ok = document.execCommand("copy");
  ta.remove();
  if (!ok) throw new Error("copy");
}
// a whole message copied as it reads (stage Zh, step 3): its HTML, which a paste into Telegram, notes or mail keeps the
// formatting from, and its plain text beside it for wherever formatting can't go → "copied"; "plain" — only the text
// went (a webview whose clipboard takes no HTML); a rejection — nothing did. The first try starts at once, inside the
// finger's gesture: only then may a page write to the clipboard
function copyRich(html, text) {
  let first;
  try {
    first = navigator.clipboard.write([new ClipboardItem({ "text/html": new Blob([html], { type: "text/html" }),
                                                           "text/plain": new Blob([text], { type: "text/plain" }) })]);
  } catch (e) { first = Promise.reject(e); }        // no clipboard API, or no ClipboardItem in it
  return first.then(() => "copied", () => (copyBoth(html, text) ? "copied" : copyText(text).then(() => "plain")));
}
// the old way to both kinds: the copy command, its event filled by hand — the command runs only with something
// selected, so a hidden field holds the text, as in copyText
function copyBoth(html, text) {
  let filled = false;
  const fill = (e) => { e.clipboardData.setData("text/html", html); e.clipboardData.setData("text/plain", text); e.preventDefault(); filled = true; };
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  document.addEventListener("copy", fill, true);
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { /* no copy command either */ }
  document.removeEventListener("copy", fill, true);
  ta.remove();
  return ok && filled;
}
document.addEventListener("click", (ev) => {
  const pre = ev.target && ev.target.closest ? ev.target.closest(COPY_BLOCKS) : null;
  const sel = window.getSelection ? window.getSelection() : null;
  if (!pre || (sel && !sel.isCollapsed && pre.contains(sel.anchorNode))) return;
  copyText(pre.textContent.replace(/\n+$/, "")).then(() => {
    haptic("success");
    emit("toast", t("copied"));
    pre.classList.add("copied");
    setTimeout(() => pre.classList.remove("copied"), 1500);
  }, () => emit("toast", t("copy.fail")));
});
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

// the model of a session from Telegram: aliases Claude Code accepts, plus whatever the settings say
const MODELS = [["", ""], ["fable", "Fable"], ["opus", "Opus"], ["sonnet", "Sonnet"], ["haiku", "Haiku"]];
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
function ModelPick({ sid, choice, now, driven, tab, dflt, canModel, canEffort, vendor, onDone, onClose }) {
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
  // another vendor's session (stage M, step 2): only its own models, the main one when nothing is picked; no effort
  if (vendor) return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick"><div class="q-t pick-h">${t("vend.model.pick", { name: vendor.name })}<button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></div>
    <div class="pick-col">${vendor.models.map((m) => html`<button key=${m} class=${"opt" + (m === (cur.model || vendor.models[0]) ? " on" : "")} disabled=${busy} onClick=${() => pick({ model: m })}>${m}</button>`)}</div>
    <div class="dim small">${t("model.vendor", { name: vendor.name })}</div></div>`;
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
  pin: '<path d="M8.5 2.5h7"/><path d="M9.5 2.5v6.3L6.5 12v2h11v-2l-3-3.2V2.5"/><path d="M12 14v7.5"/>',
  pinoff: '<path d="M8.5 2.5h7"/><path d="M9.5 2.5v6.3L6.5 12v2h11v-2l-3-3.2V2.5"/><path d="M12 14v7.5"/><path d="m4 4 16 16"/>',
  eye: '<path d="M2.5 12c1.2-2.6 5-7 9.5-7s8.3 4.4 9.5 7c-1.2 2.6-5 7-9.5 7s-8.3-4.4-9.5-7z"/><circle cx="12" cy="12" r="3"/>',
  eyeoff: '<path d="m3 3 18 18"/><path d="M10.6 10.6a2 2 0 0 0 2.8 2.8"/><path d="M9.9 5.2A9.6 9.6 0 0 1 12 5c4.5 0 8.3 4.4 9.5 7-.4.9-1.2 2.1-2.4 3.3"/><path d="M6.7 6.7C4.5 8.3 3.1 10.5 2.5 12c1.2 2.6 5 7 9.5 7 1.4 0 2.7-.4 3.9-1"/>',
};

// stage Zh: a row that slides left under the finger to show its actions — one to three buttons under it: pin, hide
// and a new task on a project's row, tags on a task's, "got it" on a card of "Your move". A vertical move stays a
// scroll (touch-action: pan-y); a short slide springs back, past a third of the buttons it stays open; a tap on a
// button does it, a tap anywhere else closes; the tap that ends a slide opens nothing. Only to the left, starting
// anywhere inside the row but a field: from the phone's left edge comes the system's own Back. One row open at a
// time, as chats in Telegram. How each slide ended goes to the computer's journal, silently: whether the gesture
// works inside Telegram's window at all is known from there, not from words on the screen (runbook, the lesson of Q97).
// A message in a session (step 3 — Claude's, and yours) is `quick`: one action, done right as the finger lets go past the
// mark — its copy — and the message springs back; it stays open on the action's round button only when that didn't work (a lift
// of the finger may not count as a tap for the clipboard in some webview — the button's tap does). Its sign comes out
// at the finger's height, past the mark it lights up with a tick. Only a finger slides a message: a mouse selects its
// words. A block of code or a table keeps its own drag, as a field does (they scroll in themselves), and a finger that
// rests half a second first is selecting words, not sliding — by the touches' own times (timeStamp): a page busy
// redrawing gets to a touch late, and by the clock of its handling a quick slide looked like a rest (msgcopy_check)
let openRow = null;                                   // the row open now: a ref to its close
const QUICK = 72, PRESS = 450;                        // a message's mark, px; a long press, ms
function SwipeRow({ acts, what = "project", cls = "", quick = false, children }) {
  const w = quick ? QUICK : acts.length > 1 ? 80 : 92, full = w * acts.length;
  const [dx, setDx] = useState(0);
  const [drag, setDrag] = useState(false);
  const [armed, setArmed] = useState(false);        // quick: past the mark — letting go now does it
  const [at, setAt] = useState(0);                  // quick: the finger's height in the row, where the sign comes out
  const g = useRef(null);
  const swiped = useRef(false);
  const me = useRef(null);
  me.current = () => setDx(0);
  useEffect(() => () => { if (openRow === me) openRow = null; }, []);
  const shut = () => { me.current(); if (openRow === me) openRow = null; };
  const opened = () => { if (openRow && openRow !== me) openRow.current(); openRow = me; };
  const tell = (how, s) => api("swipe", { end: how, ms: Math.round(s.t1 - s.t0), dx: Math.round(-s.last), what }).catch(() => {});
  const down = (e) => {
    if ((e.pointerType === "mouse" && (quick || e.button !== 0)) || e.target.closest("input, textarea, pre, .tbl")) return;
    g.current = { x: e.clientX, y: e.clientY, x0: dx, last: dx, on: false, armed: false, t0: e.timeStamp };
  };
  const move = (e) => {
    const s = g.current;
    if (!s) return;
    const mx = e.clientX - s.x, my = e.clientY - s.y;
    if (!s.on) {
      if (quick && e.timeStamp - s.t0 > PRESS) { g.current = null; return; }
      if (Math.abs(mx) < 8 || Math.abs(mx) < Math.abs(my) * 1.5) return;
      s.on = true;
      setDrag(true);
      if (quick) setAt(Math.round(s.y - e.currentTarget.getBoundingClientRect().top));
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch (x) { /* no capture: the moves still come while the finger is on the row */ }
    }
    const to = Math.min(0, s.x0 + mx);
    // past its mark a message follows the finger at a third of the pace: the sign has lit up, it may let go
    s.last = quick ? Math.max(-full - 40, to < -full ? -full + (to + full) / 3 : to) : Math.max(-full - 10, to);
    setDx(s.last);
    if (quick && (s.last <= -full) !== s.armed) {
      s.armed = s.last <= -full;
      setArmed(s.armed);
      if (s.armed) tick();
    }
  };
  const up = (e) => {
    const s = g.current;
    g.current = null;
    if (!s || !s.on) return;
    s.t1 = e.timeStamp;
    swiped.current = true;
    setTimeout(() => { swiped.current = false; }, 400);       // a tap right after the slide opens nothing; the next one is a tap again
    setDrag(false);
    const cancel = e.type === "pointercancel";
    if (quick) {
      setArmed(false);
      if (cancel || !s.armed) { shut(); return tell(cancel ? "cancel" : "back", s); }
      // now, while the lift still counts as the finger's gesture — the clipboard takes nothing later. The message
      // waits on its mark for the answer: a word for the journal — it springs back; nothing — its button stays out
      setDx(-full);
      Promise.resolve(acts[0].on("slide")).then((how) => {
        if (how) shut(); else opened();
        tell(how || "nocopy", s);
      });
      return;
    }
    const open = !cancel && s.last < -full / 3;
    setDx(open ? -full : 0);
    if (open) opened(); else if (openRow === me) openRow = null;
    tell(cancel ? "cancel" : open ? "open" : "back", s);
  };
  const click = (e) => {
    if (e.target.closest(".swr-act")) return;
    if (swiped.current || dx) { swiped.current = false; e.stopPropagation(); e.preventDefault(); shut(); }
  };
  // a message's sign: out as far as the message has slid, at the finger's height
  const style = quick ? "--p:" + Math.min(1, -dx / full).toFixed(2) + ";--at:" + at + "px" : undefined;
  return html`<div class=${"swr" + (drag ? " drag" : "") + (quick ? " quick" : "") + (armed ? " armed" : "") + (cls ? " " + cls : "")} style=${style}
    onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${up} onClickCapture=${click}>
    <div class="swr-acts" style=${quick ? undefined : "width:" + full + "px"}>${acts.map((a) => html`<button key=${a.label} class="swr-act"
      style=${quick ? undefined : "width:" + w + "px"} tabindex="-1" aria-label=${quick ? a.label : undefined}
      onClick=${(e) => { e.stopPropagation(); shut(); a.on(); }}>${ic(a.ic, 20)}${quick ? "" : html`<span>${a.label}</span>`}</button>`)}</div>
    <div class="swr-in" style=${"transform:translateX(" + dx + "px)"}>${children}</div></div>`;
}

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
// Claude sorting a project's tasks in batches (stage T, T2): its earlier ones, once, or all anew — what it does, how far
const tagJob = (j) => (j.list ? t("tags.job.list") : !j.total ? t("tags.job.start") : t("tags.job." + j.kind, { done: j.done, total: j.total }));
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

// "how it's counted": behind ⓘ, not on the screen all the time
function About({ text, label }) {
  const [open, setOpen] = useState(false);
  return html`<button class="about-b" aria-expanded=${open} onClick=${() => setOpen(!open)}>${ic("info", 15)} ${label || t("about.how")}</button>
    ${open && html`<div class="dim small about-t">${text}</div>`}`;
}

// nothing to show yet: loading — or, with the Mac away, why nothing comes (the data lives only on the Mac, nothing is kept
// in the phone), instead of "Loading…" for ever under the banner
function Loading({ err }) {
  const c = useConn();
  return html`<div class="empty">${err || (c.state === "nomac" ? t("loading.nomac") : c.state === "denied" ? "" : t("loading"))}</div>`;
}

export { About, ChoicePick, Dots, GEAR, GLYPH, Loading, MODES, ModePick, ModelPick, Sheet, SwipeRow, TimeChip, ago, agoShort, avatar, bgChip, bytes, choiceText, copyRich, dayLabel, dot, dotted, dur, durShort, effortName, hhmm, home, hue, ic, keyTap, kilo, level, llmName, modelName, nb, num, pct, plainField, queueChip, quiet, resetText, sendKey, TAG_H, tagChips, tagJob, tagSt, toDate, useNow, workChip };
