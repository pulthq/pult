// Pult app — a session: the chat, a turn's files, a project's file opened over the screen.
// Moved from app.js as it was (review 2026-10-27, 6.4).
import { api, conn, emit, on, pacer, useLive } from "../core/conn.js";
import { drafts, openLayer, useBackFor, useOverlay } from "../core/nav.js";
import { alertBox, confirmBox, haptic } from "../core/tg.js";
import { Mic, useRecorder } from "../core/voice.js";
import { locale, plural, t } from "../i18n.js";
import { clip, clipPlain, md } from "../md.js";
import { html, useEffect, useMemo, useRef, useState } from "../vendor/htm-preact-3.1.1.js";
import { Replies, ResumeAt, copyWhy, forkAsk } from "./home.js";
import { TagPick } from "../ui/cards.js";
import { Req, useRcpt } from "../ui/cards.js";
import { Dots, Loading, ModelPick, Sheet, SwipeRow, avatar, bgChip, copyRich, dayLabel, dot, dotted, dur, effortName, hhmm, home, ic, kilo, modelName, num, plainField, queueChip, sendKey, tagChips, toDate, useNow, workChip } from "../ui/kit.js";
import { BgSheet, bgLine } from "../ui/load.js";
import { Attach, Pic, Thumbs, Viewer, useAttach, useNoFold } from "../ui/pics.js";


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
  // a key of its own for each message — its kind, its time and its place among those alike — that earlier history
  // loading in above doesn't move: keyed by place in the list, every card was made anew (pictures asked for again,
  // "Show all" folded back; review 2026-10-27)
  const seen = new Map();
  const keyed = (i) => { const b = i.k + "@" + (i.ts || ""), c = seen.get(b) || 0; seen.set(b, c + 1); return Object.assign({}, i, { key: b + "#" + c }); };
  for (const i of items) {
    if (i.k === "result") continue;
    const d = i.ts ? toDate(i.ts).toDateString() : day;
    if (d && d !== day) { out.push({ k: "day", label: dayLabel(toDate(i.ts)), key: "d" + d }); day = d; }
    if (i.k === "tool" || i.k === "update") {
      const last = out[out.length - 1];
      if (last && last.k === "steps") last.steps.push(i);
      else if (i.k === "tool") out.push({ k: "steps", steps: [i], key: "g" + i.id, ts: i.ts });
      else out.push(keyed(i));                // Claude's line before any step: on its own
    } else out.push(keyed(i));
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

// a message slides to the left to copy it whole (stage Zh, step 3): Claude's as it reads — for a paste that keeps
// formatting (Telegram, notes, mail) — and as the markdown it wrote (the owner, 2026-10-29); yours as you wrote it, line
// breaks and all (2026-10-30). `rich` makes its HTML from the words. The slide's own try stays quiet when it fails: its
// button stays out, and a tap on it is the sure way; a message just copied is outlined for a moment
function CopyRow({ words, rich, what, children }) {
  const [lit, setLit] = useState(false);
  if (!words) return children;
  const copy = (via) => copyRich(rich(words), words).then((how) => {
    haptic("success");
    emit("toast", t("copied"));
    setLit(true);
    setTimeout(() => setLit(false), 1200);
    return how;
  }, () => { emit("toast", t(via === "slide" ? "msg.copy.tap" : "copy.fail")); return ""; });
  return html`<${SwipeRow} quick what=${what} cls=${lit ? "lit" : ""} acts=${[{ ic: "copy", label: t("msg.copy"), on: copy }]}>${children}</${SwipeRow}>`;
}

// one of Claude's messages; a long one that is not the last is folded to a few lines — "Show all" opens it; a slide
// copies it, folded or not
const LONG = 900;
function TextMsg({ i, fold }) {
  const [open, setOpen] = useState(false);
  const folded = fold && !open;
  const h = useMemo(() => md(i.text), [i.text]);     // the screen redraws every second: the words only when they change
  return html`<${CopyRow} words=${(i.text || "").trim()} rich=${clip} what="msg"><div class="msg"><div class=${"md" + (folded ? " fold" : "")} dangerouslySetInnerHTML=${{ __html: h }}/>
    ${fold ? html`<button class="link more2" onClick=${() => setOpen(!open)}>${t(open ? "msg.less" : "msg.more")}</button>` : ""}
    ${i.att && i.att.length ? html`<div class="atts shown">${i.att.map((a, k) => html`<${Pic} key=${k} a=${a} all=${i.att}/>`)}</div>` : ""}<${At} ts=${i.ts}/></div></${CopyRow}>`;
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
  useEffect(() => on("file", (x) => { openLayer(() => setTrail((tr) => tr.slice(0, -1))); setTrail((tr) => tr.concat([x])); }), []);
  const open = trail.length > 0;
  useNoFold(open);
  useBackFor(open);                     // a link in a plan on Home: Telegram's Back closes the file, not the app
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
  // the room under the last message for the composer over it: its height and a margin
  const room = () => {
    const el = comp.current, main = document.querySelector("main");
    if (!el || !main) return;
    main.style.paddingBottom = (el.offsetHeight + 12) + "px";
    document.documentElement.style.setProperty("--composer-h", el.offsetHeight + "px");
  };
  // the very bottom of the page, past the padding that keeps the last message above the composer (the end marker
  // sits before that padding, so scrollIntoView stopped short) — that room made first: set a frame later by its
  // observer, it came after the scroll now and then, and the chat opened a little above its end (ticks_check, 2026-10-28)
  const toBottom = () => { room(); window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "instant" }); };
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
    setTimeout(() => { const el = ta.current; if (el) { el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 160) + "px"; } }, 0); }, "s:" + sid);
  useEffect(() => { const d = drafts.take("s:" + sid); if (d) setText((c) => (c ? c + " " : "") + d); }, [sid]);
  const taRef = useMemo(() => (el) => { ta.current = el; plainField(el); }, []);   // one function: Preact sets the ref once
  useEffect(() => {
    const el = comp.current, main = document.querySelector("main");
    if (!el || !main || !window.ResizeObserver) return;
    const ro = new ResizeObserver(room);
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
    if (conn.ready) load("full");
    // a reconnect (Telegram in the background for a minute) brings only what is new: a full load dropped the earlier
    // history read so far, under the finger; "after" falls back to a full load itself when it has to
    const kick = pacer(() => load("after"));
    const offs = [on("ready", kick), on("event", (m) => { if (!m.sid || m.sid === sid) kick(); })];
    return () => { offs.forEach((f) => f()); kick.stop(); };
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
        if (await confirmBox(forkAsk(r))) return sendText(true);
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
  const used = info.ctx && info.stats ? Math.min(100, Math.round(info.stats.context * 100 / info.ctx.usable)) : null;   // not pct(): that is the helper
  // the status under the message field: where the text goes (a tab, a copy), the model, the context gauge
  const dest = lv.tab ? html`${ic("monitor", 13)} ${t("dest.tab")}` : lv.open ? html`${ic("copy", 13)} ${t("dest.copy")}` : "";
  const ctxText = info.stats && info.stats.model ? (used !== null ? t("ctx.pct", { pct: used, win: kilo(info.ctx.window) }) : t("context", { n: kilo(info.stats.context) })) : "";
  // two steady lines: the model with its effort (a tap picks them) · where the text goes and the context gauge
  // the model: the one picked for the session, else the one its last request used; the effort — the same way
  const chosen = info.choice && info.choice.model;
  const modelText = chosen ? chosen.charAt(0).toUpperCase() + chosen.slice(1) + (info.stats && info.stats.model && !modelName(info.stats.model).toLowerCase().startsWith(chosen) ? " ▸" : "")
    : info.stats && info.stats.model ? modelName(info.stats.model) : "";
  const effortNow = (info.choice && info.choice.effort) || (info.stats && info.stats.effort) || "";
  const canPick = info.switch || info.switch_effort;
  // a tap on the status explains it in plain words, in a sheet of our own
  const explain = () => { setNote([lv.tab ? t("ex.tab") : lv.open ? (copyWhy(lv) ? copyWhy(lv) + " " + t("ex.copy.then") : t("ex.copy")) : t("ex.session"),
    info.stats && info.stats.model ? t("ex.model", { m: modelName(info.stats.model) }) + (info.switch ? "" : " " + (lv.tab ? t("model.reload") : t("model.fixed"))) : "",
    effortNow ? t("ex.effort", { e: effortName(effortNow).toLowerCase() }) + (lv.tab && info.switch && !info.switch_effort ? " " + t("effort.reload") : "") : "",
    info.stats && info.stats.model ? t("ex.ctx", { n: kilo(info.stats.context), win: used !== null ? t("ex.ctx.win", { w: kilo(info.ctx.window), pct: used }) : "" }) : "",
    // the last turn's figures — once in the session's header, now here: the header keeps the title and the state
    ts ? t("turn.stats", { n: ts.req, requests: plural(ts.req, "request"), out: kilo(ts.out) }) + (ts.think ? t("turn.think", { n: kilo(ts.think) }) : "") : ""
  ].filter(Boolean)); openNote(); };
  const line1 = (modelText || canPick) && html`<button class=${"mchip" + (canPick ? " on" : "")} onClick=${canPick ? () => (pick ? closePick() : openPick()) : explain}>
    <span>${modelText || t("model")}</span>${effortNow && html`<${Dots} e=${effortNow}/>`}${canPick ? html`<span class="caret">${ic("down", 13)}</span>` : ""}</button>`;
  const line2 = (dest || ctxText) && html`<button class="where" onClick=${explain}>${dest}${dest && ctxText ? " · " : ""}<span class=${used >= 90 ? "bad" : used >= 70 ? "warn" : ""}>${ctxText}</span></button>`;
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
      : i.k === "user" ? html`<${CopyRow} key=${i.key} words=${(i.text || "").trim()} rich=${clipPlain} what="mine"><div class="msg me" data-n=${n}>${i.voice ? html`<span class="mic-i">${ic("mic", 14)}</span>` : ""}${i.text}${i.att && i.att.length ? html`<div class="atts">${i.att.map((a, k) => html`<${Pic} key=${k} a=${a} all=${i.att}/>`)}</div>` : ""}<${At} ts=${i.ts} mid=${i.mid} st="read"/></div></${CopyRow}>`
      : i.k === "note" ? html`<div class="note" key=${i.key}>${i.text}${i.ts ? " · " + hhmm(toDate(i.ts)) : ""}</div>`
      : i.k === "update" ? html`<div class="upd solo" key=${i.key}>${i.text}</div>`
      : html`<${TextMsg} key=${i.key} i=${i} fold=${i.text.length > LONG && all.slice(n + 1).some((x) => x.k === "text")}/>`)}
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
      <div class="ctl"><${Attach} a=${a} disabled=${busy} keep=${{ k: "s:" + sid, text }}/>${info.stt ? html`<${Mic} v=${v} disabled=${busy}/>` : ""}
        <div class="status">${line1}${line2}</div>
        ${lv.driven && (lv.state === "work" || lv.state === "queue") ? html`<button class="btn danger" onClick=${stop}>${t("stop")}</button>` : ""}
        <button class="btn send" aria-label=${t("send")} disabled=${busy || (!text.trim() && !a.files.length)} onClick=${() => sendText(false)}><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="M5 12l7-7 7 7"/></svg></button></div>
    </div>
  </div>`;
}

export { FileHost, Session, TurnFilesScreen };
