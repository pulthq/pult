// Pult app — an update in words: Home's line and the install block of Settings → Pult and its parts.
// Moved from app.js as it was (review 2026-10-27, 6.4).
import { api, useLive } from "../core/conn.js";
import { go } from "../core/nav.js";
import { alertBox, haptic } from "../core/tg.js";
import { noteUpd, phoneOld, useServed } from "../core/update.js";
import { t } from "../i18n.js";
import { html, useEffect, useState } from "../vendor/htm-preact-3.1.1.js";
import { ago, ic } from "./kit.js";


const updSpin = html`<span class="upd-spin" aria-hidden="true"></span>`;
const tOr = (k, other) => { const v = t(k); return v === k ? other : v; };     // a code the app has no words for: as is
const updWhy = (w) => tOr("upd.why." + w, w || "?");
const updWho = (b, i) => html`<div class="upd-who" key=${i}>${b.turn ? html`<span class="st st-work"></span>` : html`<span class="st-ic">${ic("bg", 15)}</span>`}<span>${b.project ? html`<b>${b.project}</b>${b.title && b.title !== b.project ? " · " + b.title : ""}` : b.title} <span class="dim">— ${[b.turn ? t("upd.busy.turn") : "", b.n ? t("upd.busy.bg", { n: b.n }) : ""].filter(Boolean).join(", ")}</span></span></div>`;

// Home: a line under the strip only while there is something to do or to know; a tap — Settings. The computer's own
// install states first; then what can be done from here (the computer, this phone's copy) and what doesn't work
function UpdRow({ u }) {
  useEffect(() => noteUpd(u && u.state), [u && u.state]);
  useServed();
  const st = u ? u.state : "ok", phone = phoneOld(), broken = (u && u.broken) || [];
  const mac = st === "ready" || st === "busy";
  if (st === "srv_run") {
    return html`<button class="card upd-row" onClick=${() => go("#/settings")}><span class="upd-ic">${updSpin}</span>
      <span class="upd-t"><b>${t("upd.srv.run", { v: u.next })}</b><span class="dim">${t("upd.row.srv.run")}</span></span>${ic("chev", 16)}</button>`;
  }
  const row = (icon, title, sub, cls) => html`<button class=${"card upd-row " + cls} onClick=${() => go("#/settings")}>
    <span class="upd-ic">${icon}</span><span class="upd-t"><b>${title}</b><span class="dim">${sub}</span></span>${ic("chev", 16)}</button>`;
  if (st === "wait" || st === "run" || st === "fail" || mac && !phone && !broken.length) {
    const [icon, title, sub, cls] = {
      ready: [ic("up", 17), t("upd.ready", { v: u.next }), t("upd.row.ready", { v: u.have }), ""],
      busy: [ic("up", 17), t("upd.ready", { v: u.next }), t("upd.row.busy", { n: u.left }), "attn"],
      wait: [ic("auto", 17), t("upd.wait", { v: u.next }), t("upd.row.wait", { n: u.left }), "attn"],
      run: [updSpin, t("upd.run", { v: u.next }), t("upd.row.run"), ""],
      fail: [ic("alert", 17), u.back ? t("upd.row.fail", { next: u.next, v: u.have }) : t("upd.fail.kept", { v: u.next }), t("upd.row.fail.sub"), "bad"],
    }[st];
    return row(icon, title, sub, cls);
  }
  const acts = [mac ? t("pt.home.mac") : "", phone ? t("pt.home.phone") : ""].filter(Boolean);
  const probs = broken.map((b) => (b.k === "hooks" ? t("pt.home.hooks", { ev: b.missing.join(", ") }) : t(b.next ? "pt.home.cc.next" : b.fail ? "pt.home.cc.fail" : "pt.home.cc", { v: b.v })));
  if (!acts.length && !probs.length) return "";
  // a hook event missing is a step to take, in amber; red is for what is really off (review 2026-10-27, У10)
  const sev = broken.some((b) => b.k !== "hooks") ? "bad" : "attn";
  if (!acts.length) return row(ic("alert", 17), probs[0], probs.slice(1).join(" · ") || t("pt.home.more"), sev);
  return row(ic("up", 17), t("pt.home.upd", { what: acts.join(", ") }), probs.join(" · ") || t(mac ? "upd.row.ready" : "pt.home.phone.sub", { v: u && u.have }), probs.length ? sev : "");
}

// the computer's Pult: the state, the one button, the history — the "Pult" block of a computer before stage U2, and
// the computer's row in the parts table (row: the version and "up to date" are in the row already)
function UpdBody({ v, set, row }) {
  const [busy, setBusy] = useState(false);
  const act = async (op) => {
    setBusy(true);
    try { const r = await api(op); set(r); haptic("success"); }
    catch (e) {
      // Install stops Pult itself: when its answer is lost on the way, the install most likely runs — "Installing…"
      // until the computer is back and says how it went, not an error and the same button again (2026-10-27). Into
      // the screen's data, so the table and the banner say the same
      if (op === "update_go" && e.lost) { noteUpd("run"); set({ ...v, state: "run", step: "start" }); }
      else { alertBox(e.message); api("update").then(set).catch(() => {}); }
    }
    setBusy(false);
  };
  const head = (icon, title, chip, cls) => html`<div class=${"upd-h " + (cls || "")}><b>${icon}${title}</b>${chip}</div>`;
  const news = v.news && v.news.length ? html`<div class="upd-k">${t("upd.news")}</div><ul class="upd-news">${v.news.map((x, i) => html`<li key=${i}>${x}</li>`)}</ul>` : "";
  const busyList = v.busy || [];
  const order = { prepare: 0, start: 0, stop: 1, copy: 1, check: 2, back: 3 };
  const at = order[v.step] || 0;
  const mark = (n) => (at > n ? ic("check", 15) : at === n ? updSpin : html`<span class="upd-dot"></span>`);
  const body = {
    ok: html`${head(html`<span class="upd-ok">${ic("check", 17)}</span>`, t("upd.ok", { v: v.have }), html`<span class="chip ok">${t("upd.ok.chip")}</span>`)}
      ${v.dir ? html`<div class="dim">${t("upd.ok.from", { dir: v.dir, commit: v.commit })}</div>` : ""}`,
    ready: html`${head("", t("upd.ready", { v: v.next }), html`<span class="chip ok">${t("upd.ready.chip")}</span>`)}
      <div class="dim">${t("upd.have", { v: v.have })}</div>${news}
      <button class="btn wide" disabled=${busy} onClick=${() => act("update_go")}>${t("upd.go", { v: v.next })}</button>
      <div class="dim upd-note">${t("upd.go.about")}</div>${v.srv ? html`<div class="dim upd-note">${t("upd.go.srv")}</div>` : ""}`,
    busy: html`${head("", t("upd.ready", { v: v.next }), html`<span class="chip warn">${t("upd.busy.chip")}</span>`)}
      <div class="dim">${t("upd.have", { v: v.have })}</div>${news}
      <div class="upd-k attn">${t("upd.busy.cut", { n: busyList.length })}</div>${busyList.map(updWho)}
      <div class="dim upd-note">${t("upd.busy.safe")}</div>
      <button class="btn wide" disabled=${busy} onClick=${() => act("update_wait")}>${t("upd.wait.go")}</button>
      <div class="dim upd-note">${t("upd.wait.idle")}</div>`,
    wait: html`${head(html`<span class="upd-attn">${ic("auto", 17)}</span>`, t("upd.wait", { v: v.next }), html`<span class="chip warn">${t("upd.wait.chip")}</span>`)}
      ${busyList.length ? html`<div class="upd-k">${t("upd.wait.left", { n: busyList.length })}</div>${busyList.map(updWho)}` : html`<div class="dim upd-note">${t("upd.wait.none")}</div>`}
      <div class="dim upd-note">${t("upd.wait.about")}</div>
      <button class="btn ghost wide" disabled=${busy} onClick=${() => act("update_cancel")}>${t("upd.cancel")}</button>`,
    run: html`${head(updSpin, t("upd.run", { v: v.next }), "")}
      <div class="upd-steps">${at === 3 ? html`<div class="cur">${updSpin} ${t("upd.run.back", { v: v.have })}</div>` : html`
        <div class=${at === 0 ? "cur" : ""}>${mark(0)} ${t("upd.run.keep", { v: v.have })}</div>
        <div class=${at === 1 ? "cur" : ""}>${mark(1)} ${t("upd.run.files", { v: v.next })}</div>
        <div class=${at === 2 ? "cur" : ""}>${mark(2)} ${t("upd.run.check")}</div>`}</div>
      <div class="dim upd-note">${t("upd.run.about")}</div>`,
    fail: html`${head(html`<span class="upd-bad">${ic("alert", 17)}</span>`, t(v.back ? "upd.fail" : "upd.fail.kept", { v: v.next }),
        html`<span class="chip bad">${t(v.back ? "upd.fail.chip" : "upd.fail.chip.kept")}</span>`, "bad")}
      <div>${t(v.back ? "upd.fail.back" : "upd.fail.stays", { v: v.have })}</div>
      <div class="dim upd-note">${t("upd.fail.why", { why: updWhy(v.why) })}</div>
      ${v.detail ? html`<div class="upd-detail mono">${v.detail}</div>` : ""}
      <div class="dim upd-note">${t("upd.fail.again", { v: v.next })}</div>`,
    na: html`${head("", t("upd.ok", { v: v.have }), "")}<div class="dim">${t("upd.na." + (v.why === "windows" ? "windows" : "norepo"))}</div>`,
  }[v.state] || "";
  const hist = v.hist || [];
  return html`${row && v.state === "ok" ? (v.dir ? html`<div class="dim">${t("upd.ok.from", { dir: v.dir, commit: v.commit })}</div>` : "") : body}
    ${hist.length ? html`<details class="upd-hist"><summary>${t("upd.hist", { n: hist.length })}</summary>
      ${hist.map((x, i) => html`<div class="login" key=${i}><span class=${x.ok ? "ok" : "bad"}>${ic(x.ok ? "check" : "x", 14)} ${ago(x.ts)}</span>
        <span class="dim">${x.ok ? [x.from, x.to].filter(Boolean).join(" → ") : t(x.from && x.from !== x.to ? "upd.hist.failed" : "upd.hist.kept", { to: x.to, from: x.from })} · ${tOr("upd.how." + x.how, x.how)}</span></div>`)}</details>` : ""}`;
}

// Settings, a computer before stage U2: the "Pult" block alone (before stage U the computer doesn't know the request:
// no block then)
function UpdCard() {
  const [v, , set] = useLive(() => api("update"), [], null, 10000);
  useEffect(() => noteUpd(v && v.state), [v && v.state]);
  if (!v) return "";
  return html`<h3>${t("upd.h")}</h3><div class=${"card upg upd-s-" + v.state}><${UpdBody} v=${v} set=${set}/></div>`;
}

export { UpdBody, UpdCard, UpdRow, tOr };
