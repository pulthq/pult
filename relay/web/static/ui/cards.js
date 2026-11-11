// Pult app — the cards that wait for you: a question, a permission request, a plan; the receipt of an answer.
// Moved from app.js as it was (review 2026-10-27, 6.4).
import { api } from "../core/conn.js";
import { drafts, go, useDraft, useHold } from "../core/nav.js";
import { alertBox, haptic } from "../core/tg.js";
import { Mic, useRecorder } from "../core/voice.js";
import { t } from "../i18n.js";
import { md } from "../md.js";
import { html, useEffect, useRef, useState } from "../vendor/htm-preact-3.1.1.js";
import { avatar, ctxBar, dur, ic, keyTap, llmName, nb, pauseChip, plainField, tagSt } from "./kit.js";


// ---------- cards: question, permission request, plan ----------

// a card answered here keeps "✓ Answer sent" RCPT_MS, a bar running out under it, though the computer drops the
// request at once (the owner didn't see the line at all, 2026-10-24)
const RCPT_MS = 3000;
const answeredAt = new Map();        // rid → when it was answered here
// what to show: the computer's list, and the requests answered here less than RCPT_MS ago in their old places;
// key — a row's request id (other rows never linger)
function useRcpt(list, key = (r) => r.rid) {
  const prev = useRef([]);
  const [, bump] = useState(0);
  const now = Date.now(), ids = new Set(list.map(key)), out = list.slice();
  prev.current.forEach((r, i) => { if (!ids.has(key(r)) && now - (answeredAt.get(key(r)) || 0) < RCPT_MS) out.splice(Math.min(i, out.length), 0, r); });
  prev.current = out;
  const left = out.filter((r) => !ids.has(key(r))).map((r) => answeredAt.get(key(r)) + RCPT_MS - now);
  useEffect(() => {
    if (!left.length) return;
    const tm = setTimeout(() => bump((x) => x + 1), Math.max(0, Math.min(...left)) + 20);
    return () => clearTimeout(tm);
  });
  return out;
}

// your own words in a card — an answer instead of the options, a note to a "no": a line and the microphone, Enter
// sends, as on a session's card in "Your move" (the owner, 2026-11-04: Return did nothing here, and no voice). Words
// dictated after the card went come back from the draft when it shows again
function Own({ ph, label, busy, stt, draft, onSend }) {
  const [text, setText, forget] = useDraft(draft);
  const v = useRecorder((w) => setText((c) => (c ? c.replace(/\s+$/, "") + " " : "") + w), draft);
  useEffect(() => { const d = drafts.take(draft); if (d) setText((c) => (c ? c + " " : "") + d); }, [draft]);
  const submit = () => { if (text.trim() && !busy) { forget(); onSend(text.trim()); } };
  return html`<div class="own"><input ref=${plainField} placeholder=${ph} value=${text} enterkeyhint="send" onInput=${(e) => setText(e.target.value)}
      onKeyDown=${(e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); submit(); } }}/>
    ${stt ? html`<${Mic} v=${v} disabled=${busy}/>` : ""}
    <button class="btn ghost" disabled=${busy || !text.trim()} onClick=${submit}>${label}</button></div>`;
}

function Req({ r, onDone, stt, showWhere = true, showProject = true }) {
  const [busy, setBusy] = useState(false);
  const [noting, setNoting] = useState(false);     // "Deny with a note" tapped: the field for it is open
  // checked from the start: Claude's advice in a multi-select question ("(Recommended)"), or what Telegram has checked —
  // the computer says which (0.18.4; an older one doesn't, nothing is checked); advice takes one "Done" (the owner, 2026-10-27)
  const [picks, setPicks] = useState(() => Object.fromEntries(Object.entries(r.picks || {}).map(([i, v]) => [i, [...v]])));
  const [touched, setTouched] = useState(false);   // ticks changed by hand: a reload would put the first ones back
  const [done, setDone] = useState(null);      // the answer went: "✓ Allowed" in place of the card, until the list drops it
  useHold(touched && !done);
  const [mine, setMine] = useState({});        // questions answered here, shown as answered before the list brings them back
  const chosen = Object.assign({}, r.chosen, mine);
  const send = async (args) => {
    setBusy(true);
    try {
      const res = await api("answer", Object.assign({ rid: r.rid }, args));
      if (res && res.ok === false) alertBox(res.note || t("failed"));
      else if (r.kind === "ask" && Object.keys(Object.assign({}, chosen, args.answers)).length < r.questions.length) {
        haptic("success");           // one of several questions: Claude waits for the rest, the card stays
        setMine(Object.assign({}, mine, args.answers));
      } else {
        haptic("success");
        const k = r.kind === "ask" ? "rcpt.ask" : r.kind === "plan" ? (args.act === "y" ? "rcpt.plan.y" : "rcpt.plan.n")
          : args.act === "a" ? "rcpt.always" : args.act === "y" ? "rcpt.allow" : "rcpt.deny";
        answeredAt.set(r.rid, Date.now());
        setDone(k);
      }
      onDone && onDone();
    } catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  // how long it waits, as a session's card says: "your move" puts them all in one line by time; which model asks —
  // before it, as "Running now" says it on top (Q108): a request has no tags there to push out. The two wrap from the
  // right: a line too short for both drops the model whole, and the project keeps its name
  const llm = llmName(r.llm);
  const waits = r.since && !done ? html`<span class="c-right"><span class="c-wait">${t("mine.waits", { dur: nb(dur(Date.now() / 1000 - r.since)) })}</span>${llm && html`<span class="llm">${llm}</span>`}</span>` : "";
  // the header opens the session, as a session's card on Home does: Claude's whole message before the question is
  // there (the owner, 2026-10-28: a question on Home led nowhere — nothing to read before answering)
  const open = r.sid ? () => go("#/s/" + r.sid) : null;
  const chev = open ? html`<span class="c-go">${ic("chev", 16)}</span>` : "";
  const titled = r.project !== r.title || !showProject;
  // the task's clock, stopped while the request waits (2026-10-30): beside the title, as on the other cards of "Your move"
  const clock = titled ? pauseChip(r.work) : "";
  const where = showWhere && html`<div class=${"card-h" + (open ? " tap" : "")} role=${open ? "button" : undefined} tabindex=${open ? "0" : undefined}
    onClick=${open || undefined} onKeyDown=${open ? keyTap(open) : undefined}>${showProject && r.project || waits ? html`<div class="c-proj">${showProject && r.project ? html`${avatar(r.project, 18)}<span>${r.project}</span>` : ""}${waits}${titled ? "" : chev}</div>` : ""}${titled ? html`<b class="c-title">${r.title}${clock}${chev}</b>` : ""}</div>`;
  if (done) {
    const no = done === "rcpt.deny" || done === "rcpt.plan.n" ? " no" : "";
    return html`<div class="card rcpt" role="status">${where}<div class=${"rcpt-l" + no}>${t(done)}</div>
      <div class=${"rcpt-bar" + no} style=${{ animationDuration: RCPT_MS + "ms" }}></div></div>`;
  }
  if (r.kind === "ask") {
    return html`<div class="card ask">${where}
      ${r.questions.map((qn, i) => chosen[i] ? html`<div class="q done"><div class="q-t">${qn.question}</div>→ <b>${chosen[i].join(", ")}</b></div>` : html`
        <div class="q"><div class="kind">${ic("help", 16)} ${t("kind.q")}</div><div class="q-t">${qn.question}</div>
          ${(qn.options || []).map((o) => {
            const on_ = (picks[i] || []).includes(o.label);
            return html`<button class=${"opt" + (on_ ? " on" : "")} disabled=${busy} onClick=${() => {
              if (qn.multiSelect) { setTouched(true); setPicks(Object.assign({}, picks, { [i]: on_ ? picks[i].filter((x) => x !== o.label) : [...(picks[i] || []), o.label] })); }
              else send({ answers: { [i]: [o.label] } });
            }}><b>${qn.multiSelect ? html`${ic(on_ ? "boxon" : "box", 16)} ` : ""}${o.label}</b>${o.description ? html`<span class="dim">${o.description}</span>` : ""}</button>`;
          })}
          ${qn.multiSelect && html`<button class="btn" disabled=${busy || !(picks[i] || []).length} onClick=${() => send({ answers: { [i]: picks[i] } })}>${t("done")}</button>`}
          <${Own} ph=${t("ask.own")} label=${t("ask.answer")} busy=${busy} stt=${stt} draft=${"a:" + r.rid + ":" + i} onSend=${(w) => send({ answers: { [i]: [w] } })}/>
        </div>`)}
      ${ctxBar(r.ctx)}
    </div>`;
  }
  const isPlan = r.kind === "plan";
  return html`<div class="card perm">${where}
    <div class="kind">${ic(isPlan ? "plan" : "shield", 16)} ${isPlan ? t("req.plan") : t(r.who === "codex" ? "req.perm.codex" : "req.perm")}</div>
    ${isPlan ? html`<details class="plan"><summary>${t("plan")}</summary><div class="md" data-sid=${r.sid} dangerouslySetInnerHTML=${{ __html: md(r.plan) }}/></details>`
      : html`<div class="perm-b" dangerouslySetInnerHTML=${{ __html: r.html }}/>`}
    <div class="row">
      <button class="btn" disabled=${busy} onClick=${() => send({ act: "y" })}>${isPlan ? t("approve") : t("allow")}</button>
      <button class="btn danger" disabled=${busy} onClick=${() => send({ act: "n" })}>${isPlan ? t("reject.plan") : t("deny")}</button>
    </div>
    <div class="foot quiet">${r.suggest ? html`<button class="link" disabled=${busy} onClick=${() => send({ act: "a" })}>${t(r.who === "codex" ? "always.task" : "always.short")}</button>` : html`<span></span>`}
    ${noting ? "" : html`<button class="link" onClick=${() => setNoting(true)}>${isPlan ? t("plan.notes") : t("deny.note.short")}</button>`}</div>
    ${noting && html`<${Own} ph=${t("tell.claude")} label=${t("send")} busy=${busy} stt=${stt} draft=${"n:" + r.rid} onSend=${(w) => send({ act: "n", text: w })}/>`}
    ${ctxBar(r.ctx)}
  </div>`;
}

// a task's tags (stage T; from its row's slide too — stage Zh, step 2): its section, then a topic in it. "Claude picks them" leaves both to Claude; a tap on another
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

export { Req, TagPick, useRcpt };
