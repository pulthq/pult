// Pult app — a project's tags (stage T, T2): the sections and topics Claude keeps for its tasks, as one list, the most
// used first. The owner only tidies: renames, gives a section its colour, merges two into one, hides; keeps a tag
// Claude has just made; takes or declines Claude's offers to merge two that name the same thing. Each change is the
// computer's at once and final: Claude sees the new list, and an old name it brings lands on the new one.
import { api, emit, useLive } from "../core/conn.js";
import { go, useOverlay } from "../core/nav.js";
import { alertBox, confirmBox, haptic } from "../core/tg.js";
import { q, t } from "../i18n.js";
import { html, useState } from "../vendor/htm-preact-3.1.1.js";
import { Loading, TAG_H, avatar, ic, keyTap, tagJob, tagSt } from "../ui/kit.js";

// a tag in words: a topic of another section carries its section's name
const named = (x, home) => (x.topic ? (x.sec === home ? x.topic : x.sec + " · " + x.topic) : x.sec);
const focusOnce = (el) => { if (el && !el.dataset.on) { el.dataset.on = "1"; el.focus(); el.select(); } };

function Head({ title, onClose }) {
  return html`<div class="q-t pick-h"><span>${title}</span><button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></div>`;
}

// a topic's own sheet: what can be done with it, and its tasks on the project's screen
function TopicSheet({ pkey, g, x, busy, onAct, onClose }) {
  const opt = (k, label, fn) => html`<button key=${k} class="opt" disabled=${busy} onClick=${fn}>${label}</button>`;
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick fixed tagsheet" style=${tagSt(g.c)}>
    <${Head} title=${html`<span class="tagc topic">${x.n}</span><span class="dim small0">${g.n}</span>`} onClose=${onClose}/>
    ${x.fresh && opt("keep", t("tags.keep"), () => onAct({ op: "keep", sec: g.n, topic: x.n }))}
    ${opt("rename", t("tags.rename"), () => onAct({ k: "rename", sec: g.n, topic: x.n }))}
    ${opt("merge", t("tags.merge"), () => onAct({ k: "merge", sec: g.n, topic: x.n }))}
    ${opt("hide", t("tags.hide"), () => onAct({ op: "hide", sec: g.n, topic: x.n }, t("tags.hidden.toast")))}
    ${x.cnt > 0 && opt("tasks", t("tags.tasks", { n: x.cnt }), () => go("#/p/" + encodeURIComponent(pkey) + "?tag=" + encodeURIComponent(g.n) + "&topic=" + encodeURIComponent(x.n)))}
  </div>`;
}

function RenameSheet({ sec, topic, busy, onSave, onClose }) {
  const was = topic || sec;
  const [v, setV] = useState(was);
  const ok = v.trim() && v.trim() !== was;
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick fixed tagsheet">
    <${Head} title=${t(topic ? "tags.rename.topic" : "tags.rename.sec")} onClose=${onClose}/>
    <form class="tagnew" onSubmit=${(e) => { e.preventDefault(); if (ok && !busy) onSave(v.trim()); }}>
      <input value=${v} maxlength="32" autocomplete="off" aria-label=${t("tags.name")} onInput=${(e) => setV(e.target.value)} ref=${focusOnce}/>
      <button class="btn" disabled=${busy || !ok}>${t("tags.save")}</button></form>
    <div class="dim small">${t("tags.rename.about")}</div></div>`;
}

// eight colours; the section's chips as they will look
function ColorSheet({ g, busy, onPick, onClose }) {
  const cur = (g.c || 0) % TAG_H.length;
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick fixed tagsheet">
    <${Head} title=${t("tags.color.title", { n: q(g.n) })} onClose=${onClose}/>
    <div class="swatches">${TAG_H.map((h, i) => html`<button key=${i} class=${"tsw" + (i === cur ? " on" : "")} style=${"--th:" + h}
      aria-label=${t("tags.color.n", { n: i + 1 })} aria-pressed=${i === cur} disabled=${busy} onClick=${() => (i === cur ? onClose() : onPick(i))}>${i === cur ? ic("check", 18) : ""}</button>`)}</div>
    <div class="tprev" style=${tagSt(cur)}><span class="tagc">${g.n}</span>${g.topics.slice(0, 3).map((x) => html`<span key=${x.n} class="tagc topic">${x.n}</span>`)}</div></div>`;
}

// what to merge into: a section — another section; a topic — a topic of its own section first, then of the others
function MergeSheet({ d, sec, topic, busy, onPick, onClose }) {
  const me = d.secs.find((g) => g.n === sec);
  const secs = topic ? [me, ...d.secs.filter((g) => g.n !== sec)].filter(Boolean) : d.secs.filter((g) => g.n !== sec);
  const pick = async (to) => {
    const a = q(topic || sec), b = q(named(to, sec));
    if (await confirmBox(t(topic ? "tags.merge.ask.topic" : "tags.merge.ask.sec", { a, b }))) onPick(to);
  };
  const groups = topic ? secs.map((g) => [g, g.topics.filter((x) => !(g.n === sec && x.n === topic))]).filter(([, xs]) => xs.length > 0) : [];
  const none = topic ? !groups.length : !secs.length;
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick fixed tall tagsheet">
    <${Head} title=${t("tags.merge.title", { n: q(topic || sec) })} onClose=${onClose}/>
    ${none && html`<div class="dim small">${t("tags.merge.none")}</div>`}
    ${!topic && secs.map((g) => html`<button key=${g.n} class="opt tsec" style=${tagSt(g.c)} disabled=${busy} onClick=${() => pick({ sec: g.n, topic: null })}>
      <i class="tdot"></i><span class="tn">${g.n}</span><span class="cnt-n">${g.cnt}</span></button>`)}
    ${groups.map(([g, xs]) => html`<div key=${g.n}><div class="pick-t">${g.n}</div><div class="pills" style=${tagSt(g.c)}>
      ${xs.map((x) => html`<button key=${x.n} class="tagf topic" disabled=${busy} onClick=${() => pick({ sec: g.n, topic: x.n })}>${x.n}<span>${x.cnt}</span></button>`)}</div></div>`)}
  </div>`;
}

function Tags({ pkey, open: open0 }) {
  const [d, err, set] = useLive(() => api("tags", { pkey }), [pkey]);
  const [open, setOpen] = useState(open0 || null);        // the section whose actions show
  const [sheet, setSheet] = useState(null);               // {k: "topic" | "rename" | "color" | "merge", sec, topic}
  const [openSheet, closeSheet] = useOverlay(!!sheet, (v) => { if (!v) setSheet(null); });
  const [busy, setBusy] = useState(false);
  const [shut, setShut] = useState(true);                 // the hidden ones, folded
  if (!d) return html`<${Loading} err=${err}/>`;
  const sheetFor = (s) => { setSheet(s); openSheet(); };
  // one change: the computer answers with the screen anew; a new name that is another tag's — offered to merge
  const edit = async (args, done) => {
    setBusy(true);
    try {
      const r = await api("tags_edit", Object.assign({ pkey }, args));
      set(r);
      if (r.exists) {
        setBusy(false);
        const n = q(named(r.exists, args.sec));
        if (await confirmBox(t(r.exists.topic ? "tags.exists.topic" : "tags.exists.sec", { n }))) {
          return edit({ op: "merge", sec: args.sec, topic: args.topic, to_sec: r.exists.sec, to_topic: r.exists.topic }, t("tags.merged"));
        }
        return false;
      }
      haptic("success");
      if (done) emit("toast", done);
      setBusy(false);
      return true;
    } catch (e) { alertBox(e.message); }
    setBusy(false);
    return false;
  };
  // "Sort them again": Claude makes the list anew and sorts every task the owner didn't tag — after "Are you sure?"
  const resort = async () => {
    if (!(await confirmBox(t("tags.resort.ask")))) return;
    setBusy(true);
    try { set(await api("tags_resort", { pkey })); haptic("success"); } catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  const act = async (a, done) => {                         // from a sheet: another sheet, or a change that closes it
    if (a.k) { setSheet(a); return; }
    if (await edit(a, done)) closeSheet();
  };
  const g = sheet && d.secs.find((x) => x.n === sheet.sec);
  const x = g && sheet.topic && g.topics.find((y) => y.n === sheet.topic);
  return html`<div class="project tagscr">
    <div class="ph">${avatar(d.name, 44)}<div><h2>${t("tags.title")}</h2><div class="sum dim">${d.name}</div></div></div>
    ${d.job && html`<div class="dim small tidy-run">${ic("auto", 14)} ${tagJob(d.job)}</div>`}
    ${d.note && html`<div class="pick-why">${d.note}</div>`}
    ${d.tidy && !d.job && html`<div class="dim small tidy-run">${ic("auto", 14)} ${t("tags.tidy.run")}</div>`}
    ${d.sug.map((m) => {
      const kind = m.a.topic ? "topic" : "sec", home = m.a.sec === m.b.sec ? m.a.sec : null;
      const a = q(named(m.a, home)), b = q(named(m.b, home));
      return html`<div class="card tsug" key=${a + b}><div class="q-t">${ic("auto", 16)} ${t("tags.offer")}</div>
        <div>${t("tags.offer." + kind, { a, b })}</div><div class="dim small0 stays">${t("tags.offer.stays", { b })}</div>
        <div class="foot"><button class="link" disabled=${busy} onClick=${() => edit({ op: "apart", sec: m.a.sec, topic: m.a.topic, to_sec: m.b.sec, to_topic: m.b.topic })}>${t("tags.offer.no." + kind)}</button>
          <button class="btn" disabled=${busy} onClick=${() => edit({ op: "merge", sec: m.a.sec, topic: m.a.topic, to_sec: m.b.sec, to_topic: m.b.topic }, t("tags.merged"))}>${t("tags.offer.do")}</button></div></div>`;
    })}
    ${!d.secs.length && !d.hidden.length && html`<div class="empty">${t("tags.empty")}</div>`}
    ${d.secs.length > 0 && html`<h3>${t("tags.list", { n: d.secs.length })}</h3>
    <div class="list">${d.secs.map((s) => {
      const on = open === s.n, nw = s.topics.find((y) => y.fresh);
      const fresh = s.fresh ? { sec: s.n } : nw ? { sec: s.n, topic: nw.n } : null;
      return html`<div class=${"item trow" + (on ? " open" : "")} key=${s.n} style=${tagSt(s.c)}>
        <button class="trow-h" aria-expanded=${on} onClick=${() => setOpen(on ? null : s.n)}><i class="tdot"></i><span class="tn"><b>${s.n}</b></span>
          <span class="cnt-n">${s.cnt}</span>${ic(on ? "down" : "chev", 16)}</button>
        ${s.topics.length > 0 && html`<div class="ttops">${s.topics.map((y) => html`<button key=${y.n} class=${"tagc topic" + (y.fresh ? " fresh" : "")}
          onClick=${() => sheetFor({ k: "topic", sec: s.n, topic: y.n })}>${y.n}${y.cnt > 1 ? html` <b>${y.cnt}</b>` : ""}</button>`)}</div>`}
        ${fresh && html`<div class="tfresh"><span>${t(fresh.topic ? "tags.made.topic" : "tags.made.sec", { n: q(fresh.topic || fresh.sec) })}</span>
          <button class="link" disabled=${busy} onClick=${() => edit(Object.assign({ op: "keep" }, fresh))}>${t("tags.keep")}</button>
          <button class="link" disabled=${busy} onClick=${() => sheetFor(Object.assign({ k: "merge" }, fresh))}>${t("tags.merge")}</button></div>`}
        ${on && html`<div class="tacts">
          <button class="link" onClick=${() => sheetFor({ k: "rename", sec: s.n })}>${t("tags.rename")}</button>
          <button class="link" onClick=${() => sheetFor({ k: "color", sec: s.n })}>${t("tags.color")}</button>
          <button class="link" onClick=${() => sheetFor({ k: "merge", sec: s.n })}>${t("tags.merge")}</button>
          <button class="link" disabled=${busy} onClick=${() => edit({ op: "hide", sec: s.n }, t("tags.hidden.toast"))}>${t("tags.hide")}</button></div>`}
      </div>`;
    })}</div>`}
    ${d.hidden.length > 0 && html`<h3 class="toggle" role="button" tabindex="0" aria-expanded=${!shut} onClick=${() => setShut(!shut)} onKeyDown=${keyTap(() => setShut(!shut))}>${t("tags.hidden", { n: d.hidden.length })} <span class=${"chev" + (shut ? "" : " open")}>${ic("chev", 14)}</span></h3>
      ${!shut && html`<div class="list">${d.hidden.map((h) => html`<div class="item trow hid" key=${h.sec + "/" + (h.topic || "")} style=${tagSt(h.c)}>
        <div class="trow-h"><i class="tdot"></i><span class="tn">${h.topic ? html`<span class="dim">${h.sec} · </span>${h.topic}` : html`<b>${h.sec}</b>`}</span><span class="cnt-n">${h.cnt}</span>
          <button class="link" disabled=${busy} onClick=${() => edit({ op: "show", sec: h.sec, topic: h.topic })}>${t("tags.show")}</button></div></div>`)}</div>
        <div class="dim small">${t("tags.hidden.about")}</div>`}`}
    ${(d.secs.length > 0 || d.hidden.length > 0) && html`<div class="tbtns"><button class="btn ghost" disabled=${busy || !!d.job || !d.model} onClick=${resort}>${ic("auto", 16)} ${t("tags.resort")}</button></div>
      ${!d.model && html`<div class="dim small">${t("tags.resort.off")}</div>`}`}
    <div class="dim small tfoot">${t("tags.foot")}</div>
    ${sheet && sheet.k === "topic" && g && x && html`<${TopicSheet} pkey=${pkey} g=${g} x=${x} busy=${busy} onAct=${act} onClose=${closeSheet}/>`}
    ${sheet && sheet.k === "rename" && html`<${RenameSheet} key=${sheet.sec + "/" + (sheet.topic || "")} sec=${sheet.sec} topic=${sheet.topic} busy=${busy}
      onSave=${(v) => act({ op: "rename", sec: sheet.sec, topic: sheet.topic, name: v })} onClose=${closeSheet}/>`}
    ${sheet && sheet.k === "color" && g && html`<${ColorSheet} g=${g} busy=${busy} onPick=${(c) => act({ op: "color", sec: g.n, c })} onClose=${closeSheet}/>`}
    ${sheet && sheet.k === "merge" && html`<${MergeSheet} d=${d} sec=${sheet.sec} topic=${sheet.topic} busy=${busy}
      onPick=${(to) => act({ op: "merge", sec: sheet.sec, topic: sheet.topic, to_sec: to.sec, to_topic: to.topic }, t("tags.merged"))} onClose=${closeSheet}/>`}
  </div>`;
}

export { Tags };
