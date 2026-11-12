// Pult app — the computer's load and a session's background tasks.
// Moved from app.js as it was (review 2026-10-27, 6.4).
import { api, useLive } from "../core/conn.js";
import { go } from "../core/nav.js";
import { plural, q, t } from "../i18n.js";
import { html, useState } from "../vendor/htm-preact-3.1.1.js";
import { About, Loading, ago, bytes, dur, hhmm, ic, keyTap, kilo, level, lowBatt, machine, modelName, nb, num, pct, toDate, useNow } from "./kit.js";


// ---------- screens ----------

// Claude's background tasks still running after a turn; when one ends, Claude starts a new turn by itself
const bgLine = (bg) => html`${ic("bg", 14)} ${t("bg", { list: bg.map(q).join(", ") })}`;
// how many of each kind run in the background: "2 helpers, 1 command" — the session's line under "working…"
const KINDS = [["subagent", "helper"], ["workflow", "workflow"], ["shell", "command"], ["monitor", "monitor"]];
const bgCount = (kinds) => KINDS.map(([k, w]) => [kinds.filter((x) => (x || "shell") === k).length, w]).filter(([n]) => n)
  .map(([n, w]) => n + "\u00a0" + plural(n, w)).join(", ");

// ---------- the load on the computer ----------

// cores a process keeps busy: "1 core", "0.3 cores" — "1 ядро", "0,3 ядра", "5 ядер"
const coresText = (c) => (c >= 0.95 && Math.abs(c - Math.round(c)) < 0.05 ? Math.round(c) + " " + plural(Math.round(c), "core") : num(c, 1) + " " + t("cores.frac"));
const memPct = (l) => (l.mem_total && l.mem_used != null ? Math.round(l.mem_used * 100 / l.mem_total) : null);
const stateWord = (st) => (st === "work" ? t("load.st.work") : st === "ask" ? t("st.ask") : st === "bg" ? t("st.bg") : "");

// what runs under a session: Claude's command in the background (the cog) or in a turn (▶), another program (·)
function Cmds({ cmds, now }) {
  return cmds.length ? html`<div class="cmds">${cmds.map((c, i) => html`<div class="cmd" key=${i}>
    <div class="mono">${c.bg ? ic("bg", 13) : c.claude ? ic("play", 12) : "·"} ${c.text}</div>
    <div class="dim">${[pct(c.cpu), bytes(c.mem), t("load.runs", { dur: nb(dur(now - c.started)) })].join(" · ")}</div></div>`)}</div>` : "";
}

function LoadRow({ s, now }) {
  return html`<button class="item" onClick=${() => go("#/s/" + s.sid)}>
    <div class="item-h"><b>${s.driven ? html`<span class="st-ic">${ic("phone", 14)}</span>` : ""}${s.title}</b><b class=${"pct " + level(s.cpu)}>${pct(s.cpu)}</b></div>
    <div class="dim">${[s.project !== s.title ? s.project : "", stateWord(s.state), bytes(s.mem),
      s.cpu_time != null ? t("load.total", { dur: nb(dur(s.cpu_time)) }) : "", t("load.opened", { when: ago(s.started) })].filter(Boolean).join(" · ")}</div>
    <${Cmds} cmds=${s.cmds} now=${now}/>
  </button>`;
}

// the battery (2026-11-12): the charge, where the power comes from and the system's estimate — to empty on the
// battery, to full while charging — and how worn it is; only a machine with a battery has the card
function Power({ p }) {
  const cls = lowBatt(p.pct);
  const how = p.src === "batt" ? t("pw.batt") + (p.left ? " · " + t("pw.left", { dur: dur(p.left) }) : "")
    : p.charging ? t("pw.charging") + (p.left ? " — " + t("pw.tofull", { dur: dur(p.left) }) : "") : t("pw.ac");
  const wear = [p.cycles != null && p.cycles + "\u00a0" + plural(p.cycles, "cycle"), p.health != null && t("pw.health", { pct: p.health })].filter(Boolean);
  return html`<div class="lim pw"><div class="item-h"><b>${t("pw.title")}</b><b class=${"pct " + cls}>${p.pct}\u00a0%</b></div>
    <div class="meter"><i class=${cls} style=${"width:" + Math.min(100, p.pct) + "%"}></i></div>
    <div class="dim">${how}</div>${wear.length > 0 && html`<div class="dim">${t("pw.wear", { what: wear.join(" · ") })}</div>`}</div>`;
}

// the machine: processor, memory and power now, then every Claude session on it, the busiest first; resting ones folded
function Load({ embedded }) {
  const now = useNow(5000);
  const [d, err] = useLive(() => api("load"), [], () => false, 5000);
  const [rest, setRest] = useState(false);
  if (!d) return html`<${Loading} err=${err}/>`;
  machine.set(d.machine);
  // a system whose processes Pult can't read (Windows) may still tell its battery
  if (!d.ok) return d.power ? html`<div class="list"><${Power} p=${d.power}/></div>`
    : embedded ? "" : html`<div><h2>${t("load.title")}</h2><div class="empty">${t("load.none")}</div></div>`;
  const l = d.mac, m = memPct(l);
  const busy = d.sessions.filter((s) => !s.idle), idle = d.sessions.filter((s) => s.idle);
  return html`<div>${embedded ? "" : html`<h2>${t("load.title")}</h2>`}
    <div class="list">
      <div class="lim"><div class="item-h"><b>${t("load.cpu")}</b><b class=${"pct " + level(l.cpu)}>${pct(l.cpu)}</b></div>
        <div class="meter"><i class=${level(l.cpu)} style=${"width:" + Math.min(100, l.cpu) + "%"}></i></div>
        <div class="dim">${t("load.cpu.about", { n: l.cores, cores: plural(l.cores, "core"), load: num(l.load, 1) })}</div></div>
      ${m !== null && html`<div class="lim"><div class="item-h"><b>${t("load.mem")}</b><b class=${"pct " + level(m)}>${m} %</b></div>
        <div class="meter"><i class=${level(m)} style=${"width:" + Math.min(100, m) + "%"}></i></div>
        <div class="dim">${t("load.mem.about", { used: bytes(l.mem_used), total: bytes(l.mem_total), free: bytes(l.mem_total - l.mem_used) })}</div></div>`}
      ${d.power && html`<${Power} p=${d.power}/>`}
      ${l.mem_scope === "limit" && html`<div class="dim small">${t("memory.limit")}</div>`}
    </div>
    <h3>${t("load.sessions", { n: l.claude.n, sessions: plural(l.claude.n, "session"), cpu: pct(l.claude.cpu), mem: bytes(l.claude.mem) })}</h3>
    ${!d.sessions.length && html`<div class="empty">${t("load.nosessions")}</div>`}
    ${busy.length > 0 && html`<div class="list">${busy.map((s) => html`<${LoadRow} key=${s.sid} s=${s} now=${now}/>`)}</div>`}
    ${idle.length > 0 && html`<h3 class="toggle" role="button" tabindex="0" aria-expanded=${rest} onClick=${() => setRest(!rest)} onKeyDown=${keyTap(() => setRest(!rest))}>${t("load.resting", { n: idle.length, mem: bytes(idle.reduce((a, s) => a + s.mem, 0)) })} <span class=${"chev" + (rest ? " open" : "")}>${ic("chev", 14)}</span></h3>
      ${rest && html`<div class="list">${idle.map((s) => html`<${LoadRow} key=${s.sid} s=${s} now=${now}/>`)}</div>`}`}
    <${About} text=${t("load.about")}/>
  </div>`;
}

// a tap on "in the background": each task and what it costs the computer — now, in total and at its peak
const TASK_TYPES = { shell: "bgs.shell", monitor: "bgs.monitor", subagent: "bgs.subagent", workflow: "bgs.workflow" };
function BgSheet({ sid, onClose, fixed }) {
  const now = useNow(5000);
  const [d, err] = useLive(() => api("load", { sid }), [sid], (m) => !m.sid || m.sid === sid, 5000);
  const more = () => { onClose(); setTimeout(() => go("#/load"), 60); };
  const one = (x) => html`<div class="task" key=${x.id}>
    <div class="item-h"><b>${x.what}</b><span class="chip">${t(TASK_TYPES[x.type] || "bgs.shell")}${x.agent ? " · " + x.agent : ""}</span></div>
    ${x.cmd && html`<pre class="cmdline">${x.cmd}</pre>`}
    ${x.remote && x.model ? html`<div class="kv">
          ${x.since && html`<span>${t("bgs.runs")}</span><b>${dur(now - x.since)} <span class="dim">${t("bgs.since", { hm: hhmm(toDate(x.since)) })}</span></b>`}
          <span>${t("bgs.model")}</span><b>${modelName(x.model)}</b>
          ${x.steps != null && html`<span>${t("bgs.did")}</span><b>${x.steps} ${plural(x.steps, "step")}${x.tokens ? html` <span class="dim">· ${t("bgs.tokens", { n: kilo(x.tokens) })}</span>` : ""}</b>`}
          ${x.now && html`<span>${t("bgs.now")}</span><b class="mono">${x.now}</b>`}
        </div><div class="dim small">${t("bgs.remote")}</div>`
      : x.remote ? html`<div class="dim">${x.since ? t("bgs.atleast", { dur: dur(now - x.since), hm: hhmm(toDate(x.since)) }) + " · " : ""}${t("bgs.remote")}</div>`
      : x.found === false ? html`<div class="dim">${t("bgs.gone")}</div>`
      : html`<div class="kv">
          <span>${t("bgs.runs")}</span><b>${dur(now - x.since)} <span class="dim">${t("bgs.since", { hm: hhmm(toDate(x.since)) })}</span></b>
          <span>${t("bgs.cpu")}</span><b>${pct(x.cpu)}${x.cores >= 0.1 ? html` <span class="dim">· ≈ ${coresText(x.cores)}</span>` : ""}</b>
          ${x.cpu_time != null && html`<span>${t("bgs.cputime")}</span><b>${dur(x.cpu_time)}</b>`}
          <span>${t("bgs.mem")}</span><b>${bytes(x.mem)}${x.peak ? html` <span class="dim">· ${t("bgs.peak", { mem: bytes(x.peak) })}</span>` : ""}</b>
        </div>`}</div>`;
  return html`<div class="backdrop" onClick=${onClose}></div><div class=${"card pick tall" + (fixed ? " fixed" : "")}>
    <div class="q-t pick-h"><span>${ic("bg", 17)} ${t("bgs.title")}</span><button class="x" aria-label=${t("close")} onClick=${onClose}>${ic("x", 18)}</button></div>
    ${!d ? html`<div class="dim">${err || t("loading")}</div>` : !d.ok ? html`<div class="dim">${t("load.none")}</div>` : html`
      ${!d.tasks.length && html`<div class="dim">${t("bgs.none")}</div>`}${d.tasks.map(one)}
      ${d.session && html`<div class="dim small">${t("bgs.session", { cpu: pct(d.session.cpu), mem: bytes(d.session.mem) })}</div>`}`}
    <button class="link" onClick=${more}>${t("bgs.more")}</button></div>`;
}

export { BgSheet, Load, bgCount, bgLine, memPct };
