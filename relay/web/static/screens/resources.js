// Pult app — Resources: the plan's limits and how they are spent; usage; today.
// Moved from app.js as it was (review 2026-10-27, 6.4).
import { api, useLive } from "../core/conn.js";
import { alertBox, haptic } from "../core/tg.js";
import { plural, t } from "../i18n.js";
import { html, useEffect, useRef, useState } from "../vendor/htm-preact-3.1.1.js";
import { About, Loading, ago, dur, hhmm, hue, kilo, level, nb, num, pct, resetText, toDate, useNow } from "../ui/kit.js";
import { Load } from "../ui/load.js";


// ---------- Resources: how the plan's limits are spent (stage R) ----------
// For each limit: the curve from its start to its reset against the even pace, the forecast at the current pace, how
// many sessions worked at once, what spent it. The computer counts (pult_spend.py), the app only draws — SVG by hand,
// no chart library. The data is the only loud thing: thin marks, hairline grid; red only when a limit runs out early.

// hours of one session's work, as precise as it is worth: 35 h · 5.9 h · 25 min
const shours = (h) => nb(h >= 10 ? t("dur.h", { n: Math.round(h) }) : h >= 1 ? t("dur.h", { n: num(h, 1) }) : t("dur.m", { n: Math.max(5, Math.round(h * 12) * 5) }));
const sameDay = (a, b) => a.toDateString() === b.toDateString();
const spWhen = (ts) => { const d = toDate(ts); return (sameDay(d, new Date()) ? "" : t("weekdays").split(" ")[d.getDay()] + " ") + hhmm(d); };
const durLong = (sec) => (sec >= 86400 ? t("dur.d", { n: Math.floor(sec / 86400) }) + (Math.floor(sec % 86400 / 3600) ? " " + t("dur.h", { n: Math.floor(sec % 86400 / 3600) }) : "") : dur(sec));
// a project in the spend: its own colour (the tile's); the rest, grouped, grey
const spColor = (p) => (!p || p.color == null ? "var(--c0)" : hue(p.name));

function verdict(L) {
  const left = Math.max(0, L.t1 - L.now);
  if (L.used >= 100) return [t("sp.out", { left: durLong(left) })];
  if (L.state === "none") return [t("sp.none")];
  if (L.state === "over") {
    const slow = (100 - L.used) / Math.max(1e-9, L.rate * left / 3600);
    return [t("sp.over.v", { left: durLong(left), hit: spWhen(L.hit), gap: durLong(L.t1 - L.hit) }),
      t(slow > 0.66 ? "sp.slow.3" : slow > 0.4 ? "sp.slow.2" : "sp.slow.1")];
  }
  const out = [t("sp.at", { left: durLong(left), proj: "~" + pct(L.proj) })];
  let s = t(L.state === "under" ? "sp.burn" : "sp.free", { spare: "~" + pct(L.spare) });
  if (L.sh_left != null) s += t("sp.sh", { sh: shours(L.sh_left) });
  if (L.par != null && L.par >= 1) {
    const n = Math.round(L.par);
    s += t("sp.par", { n, sessions: plural(n, "session"), hm: hhmm(toDate(L.t1)) });
  }
  out.push(s + ".");
  if (L.tighter) out.push(t("sp.tighter", { sh: L.tighter.sh != null ? shours(L.tighter.sh) : "—" }));
  return out;
}

function PaceChart({ L }) {
  const box = useRef(null);
  const [w, setW] = useState(0);
  const [hx, setHx] = useState(null);
  useEffect(() => {
    const el = box.current;
    const fit = () => setW(el.clientWidth);
    fit();
    const ro = window.ResizeObserver ? new ResizeObserver(fit) : null;
    if (ro) ro.observe(el); else window.addEventListener("resize", fit);
    const away = (e) => { if (!el.contains(e.target)) setHx(null); };       // a tap elsewhere hides the readout
    document.addEventListener("pointerdown", away);
    return () => { if (ro) ro.disconnect(); else window.removeEventListener("resize", fit); document.removeEventListener("pointerdown", away); };
  }, []);
  useEffect(() => setHx(null), [L.key]);
  if (!w) return html`<div class="chart" ref=${box}></div>`;
  const W = w, PT = 16, PH = 150, ST = PT + PH + 20, SH = 38, XB = ST + SH + 16, HT = XB + 4;
  const X = (ts) => (ts - L.t0) / (L.t1 - L.t0) * W, Y = (p) => PT + (1 - Math.min(p, 100) / 100) * PH;
  let c = 0;
  const cums = L.bars.map((b) => (c += b[0]));
  const end = (i) => Math.min(L.t0 + (i + 1) * L.step, L.now);
  const pts = [[0, Y(0)]].concat(cums.map((v, i) => [X(end(i)), Y(v)]));
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join("");
  // the axis: days for the week, hours for the window
  const ticks = [], d = toDate(L.t0);
  if (L.key === "week") { d.setHours(24, 0, 0, 0); for (; d / 1000 < L.t1; d.setDate(d.getDate() + 1)) ticks.push(d / 1000); }
  else { d.setMinutes(60, 0, 0); for (; d / 1000 < L.t1; d.setHours(d.getHours() + 1)) ticks.push(d / 1000); }
  const marks = [L.t0].concat(ticks, [L.t1]);
  const labels = L.key === "week"
    ? marks.slice(0, -1).map((a, i) => [(X(a) + X(marks[i + 1])) / 2, X(marks[i + 1]) - X(a) > 22 ? t("weekdays").split(" ")[toDate(a + 60).getDay()] : ""])
    : ticks.map((a) => [X(a), hhmm(toDate(a))]);
  const ink = { "text-anchor": "end", class: "ink" };
  const hitX = L.hit ? X(L.hit) : null, endP = L.proj == null ? null : L.hit ? 100 : L.proj;
  const short = W - X(L.now) < 70;                                  // a short forecast: one label "82 % → ~88 %"
  const nBars = Math.round((L.t1 - L.t0) / L.step), bw = W / nBars, gap = bw >= 4 ? 1 : 0;
  const maxN = Math.max(4, ...L.bars.map((b) => b[1] + b[2]));
  // the readout under the finger: the bar's spend, sessions at once and projects; past now — the forecast
  let tip = null, cx = 0, cy = 0;
  if (hx != null) {
    const at = L.t0 + hx / W * (L.t1 - L.t0);
    if (at < L.now && L.bars.length) {
      const i = Math.min(Math.floor((at - L.t0) / L.step), L.bars.length - 1), b = L.bars[i], s = L.t0 + i * L.step;
      cx = X(Math.min(s + L.step / 2, L.now)); cy = Y(cums[i]);
      tip = html`<div class="dim">${(L.key === "week" ? t("weekdays").split(" ")[toDate(s + 60).getDay()] + " " : "") + hhmm(toDate(s))}–${hhmm(toDate(end(i)))}</div>
        <div class="v">${t("sp.tip.spent", { d: "+" + pct(b[0]), c: pct(cums[i]) })}</div>
        <div>${b[1] || b[2] ? t("sp.tip.at", { who: (b[1] ? t("sp.tip.n", { n: b[1], sessions: plural(b[1], "session") }) : "")
          + (b[1] && b[2] ? t("sp.tip.and") : "") + (b[2] ? t("sp.tip.n", { n: b[2], sessions: plural(b[2], "agent") }) : "") }) : t("sp.tip.idle")}</div>
        ${b[3].map(([j, v]) => html`<div><i class="k" style=${"background:" + spColor(L.projects[j])}></i>${(L.projects[j] || {}).name} · ${pct(v)}</div>`)}
        ${b[4] ? html`<div><i class="k" style="background:var(--pace)"></i>${t("sp.elsewhere")} · ${pct(b[4])}</div>` : ""}`;
    } else if (L.rate != null) {
      cx = hx;
      const p = Math.min(100, L.used + L.rate * (at - L.now) / 3600);
      cy = Y(p);
      tip = html`<div class="dim">${t("sp.tip.fc", { when: spWhen(at) })}</div><div class="v">~${pct(p)}</div>
        <div>${t("sp.tip.rate", { r: pct(L.rate) })}</div>`;
    }
  }
  const pick = (e) => { const r = e.currentTarget.getBoundingClientRect(); setHx(Math.max(0, Math.min(W, (e.clientX - r.left) / r.width * W))); };
  return html`<div class="chart" ref=${box}>
    <svg viewBox=${"0 0 " + W + " " + HT} height=${HT} role="img" aria-label=${L.name + ": " + pct(L.used) + (endP != null ? " → ~" + pct(endP) : "")}
      onPointerMove=${pick} onPointerDown=${pick} onPointerLeave=${(e) => e.pointerType === "mouse" && setHx(null)}>
      <line x1="0" x2=${W} y1=${Y(0)} y2=${Y(0)} stroke="var(--grid)"/><line x1="0" x2=${W} y1=${Y(50)} y2=${Y(50)} stroke="var(--grid)"/>
      <line x1="0" x2=${W} y1=${Y(100)} y2=${Y(100)} stroke="var(--axis)"/>
      <text x="0" y=${Y(100) - 4}>100 %</text><text x="0" y=${Y(50) - 4}>50 %</text>
      ${ticks.map((a) => html`<line x1=${X(a)} x2=${X(a)} y1=${PT} y2=${ST + SH} stroke="var(--grid)"/>`)}
      ${labels.map(([x, s]) => s && html`<text x=${x} y=${XB} text-anchor="middle">${s}</text>`)}
      <line x1="0" y1=${Y(0)} x2=${W} y2=${Y(100)} stroke="var(--pace)" stroke-width="1.5"/>
      <path d=${line + "L" + X(L.now).toFixed(1) + " " + Y(0) + "L0 " + Y(0) + "Z"} fill="var(--s1)" opacity="0.1"/>
      <path d=${line} fill="none" stroke="var(--s1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
      ${endP != null && html`<line x1=${X(L.now)} y1=${Y(L.used)} x2=${L.hit ? hitX : W} y2=${Y(endP)} stroke=${L.hit ? "var(--danger)" : "var(--s1)"} stroke-width="2" stroke-dasharray="4 4" stroke-linecap="round"/>`}
      ${L.hit && L.used < 100 ? html`<rect x=${hitX} y=${Y(100) - 3} width=${Math.max(0, W - hitX)} height="6" rx="3" fill="var(--danger)" opacity="0.25"/>
        <circle cx=${hitX} cy=${Y(100)} r="4.5" fill="var(--danger)" stroke="var(--card)" stroke-width="2"/>
        <text x=${hitX > W * 0.6 ? W : hitX} y=${Y(100) - 6} text-anchor=${hitX > W * 0.6 ? "end" : "start"} class="ink">${t("sp.runs.out", { when: spWhen(L.hit) })}</text>` : ""}
      ${endP != null && !L.hit ? html`<circle cx=${W - 4} cy=${Y(endP)} r="4" fill="var(--card)" stroke="var(--s1)" stroke-width="2"/>
        ${!short && html`<text x=${W - 12} y=${Y(endP) - 8} ...${ink}>~${pct(endP)}</text>`}` : ""}
      <circle cx=${X(L.now)} cy=${Y(L.used)} r="4.5" fill="var(--s1)" stroke="var(--card)" stroke-width="2"/>
      <text x=${X(L.now) - 8} y=${Y(L.used) - 9} ...${ink}>${pct(L.used) + (short && endP != null && !L.hit ? " → ~" + pct(endP) : "")}</text>
      <text x="0" y=${ST - 2}>${t("sp.at.once", { n: maxN })}</text>
      ${L.bars.map((b, i) => {
        if (!b[1] && !b[2]) return "";
        const x = i * bw, bwid = Math.max(1, bw - gap), hs = b[1] / maxN * SH, ha = b[2] / maxN * SH;
        return html`<rect x=${x} y=${ST + SH - hs} width=${bwid} height=${hs} fill="var(--s1)"/>${ha ? html`<rect x=${x} y=${ST + SH - hs - ha - (hs ? 1 : 0)} width=${bwid} height=${ha} fill="var(--s1-soft)"/>` : ""}`;
      })}
      <line x1="0" x2=${W} y1=${ST + SH + 0.5} y2=${ST + SH + 0.5} stroke="var(--axis)"/>
      ${tip && html`<line x1=${cx} x2=${cx} y1=${PT - 6} y2=${ST + SH} stroke="var(--ink)" stroke-opacity="0.35"/>
        <circle cx=${cx} cy=${cy} r="4" fill="var(--s1)" stroke="var(--card)" stroke-width="2"/>`}
    </svg>
    ${tip && html`<div class=${"tip" + (cy < PT + 70 ? " below" : "")} style=${"left:" + Math.max(100, Math.min(W - 100, cx)) + "px;top:" + (cy < PT + 70 ? cy + 14 : cy - 12) + "px"}>${tip}</div>`}
  </div>`;
}

// the same as a table: a row a day (the week) or half an hour (the window)
function SpendTable({ L }) {
  const per = L.key === "week" ? 24 : 6, rows = [];
  let c = 0;
  for (let i = 0; i < L.bars.length; i += per) {
    const part = L.bars.slice(i, i + per), s = L.t0 + i * L.step;
    const add = part.reduce((a, b) => a + b[0], 0);
    c += add;
    rows.push(html`<tr><td>${(L.key === "week" ? t("weekdays").split(" ")[toDate(s + 60).getDay()] + " " : "") + hhmm(toDate(s))}</td>
      <td>+${pct(add)}</td><td>${pct(c)}</td><td>${Math.max(...part.map((b) => b[1]))}</td></tr>`);
  }
  return html`<table class="tv"><thead><tr><th>${t("sp.t.from")}</th><th>+ %</th><th>${t("sp.t.total")}</th><th>${t("sp.t.peak")}</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// what spent the limit: a project keeps its colour, the five biggest have one, the rest are "other"
function Spent({ L }) {
  const parts = L.projects.filter((p) => p.color != null).map((p) => [p.name, p.pct, spColor(p), p.sh]);
  const rest = L.projects.filter((p) => p.color == null);
  const restPct = rest.reduce((a, p) => a + p.pct, 0);
  if (restPct >= 0.3) parts.push([t("sp.other"), restPct, "var(--c0)", L.per_sh ? restPct / L.per_sh : null]);
  if (L.ext >= 0.3) parts.push([t("sp.elsewhere"), L.ext, "var(--pace)", null]);
  if (!parts.length) return "";
  return html`<h3>${t("sp.ate." + L.key)}</h3><div class="card spent">
    <div class="stack">${parts.map(([, v, col], i) => html`<i key=${i} style=${"flex:" + v + ";background:" + col}></i>`)}</div>
    ${parts.map(([n, v, col, sh], i) => html`<div class="prow" key=${i}><span><i class="swatch" style=${"background:" + col}></i>${n}</span>
      <span class="dim">${pct(v)}${sh != null ? " · ≈ " + shours(sh) : ""}</span></div>`)}</div>`;
}

function Spend() {
  const [d, err, set] = useLive(() => api("spend"), [], () => false, 60000);
  const [key, setKey] = useState(null);
  const [table, setTable] = useState(false);
  const [busy, setBusy] = useState(false);
  useNow(30000);
  if (!d && err) return html`<${Usage}/>`;          // an older Pult on the computer, or no reading: the old screen says why
  if (!d) return html`<${Loading}/>`;
  if (!d.limits.length) return html`<${Usage}/>`;
  const by = Object.fromEntries(d.limits.map((x) => [x.key, x]));
  // the week opens first — the budget that has to last; the window only when it runs out first and the week doesn't
  const auto = by.h5 && by.h5.hit && !(by.week && by.week.hit) ? "h5" : by.week ? "week" : "h5";
  const L = by[key] || by[auto];
  const other = d.limits.find((x) => x !== L);
  const refresh = async () => {
    setBusy(true);
    try { set(await api("spend", { force: true })); haptic("success"); } catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  const share = (name) => (d.shares || []).find((x) => name.indexOf(x.name) >= 0);
  const chip = { pace: "ok", under: "info", over: "bad" }[L.state];
  return html`<div>
    ${d.limits.length > 1 && html`<div class="seg spend-seg">${d.limits.map((x) => html`<button key=${x.key} class=${x === L ? "on" : ""}
      onClick=${() => setKey(x.key)}>${t("sp.short." + x.key)}</button>`)}</div>`}
    <div class="card spend">
      <div class="sp-h"><span>${t("sp.name." + L.key)}${d.plan ? " · " + d.plan.charAt(0).toUpperCase() + d.plan.slice(1) : ""}</span><span>${t("usage.reset", { when: spWhen(L.t1) })}</span></div>
      <div class="sp-hero"><span class="big">${pct(L.used)}</span>${chip && html`<span class=${"vchip " + chip}>${t("sp.chip." + L.state)}</span>`}</div>
      <div class="verdict">${verdict(L).join(" ")}</div>
      <${PaceChart} L=${L}/>
      <div class="sp-leg"><span><i class="swatch" style="background:var(--s1)"></i>${t("sp.sessions")}</span><span><i class="swatch" style="background:var(--s1-soft)"></i>${t("sp.agents")}</span>
        <span><i class="swatch line" style="background:var(--pace)"></i>${t("sp.even")}</span>
        <button class="link" onClick=${() => setTable(!table)}>${t(table ? "sp.chart" : "sp.table")}</button></div>
      ${table && html`<${SpendTable} L=${L}/>`}
    </div>
    <div class="list">
      ${other && html`<button class="lim" onClick=${() => setKey(other.key)}>
        <div class="item-h"><b>${t("sp.short." + other.key)}</b><b class="pct">${pct(other.used)}</b></div>
        <div class="meter"><i class=${other.state === "over" ? "bad" : "spend"} style=${"width:" + Math.min(100, other.used) + "%"}></i></div>
        <div class="dim">${t("usage.reset", { when: spWhen(other.t1) })}${other.hit ? " · " + t("sp.runs.out", { when: spWhen(other.hit) }) : other.proj != null ? " · " + t("sp.other.at", { proj: "~" + pct(other.proj) }) : ""}</div></button>`}
      ${(d.others || []).map((x) => { const sh = share(x.name); return html`<div class="lim" key=${x.name}>
        <div class="item-h"><b>${x.name}</b><b class=${"pct " + level(x.percent)}>${pct(x.percent)}</b></div>
        <div class="meter"><i class=${level(x.percent) || "spend"} style=${"width:" + Math.min(100, x.percent) + "%"}></i></div>
        <div class="dim">${sh ? t("sp.share", { used: sh.used, allow: sh.allow }) + " · " : ""}${t("usage.reset", { when: spWhen(x.resets_at) })}</div></div>`; })}
    </div>
    <${Spent} L=${L}/>
    ${d.extra && d.extra.enabled && html`<div class="dim small">${t("usage.extra", { used: d.extra.used ?? 0, limit: d.extra.limit ?? "—", cur: d.extra.currency || "" })}</div>`}
    <div class="res-foot"><span class="dim">${t("usage.updated", { ago: ago(d.ts) })}</span>
      <button class="link" disabled=${busy} onClick=${refresh}>${busy ? t("refreshing") : t("refresh")}</button></div>
    <${About} text=${t("sp.about") + (L.per_sh ? " " + t("sp.about.sh", { per: pct(L.per_sh), limit: t("sp.of." + L.key) }) : "")
      + (d.fable_x >= 1.5 ? " " + t("sp.about.fable", { x: num(d.fable_x, 1) }) : "") + " " + t("usage.alerts")}/>
  </div>`;
}

// Resources: can I keep working — the plan's limits, or the computer's load; two sections, not five screens of one
const RES = ["lim", "pc"];
const resStore = {
  get() { try { const k = sessionStorage.getItem("pult.res"); return RES.includes(k) ? k : "lim"; } catch (e) { return "lim"; } },
  set(k) { try { sessionStorage.setItem("pult.res", k); } catch (e) {} },
};
function Resources() {
  const [sec, setSec] = useState(resStore.get);
  const pick = (k) => { setSec(k); resStore.set(k); };
  return html`<div><h2>${t("res.title")}</h2>
    <div class="subtabs" role="tablist">${RES.map((k) => html`<button key=${k} role="tab" aria-selected=${sec === k} class=${sec === k ? "on" : ""}
      onClick=${() => pick(k)}>${t("res." + k)}</button>`)}</div>
    ${sec === "pc" ? html`<${Load} embedded=${true}/>` : html`<${Spend}/>`}
  </div>`;
}

function Usage() {
  const [d, err, set] = useLive(() => api("usage"), [], () => false);
  const [busy, setBusy] = useState(false);
  useNow(30000);
  const refresh = async () => {
    setBusy(true);
    try { set(await api("usage", { force: true })); haptic("success"); } catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  if (!d) return html`<div><${Loading} err=${err && t("usage.failed", { err })}/><${Today}/></div>`;
  return html`<div><h3>${t("usage")}</h3>
    <div class="dim">${d.plan ? t("usage.plan", { plan: d.plan.charAt(0).toUpperCase() + d.plan.slice(1) }) : ""}</div>
    <div class="list">${d.limits.map((x) => html`<div class="lim" key=${x.name}>
      <div class="item-h"><b>${x.name}</b><b class=${"pct " + level(x.percent)}>${x.percent} %</b></div>
      <div class="meter"><i class=${level(x.percent)} style=${"width:" + Math.min(100, x.percent) + "%"}></i></div>
      <div class="dim">${t("usage.reset", { when: resetText(x.resets_at) })}</div></div>`)}</div>
    ${d.week_by.length > 0 && html`<div class="dim small">${t("usage.week", { list: d.week_by.map((x) => x.name + " " + x.percent + " %").join(" · ") })}</div>`}
    ${d.extra.enabled && html`<div class="dim small">${t("usage.extra", { used: d.extra.used ?? 0, limit: d.extra.limit ?? "—", cur: d.extra.currency || "" })}</div>`}
    <button class="btn ghost wide" disabled=${busy} onClick=${refresh}>${busy ? t("refreshing") : t("refresh")}</button>
    <div class="dim small">${t("usage.updated", { ago: ago(d.ts) })}</div>
    <${Today}/>
  </div>`;
}

// tokens today by project — from the Mac's transcripts; refreshes itself every 30 s
function Today() {
  const [d] = useLive(() => api("today"), [], () => false);
  if (!d || !d.projects.length) return "";
  const all = d.projects.reduce((s, p) => s + p.out, 0) || 1;
  return html`<h3>${t("today.title")}</h3>
    <div class="list">${d.projects.slice(0, 12).map((p) => html`<div class="lim" key=${p.pkey}>
      <div class="item-h"><b>${p.name}</b><b class="pct">${Math.round(p.out * 100 / all)} %</b></div>
      <div class="meter"><i style=${"width:" + Math.max(1, p.out * 100 / all) + "%"}></i></div>
      <div class="dim">${t("today.row", { n: p.req, requests: plural(p.req, "request"), out: kilo(p.out), read: kilo(p.read) })}</div></div>`)}</div>
    <div class="dim small">${t("today.about")}</div>`;
}

export { Resources };
