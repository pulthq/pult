// Pult app — one's own model's panel (stage M, step 6.4; the owner, 2026-11-08: "how much room is left on the server, how
// much each model takes — a tab"): Resources → Local model, and Settings' card opens it on its own. The server's disk and
// card as the reader beside Ollama sees them, its models by their weights — a base and the copies made from it hold the
// weights once, so a family is one size — which ones take tasks (the tick and the star, as Settings had them), which one
// is in the card's memory, and a download from ollama.com with its progress. The computer asks the server; this only draws.
import { api, useLive } from "../core/conn.js";
import { go, useKept, useOverlay } from "../core/nav.js";
import { alertBox, confirmBox, haptic, tick } from "../core/tg.js";
import { locale, t } from "../i18n.js";
import { html, useState } from "../vendor/htm-preact-3.1.1.js";
import { About, GEAR, Loading, hhmm, ic, num, plainField, toDate, useNow } from "../ui/kit.js";

// bytes on the disk as Ollama writes them (ollama list) and the disk is sold — decimal gigabytes, terabytes past a
// thousand; the card's memory as the card is sold and nvidia-smi counts it — binary ("16 GB" is 16 376 MiB)
const gb = (b, round) => (b >= 1e12 ? t("tb", { n: num(b / 1e12, 1) }) : t("gb", { n: num(b / 1e9, round || b >= 1e11 ? 0 : 1) })).replace(/ /g, "\u00a0");
const gib = (b) => t("gb", { n: num(b / 1073741824, b >= 10 * 1073741824 ? 0 : 1) }).replace(/ /g, "\u00a0");
const ctxK = (n) => t("kilo.k", { n: Math.round(n / 1024) });
const prm = (s) => { const m = /^([\d.]+)\s*B$/i.exec(s || ""); return m ? t("vend.list.bn", { n: num(+m[1], 1) }) : s || ""; };
const pc = (a, b) => (b > 0 ? Math.max(0, Math.min(100, (a * 100) / b)) : 0);
const untilHm = (s) => { const d = new Date(s); return isNaN(d) ? "" : d.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" }); };

// a bar of parts: [{w: bytes, c: class}] over the whole; a part too thin to see still shows as a sliver
function Bar({ parts, whole }) {
  return html`<div class="lp-bar">${parts.filter((p) => p.w > 0).map((p, i) => html`<i key=${i} class=${p.c} style=${"width:" + Math.max(pc(p.w, whole), 0.8) + "%"}></i>`)}</div>`;
}
const Leg = ({ items }) => html`<div class="lp-lg">${items.filter(Boolean).map(([c, text], i) => html`<span key=${i}><i class=${c}></i>${text}</span>`)}</div>`;

function Disk({ d }) {
  const k = d.disk, other = k.total - k.free - Math.min(d.total, k.total - k.free), left = k.free - d.reserve;
  return html`<div class="item static lp-card">
    <div class="lp-h"><b>${t("lp.disk", { label: k.label || "" }).trim()}</b><span class="lp-big">${t("lp.free", { gb: gb(k.free) })}</span></div>
    <${Bar} whole=${k.total} parts=${[{ w: other, c: "o" }, { w: d.total, c: "m" }]}/>
    <${Leg} items=${[["o", t("lp.other", { gb: gb(other) })], ["m", t("lp.models", { gb: gb(d.total) })], ["f", t("lp.of", { gb: gb(k.total) })]]}/>
    <div class=${"lp-note" + (left > 0 ? "" : " warn")}>${left > 0 ? t("lp.room", { gb: gb(left, true), keep: gb(d.reserve) }) : t("lp.noroom", { keep: gb(d.reserve) })}</div>
  </div>`;
}

function Card({ d, onUnload, busy }) {
  const g = d.gpu, m = d.mem[0];
  const base = g.base != null && g.base <= g.used ? g.base : null;
  const ours = m ? (base != null ? g.used - base : null) : 0;
  const parts = m && ours != null ? [{ w: base, c: "o" }, { w: ours, c: "m" }] : [{ w: g.used, c: m ? "m" : "o" }];
  return html`<div class="item static lp-card">
    <div class="lp-h"><b>${t("lp.card")}</b><span class="lp-big">${t("lp.used", { a: gib(g.used), b: gib(g.total) })}</span></div>
    <${Bar} whole=${g.total} parts=${parts}/>
    <${Leg} items=${m && ours != null ? [["o", t("lp.others", { gb: gib(base) })], ["m", m.name + " ≈\u00a0" + gib(ours)], ["f", t("lp.left", { gb: gib(g.total - g.used) })]]
      : [["o", t(m ? "lp.taken" : "lp.others", { gb: gib(g.used) })], ["f", t("lp.left", { gb: gib(g.total - g.used) })]]}/>
    ${m ? html`<div class="lp-mem"><span>${ic("clock", 15)}${t("lp.inmem", { name: m.name, hm: untilHm(m.until) })}</span>
        <button class="btn ghost sm" disabled=${busy} onClick=${() => onUnload(m.name)}>${t("lp.unload")}</button></div>`
      : html`<div class="lp-note">${t("lp.nomem")}</div>`}
  </div>`;
}

// a model of the server: its name and what is known of it; one that can take a task has its tick and its star
function Row({ name, r, d, head, mem, busy, onTick, onStar, onOpen }) {
  const on = d.models.includes(name), star = on && d.models[0] === name, kin = d.kin[name] || {};
  const sub = [r.ctx ? ctxK(r.ctx) : r.tools ? t("vend.local.noctx") : t("vend.local.notools"),
    head ? prm(r.params) : kin.from ? t("lp.same") : prm(r.params)].filter(Boolean).join(" · ");
  return html`<div class=${"lp-row" + (head ? " head" : " kid") + (r.fit ? " fit" : "") + (on ? " on" : "")}>
    ${r.fit ? html`<button class="lp-box" role="checkbox" aria-checked=${on} aria-label=${name} disabled=${busy} onClick=${() => onTick(name)}>${on ? ic("check", 15) : ""}</button>`
      : html`<span class="lp-nobox"></span>`}
    <button class="lp-nm" onClick=${() => onOpen(name)}><b>${name}</b><span class="dim">${sub}${mem ? html` · <em class="lp-in">${t("lp.inmem.short")}</em>` : ""}</span></button>
    ${head ? html`<span class="lp-sz">${gb(r.size || 0)}</span>` : html`<span class="lp-sz dim">${t("lp.plus0")}</span>`}
    ${on ? html`<button class=${"mstar" + (star ? " on" : "")} aria-pressed=${star} aria-label=${t("vend.list.main")} disabled=${busy || star} onClick=${() => onStar(name)}>${ic("star", 18)}</button>` : ""}
  </div>`;
}

// a model's sheet: its facts, what its removal gives back, and what can be done with it
function ModelSheet({ name, d, busy, onClose, onUnload, onDelete, onCopy, onSettings }) {
  const r = d.rows[name], kin = d.kin[name] || {}, mem = d.mem.some((m) => m.name === name);
  const fam = d.fams.find((f) => f.head === name || f.rest.includes(name)) || { head: name, rest: [] };
  const mates = [fam.head].concat(fam.rest).filter((n) => n !== name);
  const can = !r.fit && r.tools && !kin.copy && (!r.max || r.max >= d.min);
  const lines = [[gb(r.size || 0), prm(r.params), r.ctx ? t("lp.ctx", { ctx: ctxK(r.ctx) }) : t("vend.local.noctx")].filter(Boolean).join(" · "),
    mates.length ? t("lp.shared", { names: mates.join(", ") }) : t("lp.alone", { gb: gb(r.size || 0) }),
    r.fit ? (d.models.includes(name) ? (d.models[0] === name ? t("lp.is.main") : t("lp.is.in")) : t("lp.is.off")) : kin.copy ? t("lp.copyis", { m: kin.copy }) : ""];
  return html`<div class="backdrop" onClick=${onClose}></div><div class="card pick fixed lp-sheet">
    <div class="q-t pick-h">${name}<button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></div>
    ${lines.filter(Boolean).map((l, i) => html`<p class="sheet-p" key=${i}>${l}</p>`)}
    <button class="field lm-in" onClick=${() => onSettings(name)}><span class="lm-in-t">${GEAR}<b>${t("lm.in")}</b>
      <i class="dim vf-sub">${t("lm.in.sub")}</i></span><span class="dim">${ic("chev", 18)}</span></button>
    <div class="lp-acts">
      ${mem && html`<button class="btn ghost" disabled=${busy} onClick=${() => onUnload(name)}>${t("lp.unload.long")}</button>`}
      ${can && html`<button class="btn ghost" disabled=${busy} onClick=${() => onCopy(name)}>${ic("plus", 14)} ${t("vend.list.make", { ctx: ctxK(Math.min(d.copy, r.max || d.copy)) })}</button>`}
      <button class="btn ghost danger" disabled=${busy} onClick=${() => onDelete(name)}>${t("lp.delete", { gb: gb(r.frees) })}</button>
    </div></div>`;
}

// a download from ollama.com: the name, the look first — its size, the room after it, the card it needs — then the
// download, which the server does itself; its progress comes with the panel
function Pull({ d, busy, setBusy, onPanel }) {
  const [name, setName] = useState("");
  const [look, setLook] = useState(null);
  useNow(5000);
  const p = d.pull;
  const ask = async (go) => {
    if (go && look.after == null && !(await confirmBox(t("lp.pull.blind.q", { name: look.model, gb: gb(look.size) })))) return;
    setBusy("pull");
    try {
      const r = await api("local_pull", { model: (go ? look.model : name).trim(), go });
      if (go) { setLook(null); setName(""); haptic("success"); onPanel(); } else setLook(r.look);
    } catch (e) { alertBox(e.message); }
    setBusy("");
  };
  const stop = async () => { if (await confirmBox(t("lp.pull.stop.q", { name: p.model }))) { try { onPanel(await api("local_pull_stop")); } catch (e) { alertBox(e.message); } } };
  if (p && p.run) {
    const left = p.rate > 0 ? Math.round((p.total - p.done) / p.rate / 60) : null;
    return html`<div class="item static lp-card lp-pull">
      <div class="lp-h"><b>${p.model}</b><span class="lp-big">${Math.floor(pc(p.done, p.total))}\u00a0%</span></div>
      <div class="lp-bar"><i class="m" style=${"width:" + pc(p.done, p.total) + "%"}></i></div>
      <div class="lp-note">${[t("lp.pull.of", { a: gb(p.done), b: gb(p.total) }), p.rate > 0 && t("lp.pull.rate", { n: num(p.rate / 1e6, 0) }),
        left != null && t("lp.pull.eta", { n: Math.max(1, left) })].filter(Boolean).join(" · ")}</div>
      <div class="lp-acts"><button class="btn ghost sm" onClick=${stop}>${t("lp.pull.stop")}</button></div></div>`;
  }
  return html`<div class="item static lp-card">
    ${p && p.end && html`<div class=${"lp-note" + (p.err ? " warn" : p.stopped ? "" : " ok")}>${p.err ? t("lp.pull.err", { name: p.model, why: p.err })
      : p.stopped ? t("lp.pull.stopped", { name: p.model }) : t("lp.pull.done", { name: p.model })}</div>`}
    <div class="keyrow"><input ref=${plainField} placeholder=${t("lp.pull.ph")} value=${name} onInput=${(e) => { setName(e.target.value); setLook(null); }}/>
      <button class="btn" disabled=${!name.trim() || !!busy} onClick=${() => ask(false)}>${busy === "pull" && !look ? t("lp.pull.looking") : t("lp.pull.look")}</button></div>
    ${look && html`<div class="lp-look">
      <div><b>${look.model}</b> — ${gb(look.size)}</div>
      ${look.after != null ? html`<div class=${look.ok ? "" : "warn"}>${t(look.ok ? "lp.pull.after" : "lp.pull.after.no", { gb: gb(Math.max(0, look.after)), keep: gb(look.reserve) })}</div>`
        : html`<div class="warn">${t("lp.pull.blind")}</div>`}
      ${look.card && html`<div class=${look.need <= look.card ? "" : "warn"}>${t(look.need <= look.card ? "lp.pull.fits" : "lp.pull.nofit", { need: gib(look.need), card: gib(look.card) })}</div>`}
      <button class="btn wide" disabled=${!look.ok || !!busy} onClick=${() => ask(true)}>${t("lp.pull.go", { gb: gb(look.size) })}</button></div>`}
    <div class="dim small">${t("lp.pull.about")}</div></div>`;
}

function LocalPanel({ embedded }) {
  const [d, err, set] = useLive(() => api("local_panel"), [], (m) => m.kind === "local", 15000);
  const [busy, setBusy] = useState("");
  const [sheet, setSheet] = useState(false);       // a model's sheet over the panel, through the history like any layer
  const [which, setWhich] = useState(null);
  const [openSheet, closeSheet] = useOverlay(sheet, setSheet);
  const [url, setUrl] = useState(null);             // null — as saved; a string — the address being changed
  if (!d) return html`<${Loading} err=${err}/>`;
  if (!d.on && !d.fams.length) return html`<div>${!embedded && html`<h2>${t("res.llm")}</h2>`}<div class="empty">${t("lp.off")}</div>
    <a class="btn ghost wide" href="#/settings/models">${t("lp.off.go")}</a></div>`;
  const panel = (r) => { if (r && r.fams) set(r); };
  const act = async (k, fn) => { setBusy(k); try { const r = await fn(); panel(r); if (r && r.words) { haptic("success"); alertBox(r.words); } } catch (e) { alertBox(e.message); } setBusy(""); };
  const unload = (name) => act("unload", () => api("local_unload", { model: name }));
  const del = async (name) => {
    const r = d.rows[name];
    if (!(await confirmBox(t(r.frees ? "lp.delete.q" : "lp.delete.q0", { name, gb: gb(r.frees), from: d.name ? t("lp.from", { name: d.name }) : t("lp.from0") })))) return;
    closeSheet();
    act("delete", () => api("local_delete", { model: name }));
  };
  // the sheet's step in the history goes first, then the settings take a step of their own: Back from them — the panel
  const settings = (name) => { addEventListener("popstate", () => setTimeout(() => go("#/lm/" + encodeURIComponent(name)), 0), { once: true }); closeSheet(); };
  const copy = (name) => { closeSheet(); act("copy", async () => { const r = await api("vendor_copy", { model: name }); return Object.assign(await api("local_panel"), { words: r.words }); }); };
  const saveTicks = async (models) => {
    const was = d.models;
    set(Object.assign({}, d, { models }));
    try { await api("vendor_models", { vendor: "local", models: models.join(", ") }); tick(); } catch (e) { set(Object.assign({}, d, { models: was })); alertBox(e.message); }
  };
  const onTick = (n) => {
    const on = d.models.includes(n);
    if (on && d.models.length === 1) { alertBox(t("vend.list.one.local")); return; }
    saveTicks(on ? d.models.filter((m) => m !== n) : d.models.concat([n]));
  };
  const onStar = (n) => saveTicks([n].concat(d.models.filter((m) => m !== n)));
  const inMem = new Set(d.mem.map((m) => m.name));
  const canCopy = (n) => { const r = d.rows[n], k = d.kin[n] || {}; return r && !r.fit && r.tools && !k.copy && (!r.max || r.max >= d.min); };
  const where = d.name || t("lp.server"), on = d.name ? t("lp.on", { name: d.name }) : t("lp.on0");
  return html`<div class="lp">${!embedded && html`<h2>${t("res.llm")}</h2>`}
    ${url != null ? html`<div class="dim vend-m">${t("vend.local.url")}</div>
      <div class="keyrow wrap"><input ref=${plainField} inputmode="url" value=${url} data-saved=${d.url} onInput=${(e) => setUrl(e.target.value)}/>
        <button class="btn" disabled=${!url.trim() || !!busy} onClick=${() => act("re", async () => { const r = await api("vendor_local", { url: url.trim() }); setUrl(null);
          return Object.assign(await api("local_panel"), { words: r.words }); })}>${t("vend.local.again")}</button></div>`
    : html`<div class="vl-srv lp-srv"><button class="vl-at" onClick=${() => setUrl(d.url)}>${[html`<b>${where}</b>`, d.version && "Ollama " + d.version,
      d.at && t("vend.list.at", { hm: hhmm(toDate(d.at)) })].filter(Boolean).reduce((a, x, i) => (i ? a.concat([" · ", x]) : [x]), [])}</button>
      <button class=${"vl-re" + (busy === "re" ? " spin" : "")} aria-label=${t("vend.local.again")} disabled=${!!busy}
        onClick=${() => act("re", async () => { await api("vendor_local", {}); return api("local_panel"); })}>${ic("auto", 17)}</button></div>`}
    ${!d.on && html`<div class="vl-down">${ic("info", 15)}<span>${t("lp.offnote")}</span></div>`}
    ${d.down && html`<div class="vl-down">${ic("alert", 15)}<span>${d.down}</span></div>`}
    ${d.info ? html`<div class="list lp-cards">${d.disk && html`<${Disk} d=${d}/>`}${d.gpu && html`<${Card} d=${d} busy=${!!busy} onUnload=${unload}/>`}</div>`
      : !d.down && html`<div class="lp-noinfo">${ic("info", 15)}<span>${t("lp.noinfo", { on })}</span></div>`}
    <h3 class="lp-mh">${t("lp.list", { on })}<span>${gb(d.total)}</span></h3>
    <div class="dim small lp-legend">${t("lp.legend")}</div>
    <div class="lp-fams">${d.fams.map((f) => html`<div class="lp-fam" key=${f.head}>
      ${[f.head].concat(f.rest).map((n, i) => html`<${Row} key=${n} name=${n} r=${d.rows[n]} d=${d} head=${i === 0} mem=${inMem.has(n)} busy=${!!busy}
        onTick=${onTick} onStar=${onStar} onOpen=${(x) => { setWhich(x); openSheet(); }}/>`)}
      ${!f.rest.length && canCopy(f.head) && html`<div class="lp-row kid lp-mk"><button class="mmake" disabled=${!!busy} onClick=${() => copy(f.head)}>${ic("plus", 14)}
        ${busy === "copy" ? t("vend.list.making") : t("vend.list.make", { ctx: ctxK(Math.min(d.copy, d.rows[f.head].max || d.copy)) })}</button></div>`}
</div>`)}</div>
    <h3>${t("lp.pull")}</h3>
    <${Pull} d=${d} busy=${busy} setBusy=${setBusy} onPanel=${(r) => (r ? panel(r) : api("local_panel").then(panel).catch(() => {}))}/>
    <div class="vl-foot">${d.on ? html`<button class="link" disabled=${!!busy} onClick=${() => act("off", async () => { const r = await api("vendor_local", { on: false });
        return Object.assign(await api("local_panel"), { words: r.words }); })}>${t("vend.local.turnoff")}</button>` : html`<span></span>`}
      <${About} text=${t("lp.about")} label=${t("more")}/></div>
    ${sheet && which && d.rows[which] && html`<${ModelSheet} name=${which} d=${d} busy=${!!busy} onClose=${closeSheet} onUnload=${(n) => { closeSheet(); unload(n); }}
      onDelete=${del} onCopy=${copy} onSettings=${settings}/>`}
  </div>`;
}

// a model's settings (stage M, step 6.5; the owner, 2026-11-08: "the system settings of each model separately" — lesson 6
// of his own course: the system prompt, the temperature, the context length, through the Modelfile): what the server has
// in the model, changed here and written into the model itself — the first change keeps it as it was, to come back to —
// and what Pult does with it in a task. Each context it can take says how much of the card it would want.
const FINE = ["top_k", "top_p", "min_p", "repeat_penalty", "presence_penalty"];
const OWN = ["system", "ctx", "tools", "after"];

function LocalModel({ name }) {
  const [d, err, set] = useLive(() => api("local_model", { model: name }), [name]);
  // the owner's changes, not saved yet — kept by the model for this window's life: Back, or a look at another screen,
  // dropped them without a word (review 2026-11-11, UX25); the button still says how many wait to be saved
  const [ed, setEd] = useKept("lm.ed:" + name, {});
  const [busy, setBusy] = useState("");
  const [fine, setFine] = useState(false);
  if (!d) return html`<${Loading} err=${err}/>`;
  const was = (k) => (OWN.includes(k) ? d[k] : d.params[k].v);
  const v = (k) => (k in ed ? ed[k] : was(k));
  const put = (k, x) => setEd(Object.assign({}, ed, { [k]: x }, k === "ctx" && x < d.all_ctx && d.tools === "all" ? { tools: "five" } : {}));
  const dirty = Object.keys(ed).filter((k) => ed[k] !== was(k) && !(typeof ed[k] === "number" && isNaN(ed[k])));
  const call = async (k, fn) => {
    setBusy(k);
    try { const r = await fn(); set(r); setEd({}); haptic("success"); if (r.words) alertBox(r.words); } catch (e) { alertBox(e.message); }
    setBusy("");
  };
  const save = () => call("save", () => {
    const args = { model: name }, params = {};
    for (const k of dirty) { if (OWN.includes(k)) args[k] = ed[k]; else params[k] = ed[k]; }
    if (Object.keys(params).length) args.params = params;
    return api("local_tune", args);
  });
  const undo = async () => { if (await confirmBox(t("lm.was.q", { name }))) call("was", () => api("local_untune", { model: name })); };
  const sys = v("system"), ctx = v("ctx"), temp = v("temperature");
  const pick = d.ctxs.find((c) => c.n === ctx), over = pick && d.room != null && pick.vram > d.room;
  // all of Claude Code's tools only with a context that takes their descriptions (~22K tokens): a shorter one — the five
  const allNo = (ctx || 0) < d.all_ctx;
  const tools = allNo ? "five" : v("tools");
  const seg = (k, opts, cur, off) => html`<div class="seg">${opts.map((o) => html`<button key=${o} class=${cur === o ? "on" : ""} disabled=${!!busy || (off && o === "all")}
    onClick=${() => put(k, o)}>${t("lm." + k + "." + o)}</button>`)}</div>
    <div class="dim small lm-note">${off ? t("lm.tools.allno", { ctx: ctxK(d.all_ctx) }) : t("lm." + k + "." + cur + ".about")}</div>`;
  return html`<div class="lm">
    <h2 class="lm-t">${name}</h2>
    <div class="dim lm-sub">${[d.where ? t("lp.on", { name: d.where }) : t("lp.on0"), d.size && gb(d.size), prm(d.params_n)].filter(Boolean).join(" · ")}</div>
    ${!d.tools_ok && html`<div class="vl-down">${ic("info", 15)}<span>${t("lm.notools")}</span></div>`}
    <h3>${t("lm.system")}</h3>
    <textarea class="lm-sys" rows="6" maxlength=${d.sysmax} placeholder=${t("lm.system.ph")} value=${sys} disabled=${!!busy}
      onInput=${(e) => put("system", e.target.value)}></textarea>
    <div class="dim small lm-cnt"><span>${t("lm.system.about")}</span><span class="lm-n">${sys.length}\u00a0/\u00a0${d.sysmax}</span></div>
    <h3>${t("lm.ctx")}</h3>
    <div class="lm-ctxs">${d.ctxs.map((c) => html`<button key=${c.n} class=${"lm-ctx" + (c.n === ctx ? " on" : "") + (d.room != null && c.vram > d.room ? " over" : "")}
      disabled=${d.busy || !!busy} onClick=${() => put("ctx", c.n)}><b>${ctxK(c.n)}</b><span>${c.vram ? "≈\u00a0" + gib(c.vram) : ""}</span></button>`)}</div>
    <div class=${"small lm-note" + (d.busy ? " ps-busy" : over ? " warn" : " dim")}>${d.busy ? t("lm.ctx.busy") : over ? t("lm.ctx.over", { room: gib(d.room) })
      : ctx ? t(d.room != null ? "lm.ctx.about" : "lm.ctx.about0", { room: gib(d.room || 0) }) : t("lm.ctx.none")}</div>
    <h3 class="lm-h">${t("lm.temp")}<span class="lm-val">${num(temp, 2)}</span></h3>
    <input class="lm-range" type="range" min="0" max="2" step="0.05" value=${temp} disabled=${!!busy} aria-label=${t("lm.temp")}
      style=${"--p:" + pc(temp, 2) + "%"} onInput=${(e) => put("temperature", +e.target.value)}/>
    <div class="lm-scale dim small"><span>${t("lm.temp.lo")}</span><span>${t("lm.temp.mid")}</span><span>${t("lm.temp.hi")}</span></div>
    <button class=${"lm-fine-h" + (fine ? " open" : "")} onClick=${() => setFine(!fine)}><span><b>${t("lm.fine")}</b>
      ${!fine && html`<i class="dim">${FINE.map((k) => k + " " + num(v(k), 2)).join(" · ")}</i>`}</span><span class="lm-chev">${ic("chev", 16)}</span></button>
    ${fine && html`<div class="list lm-fine">${FINE.map((k) => html`<label class=${"item static lm-p" + (d.params[k].set || k in ed ? "" : " def")} key=${k}>
      <span><b>${k}</b><i class="dim">${t("lm.p." + k)}</i></span>
      <input inputmode="decimal" value=${String(num(v(k), 3)).replace(/\u00a0/g, "")} disabled=${!!busy}
        onChange=${(e) => put(k, parseFloat(e.target.value.replace(",", ".")))}/></label>`)}</div>`}
    <h3>${t("lm.pult")}</h3>
    <div class="lm-l">${t("lm.tools")}</div>
    ${seg("tools", ["five", "all"], tools, allNo)}
    <div class="lm-l">${t("lm.after")}</div>
    ${seg("after", ["keep", "free"], v("after"), false)}
    <button class="btn wide lm-save" disabled=${!dirty.length || !!busy} onClick=${save}>${busy === "save" ? t("lm.saving") : dirty.length ? t("lm.save.n", { n: dirty.length }) : t("lm.save")}</button>
    <div class="dim small lm-where">${t("lm.where", { on: d.where ? t("lp.on", { name: d.where }) : t("lp.on0") })}</div>
    ${d.was && html`<button class="link lm-was" disabled=${!!busy} onClick=${undo}>${ic("back", 14)} ${t("lm.was")}</button>`}
  </div>`;
}

// Home's line while a model downloads (the owner, 2026-11-08: "and its progress shown in Pult"): under the strip while
// it runs, and its end for a quarter of an hour after; a tap — the panel
function PullRow({ p }) {
  useNow(5000);
  if (!p || p.stopped || !(p.run || (p.end && Date.now() / 1000 - p.end < 900))) return "";
  const pct = Math.floor(pc(p.done, p.total)), left = p.rate > 0 ? Math.round((p.total - p.done) / p.rate / 60) : null;
  const sub = p.run ? [t("lp.pull.of", { a: gb(p.done), b: gb(p.total) }), p.rate > 0 && t("lp.pull.rate", { n: num(p.rate / 1e6, 0) }),
    left != null && t("lp.pull.eta", { n: Math.max(1, left) })].filter(Boolean).join(" · ") : p.err ? p.err : t("lp.home.next");
  return html`<button class=${"card upd-row lp-home" + (p.err ? " attn" : "")} onClick=${() => go("#/local")}><span class="upd-ic">${ic(p.run ? "server" : p.err ? "alert" : "check", 17)}</span>
    <span class="upd-t"><b>${t(p.run ? "lp.home.run" : p.err ? "lp.home.fail" : "lp.home.done", { name: p.model, pct })}</b><span class="dim">${sub}</span>
      ${p.run && html`<span class="lp-bar thin"><i class="m" style=${"width:" + pc(p.done, p.total) + "%"}></i></span>`}</span>${ic("chev", 16)}</button>`;
}

export { LocalModel, LocalPanel, PullRow };
