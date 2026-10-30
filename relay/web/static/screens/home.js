// Pult app — Home: whose move, what runs, the projects; the rows Home and a project share.
// Moved from app.js as it was (review 2026-10-27, 6.4).
import { api, useLang, useLive } from "../core/conn.js";
import { drafts, go, useHold, useOverlay } from "../core/nav.js";
import { alertBox, confirmBox, haptic } from "../core/tg.js";
import { Mic, useRecorder } from "../core/voice.js";
import { plural, t } from "../i18n.js";
import { html, useEffect, useRef, useState } from "../vendor/htm-preact-3.1.1.js";
import { Req, TagPick, useRcpt } from "../ui/cards.js";
import { GEAR, GLYPH, Loading, MODES, ModePick, SwipeRow, TimeChip, ago, agoShort, avatar, bgChip, dot, dur, durShort, hhmm, ic, keyTap, llmName, nb, pct, plainField, queueChip, quiet, tagChips, toDate, useNow, workChip } from "../ui/kit.js";
import { BgSheet, bgLine, memPct } from "../ui/load.js";
import { UpdRow } from "../ui/upd.js";

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

// why a session open on the computer takes no message from here — a Claude Code Pult isn't checked on, a tab started
// before the wrapper, a terminal (the computer tells from 0.17.4; a friend got only "open in a tab", 2026-10-26)
const copyWhy = (x) => { const k = "fork.why." + (x && x.why); const s = t(k, { v: x && x.v, step: x && x.step }); return s === k ? "" : s; };
const forkAsk = (r) => (copyWhy(r) ? copyWhy(r) + "\n\n" + t("fork.copy") : t("fork.ask"));

// a message from a card or a ready reply into the session: the same ways as the session's own field — straight in,
// into the tab, or a copy when it is open on the computer without Pult (asked first)
async function sendTo(sid, text) {
  let r = await api("send", { sid, text });
  if (r.need === "fork") {
    if (!(await confirmBox(forkAsk(r)))) return false;
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
  const pend = useRef(null);                      // the reply counting down: it goes even if the screen goes first
  useHold(!!wait);
  useEffect(() => () => {
    clearInterval(timer.current);
    const text = pend.current;
    pend.current = null;
    if (text) sendTo(sid, text).catch((err) => alertBox(err.message));   // the owner saw "sending" and left: it goes
  }, []);
  if (!replies || !replies.length) return "";
  const pick = (text, e) => {
    e && e.stopPropagation();
    clearInterval(timer.current);
    pend.current = text;
    setWait({ text, left: UNDO });
    timer.current = setInterval(() => setWait((w) => {
      if (!w) return w;
      if (w.left > 1) return Object.assign({}, w, { left: w.left - 1 });
      clearInterval(timer.current);
      pend.current = null;
      sendTo(sid, w.text).then((ok) => ok && onSent && onSent(w.text)).catch((err) => alertBox(err.message));
      return null;
    }), 1000);
  };
  const undo = (e) => { e.stopPropagation(); clearInterval(timer.current); pend.current = null; setWait(null); };
  return wait ? html`<div class="qr wait"><span>${t("reply.will", { text: wait.text })} · ${wait.left}</span><button class="link" onClick=${undo}>${t("undo")}</button></div>`
    : html`<div class="qr">${replies.map((x) => html`<button key=${x} onClick=${(e) => pick(x, e)}>${x}</button>`)}</div>`;
}

// your own words right in the card: a line and the microphone, Enter or the arrow sends
function QuickReply({ sid, stt, onSent }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const v = useRecorder((w) => setText((c) => (c ? c.replace(/\s+$/, "") + " " : "") + w), "q:" + sid);
  useEffect(() => { const d = drafts.take("q:" + sid); if (d) setText((c) => (c ? c + " " : "") + d); }, [sid]);
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

// "Your move": a session that ended and waits for you — its project and tags, how long, what came out, what is
// needed; ready replies, your own words, "Got it" to put it to rest; the title opens the session. The tags stay on
// the top line, as in "Running now": in front of the line they ate it (2026-10-26). Which model did the work — at
// the foot, across from "Got it" (Q108): on the top line, beside how long it waits, it pushed the tags out
function Mine({ r, now, onGot, stt, showProject = true }) {
  const [busy, setBusy] = useState(false);
  const [resume, setResume] = useState(r.resume);
  const llm = llmName(r.llm);                // a computer before 0.18.31 doesn't say: no mark
  const got = async (e) => {
    e && e.stopPropagation();
    setBusy(true);
    try { await api("seen", { sid: r.sid }); haptic("success"); onGot && onGot(r.sid); } catch (err) { alertBox(err.message); }
    setBusy(false);
  };
  const open = () => go("#/s/" + r.sid);
  const sent = () => onGot && onGot(r.sid);
  // open on the computer without Pult's wrapper: an answer from here goes as a copy — said before it is typed, as
  // under the session's own field (a friend learned it only after writing a whole answer, 2026-10-26)
  const copy = r.open && !r.tab && !r.driven;
  const aboutCopy = (e) => { e.stopPropagation(); alertBox(t("ex.copy")); };
  return html`<${SwipeRow} what="card" cls="card-sw" acts=${[{ ic: "check", label: t("mine.got"), on: got }]}><div class=${"card mine" + (r.state === "fail" ? " fail" : "")}>
    <div class="card-h tap" role="button" tabindex="0" onClick=${open} onKeyDown=${keyTap(open)}><div class="c-proj"><span class="run-w">${showProject && r.project ? html`<span class="run-who">${avatar(r.project, 18)}<span class="run-p">${r.project}</span></span>` : ""}${tagChips(r.tags)}</span><span class="c-wait">${t("mine.waits", { dur: nb(dur(now - r.since)) })}</span></div>
      <b class="c-title">${r.state === "fail" ? ic("alert", 16) : ""}${r.title}<span class="c-go">${ic("chev", 16)}</span></b></div>
    ${r.need ? html`<div class="ln dim tap" onClick=${open}>${r.line}</div><div class="now tap" onClick=${open}>${r.need}</div>` : html`<div class="now tap" onClick=${open}>${r.line}</div>`}
    ${r.fail === "rate_limit" ? html`<${ResumeAt} sid=${r.sid} resume=${resume} reset=${r.reset} onSet=${setResume}/>` : html`<${Replies} sid=${r.sid} replies=${r.replies} onSent=${sent}/>`}
    <${QuickReply} sid=${r.sid} stt=${stt} onSent=${sent}/>
    <div class="foot quiet"><span class="foot-l">${llm && html`<span class="llm">${llm}</span>`}${copy && html`<button class="link copy" onClick=${aboutCopy}>${ic("copy", 15)} ${t("dest.copy")}</button>`}</span><button class="link" disabled=${busy} onClick=${got}>${ic("check", 15)} ${t("mine.got")}</button></div>
  </div></${SwipeRow}>`;
}

// "While you were away": what happened since you last had the app open (an hour or more ago) — turns, what is done,
// what waits; a line per project. Gone with the next long break, or with ×
function Catchup({ c, onClose }) {
  return html`<div class="card catch"><div class="item-h"><b>${t("catch.title")}</b><span class="dim nowrap">${t("catch.since", { hm: agoShort(c.from) })}
    <button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></span></div>
    <div class="dim cnts">${[t("catch.turns", { n: c.turns, turns: plural(c.turns, "turn"), p: c.projects }), c.done ? html`<span class="cnt ok">${ic("check", 14)}${c.done}</span>` : "", c.mine ? html`<span class="cnt">${dot("attn")}${c.mine}</span>` : ""].filter(Boolean).map((m, i) => html`${i ? html`<span class="sep">·</span>` : ""}${m}`)}</div>
    ${c.lines.map((x) => html`<div class="ln tap" key=${x.pkey} onClick=${() => go("#/p/" + encodeURIComponent(x.pkey))}>${x.you ? dot("attn") : x.fail ? ic("alert", 14) : ic("check", 14)} <b>${x.name}</b> — ${x.line}</div>`)}</div>`;
}

// a session's mark in front of its title: the beating dot while it works, its background task, the queue, a fresh report
const rowIcon = (r) => (r.state === "work" ? html`<span class="st st-work"></span>` : r.state === "bg" ? html`<span class="st-ic">${ic("bg", 15)}</span>`
  : r.state === "queue" ? html`<span class="st-ic">${ic("clock", 15)}</span>`
  : r.state === "done" ? html`<span class="st-ic ok">${ic("check", 15)}</span>` : r.driven ? html`<span class="st-ic">${ic("phone", 15)}</span>` : "");
const ctxWarn = (r) => (r.ctx != null && r.ctx >= 90 ? html`<span class="pct bad">${ic("alert", 13)} ${r.ctx} %</span>` : "");

// a row slides to a task's tags when the screen gives it onTags (stage Zh, step 2 — Q102): the sheet of the session's screen
const tagsAct = (r, onTags) => [{ ic: "tag", label: t("row.tags"), on: () => onTags(r.sid) }];

// one session on the board: what it does now or how its last turn ended, in a line or two; which model did it — at
// the right end of the second line, as a chat list's badge (Q109): the title, cut already, keeps its room
function BoardRow({ r, now, onBg, onTags }) {
  const bgTap = (e) => { e.stopPropagation(); onBg(r); };
  const llm = llmName(r.llm);
  const right = r.state === "work" ? workChip(r.since, now)
    : r.state === "queue" ? queueChip(r.since, now)
    : r.state === "bg" ? bgChip(r.since, now, bgTap)
    : html`<span class="dim nowrap">${agoShort(r.ts)}</span>`;
  const open = () => go("#/s/" + r.sid);
  // a row, not a <button>: its background task is a tap of its own, and a button can't hold one
  const body = html`<div role="button" tabindex="0" class=${"item brow" + (r.state === "idle" ? " rest" : "") + (r.state === "done" ? " fresh" : "")} onClick=${open} onKeyDown=${keyTap(open)}>
    <div class="item-h"><b class="one">${rowIcon(r)}${r.title}</b><span class="meta">${ctxWarn(r)}${right}</span></div>
    ${(r.line || (r.tags && r.tags.length > 0) || llm) && html`<div class="ln-row"><div class="ln">${tagChips(r.tags)}${r.line}</div>${llm && html`<span class="llm">${llm}</span>`}</div>`}
    ${r.bg && r.bg.length > 0 && html`<div class="bg tap" role="button" tabindex="0" onClick=${bgTap} onKeyDown=${keyTap(bgTap)}>${bgLine(r.bg)} ${ic("chev", 14)}</div>`}
  </div>`;
  return onTags ? html`<${SwipeRow} what="task" acts=${tagsAct(r, onTags)}>${body}</${SwipeRow}>` : body;
}

// the request and the title say the same in a task's first turn (the title is its first request, cut)
const sameStart = (a, b) => { const x = String(a || "").replace(/…$/, ""), y = String(b || "").replace(/…$/, ""); return !!x && !!y && (x.startsWith(y) || y.startsWith(x)); };

// one session in "Running now" (Home; a project's screen — without the project): where on top — the project and the
// task's tags, a tag that doesn't fit left out whole; the title whole, two lines at most, with its time beside it;
// then what you asked in this turn and what Claude says so far — or, while its background task runs, how the turn
// ended. The owner, 2026-10-26: a title cut after three words over a line of tags cut the same way said nothing.
// At the top line's right end — which model does the task (2026-10-30); the project and the tags give way to it
function RunRow({ r, now, onBg, onTags, showProject = true }) {
  const bgTap = (e) => { e.stopPropagation(); onBg(r); };
  const chip = r.state === "work" ? workChip(r.since, now) : r.state === "queue" ? queueChip(r.since, now) : bgChip(r.since, now, bgTap);
  // a computer before 0.17.3 gives a turn one line: Claude's words, else the request when it was typed there
  const said = r.state === "queue" ? "" : r.state === "work" && "now" in r ? r.now || (!r.ask && r.note) : r.line;
  const asked = r.state === "queue" ? r.line : r.state === "work" ? r.ask : "";
  const ask = asked && !sameStart(asked, r.title) ? asked : "";
  const where = (showProject && r.project) || (r.tags && r.tags.length > 0);
  const llm = llmName(r.llm);                // a computer before 0.18.30 doesn't say: no mark
  const open = () => go("#/s/" + r.sid);
  const body = html`<div role="button" tabindex="0" class="item run" onClick=${open} onKeyDown=${keyTap(open)}>
    ${where || llm ? html`<div class="run-top">${where ? html`<div class="run-w">${showProject && r.project ? html`<span class="run-who">${avatar(r.project, 16)}<span class="run-p">${r.project}</span></span>` : ""}${tagChips(r.tags)}</div>` : ""}${llm && html`<span class="llm">${llm}</span>`}</div>` : ""}
    <div class="run-h"><div class="run-t">${rowIcon(r)}${r.title}</div><span class="meta">${ctxWarn(r)}${chip}</span></div>
    ${ask && html`<div class=${"run-ask" + (said ? "" : " solo")}>${t("run.you", { text: ask })}</div>`}
    ${said && html`<div class="run-now">${said}</div>`}
    ${r.state === "bg" && r.bg && r.bg.length > 0 && html`<div class="bg tap" role="button" tabindex="0" onClick=${bgTap} onKeyDown=${keyTap(bgTap)}>${bgLine(r.bg)} ${ic("chev", 14)}</div>`}
  </div>`;
  return onTags ? html`<${SwipeRow} what="task" acts=${tagsAct(r, onTags)}>${body}</${SwipeRow}>` : body;
}

// a project on the board: who works and who waits for you, today's turns; its live sessions; the resting folded;
// the pinned (stage Zh) carry their mark and come first — the computer orders them
function ProjectBlock({ p, now, onBg, onTags }) {
  const open = () => go("#/p/" + encodeURIComponent(p.pkey));
  const meta = [p.work ? html`<span class="cnt">${dot("work")}${p.work}</span>` : "", p.mine ? html`<span class="cnt">${dot("attn")}${p.mine}</span>` : "",
    p.turns ? t("proj.turns", { n: p.turns, turns: plural(p.turns, "turn") }) : "",
    !p.rows.length && p.resting ? t("proj.resting", { n: p.resting }) : ""].filter(Boolean);
  return html`<div class="list proj">
    <button class="item proj-h" onClick=${open}><span class="pname">${avatar(p.name, 34)}<span class="pn"><b>${p.name}</b><span class="dim pmeta">${meta.length ? meta.map((m, i) => html`${i ? html`<span class="sep">·</span>` : ""}${m}`) : t("proj.quiet")}</span></span><span class="ptail">${p.pinned ? ic("pin", 15) : ""}${ic("chev", 16)}</span></span></button>
    ${p.rows.map((r) => html`<${BoardRow} key=${r.sid} r=${r} now=${now} onBg=${onBg} onTags=${onTags}/>`)}
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
  const [tagFor, setTagFor] = useState(null);           // a task's tags from its row's slide (stage Zh, step 2): {sid, info}
  const [openTag, closeTag] = useOverlay(!!tagFor, (v) => { if (!v) setTagFor(null); });
  const seenN = useRef(-1);
  const yours = useRcpt(d ? moves(d.pending, d.mine || []) : [], moveKey);
  if (!d) return html`<${Loading} err=${err}/>`;
  if (seenN.current < 0) seenN.current = (d.pending || []).length + (d.mine || []).length;     // no buzz on opening
  useLang(d.lang);
  const onBg = (s) => { setBgFor(s.sid); openBg(); };
  const onTags = (sid) => api("taginfo", { sid }).then((info) => { setTagFor({ sid, info }); openTag(); }).catch((e) => alertBox(e.message));
  const reload = () => api("overview").then(set).catch(() => {});
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
  const rest = board.filter((p) => !p.hidden).map((p) => Object.assign({}, p, { rows: p.rows.filter((r) => !runs(r)) }));   // a hidden project's block stays off the board (Q101)
  return html`<div>
    <${Top} mac=${d.mac} load=${d.load} usagePct=${d.usage_pct} usageTop=${d.usage_top} pager=${d.pager} onSet=${(m) => set(Object.assign({}, d, { mac: Object.assign({}, d.mac, { mode: m }) }))}/>
    <${UpdRow} u=${d.update}/>
    ${nRun > 0 && html`<h3>${t("home.running", { n: nRun - nQueue })}${nQueue ? " · " + t("home.queued", { n: nQueue }) : ""}</h3><div class="list">
      ${running.map((r) => html`<${RunRow} key=${r.sid} r=${r} now=${now} onBg=${onBg} onTags=${onTags}/>`)}
      ${jobsOn.map((j) => html`<${Job} key=${j.id} j=${j} now=${now} row=${true}/>`)}</div>`}
    ${d.catchup && html`<${Catchup} c=${d.catchup} onClose=${() => { api("catchup_off").catch(() => {}); set(Object.assign({}, d, { catchup: null })); }}/>`}
    ${(n > 0 || yours.length > 0) && html`<h3>${t("home.mine", { n })}</h3>
      ${yours.map((e) => e.req ? html`<${Req} key=${e.key} r=${e.req}/>`
        : html`<${Mine} key=${e.key} r=${Object.assign({ reset: d.reset }, e.mine)} now=${now} onGot=${gone} stt=${d.stt}/>`)}`}
    ${rest.length > 0 && html`<h3>${t("home.projects")}</h3>${rest.map((p) => html`<${ProjectBlock} key=${p.pkey} p=${p} now=${now} onBg=${onBg} onTags=${onTags}/>`)}`}
    ${!n && !board.length && !nRun && html`<div class="empty">${t("home.quiet")}</div>`}
    ${jobsDone.length > 0 && html`<h3>${t("home.jobs")}</h3><div class="list">${jobsDone.map((j) => html`<${Job} key=${j.id} j=${j} now=${now}/>`)}</div>`}
    ${bgFor && html`<${BgSheet} sid=${bgFor} fixed=${true} onClose=${closeBg}/>`}
    ${tagFor && html`<${TagPick} sid=${tagFor.sid} info=${tagFor.info} onDone=${reload} onClose=${closeTag}/>`}
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

export { BoardRow, Home, Mine, Replies, ResumeAt, RunRow, copyWhy, forkAsk, moveKey, moves };
