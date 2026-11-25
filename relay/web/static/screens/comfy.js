// Pult app — ComfyUI's models (stage M, step 6.7; the owner, 2026-11-21: "as with Ollama, I'd like to manage the local
// models from Pult without you, in ComfyUI too"; 2026-11-25: "music there as well"): Resources → ComfyUI, and #/comfy
// on its own. The gateway beside ComfyUI on the server says which sets of its verified list are on the disk, downloads
// one, removes one, keeps the main one of each kind, makes a trial picture or tune; the disk and the card come from the
// reader beside Ollama. The computer asks the server; this only draws.
import { api, useLive } from "../core/conn.js";
import { go, useOverlay } from "../core/nav.js";
import { alertBox, confirmBox, haptic } from "../core/tg.js";
import { locale, plural, t } from "../i18n.js";
import { html, useEffect, useState } from "../vendor/htm-preact-3.1.1.js";
import { About, Loading, ic, num, useNow } from "../ui/kit.js";
import { Bar, Leg, gb, gib } from "./local.js";

const KINDS = ["image", "audio"];
const pc = (a, b) => (b > 0 ? Math.max(0, Math.min(100, (a * 100) / b)) : 0);
const prm = (s) => { const m = /^([\d.]+)\s*B$/i.exec(s || ""); return m ? t("vend.list.bn", { n: num(+m[1], 1) }) : s || ""; };
const mmss = (s) => Math.floor(s / 60) + ":" + String(Math.floor(s % 60)).padStart(2, "0");
// a release as people say it: "2026-01" → "January 2026"
const month = (s) => { const m = /^(\d{4})-(\d{2})$/.exec(s || ""); return m ? new Date(+m[1], +m[2] - 1, 1).toLocaleDateString(locale(), { month: "long", year: "numeric" }) : s || ""; };
const steps = (s) => s.kind === "image" && s.steps ? s.steps + " " + plural(s.steps, "step") : "";
const langs = (s) => s.kind === "audio" && s.langs ? t("cf.langs", { n: s.langs }) : "";
const does = (s) => s.does.map((x) => t("cf.does." + x)).join(", ");
// the gateway's word for a failed download in the owner's words; its own English when Pult has none for it
const whyOf = (p) => { const k = "cf.why." + (p.why || ""); return p.why && t(k) !== k ? t(k) : p.err || ""; };
// a set's files by their part — the weights, the encoders, the VAE — each part's bytes once: [[words, bytes]]
const parts = (fs) => {
  const by = {};
  for (const f of fs) (by[f.folder] = by[f.folder] || []).push(f);
  return Object.entries(by).map(([k, xs]) => { const many = "cf.fs." + k; return [xs.length > 1 && t(many) !== many ? t(many) : t("cf.f." + k), xs.reduce((a, f) => a + f.size, 0)]; });
};
const vramGb = (s) => t("gb", { n: num(s.vram_gb, s.vram_gb % 1 ? 1 : 0) }).replace(/ /g, " ");

function DiskBox({ d }) {
  const k = d.disk, models = d.ollama + d.bytes.comfy + d.bytes.also, other = Math.max(0, k.total - k.free - models);
  const over = d.cap && d.total >= d.cap;
  return html`<div class="item static lp-card">
    <div class="lp-h"><b>${t("lp.disk", { label: k.label || "" }).trim()}</b><span class="lp-big">${t("lp.free", { gb: gb(k.free) })}</span></div>
    <${Bar} whole=${k.total} parts=${[{ w: other, c: "o" }, { w: d.ollama, c: "m" }, { w: d.bytes.comfy, c: "g" }, { w: d.bytes.also, c: "a" }]}/>
    <${Leg} items=${[["o", t("lp.other", { gb: gb(other) })], d.ollama > 0 && ["m", t("cf.ollama", { gb: gb(d.ollama) })], ["g", t("cf.comfy", { gb: gb(d.bytes.comfy) })],
      d.bytes.also > 0 && ["a", t("cf.also", { gb: gb(d.bytes.also) })], ["f", t("lp.of", { gb: gb(k.total) })]]}/>
    <div class=${"lp-note" + (over ? " warn" : "")}>${d.cap ? t(over ? "cf.models.over" : "cf.models", { a: gb(d.total), cap: gb(d.cap) }) : t("cf.models0", { a: gb(d.total) })}
      ${" " + t("cf.keep", { keep: gb(d.keep) })}</div>
  </div>`;
}

function CardBox({ d, busy, onFree, onOff }) {
  const g = d.gpu, c = d.comfy, min = Math.round((c.stop_after || 600) / 60), on = c.state === "running";
  return html`<div class="item static lp-card">
    ${g && html`<div class="lp-h"><b>${t("lp.card")}</b><span class="lp-big">${t("lp.used", { a: gib(g.used), b: gib(g.total) })}</span></div>
      <${Bar} whole=${g.total} parts=${[{ w: g.used, c: on ? "g" : "o" }]}/>`}
    <div class="lp-note">${t(on ? "cf.card.on" : "cf.card.off", { min })}</div>
    ${on && html`<div class="lp-acts">${c.loaded && html`<button class="btn ghost sm" disabled=${busy} onClick=${onFree}>${t("cf.free")}</button>`}
      <button class="btn ghost sm" disabled=${busy} onClick=${onOff}>${t("cf.off")}</button></div>`}
  </div>`;
}

// a set of the list: whole on the disk — its size and its star; not yet — what it would bring
function SetRow({ s, d, busy, onStar, onOpen }) {
  const main = d.main[s.kind] === s.id, part = !s.ready && s.files.some((f) => f.part > 0);
  const sub = s.ready ? [main && t("cf.main"), prm(s.params), steps(s) || langs(s), s.license]
    : part ? [t("cf.part", { a: gb(s.size - s.need), b: gb(s.size) })] : [does(s), prm(s.params), s.license];
  return html`<div class="lp-fam"><div class=${"lp-row head cf-row" + (s.ready ? " fit on" : "")}>
    <span class="cf-k">${ic(s.kind === "audio" ? "music" : "image", 18)}</span>
    <button class="lp-nm" onClick=${() => onOpen(s.id)}><b>${s.name}</b><span class="dim">${sub.filter(Boolean).join(" · ")}</span></button>
    <span class=${"lp-sz" + (s.ready ? "" : " dim")}>${s.ready ? gb(s.size) : "+" + gb(s.need)}</span>
    ${s.ready && html`<button class=${"mstar" + (main ? " on" : "")} aria-pressed=${main} aria-label=${t("cf.make.main")} disabled=${busy || main}
      onClick=${() => onStar(s.id)}>${ic("star", 18)}</button>`}
  </div></div>`;
}

// the trial on a set's card: its time while it goes, then the picture or the tune itself
function Trial({ s, tr, res }) {
  useNow(1000);
  if (!tr || tr.id !== s.id) return html`<div class="dim small cf-words">${t("cf.try.words." + s.kind)}</div>`;
  if (tr.run) {
    const secs = Math.max(0, Date.now() / 1000 - tr.since);
    return html`<div class="cf-trial"><div class="lp-note">${t("cf.trying", { t: mmss(secs) })}</div>
      ${secs < 75 && html`<div class="dim small">${t("cf.trying.cold")}</div>`}</div>`;
  }
  if (tr.err) return html`<div class="lp-note warn">${tr.err}</div>`;
  const facts = t("cf.tried", { secs: num(tr.secs, 1), seed: tr.seed }) + (tr.start ? t("cf.tried.start", { s: num(tr.start, 0) }) : "");
  return html`<div class="cf-trial">
    ${res && res.since === tr.since ? (s.kind === "audio" ? html`<audio class="cf-audio" controls src=${res.url}></audio>`
      : html`<img class="cf-pic" src=${res.url} alt=${t("cf.try.words.image")}/>`) : html`<${Loading}/>`}
    <div class="dim small">${facts}</div></div>`;
}

function SetSheet({ s, d, busy, res, onClose, onPull, onMain, onTry, onDelete }) {
  const main = d.main[s.kind] === s.id, tr = d.trial, trying = !!(tr && tr.run);
  const name = (id) => (d.sets.find((x) => x.id === id) || { name: id }).name;
  const lines = [[t("cf.kind." + s.kind), does(s), prm(s.params), steps(s), langs(s), s.license].filter(Boolean).join(" · ")];
  if (s.maker || s.released) lines.push(t("cf.made", { maker: s.maker || "", when: month(s.released) }).replace(/^ · | · $/g, ""));
  const shared = s.files.filter((f) => f.shared.length && (s.ready ? true : f.have));
  if (s.ready) lines.push(t("cf.have", { gb: gb(s.size) }));
  else {
    lines.push(t("cf.get", { gb: gb(s.need), files: parts(s.files.filter((f) => !f.have)).map(([w, b]) => w + " " + gb(b)).join(", ") }));
    if (s.files.some((f) => f.have)) lines.push(t("cf.get.have", { what: parts(s.files.filter((f) => f.have)).map(([w]) => w).join(", ") }));
  }
  for (const f of shared) lines.push(t("cf.shared", { names: f.shared.map(name).join(", "), what: t("cf.f." + f.folder) }));
  if (s.vram_gb) lines.push(d.gpu ? t(s.vram_gb * 1e9 <= d.gpu.total ? "cf.vram" : "cf.vram.no", { need: vramGb(s), card: gib(d.gpu.total) }) : t("cf.vram0", { need: vramGb(s) }));
  const r = s.room;
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick fixed lp-sheet cf-sheet">
    <div class="q-t pick-h">${s.name}<button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></div>
    ${lines.map((l, i) => html`<p class="sheet-p" key=${i}>${l}</p>`)}
    ${!s.tried && html`<p class="sheet-p dim">${ic("info", 14)} ${t("cf.untried")}</p>`}
    ${s.ready && main && html`<p class="sheet-p">${t("cf.is.main." + s.kind)}</p>`}
    ${s.ready ? html`<${Trial} s=${s} tr=${tr} res=${res}/>
      <div class="lp-acts">
        ${!main && html`<button class="btn ghost" disabled=${busy} onClick=${() => onMain(s.id)}>${ic("star", 14)} ${t("cf.make.main")}</button>`}
        <button class="btn" disabled=${busy || trying} onClick=${() => onTry(s.id)}>${ic(s.kind === "audio" ? "play" : "image", 14)} ${t("cf.try." + s.kind)}</button>
        <button class="btn ghost danger" disabled=${busy || trying} onClick=${() => onDelete(s)}>${t("cf.delete", { gb: gb(s.frees) })}</button>
      </div>`
    : html`<div class="lp-look">
      ${r && r.after != null && html`<div class=${r.disk_ok ? "" : "warn"}>${t(r.disk_ok ? "cf.after" : "cf.after.no", { gb: gb(Math.max(0, r.after)), keep: gb(r.keep) })}</div>`}
      ${r && r.cap && html`<div class=${r.cap_ok ? "" : "warn"}>${t(r.cap_ok ? "cf.cap" : "cf.cap.no", { a: gb(r.total), cap: gb(r.cap) })}</div>`}
      <button class="btn wide" disabled=${busy || !r || !r.ok || !!(d.pull && d.pull.run)} onClick=${() => onPull(s)}>${t("cf.go", { gb: gb(s.need) })}</button>
      <div class="dim small">${t("cf.pull.about")}</div></div>`}
  </div>`;
}

// the gateway's download: its progress while it goes, its end for a quarter of an hour after
function PullBox({ p, busy, onStop }) {
  useNow(5000);
  if (p.run) {
    const left = p.rate > 0 ? Math.round((p.total - p.done) / p.rate / 60) : null;
    return html`<div class="item static lp-card lp-pull">
      <div class="lp-h"><b>${p.name}</b><span class="lp-big">${Math.floor(pc(p.done, p.total))} %</span></div>
      <div class="lp-bar"><i class="g" style=${"width:" + pc(p.done, p.total) + "%"}></i></div>
      <div class="lp-note">${p.phase === "check" ? t("cf.pull.check") : [t("lp.pull.of", { a: gb(p.done), b: gb(p.total) }),
        p.rate > 0 && t("lp.pull.rate", { n: num(p.rate / 1e6, 0) }), left != null && t("lp.pull.eta", { n: Math.max(1, left) })].filter(Boolean).join(" · ")}</div>
      <div class="lp-acts"><button class="btn ghost sm" disabled=${busy} onClick=${onStop}>${t("lp.pull.stop")}</button></div></div>`;
  }
  if (!p.end || Date.now() / 1000 - p.end > 900) return "";
  return html`<div class=${"lp-note cf-end" + (p.err ? " warn" : p.stopped ? "" : " ok")}>${p.err ? t("lp.pull.err", { name: p.name, why: whyOf(p) })
    : p.stopped ? t("lp.pull.stopped", { name: p.name }) : t("cf.pull.done", { name: p.name })}</div>`;
}

function ComfyPanel({ embedded }) {
  const [d, err, set] = useLive(() => api("comfy_panel"), [], (m) => m.kind === "comfy", 15000);
  const [busy, setBusy] = useState("");
  const [sheet, setSheet] = useState(false);       // a set's card over the tab, through the history like any layer
  const [which, setWhich] = useState(null);
  const [openSheet, closeSheet] = useOverlay(sheet, setSheet);
  const [res, setRes] = useState(null);             // the last trial's file: {since, url}
  const tr = d && d.trial;
  useEffect(() => {
    if (!tr || tr.run || tr.err || !tr.end || (res && res.since === tr.since)) return;
    api("comfy_trial").then((x) => {
      const raw = atob(x.data), b = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) b[i] = raw.charCodeAt(i);
      setRes((was) => { if (was) URL.revokeObjectURL(was.url); return { since: x.trial.since, url: URL.createObjectURL(new Blob([b], { type: x.mime })) }; });
    }).catch(() => {});
  }, [tr && tr.since, tr && tr.end]);
  if (!d) return html`<${Loading} err=${err}/>`;
  const panel = (r) => { if (r && r.sets) set(r); };
  const act = async (k, fn) => { setBusy(k); try { const r = await fn(); panel(r); if (r && r.words) { haptic("success"); alertBox(r.words); } } catch (e) { alertBox(e.message); } setBusy(""); };
  const where = d.name || t("cf.server");
  if (d.down) {
    return html`<div class="lp cf">${!embedded && html`<h2>${t("res.gen")}</h2>`}
      <div class="vl-down">${ic("alert", 15)}<span>${d.down}</span></div>
      ${d.old && html`<div class="cf-how"><div class="small">${t("cf.old.how")}</div><pre class="cf-cmd">${t("cf.old.cmd")}</pre></div>`}
      <div class="vl-foot"><button class="link" disabled=${!!busy} onClick=${() => act("re", () => api("comfy_panel"))}>${t("cf.again")}</button>
        <${About} text=${t("cf.about")} label=${t("more")}/></div></div>`;
  }
  const c = d.comfy, st = d.job ? t("cf.state." + d.job.kind) : c.state === "running" ? t(c.loaded ? "cf.state.loaded" : "cf.state.on") : t("cf.state.off");
  const pull = (s) => { closeSheet(); act("pull", () => api("comfy_pull", { id: s.id, go: true })); };
  const stop = async () => { if (await confirmBox(t("lp.pull.stop.q", { name: d.pull.name }))) act("stop", () => api("comfy_pull_stop")); };
  const main = (id) => act("main", () => api("comfy_main", { id }));
  const tryIt = (id) => act("try", () => api("comfy_try", { id }));
  const del = async (s) => {
    if (!(await confirmBox(t(s.frees ? "cf.delete.q" : "cf.delete.q0", { name: s.name, gb: gb(s.frees), where })))) return;
    closeSheet();
    act("delete", () => api("comfy_remove", { id: s.id }));
  };
  const off = async () => { if (await confirmBox(t("cf.off.q"))) act("off", () => api("comfy_off")); };
  const cur = which && d.sets.find((s) => s.id === which);
  const other = tr && !sheet && tr.end && !tr.err && d.sets.find((s) => s.id === tr.id);
  return html`<div class="lp cf">${!embedded && html`<h2>${t("res.gen")}</h2>`}
    <div class="vl-srv lp-srv"><span class="vl-at">${[html`<b>${where}</b>`, c.version && "ComfyUI " + c.version, st].filter(Boolean)
      .reduce((a, x, i) => (i ? a.concat([" · ", x]) : [x]), [])}</span>
      <button class=${"vl-re" + (busy === "re" ? " spin" : "")} aria-label=${t("cf.again")} disabled=${!!busy}
        onClick=${() => act("re", () => api("comfy_panel"))}>${ic("auto", 17)}</button></div>
    <div class="list lp-cards">${d.disk && html`<${DiskBox} d=${d}/>`}
      <${CardBox} d=${d} busy=${!!busy} onFree=${() => act("free", () => api("comfy_free"))} onOff=${off}/></div>
    ${d.pull && html`<${PullBox} p=${d.pull} busy=${!!busy} onStop=${stop}/>`}
    ${KINDS.map((k) => { const ss = d.sets.filter((s) => s.kind === k); return ss.length > 0 && html`<h3 class="lp-mh" key=${k}>${t("cf.kind." + k)}</h3>
      <div class="lp-fams">${ss.map((s) => html`<${SetRow} key=${s.id} s=${s} d=${d} busy=${!!busy} onStar=${main} onOpen=${(x) => { setWhich(x); openSheet(); }}/>`)}</div>`; })}
    <div class="dim small lp-legend cf-legend">${t("cf.legend")}</div>
    ${other && html`<button class="link cf-last" onClick=${() => { setWhich(other.id); openSheet(); }}>${t("cf.tried.other", { name: other.name })}</button>`}
    <div class="vl-foot"><span></span><${About} text=${t("cf.about")} label=${t("more")}/></div>
    ${sheet && cur && html`<${SetSheet} s=${cur} d=${d} busy=${!!busy} res=${res} onClose=${closeSheet} onPull=${pull} onMain=${main} onTry=${tryIt} onDelete=${del}/>`}
  </div>`;
}

// Home's line while the gateway downloads, as the local model's: under the strip while it runs, its end for a
// quarter of an hour after; a tap — the tab
function GenRow({ p }) {
  useNow(5000);
  if (!p || p.stopped || !(p.run || (p.end && Date.now() / 1000 - p.end < 900))) return "";
  const pct = Math.floor(pc(p.done, p.total)), left = p.rate > 0 ? Math.round((p.total - p.done) / p.rate / 60) : null;
  const sub = p.run ? (p.phase === "check" ? t("cf.pull.check") : [t("lp.pull.of", { a: gb(p.done), b: gb(p.total) }), p.rate > 0 && t("lp.pull.rate", { n: num(p.rate / 1e6, 0) }),
    left != null && t("lp.pull.eta", { n: Math.max(1, left) })].filter(Boolean).join(" · ")) : p.err ? whyOf(p) : t("cf.home.next");
  return html`<button class=${"card upd-row lp-home" + (p.err ? " attn" : "")} onClick=${() => go("#/comfy")}><span class="upd-ic">${ic(p.run ? "server" : p.err ? "alert" : "check", 17)}</span>
    <span class="upd-t"><b>${t(p.run ? "lp.home.run" : p.err ? "lp.home.fail" : "cf.home.done", { name: p.name, pct })}</b><span class="dim">${sub}</span>
      ${p.run && html`<span class="lp-bar thin"><i class="g" style=${"width:" + pc(p.done, p.total) + "%"}></i></span>`}</span>${ic("chev", 16)}</button>`;
}

export { ComfyPanel, GenRow };
