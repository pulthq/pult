// Pult app — projects and their tags, a new task, a new project.
// Moved from app.js as it was (review 2026-10-27, 6.4).
import { api, conn, on, useLive } from "../core/conn.js";
import { drafts, go, useOverlay } from "../core/nav.js";
import { alertBox, confirmBox, haptic } from "../core/tg.js";
import { Mic, useRecorder } from "../core/voice.js";
import { plural, t } from "../i18n.js";
import { html, useEffect, useRef, useState } from "../vendor/htm-preact-3.1.1.js";
import { BoardRow, Mine, RunRow, moveKey, moves } from "./home.js";
import { Req, useRcpt } from "../ui/cards.js";
import { ChoicePick, Loading, agoShort, avatar, choiceText, dot, dotted, dur, ic, keyTap, plainField, sendKey, tagChips, tagJob, tagSt, useNow } from "../ui/kit.js";
import { BgSheet } from "../ui/load.js";
import { Attach, Thumbs, useAttach } from "../ui/pics.js";


// stage Zh: a row that slides left under the finger to show one action — "Pin" or "Unpin" on a project's row. A
// vertical move stays a scroll (touch-action: pan-y); a short slide springs back, past a third of the action it stays
// open; a tap on the action does it, a tap anywhere else closes; the tap that ends a slide opens nothing. Only to the
// left, starting anywhere inside the row: from the phone's left edge comes the system's own Back. One row open at a
// time, as chats in Telegram. How each slide ended goes to the computer's journal, silently: whether the gesture
// works inside Telegram's window at all is known from there, not from words on the screen (runbook, the lesson of Q97)
const SW_W = 92;
let openRow = null;                                   // the row open now: a ref to its close
function SwipeRow({ act, onAct, children }) {
  const [dx, setDx] = useState(0);
  const [drag, setDrag] = useState(false);
  const g = useRef(null);
  const swiped = useRef(false);
  const me = useRef(null);
  me.current = () => setDx(0);
  useEffect(() => () => { if (openRow === me) openRow = null; }, []);
  const shut = () => { me.current(); if (openRow === me) openRow = null; };
  const tell = (how, s) => api("swipe", { end: how, ms: Math.round(performance.now() - s.t0), dx: Math.round(-s.last) }).catch(() => {});
  const down = (e) => { if (e.pointerType === "mouse" && e.button !== 0) return; g.current = { x: e.clientX, y: e.clientY, x0: dx, last: dx, on: false, t0: performance.now() }; };
  const move = (e) => {
    const s = g.current;
    if (!s) return;
    const mx = e.clientX - s.x, my = e.clientY - s.y;
    if (!s.on) {
      if (Math.abs(mx) < 8 || Math.abs(mx) < Math.abs(my) * 1.5) return;
      s.on = true;
      setDrag(true);
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch (x) { /* no capture: the moves still come while the finger is on the row */ }
    }
    s.last = Math.max(-SW_W - 10, Math.min(0, s.x0 + mx));
    setDx(s.last);
  };
  const up = (e) => {
    const s = g.current;
    g.current = null;
    if (!s || !s.on) return;
    swiped.current = true;
    setTimeout(() => { swiped.current = false; }, 400);       // a tap right after the slide opens nothing; the next one is a tap again
    setDrag(false);
    const open = e.type !== "pointercancel" && s.last < -SW_W / 3;
    setDx(open ? -SW_W : 0);
    if (open) { if (openRow && openRow !== me) openRow.current(); openRow = me; } else if (openRow === me) openRow = null;
    tell(e.type === "pointercancel" ? "cancel" : open ? "open" : "back", s);
  };
  const click = (e) => {
    if (e.target.closest(".swr-act")) return;
    if (swiped.current || dx) { swiped.current = false; e.stopPropagation(); e.preventDefault(); shut(); }
  };
  return html`<div class=${"swr" + (drag ? " drag" : "")} onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${up} onClickCapture=${click}>
    <button class="swr-act" tabindex="-1" onClick=${(e) => { e.stopPropagation(); shut(); onAct(); }}>${act}</button>
    <div class="swr-in" style=${"transform:translateX(" + dx + "px)"}>${children}</div></div>`;
}

// every project in one list, in the same grammar as the board: who waits, who works, the latest outcome; quiet ones last;
// the pinned on top (stage Zh) — a slide left on a row pins or unpins it, and the list takes the computer's order at once
function Projects() {
  const [d, err, set] = useLive(() => api("projects"), []);          // live: the counts change with every turn
  if (!d) return html`<${Loading} err=${err}/>`;
  const pin = async (p) => {
    try {
      const r = await api("pin", { pkey: p.pkey, on: !p.pinned, via: "swipe" });
      haptic("success");
      const rows = d.projects.map((x) => (x.pkey === p.pkey ? Object.assign({}, x, { pinned: r.pinned ? Date.now() / 1000 : 0 }) : x));
      set(Object.assign({}, d, { projects: rows.sort((a, b) => (b.pinned || 0) - (a.pinned || 0)) }));
    } catch (e) { alertBox(e.message); }
  };
  const add = d.create && html`<div class="stick"><button class="btn wide" onClick=${() => go("#/newproject")}>${t("np.create")}</button></div>`;
  if (!d.projects.length) return html`<div><h2>${t("projects")}</h2><div class="empty">${t("projects.none")}</div>${add}</div>`;
  return html`<div><h2>${t("projects")}</h2><div class="list">${d.projects.map((p) => html`
    <${SwipeRow} key=${p.pkey} act=${html`${ic(p.pinned ? "pinoff" : "pin", 20)}<span>${t(p.pinned ? "unpin" : "pin")}</span>`} onAct=${() => pin(p)}>
    <button class=${"item proj-h" + (p.mine || p.work || p.open ? "" : " rest")} onClick=${() => go("#/p/" + encodeURIComponent(p.pkey))}>
      <span class="pname">${avatar(p.name, 34)}<span class="pn"><b>${p.name}</b><span class="dim pmeta">${dotted([
        p.work ? html`<span class="cnt">${dot("work")}${p.work}</span>` : "", p.mine ? html`<span class="cnt">${dot("attn")}${p.mine}</span>` : "",
        p.turns ? t("proj.turns", { n: p.turns, turns: plural(p.turns, "turn") }) : agoShort(p.last)])}</span>
        <span class="ln pline">${p.line || html`<span class="path">${p.path}</span>`}</span></span><span class="ptail">${p.pinned ? ic("pin", 15) : ""}${ic("chev", 16)}</span></span></button></${SwipeRow}>`)}</div>${add}</div>`;
}

// a project's screen — its board, large: what waits for you (answer right here), what runs, today's outcomes, then
// the earlier sessions folded; a new task at the bottom, under the thumb. A red mark anywhere leads here or deeper
// the project's sections with how many of the screen's tasks each has (stage T); a tap narrows every list on the
// screen to that section and shows its topics in a second row; a second tap or "All" brings everything back. The
// button at its right opens the project's tags (T2): beside the row, not in it — at the row's end it went out of
// sight with many sections
function TagBar({ set, sel, top, all, onSel, onTop, pkey }) {
  const sec = sel && set.find((g) => g.n === sel);
  return html`<div class="tagrow"><div class="tagbar" role="toolbar">
    <button class=${"tagf" + (sel ? "" : " on")} onClick=${() => onSel(null)}>${t("tags.all")}<span>${all}</span></button>
    ${set.map((g) => html`<button key=${g.n} class=${"tagf" + (sel === g.n ? " on" : "")} style=${tagSt(g.c)}
      onClick=${() => onSel(sel === g.n ? null : g.n)}><i></i>${g.n}<span>${g.cnt}</span></button>`)}
  </div>${pkey && html`<button class="tagf edit" aria-label=${t("tags.edit")} title=${t("tags.edit")} onClick=${() => go("#/tags/" + encodeURIComponent(pkey))}>${ic("tag", 16)}</button>`}</div>
  ${sec && sec.topics.length > 1 && html`<div class="tagbar sub" style=${tagSt(sec.c)}>
    <button class=${"tagf" + (top ? "" : " on")} onClick=${() => onTop(null)}>${t("tags.topics.all")}<span>${sec.cnt}</span></button>
    ${sec.topics.map((x) => html`<button key=${x.n} class=${"tagf" + (top === x.n ? " on" : "")} onClick=${() => onTop(top === x.n ? null : x.n)}>${x.n}<span>${x.cnt}</span></button>`)}
  </div>`}`;
}

function Project({ pkey, tag, topic }) {
  const now = useNow(1000);
  const [d, err, set] = useLive(() => api("project", { pkey }), [pkey]);
  const [more, setMore] = useState(false);
  const [sel, setSel0] = useState(tag || null);           // stage T: the section the lists are narrowed to, and its topic
  const [top, setTop] = useState(topic || null);
  const setSel = (v) => { setSel0(v); setTop(null); };
  const [bgFor, setBgFor] = useState(null);
  const [openBg, closeBg] = useOverlay(!!bgFor, (v) => { if (!v) setBgFor(null); });
  const yours = useRcpt(d ? moves(d.pending, d.mine) : [], moveKey);           // as on Home: one line by time
  if (!d) return html`<${Loading} err=${err}/>`;
  const onBg = (s) => { setBgFor(s.sid); openBg(); };
  const gone = (sid) => set(Object.assign({}, d, { mine: d.mine.filter((r) => r.sid !== sid) }));
  const tagsOf = new Map([...d.mine, ...d.live, ...d.today, ...d.earlier].map((r) => [r.sid, r.tags || []]));
  const has = (sid) => { const g = tagsOf.get(sid) || []; return !sel || (g[0] && g[0].n === sel && (!top || (g[1] && g[1].n === top))); };
  const mineF = yours.filter((e) => has(e.req ? e.req.sid : e.mine.sid));
  const liveF = d.live.filter((r) => has(r.sid)), todayF = d.today.filter((r) => has(r.sid)), earlierF = d.earlier.filter((r) => has(r.sid));
  const waits = sel ? mineF.length : d.pending.length + d.mine.length;
  const sum = d.turns ? t("sum.today", { n: d.turns, turns: plural(d.turns, "turn"), dur: dur(d.secs) }) : t("proj.quiet");
  const pin = async () => {
    try { const r = await api("pin", { pkey, on: !d.pinned, via: "button" }); haptic("success"); set(Object.assign({}, d, { pinned: r.pinned })); }
    catch (e) { alertBox(e.message); }
  };
  return html`<div class="project">
    <div class="ph">${avatar(d.name, 44)}<div><h2>${d.name}</h2><div class="sum dim">${sum}</div></div>
      <button class=${"pinb" + (d.pinned ? " on" : "")} aria-label=${t(d.pinned ? "unpin" : "pin")} title=${t(d.pinned ? "unpin" : "pin")} aria-pressed=${!!d.pinned} onClick=${pin}>${ic("pin", 20)}</button></div>
    ${d.tagset && (d.tagset.length > 0 || d.tags_n > 0) && html`<${TagBar} set=${d.tagset} sel=${sel} top=${top} all=${tagsOf.size} onSel=${setSel} onTop=${setTop} pkey=${d.tags_n != null ? pkey : null}/>`}
    ${d.tag_job && html`<div class="dim small tidy-run">${ic("auto", 14)} ${tagJob(d.tag_job)}</div>`}
    ${(waits > 0 || mineF.length > 0) && html`<h3>${t("proj.waits", { n: waits })}</h3>
      ${mineF.map((e) => e.req ? html`<${Req} key=${e.key} r=${e.req} showProject=${false}/>`
        : html`<${Mine} key=${e.key} r=${Object.assign({ reset: d.reset }, e.mine)} now=${now} onGot=${gone} stt=${d.stt} showProject=${false}/>`)}`}
    ${liveF.length > 0 && html`<h3>${t("proj.live", { n: liveF.length })}</h3><div class="list">${liveF.map((r) => html`<${RunRow} key=${r.sid} r=${r} now=${now} onBg=${onBg} showProject=${false}/>`)}</div>`}
    ${todayF.length > 0 && html`<h3>${t("proj.today")}</h3><div class="list">${todayF.map((r) => html`<${BoardRow} key=${r.sid} r=${r} now=${now} onBg=${onBg}/>`)}</div>`}
    ${!waits && !mineF.length && !liveF.length && !todayF.length && !(sel && earlierF.length) && html`<div class="empty small">${t("proj.nothing")}</div>`}
    ${earlierF.length > 0 && html`<h3 class="toggle" role="button" tabindex="0" aria-expanded=${more} onClick=${() => setMore(!more)} onKeyDown=${keyTap(() => setMore(!more))}>${t("proj.earlier", { n: earlierF.length })} <span class=${"chev" + (more || sel ? " open" : "")}>${ic("chev", 14)}</span></h3>
      ${(more || sel) && html`<div class="list">${earlierF.map((x) => html`<button class="item brow rest" key=${x.sid} onClick=${() => go("#/s/" + x.sid)}>
        <div class="item-h"><b>${x.driven ? html`<span class="st-ic">${ic("phone", 14)}</span>` : ""}${x.title}</b><span class="meta"><span class="dim nowrap">${agoShort(x.last)}</span></span></div>
        ${x.line || x.open || (x.tags && x.tags.length > 0) ? html`<div class="ln">${tagChips(x.tags)}${x.line || (x.open ? t("open.mac") : "")}</div>` : ""}</button>`)}</div>`}`}
    <div class="stick"><button class="btn wide" onClick=${() => go("#/new?pkey=" + encodeURIComponent(pkey))}>${t("project.new")}</button></div>
    ${bgFor && html`<${BgSheet} sid=${bgFor} fixed=${true} onClose=${closeBg}/>`}
  </div>`;
}

// a task's tags (stage T): its section, then a topic in it. "Claude picks them" leaves both to Claude; a tap on another
// section or on a topic makes the choice the owner's, and Claude never changes it again. Each tap is saved at once,
// as in the model menu; a new section or topic by name, right here
function TagPick({ sid, info, onDone, onClose }) {
  const [tags, setTags] = useState(info.tags || []);
  const [set, setSet] = useState(info.tagset || []);
  const [auto, setAuto] = useState(info.tag_auto !== false);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(null);          // "sec" | "topic": the field for a new name is open
  const [name, setName] = useState("");
  const sec = tags[0] ? tags[0].n : null, top = tags[1] ? tags[1].n : null;
  const cur = set.find((g) => g.n === sec);
  const pick = async (args) => {
    setBusy(true);
    try { const r = await api("tag", Object.assign({ sid }, args)); haptic("success"); setTags(r.tags || []); setSet(r.tagset || []); setAuto(!!r.auto); onDone(); }
    catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  const add = (e) => {
    e.preventDefault();
    const v = name.trim();
    if (!v) return;
    const kind = adding;
    setAdding(null); setName("");
    pick(kind === "sec" ? { sec: v } : { sec, topic: v });
  };
  const field = (kind) => (adding === kind ? html`<form class="tagnew" onSubmit=${add}><input value=${name} placeholder=${t("tags.name")} maxlength="32"
      autocomplete="off" onInput=${(e) => setName(e.target.value)} ref=${(el) => el && !el.dataset.on && ((el.dataset.on = "1"), el.focus())}/>
      <button class="btn" disabled=${busy || !name.trim()}>${t("tags.add")}</button></form>`
    : html`<button class="tagf add" disabled=${busy} onClick=${() => { setAdding(kind); setName(""); }}>${ic("plus", 14)} ${t(kind === "sec" ? "tags.sec.new" : "tags.topic.new")}</button>`);
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick tall tagpick"><div class="q-t pick-h">${t("tags.task")}<button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></div>
    <button class=${"opt auto" + (auto ? " on" : "")} disabled=${busy} onClick=${() => { if (!auto) pick({ auto: true }); }}>${ic("auto", 16)}<span class="tn">${t("tags.auto")}</span>${auto ? ic("check", 16) : ""}<span class="dim">${t("tags.auto.about")}</span></button>
    <div class="pick-t">${t("tags.sec")}</div>
    <div class="pills">${set.map((g) => html`<button key=${g.n} class=${"tagf" + (sec === g.n ? " on" : "") + (g.fresh ? " fresh" : "")} style=${tagSt(g.c)} disabled=${busy}
      onClick=${() => { if (sec !== g.n) pick({ sec: g.n }); }}><i></i>${g.n}</button>`)}${field("sec")}</div>
    ${sec && html`<div class="pick-t">${t("tags.topic")}</div>
    <div class="pills" style=${cur ? tagSt(cur.c) : ""}>${(cur ? cur.topics : []).map((x) => html`<button key=${x.n} class=${"tagf topic" + (top === x.n ? " on" : "") + (x.fresh ? " fresh" : "")} disabled=${busy}
      onClick=${() => pick({ sec, topic: top === x.n ? "" : x.n })}>${x.n}</button>`)}${field("topic")}</div>`}
    <div class="dim small">${t("tags.mine")}</div></div>`;
}

// the new-task form picks with the app's own lists, not native <select>s: in Telegram on Android the project list
// would not let the owner pick (2026-10-21), and the 30-s poll reorders projects (what needs you first), so the rows
// could move under the finger — a list is frozen while it is open. The form starts on the project last started here,
// never on whatever needs you first: that is how a "have a look" went to the wrong project (2026-10-21)
const LAST_NEW = {
  get() { try { return localStorage.getItem("pult.newPkey") || ""; } catch (e) { return ""; } },
  set(k) { try { localStorage.setItem("pult.newPkey", k); } catch (e) {} },
};

function ProjectPick({ projects, cur, onPick, onClose, create }) {
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick tall fixed">
    <div class="q-t pick-h">${t("new.pick.title")}<button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></div>
    ${create && html`<button class="opt add" onClick=${() => { onClose(); go("#/newproject"); }}>${t("np.create")}</button>`}
    ${projects.map((x) => html`<button key=${x.pkey} class=${"opt" + (x.pkey === cur ? " on" : "")} onClick=${() => onPick(x.pkey)}>${x.name}${x.pinned ? html`<i class="opt-pin">${ic("pin", 14)}</i>` : ""}</button>`)}</div>`;
}

function NewTask({ pkey }) {
  const [d, err] = useLive(() => api("projects"), [], () => false);
  const [p, setP] = useState(pkey || "");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const [sheet, setSheet] = useState(null);         // {k: "project", list} — the list as it was when opened — or {k: "model"}
  const a = useAttach();
  const v = useRecorder((w) => setText((c) => (c ? c.replace(/\s+$/, "") + " " : "") + w), "new");
  useEffect(() => { const d = drafts.take("new"); if (d) setText((c) => (c ? c + " " : "") + d); }, []);
  useEffect(() => {
    const last = LAST_NEW.get();
    if (d && !p && last && d.projects.some((x) => x.pkey === last)) setP(last);
  }, [d]);
  if (!d) return html`<${Loading} err=${err}/>`;
  const send = async () => {
    setBusy(true);
    try {
      const r = await api("new", { pkey: p, text, files: a.payload(), model, effort });
      LAST_NEW.set(p); haptic("success"); go("#/s/" + r.sid, true);
    }
    catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  const cur = d.projects.find((x) => x.pkey === p);
  const close = () => setSheet(null);
  return html`<div class="form"><h2>${t("new.title")}</h2>
    <label class="lbl">${t("new.project")}</label>
    <button class=${"field" + (p ? "" : " empty")} onClick=${() => setSheet({ k: "project", list: d.projects })}>
      <span>${p ? (cur ? cur.name : p) : t("new.pick")}</span><span class="dim">${ic("down", 18)}</span></button>
    <label class="lbl">${t("new.what")}</label>
    <textarea ref=${plainField} rows="6" placeholder=${t("new.placeholder")} value=${text} onKeyDown=${sendKey(() => { if (!busy && p && (text.trim() || a.files.length)) send(); }, setText)} onInput=${(e) => setText(e.target.value)}/>
    <${Thumbs} a=${a}/>
    <${Attach} a=${a} disabled=${busy} wide=${true} keep=${{ k: "new", text }}/>
    ${d.stt ? html`<${Mic} v=${v} disabled=${busy} wide=${true}/>` : ""}
    <label class="lbl">${t("model.pick")}</label>
    <button class="field" onClick=${() => setSheet({ k: "model" })}>
      <span>${choiceText(model, effort, d.choice)}</span><span class="dim">${ic("down", 18)}</span></button>
    <button class="btn wide" disabled=${busy || !p || (!text.trim() && !a.files.length)} onClick=${send}>${t("new.start")}</button>
    <div class="dim small">${t("new.about")}</div>
    ${sheet && sheet.k === "project" && html`<${ProjectPick} projects=${sheet.list} cur=${p} create=${d.create} onClose=${close} onPick=${(k) => { setP(k); haptic("success"); close(); }}/>`}
    ${sheet && sheet.k === "model" && html`<${ChoicePick} model=${model} effort=${effort} def=${d.choice} onClose=${close}
      onPick=${(c) => { if ("model" in c) setModel(c.model); if ("effort" in c) setEffort(c.effort); haptic("success"); }}/>`}
  </div>`;
}

// ---------- a new project (stage S) ----------
// A folder on the computer for something Claude hasn't worked on yet. The folder's name follows the title (the
// computer turns it into Latin — one rule for the app and the daemon) until the owner edits it; the place is picked
// level by level inside the home folder; three ways to begin. The computer checks everything again on "Create".

const HOWS = ["empty", "describe", "clone"];
const STEPS = { receive: "np.step.receive", resolve: "np.step.resolve", files: "np.step.files" };

function FolderPick({ start, onPick, onClose }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const load = (args) => api("dirs", args).then((x) => { setD(x); setErr(null); }).catch((e) => setErr(e.message));
  useEffect(() => { load(start ? { path: start } : {}); }, []);
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick tall fixed">
    <div class="q-t pick-h"><span class="path">${d ? d.show : "…"}</span><button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></div>
    ${err && html`<div class="pick-why">${err}</div>`}
    ${d && html`<button class="btn wide" onClick=${() => onPick(d)}>${t("np.pick.here")}</button>
      ${d.up && html`<button class="opt up" onClick=${() => load({ path: d.up })}>${ic("up", 16)} ${t("np.pick.up")}</button>`}
      ${d.dirs.map((n) => html`<button key=${n} class="opt" onClick=${() => load({ path: d.path, into: n })}>${ic("folder", 16)} ${n}</button>`)}
      ${!d.dirs.length && html`<div class="dim small">${t("np.pick.none")}</div>`}`}
  </div>`;
}

function NewProject() {
  const [d] = useLive(() => api("projects"), [], () => false);       // only for the microphone: shown with a key
  const [title, setTitle] = useState("");
  const [name, setName] = useState("");
  const [edited, setEdited] = useState(false);       // the owner typed the folder's name: it no longer follows the title
  const [place, setPlace] = useState(null);           // {path, show, tabs}
  const [how, setHow] = useState("empty");
  const [about, setAbout] = useState("");
  const [link, setLink] = useState("");
  const [text, setText] = useState("");
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const [sheet, setSheet] = useState(null);           // "dir" | "model"
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState(null);               // a clone in progress: {step, sec}
  const a = useAttach();
  const howRef = useRef(how);
  howRef.current = how;
  const add = (set) => (w) => set((c) => (c ? c.replace(/\s+$/, "") + " " : "") + w);
  const v = useRecorder((w) => (howRef.current === "describe" ? add(setAbout) : add(setText))(w));
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  // the default place until the owner picks one: a reconnect put the default back over their choice (review 2026-10-27, П8)
  useEffect(() => {
    const dflt = () => api("dirs").then((x) => setPlace((p) => p || x)).catch(() => {});
    if (conn.ready) dflt();
    return on("ready", dflt);
  }, []);
  useEffect(() => {                                    // the folder's name, as the computer will make it
    if (edited) return;
    const src = how === "clone" ? link : "";
    if (!title.trim() && !src.trim()) { setName(""); return; }
    const timer = setTimeout(() => api("folder", { title, link: src }).then((r) => alive.current && !edited && setName(r.name)).catch(() => {}), 300);
    return () => clearTimeout(timer);
  }, [title, link, how, edited]);
  const finish = (r) => {
    haptic("success");
    if (r.git === false) alertBox(t("np.nogit"));
    if (r.busy) alertBox(r.busy);            // the project is made; its first turn has no place yet (0.18.6)
    go(r.sid ? "#/s/" + r.sid : "#/p/" + encodeURIComponent(r.pkey), true);
  };
  const watch = (job) => new Promise((ok, no) => {
    const tick = () => api("job", { job }).then((j) => {
      if (!alive.current) return ok(null);
      if (j.state === "run") { setJob(j); setTimeout(tick, 1000); }
      else if (j.state === "done") ok(j);
      else no(new Error(j.error));
    }).catch(no);
    tick();
  });
  const create = async (big = false) => {
    setBusy(true);
    try {
      let r = await api("create", { title, name, parent: place && place.path, how, about, link, text, files: a.payload(), model, effort, big });
      if (r.big) {
        setBusy(false);
        if (await confirmBox(t("np.big", { mb: r.big }))) return create(true);
        return;
      }
      if (r.job) r = await watch(r.job);
      if (r) finish(r);
    }
    catch (e) { alertBox(e.message); }
    if (alive.current) { setBusy(false); setJob(null); }
  };
  const ready = !busy && place && name.trim() && (title.trim() || how === "clone") && (how !== "describe" || about.trim()) && (how !== "clone" || link.trim());
  const step = job && job.step ? t(STEPS[job.step[0]], { p: job.step[1] }) : "";
  const close = () => setSheet(null);
  return html`<div class="form"><h2>${t("np.title")}</h2>
    <label class="lbl">${t("np.name")}</label>
    <input ref=${plainField} value=${title} placeholder=${t("np.name.ph")} onInput=${(e) => setTitle(e.target.value)}/>
    <label class="lbl">${t("np.folder")}</label>
    <input ref=${plainField} class="mono" value=${name} placeholder=${t("np.folder.ph")} onInput=${(e) => { setEdited(true); setName(e.target.value.trim()); }}/>
    <label class="lbl">${t("np.where")}</label>
    <button class="field" onClick=${() => setSheet("dir")}><span class="path">${place ? place.show : "…"}</span><span class="dim">${ic("down", 18)}</span></button>
    ${place && place.tabs === false && html`<div class="dim small np-hint">${t("np.notabs")}</div>`}
    <label class="lbl">${t("np.how")}</label>
    ${HOWS.map((h) => html`<button key=${h} class=${"opt" + (how === h ? " on" : "")} onClick=${() => setHow(h)}>${t("np." + h)}<span class="dim">${t("np." + h + ".about")}</span></button>`)}
    ${how === "clone" && html`<label class="lbl">${t("np.link")}</label>
      <input ref=${plainField} type="url" inputmode="url" value=${link} placeholder="https://github.com/…" onInput=${(e) => setLink(e.target.value)}/>`}
    ${how === "describe" ? html`<label class="lbl">${t("np.about")}</label>
      <textarea ref=${plainField} rows="5" placeholder=${t("np.about.ph")} value=${about} onInput=${(e) => setAbout(e.target.value)}/>`
    : html`<label class="lbl">${t("np.task")}</label>
      <textarea ref=${plainField} rows="4" placeholder=${t("new.placeholder")} value=${text} onInput=${(e) => setText(e.target.value)}/>
      <${Thumbs} a=${a}/><${Attach} a=${a} disabled=${busy} wide=${true} keep=${{}}/>`}
    ${d && d.stt && html`<${Mic} v=${v} disabled=${busy} wide=${true}/>`}
    ${(how === "describe" || text.trim() || a.files.length > 0) && html`<label class="lbl">${t("model.pick")}</label>
      <button class="field" onClick=${() => setSheet("model")}>
        <span>${choiceText(model, effort, d && d.choice)}</span><span class="dim">${ic("down", 18)}</span></button>`}
    <button class="btn wide" disabled=${!ready} onClick=${() => create()}>${busy ? (job ? t("np.cloning") + (step ? " · " + step : "") + " · " + dur(job.sec) : "…") : t("np.go")}</button>
    <div class="dim small">${t("np.help")}</div>
    ${sheet === "dir" && html`<${FolderPick} start=${place && place.path} onClose=${close} onPick=${(x) => { setPlace(x); haptic("success"); close(); }}/>`}
    ${sheet === "model" && html`<${ChoicePick} model=${model} effort=${effort} def=${d && d.choice} onClose=${close}
      onPick=${(c) => { if ("model" in c) setModel(c.model); if ("effort" in c) setEffort(c.effort); haptic("success"); }}/>`}
  </div>`;
}

export { NewProject, NewTask, Project, Projects, TagPick };
