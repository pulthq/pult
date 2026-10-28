// Pult app — Settings: Pult and its parts, logins, the switches.
// Moved from app.js as it was (review 2026-10-27, 6.4).
import { api, useLang, useLive } from "../core/conn.js";
import { useOverlay } from "../core/nav.js";
import { alertBox, confirmBox, haptic } from "../core/tg.js";
import { OWN_V, checkServed, noteUpd, phoneOld, served, useServed } from "../core/update.js";
import { locale, plural, t } from "../i18n.js";
import { html, useEffect, useState } from "../vendor/htm-preact-3.1.1.js";
import { About, ChoicePick, Loading, ModePick, ago, choiceText, dur, hhmm, ic, plainField, toDate } from "../ui/kit.js";
import { UpdBody, UpdCard, tOr } from "../ui/upd.js";


// stage U2: every part of Pult in one table — what is there, how far behind the source folder's branch (main), who
// brings it up to date. A tap opens a row: the details and who does it; the computer's row holds the install block.
// The phone's row is the app's own: only it knows which copy it runs
const PART_IC = { mac: "monitor", web: "server", relay: "relay", phone: "phone", tabs: "tabs", hooks: "hook", cc: "spark", gh: "tag" };
const ddmm = (ts) => toDate(ts).toLocaleDateString(locale(), { day: "2-digit", month: "2-digit" });
const dayOrTime = (ts) => (toDate(ts).toDateString() === new Date().toDateString() ? hhmm(toDate(ts)) : ddmm(ts));
const commits = (n) => n + "\u00a0" + plural(n, "commit");

function partChip(r, b) {
  if (r.st === "ok") return r.k === "cc" && (ccRec(r, r.have) || {}).ok ? t("pt.cc.here") : t("pt." + r.k + ".ok", { b });
  if (r.k === "mac") return r.upd.state === "run" ? t("pt.mac.run") : r.upd.state === "fail" ? t("upd.fail.chip")
    : r.upd.state === "na" ? t(r.upd.why === "windows" ? "pt.mac.win" : "pt.unknown") : r.n ? "\u2212" + commits(r.n) : t("upd.ready.chip");
  if (r.k === "web" || r.k === "relay") {
    const s = r.srv;
    if (s && s.state === "run") return t("pt.srv.run", { v: s.tag });
    if (s && s.final) return t("pt.srv.fail", { v: s.tag });
    if (s && s.self && !r.n) return t("pt.srv.self.chip");          // its code is current, its updater isn't (0.18.6)
    return r.st === "warn" ? "\u2212" + commits(r.n) : t(r.why === "other" ? "pt.other" : "pt.unknown", { b });
  }
  if (r.k === "phone") return t(r.st === "warn" ? "pt.phone.old" : "pt.unknown");
  if (r.k === "tabs") return t("pt.tabs.old", { n: r.n_old });
  if (r.k === "hooks") return r.have ? t("pt.hooks.missing", { n: r.missing.length }) : t("pt.hooks.off");
  if (r.k === "cc") return r.checking ? t("pt.cc.run") : ccFailed(r) ? t("pt.cc.failed")
    : t(r.st === "bad" ? "pt.cc.off" : r.st === "attn" ? "pt.cc.fresh" : "pt.cc.nowrap");
  if (r.k === "gh") return t("pt.gh.waiting", { n: r.waiting });
  return "";
}

function partHave(r) {
  if (r.have == null) return "\u2014";
  if (r.k === "web" || r.k === "relay") return ddmm(r.have);
  if (r.k === "phone") return dayOrTime(+r.have);
  if (r.k === "hooks") return t("pt.hooks.have", { n: r.have, all: r.all });
  return String(r.have);
}

const who = (icon, text) => html`<div class="who">${ic(icon, 14)}<span>${text}</span></div>`;
const newsList = (xs) => (xs && xs.length ? html`<ul class="upd-news">${xs.map((x, i) => html`<li key=${i}>${x}</li>`)}</ul>` : "");

// stage U3, a clone of Pult's GitHub repository: whether the server takes this computer's releases itself, and how
// its last one went; without the updater — how to have it
function srvMore(r) {
  if (!r.auto) return who("server", t("pt.srv.manual"));
  const s = r.srv || {}, why = (w) => tOr("pt.srv.why." + w, w || "?");
  const line = s.state === "run" ? t("pt.srv.st.run", { v: s.tag, step: tOr("pt.srv.step." + s.step, s.step || "…") })
    : s.state === "done" ? t("pt.srv.st.done", { v: s.tag, ago: ago(s.ts) })
    : s.state === "fail" && s.final ? t(s.back && s.back_ok === false ? "pt.srv.st.dead" : "pt.srv.st.fail", { v: s.tag, have: s.have || "?", why: why(s.why) })
    : s.state === "fail" ? t("pt.srv.st.retry", { v: s.tag, why: why(s.why) })
    : s.state === "refused" ? t(s.why === "older" ? "pt.srv.st.older" : "pt.srv.st.unofficial", { v: s.tag })
    : s.have ? t("pt.srv.st.idle", { v: s.have }) : "";
  // a release it won't try by itself: the owner's word starts it anew (0.18.5)
  const again = async () => {
    try { const x = await api("srv_retry"); haptic("success"); alertBox(t("pt.srv.retry.sent", { v: x.v })); }
    catch (e) { alertBox(e.message); }
  };
  // what only the server's install.sh replaces is older than this release (review 2026-10-27, У5)
  const own = s.self === "old" ? t("pt.srv.self.old") : s.self && s.self.length ? t("pt.srv.self", { files: s.self.join(", ") }) : "";
  return html`${who("auto", t("pt.srv.auto"))}${line ? html`<div class=${"upd-note" + (s.final ? "" : " dim")}>${line}</div>` : ""}
    ${own ? html`<div class="upd-note">${own}</div>${who("server", t("pt.srv.self.who"))}` : ""}
    ${s.detail && s.state === "fail" ? html`<div class="upd-detail mono">${s.detail}</div>` : ""}
    ${s.final ? html`<button class="btn wide" onClick=${again}>${t("pt.srv.retry")}</button>` : ""}`;
}

// Claude Code in the table: what the tabs run, what the wrapper is allowed on, and what Pult's own check on this
// computer found (stage A) — passed, failed at a step, couldn't run, running now — with "Check again"
const ccRec = (r, v) => (r.checked && v && r.checked[v]) || null;
const ccFailed = (r) => [...(r.off || []), r.fresh].some((v) => { const c = ccRec(r, v); return !!c && c.ok === false && !c.error; });
function CcMore({ r, set }) {
  const [busy, setBusy] = useState(false);
  if (!r.wrapped) return html`<div class="dim">${t("pt.cc.nowrap.about")}</div>${r.cli ? html`<div class="dim upd-note">${t("pt.cc.app", { cli: r.cli, sdk: r.sdk })}</div>` : ""}`;
  const off = r.off || [];
  const v = r.checking || off[off.length - 1] || r.fresh;          // the version a check is about
  const c = ccRec(r, v);
  const hereV = [r.have, r.newest].find((x) => (ccRec(r, x) || {}).ok), here = ccRec(r, hereV);
  const again = async () => {
    setBusy(true);
    try { const x = await api("tab_check"); if (x.note) alertBox(x.note); else haptic("success"); set(); } catch (e) { alertBox(e.message); }
    setBusy(false);
  };
  const auto = r.auto !== false;                                   // a computer before 0.18.1 says nothing: as before
  const check = r.checking ? html`<div class="upd-note">${t("pt.cc.checking", { v: r.checking })}</div>`
    : c && c.error ? html`<div class="upd-note">${t("pt.cc.err", { v, when: dayOrTime(c.ts), why: t("check.why." + c.error) })}</div>`
    : c && c.ok === false ? html`<div class="upd-note bad">${t("pt.cc.failedin", { v, when: dayOrTime(c.ts), step: t("tab.step." + (c.step || "own")) })}</div>`
    : v && r.auto === false ? html`<div class="dim upd-note">${t("pt.cc.manual")}</div>` : "";
  const canAgain = r.auto !== undefined && v && !r.checking && (!c || c.ok === false || c.error || !auto);
  return html`${off.length ? html`<div>${t("pt.cc.offin", { v: off.join(", "), ok: r.verified || "?" })}</div>`
      : html`<div>${t("pt.cc.runs", { v: r.have, ok: r.verified || "?" })}</div>`}
    ${here ? html`<div class="dim upd-note">${t("pt.cc.herein", { v: hereV, when: dayOrTime(here.ts) })}${hereV !== r.have ? " " + t("pt.cc.next.ok") : ""}</div>` : ""}
    ${r.fresh && !r.checking && !c ? html`<div class="dim upd-note">${t(auto && r.auto !== undefined ? "pt.cc.next.auto" : "pt.cc.next", { v: r.fresh })}</div>` : ""}
    ${check}
    ${r.cli ? html`<div class="dim upd-note">${t("pt.cc.app", { cli: r.cli, sdk: r.sdk })}</div>` : ""}
    ${canAgain ? html`<button class="btn wide" disabled=${busy} onClick=${again}>${t(c ? "pt.cc.again" : "pt.cc.check")}</button>` : ""}
    ${v && !r.checking && (r.auto === undefined || (c && c.ok === false) || !auto) ? who("term", t("pt.cc.who", { v })) : ""}`;
}

function PartMore({ r, set, b }) {
  if (r.k === "mac") return html`${r.n ? html`<div class="dim">${t("pt.lag.short", { n: commits(r.n), since: ddmm(r.since), b })}</div>` : ""}
    <${UpdBody} v=${r.upd} set=${set} row=${true}/>`;
  if (r.k === "web" || r.k === "relay") {
    const auto = r.auto === undefined ? "" : srvMore(r);
    if (!r.commit) return html`<div class="dim">${t("pt.why." + r.why, { b })}</div>${auto}`;
    return html`<div class="dim">${t("pt." + r.k + ".from", { commit: r.commit, d: ddmm(r.have) })}</div>
      ${r.n ? html`<div class="dim upd-note">${t("pt.lag", { n: commits(r.n), since: ddmm(r.since), b })}</div>${newsList(r.news)}
      ${r.auto === undefined ? who("server", t("pt.web.who")) : ""}` : ""}${auto}`;
  }
  if (r.k === "phone") {
    if (r.st === "ok") return html`<div class="dim">${t("pt.phone.same")}</div>`;
    if (r.st === "info") return html`<div class="dim">${t("pt.phone.unknown")}</div>`;
    return html`<div class="dim">${t("pt.phone.diff", { mine: dayOrTime(+r.have), srv: dayOrTime(+r.srv) })}</div>
      <button class="btn wide" onClick=${() => location.reload()}>${t("pt.phone.reload")}</button>`;
  }
  if (r.k === "tabs") {
    if (!r.have) return html`<div class="dim">${t("pt.tabs.none")}</div>`;
    return html`<div class="dim">${t(r.old.length || r.unknown ? "pt.tabs.some" : "pt.tabs.all", { n: r.have })}</div>
      ${r.old.length ? html`<div class="upd-note">${t("pt.tabs.oldin", { list: r.old.join(", ") })}</div>
      <div class="dim upd-note">${t("pt.tabs.works")}</div>${who("monitor", t("pt.tabs.who"))}` : ""}
      ${r.unknown ? html`<div class="dim upd-note">${t("pt.tabs.unknown", { n: r.unknown })}</div>` : ""}`;
  }
  if (r.k === "hooks") {
    if (r.st === "ok") return html`<div class="dim">${t("pt.hooks.all", { n: r.all })}</div>`;
    return html`<div>${r.have ? t("pt.hooks.no", { list: r.missing.join(", ") }) : t("pt.hooks.none")}</div>
      ${who("monitor", t("pt.hooks.who"))}`;
  }
  if (r.k === "cc") return html`<${CcMore} r=${r} set=${set}/>`;
  if (r.k === "gh") return html`<div class="dim">${t("pt.gh.last", { v: r.have, d: r.date })}</div>
    ${r.waiting ? html`<div class="dim upd-note">${t("pt.gh.todo", { n: r.waiting })}</div>${who("term", t("pt.gh.who"))}` : ""}`;
  return "";
}

function Parts() {
  const [d, err, set] = useLive(() => api("parts"), [], (m) => m.kind === "update", 10000);
  const [open, setOpen] = useState(undefined);       // undefined — nothing tapped yet
  useServed();
  useEffect(() => { checkServed(true); }, []);
  const mac = d && d.rows.find((r) => r.k === "mac");
  useEffect(() => noteUpd(mac && mac.upd.state), [mac && mac.upd.state]);
  // the computer's row stands open while there is something to do with it — Home's line about it leads here
  const shown = open !== undefined ? open : mac && mac.upd.state !== "ok" && mac.upd.state !== "na" ? "mac" : null;
  if (err && !d) return html`<${UpdCard}/>`;      // a computer before stage U2 ("no such request: parts"), or a failure
  if (!d) return "";
  const reload = () => api("parts").then(set).catch(() => {});
  // the computer's own answer to its buttons shows at once ("Installing…"), the table follows: a reload sent as the
  // install stops Pult may get no answer at all (2026-10-27)
  const setMac = (u) => {
    if (u && u.state) set((cur) => cur && { ...cur, rows: cur.rows.map((x) => (x.k === "mac" ? { ...x, upd: u } : x)) });
    reload();
  };
  const rows = d.rows.slice();
  if (OWN_V) {
    const ph = { k: "phone", have: OWN_V, srv: served.v, st: !served.v ? "info" : phoneOld() ? "warn" : "ok" };
    const at = rows.findIndex((r) => r.k === "tabs" || r.k === "hooks");
    rows.splice(at < 0 ? rows.length : at, 0, ph);
  }
  const b = d.branch || "main";
  const late = rows.filter((r) => r.st === "warn" || r.st === "bad").length, note = rows.filter((r) => r.st === "attn").length;
  return html`<h3>${t("pt.h")}</h3><div class=${"card upg parts upd-s-" + mac.upd.state}>
    <div class="upd-h"><b>${late ? html`<span class="upd-attn">${ic("up", 17)}</span>` : html`<span class="upd-ok">${ic("check", 17)}</span>`}
      ${late ? t("pt.late", { n: late, all: rows.length }) : t("pt.allok", { b })}</b>
      <span class=${"chip " + (late || note ? "warn" : "ok")}>${late ? t("pt.chip.late") : note ? t("pt.chip.note", { n: note }) : t("upd.ok.chip")}</span></div>
    <div class="parts-t">
      <div class="parts-hd"><span>${t("pt.col.part")}</span><span>${t("pt.col.have")}</span><span>${t("pt.col.lag", { b })}</span></div>
      ${rows.map((r) => html`<div class=${"part st-" + r.st + (shown === r.k ? " open" : "")} key=${r.k} data-k=${r.k}>
        <button class="part-r" aria-expanded=${shown === r.k} onClick=${() => setOpen(shown === r.k ? null : r.k)}>
          <span class="part-ic">${ic(PART_IC[r.k], 18)}</span>
          <span class="part-n"><b>${t("pt." + r.k)}</b><span class="dim">${t("pt." + r.k + ".sub")}</span></span>
          <span class="part-v mono">${partHave(r)}</span>
          <span class=${"pchip " + r.st}>${r.st === "ok" ? ic("check", 13) : ""}${partChip(r, b)}</span>
        </button>
        ${shown === r.k ? html`<div class="part-x"><${PartMore} r=${r} set=${r.k === "mac" ? setMac : reload} b=${b}/></div>` : ""}
      </div>`)}
    </div>
    ${d.head ? html`<div class="dim parts-f">${t("pt.foot", { b, head: d.head, hm: hhmm(toDate(d.at)) })}</div>` : ""}
  </div>`;
}

function Settings() {
  const [d, err, set] = useLive(() => api("settings"), [], () => false);
  const [key, setKey] = useState("");
  const [kbusy, setKbusy] = useState(false);
  const [words, setWords] = useState(null);        // null — as saved on the computer
  const [pick, setPick] = useState(false);          // the default model and effort, in the same menu as a new task's
  const [openPick, closePick] = useOverlay(pick, setPick);
  if (!d) return html`<${Loading} err=${err}/>`;
  useLang(d.prefs.lang);
  const toggle = async (k) => {
    try { const p = await api("prefs", { [k]: !d.prefs[k] }); set(Object.assign({}, d, { prefs: Object.assign({}, d.prefs, p) })); haptic("success"); }
    catch (e) { alertBox(e.message); }
  };
  // a switch: one line under it, the rest behind "More"
  const sw = (k, label, hint, more) => html`<div class="item sw-row">
    <button class="sw-h" role="switch" aria-checked=${!!d.prefs[k]} onClick=${() => toggle(k)}><b>${label}</b><span class=${"sw" + (d.prefs[k] ? " on" : "")}></span></button>
    <div class="dim">${hint}</div>${more ? html`<${About} text=${more} label=${t("more")}/>` : ""}</div>`;
  const setLangPref = async (k) => {
    try { await api("prefs", { lang: k }); set(Object.assign({}, d, { prefs: Object.assign({}, d.prefs, { lang: k }) })); useLang(k); haptic("success"); }
    catch (e) { alertBox(e.message); }
  };
  const setPace = async (n) => {
    try { const p = await api("prefs", { pace: n }); set(Object.assign({}, d, { prefs: Object.assign({}, d.prefs, p) })); haptic("success"); }
    catch (e) { alertBox(e.message); }
  };
  const setChoice = async (c) => {
    try { const p = await api("prefs", c); set(Object.assign({}, d, { prefs: Object.assign({}, d.prefs, p) })); haptic("success"); }
    catch (e) { alertBox(e.message); }
  };
  const saveKey = async (k) => {
    setKbusy(true);
    try { const r = await api("stt_key", { key: k.trim() }); set(Object.assign({}, d, { stt: Object.assign({}, d.stt || {}, { on: r.on }) })); setKey(""); haptic("success"); alertBox(t(r.on ? "voice.saved" : "voice.removed")); }
    catch (e) { alertBox(e.message); }
    setKbusy(false);
  };
  const saveWords = async () => {
    setKbusy(true);
    try { const r = await api("stt_words", { words }); set(Object.assign({}, d, { stt: Object.assign({}, d.stt, { words: r.words }) })); setWords(null); haptic("success"); }
    catch (e) { alertBox(e.message); }
    setKbusy(false);
  };
  return html`<div><h2>${t("settings")}</h2>
    <${Parts}/>
    ${d.gh && d.gh.release ? html`<div class="list">${sw("gh", t("gh"), d.gh.at && d.prefs.gh ? t(d.gh.ok ? "gh.at" : "gh.fail", { hm: hhmm(toDate(d.gh.at)) }) : t("gh.short"), t("gh.about"))}</div>` : ""}
    ${"vcheck" in d.prefs ? html`<div class="list">${sw("vcheck", t("vcheck"), t("vcheck.short"), t("vcheck.about"))}</div>` : ""}
    ${"model" in d.prefs ? html`<h3>${t("model.pick")}</h3>
    <button class="field" onClick=${openPick}><span>${choiceText(d.prefs.model, d.prefs.effort)}</span><span class="dim">${ic("down", 18)}</span></button>
    <div class="dim small">${t("def.about")}</div>
    ${pick && html`<${ChoicePick} model=${d.prefs.model} effort=${d.prefs.effort} def=${d.cc} top=${t("pick.as.cc.short")}
      note=${t("def.cc.note")} onClose=${closePick} onPick=${setChoice}/>`}` : ""}
    <h3>${t("notifications")}</h3><div class="list">${sw("pager", t("pager"), t("pager.short"), t("pager.about"))}${d.prefs.pager ? "" : sw("vehi", t("vehi"), t("vehi.about"))}${sw("brief", t("brief"), t("brief.short"), t("brief.about"))}${"hashtags" in d.prefs ? sw("hashtags", t("hashtags"), t("hashtags.short"), t("hashtags.about")) : ""}</div>
    <h3>${t("where")}</h3>
    <${ModePick} mode=${d.prefs.mode} pager=${d.prefs.pager} onSet=${(m) => set(Object.assign({}, d, { prefs: Object.assign({}, d.prefs, { mode: m }) }))}/>
    ${d.prefs.pace ? html`<h3>${t("pace")}</h3>
    <div class="seg">${[85, 90, 95].map((n) => html`<button key=${n} class=${d.prefs.pace === n ? "on" : ""} onClick=${() => setPace(n)}>${n}\u00a0%</button>`)}</div>
    <div class="dim small">${t("pace.about", { n: d.prefs.pace })}</div>` : ""}
    <h3>${t("language")}</h3>
    <div class="seg">${[["en", "English"], ["ru", "Русский"]].map(([k, label]) => html`<button key=${k}
      class=${d.prefs.lang === k ? "on" : ""} onClick=${() => setLangPref(k)}>${label}</button>`)}</div>
    <h3>${t("voice")}</h3><div class="list"><div class="item static">
      <div>${d.stt && d.stt.on ? t("voice.on") : t("voice.off")}</div>
      <div class="dim">${t("voice.privacy", { lang: (d.stt && d.stt.lang) || "auto" })}</div>
      <div class="keyrow"><input type="password" ref=${plainField} placeholder=${t("voice.key")} value=${key} onInput=${(e) => setKey(e.target.value)}/>
        <button class="btn" disabled=${!key.trim() || kbusy} onClick=${() => saveKey(key)}>${t("voice.save")}</button></div>
      ${d.stt && d.stt.on ? html`<button class="link" disabled=${kbusy} onClick=${() => saveKey("")}>${t("voice.remove")}</button>` : ""}
    </div>
    ${d.stt && d.stt.on && typeof d.stt.words === "string" ? html`<div class="item static">
      <div>${t("voice.words")}</div><div class="dim">${t("voice.words.about")}</div>
      <div class="keyrow"><input ref=${plainField} maxlength="280" placeholder=${t("voice.words.ph")} value=${words === null ? d.stt.words : words} onInput=${(e) => setWords(e.target.value)}/>
        <button class="btn" disabled=${words === null || words.trim() === d.stt.words || kbusy} onClick=${saveWords}>${t("voice.save")}</button></div>
    </div>` : ""}</div>
    <${Logins}/>
    <h3>${t("status")}</h3><div class="list"><div class="item static">
      <div>${t("status.pult", { v: d.version, mac: d.mac.away ? t("mac.away", { dur: dur(d.mac.idle) }) : t("mac.here") })}</div>
      <div class="dim">${t("status.tg", { how: t("tg." + (d.telegram === "proxy" ? "proxy" : "direct")) })}</div>
    </div></div>
    <details class="logbox"><summary>${t("log", { n: d.log.length })}</summary>
      <pre class="log">${d.log.slice().reverse().join("\n")}</pre></details>
  </div>`;
}

// the app's recent logins: when, from which network and device, how — and a way to log every window out
// logins in a row from the same window, network and device read as one line: "8 times", the latest time
const runs = (xs) => xs.reduce((out, x) => {
  const last = out[out.length - 1];
  if (last && last.ok === x.ok && last.how === x.how && last.net === x.net && last.dev === x.dev) last.n += 1;
  else out.push(Object.assign({ n: 1 }, x));
  return out;
}, []);
function Logins() {
  const [d] = useLive(() => api("logins"), [], () => false);
  if (!d) return "";
  const out = async () => {
    if (!(await confirmBox(t("logins.confirm")))) return;
    try { await api("logout_all"); haptic("success"); } catch (e) { alertBox(e.message); }
  };
  return html`<h3>${t("logins")}</h3><div class="list"><div class="item static">
    ${d.locked ? html`<div class="warn">${t("logins.locked", { files: d.locked })}</div>` : ""}
    ${runs(d.logins).slice(0, 8).map((x, i) => html`<div class="login" key=${i}>
      <span class=${x.ok ? "ok" : "bad"}>${ic(x.ok ? "check" : "x", 14)} ${ago(x.ts)}</span>
      <span class="dim">${[t("logins.how." + x.how), x.net, x.dev, x.n > 1 ? t("logins.times", { n: x.n, times: plural(x.n, "time") }) : ""].filter(Boolean).join(" · ")}</span></div>`)}
    ${d.logins.length ? "" : html`<div class="dim">${t("logins.none")}</div>`}
    <button class="link danger" onClick=${out}>${t("logins.out")}</button>
  </div></div>`;
}

export { Settings, ddmm };
