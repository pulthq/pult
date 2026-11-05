// Pult app — a project's settings (stage M, step 7.2; Q138, Q142–Q148): its model, which does every task of it and
// changes only while nothing runs there; the helper Claude haiku and what it costs the project's isolation; what its
// topic in Telegram gets; its review by another vendor; its tags, pin and fold. The sketches — slides 4–6 of
// docs/isolation-presentation.html.
import { api, useLive } from "../core/conn.js";
import { go, useOverlay } from "../core/nav.js";
import { alertBox, confirmBox, haptic } from "../core/tg.js";
import { t } from "../i18n.js";
import { html, useState } from "../vendor/htm-preact-3.1.1.js";
import { Loading, avatar, codexModel, ic } from "../ui/kit.js";

// a model in words, under its name in the sheet: what it runs as, or in short why it can't take a task now (a tap says
// the whole of it); in the field — only what it runs as
const sub = (m) => (m.why ? (m.id === "codex" ? t("who.codex.missing") : m.local ? t("who.local.off") : t("who.nokey"))
  : m.id === "claude" ? t("who.claude") : m.id === "codex" ? t("who.codex.row", { m: codexModel(m.sub) || t("who.codex.model") })
  : m.local ? t("who.local.row", { m: m.sub || "?" }) : t("who.inside", { m: m.sub || "?" }));
const runs = (m) => (m.id === "claude" ? t("who.claude") : m.id === "codex" ? codexModel(m.sub) || t("who.codex.model") : m.sub || "");

// what runs in the project now: the change waits for it (Q138)
const busyText = (busy) => (busy.length === 1 ? t("ps.busy", { what: busy[0].title }) : t("ps.busy.n", { what: busy[0].title, m: busy.length - 1 }));

// the change, said before it is made (slide 5): who sees the project's files and where its code goes, what stays with the
// model before, what the helper does
function changeText(d, m) {
  const where = m.id === "claude" ? t("ps.ch.claude") : m.id === "codex" ? t("ps.ch.codex") : m.local ? t("ps.ch.home", { name: m.name }) : t("ps.ch.cloud", { name: m.name });
  const haiku = m.id === "claude" && !d.haiku ? " " + t("ps.ch.haiku.on") : m.id !== "claude" && d.haiku ? " " + t("ps.ch.haiku.off") : "";
  return t("ps.ch.q", { name: m.name }) + "\n\n" + where + " " + t("ps.ch.old", { old: d.model.name }) + haiku;
}

function ModelSheet({ d, onPick, onClose }) {
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick tall fixed who">
    <div class="q-t pick-h">${t("ps.model")}<button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></div>
    ${d.busy.length > 0 && html`<div class="pick-why">${busyText(d.busy)}</div>`}
    ${d.models.map((m) => html`<button key=${m.id} class=${"opt" + (m.id === d.model.id ? " on" : "") + (m.why ? " vo-off" : "")} onClick=${() => onPick(m)}>${m.name}<span class="dim">${sub(m)}</span></button>`)}
    ${!d.busy.length && html`<div class="dim small">${t("ps.model.when")}</div>`}</div>`;
}

function ProjectSettings({ pkey }) {
  const [d, err, set] = useLive(() => api("projset", { pkey }), [pkey]);
  const [busy, setBusy] = useState(false);
  const [sheet, setSheet] = useState(false);
  const [openSheet, closeSheet] = useOverlay(sheet, setSheet);
  if (!d) return html`<${Loading} err=${err}/>`;
  const call = async (op, args, words) => {
    setBusy(true);
    try { set(await api(op, Object.assign({ pkey }, args))); haptic("success"); if (words) alertBox(words); }
    catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  const pick = async (m) => {
    if (m.id === d.model.id) return closeSheet();
    if (m.why) return alertBox(m.why);
    if (d.busy.length) return alertBox(busyText(d.busy));
    closeSheet();
    if (await confirmBox(changeText(d, m))) call("project_model", { model: m.id });
  };
  // the helper on in a project of another model: its tasks' words go to Anthropic — asked, said what it costs (Q142)
  const haiku = async () => {
    if (!d.haiku && d.model.id !== "claude" && !(await confirmBox(t("ps.haiku.ask")))) return;
    call("project_prefs", { haiku: !d.haiku });
  };
  const flag = async (op, on) => {
    try { await api(op, { pkey, on, via: "button" }); haptic("success"); set(Object.assign({}, d, op === "pin" ? { pinned: on, hidden: on ? false : d.hidden } : { hidden: on, pinned: on ? false : d.pinned })); }
    catch (e) { alertBox(e.message); }
  };
  const deny = async () => {
    try { await api("vendors_ok", { pkey, on: false }); haptic("success"); set(Object.assign({}, d, { review: Object.assign({}, d.review, { ok: false }) })); }
    catch (e) { alertBox(e.message); }
  };
  const m = d.model;
  return html`<div class="project psets">
    <div class="ph">${avatar(d.name, 44)}<div><h2>${t("ps.title")}</h2><div class="sum dim">${d.name}</div></div></div>
    <h3>${t("ps.model")}</h3>
    <button class="field ps-model" disabled=${busy} onClick=${openSheet}><span><b>${m.name}</b>${runs(m) && html`<i class="dim vf-sub"> · ${runs(m)}</i>`}</span><span class="dim">${ic("chev", 18)}</span></button>
    <div class=${"dim small" + (d.busy.length ? " ps-busy" : "")}>${d.busy.length ? busyText(d.busy) : t("ps.model.when")}</div>
    ${m.why && html`<div class="pick-why">${m.why}</div>`}
    <h3>${t("ps.haiku")}</h3>
    <div class="list"><div class="item sw-row">
      <button class="sw-h" role="switch" aria-checked=${!!d.haiku} disabled=${busy} onClick=${haiku}><b>${t("ps.haiku.sw")}</b><span class=${"sw" + (d.haiku ? " on" : "")}></span></button>
      <div class="dim">${t(m.id === "claude" ? "ps.haiku.claude" : d.haiku ? "ps.haiku.on" : "ps.haiku.off")}</div>
      ${!d.brief && html`<div class="dim small ps-note">${t("ps.haiku.brief")}</div>`}</div></div>
    <h3>${t("ps.topic")}</h3>
    <div class="seg ps-topic">${["full", "done"].map((k) => html`<button key=${k} class=${d.topic === k ? "on" : ""} disabled=${busy} onClick=${() => d.topic !== k && call("project_prefs", { topic: k })}>${t("ps.topic." + k)}</button>`)}</div>
    <div class="dim small">${t("ps.topic." + d.topic + ".about")}</div>
    <h3>${t("ps.review")}</h3>
    <div class="dim small ps-review">${t(d.review.mine ? "ps.review.codex" : "ps.review.about")}</div>
    ${d.review.ok ? html`<div class="vline">${ic("eye", 14)}<span>${t("ps.review.ok")}</span><button class="link" onClick=${deny}>${t("vend.deny")}</button></div>`
      : d.review.codex && !d.review.mine && html`<div class="dim small">${t("ps.review.ask")}</div>`}
    <h3>${t("ps.more")}</h3>
    <div class="list">
      <button class="item ps-row" onClick=${() => go("#/tags/" + encodeURIComponent(pkey))}><span>${ic("tag", 18)} ${t("ps.tags")}</span>${ic("chev", 16)}</button>
      <button class="item ps-row" onClick=${() => flag("pin", !d.pinned)}><span>${ic(d.pinned ? "pinoff" : "pin", 18)} ${t(d.pinned ? "unpin" : "pin")}</span></button>
      <button class="item ps-row" onClick=${() => flag("hide", !d.hidden)}><span>${ic(d.hidden ? "eye" : "eyeoff", 18)} ${t(d.hidden ? "unhide" : "hide")}</span></button>
    </div>
    ${sheet && html`<${ModelSheet} d=${d} onPick=${pick} onClose=${closeSheet}/>`}
  </div>`;
}

export { ProjectSettings, changeText };
