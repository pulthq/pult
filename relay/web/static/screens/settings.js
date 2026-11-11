// Pult app — Settings: Pult and its parts, logins, the switches.
// Moved from app.js as it was (review 2026-10-27, 6.4).
import { api, useLang, useLive } from "../core/conn.js";
import { useOverlay } from "../core/nav.js";
import { alertBox, confirmBox, haptic, tick } from "../core/tg.js";
import { OWN_V, checkServed, noteUpd, phoneOld, served, useServed } from "../core/update.js";
import { locale, plural, t } from "../i18n.js";
import { html, useEffect, useState } from "../vendor/htm-preact-3.1.1.js";
import { About, ChoicePick, Loading, ModePick, ago, choiceText, dur, hhmm, ic, num, plainField, toDate } from "../ui/kit.js";
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
// stage A2: what is out, and the Claude Code sessions from the app start on — the newest version that passed the check
// of a session from the app here (Pult's own copy of it), or the one built into Pult; a computer before it says neither
function ccApp(r) {
  const a = r.app, l = r.latest;
  const out = l && l.v ? html`<div class="dim upd-note">${t("pt.cc.latest", { v: l.v, when: dayOrTime(l.seen) })}</div>` : "";
  if (!a) return html`${out}${r.cli ? html`<div class="dim upd-note">${t("pt.cc.app", { cli: r.cli, sdk: r.sdk })}</div>` : ""}`;
  const line = a.own ? (a.ts ? t("pt.cc.appown", { v: a.v, when: dayOrTime(a.ts) }) : t("pt.cc.appown.nots", { v: a.v }))
    : t(a.on ? "pt.cc.appsdk" : "pt.cc.appoff", { v: a.v || "?", sdk: r.sdk || "?" });
  return html`${out}<div class="dim upd-note">${line}</div>`;
}
function CcMore({ r, set }) {
  const [busy, setBusy] = useState(false);
  if (!r.wrapped) return html`<div class="dim">${t("pt.cc.nowrap.about")}</div>${ccApp(r)}`;
  const off = r.off || [];
  const nc = ccRec(r, r.newest), appFail = !!nc && nc.app === false && !nc.error;    // stage A2: the app's step failed
  const v = r.checking || off[off.length - 1] || r.fresh || (appFail ? r.newest : undefined);   // the version a check is about
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
    : c && c.app === false ? html`<div class="upd-note bad">${t("pt.cc.appfail", { v, when: dayOrTime(c.ts), have: (r.app && r.app.v) || r.cli || "?" })}</div>`
    : v && r.auto === false ? html`<div class="dim upd-note">${t("pt.cc.manual")}</div>` : "";
  const canAgain = r.auto !== undefined && v && !r.checking && (!c || c.ok === false || c.error || c.app === false || !auto);
  return html`${off.length ? html`<div>${t("pt.cc.offin", { v: off.join(", "), ok: r.verified || "?" })}</div>`
      : html`<div>${t("pt.cc.runs", { v: r.have, ok: r.verified || "?" })}</div>`}
    ${here ? html`<div class="dim upd-note">${t("pt.cc.herein", { v: hereV, when: dayOrTime(here.ts) })}${hereV !== r.have ? " " + t("pt.cc.next.ok") : ""}</div>` : ""}
    ${r.fresh && !r.checking && !c ? html`<div class="dim upd-note">${t(auto && r.auto !== undefined ? "pt.cc.next.auto" : "pt.cc.next", { v: r.fresh })}</div>` : ""}
    ${check}
    ${ccApp(r)}
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

// a vendor's models as a list (2026-11-08, the owner: "the models through commas are awkward and unclear — a list with
// ticks"): a tick puts a model into a task's menu, the star makes it the main one — the one a task gets when none is
// picked. Each tap is saved at once; rows keep their places, only the star moves. The ticked ones go to the computer
// the starred first, as a line with commas: a computer from before the list takes only that; at least one stays ticked
const ctxK = (n) => t("kilo.k", { n: Math.round(n / 1024) });
// a model's size as Ollama itself writes it (ollama list: decimal gigabytes)
const gb = (b) => t("gb", { n: num(b / 1e9, 1) }).replace(/ /g, "\u00a0");
const prm = (s) => { const m = /^([\d.]+)\s*B$/i.exec(s || ""); return m ? t("vend.list.bn", { n: num(+m[1], 1) }) : s || ""; };
function ModelRows({ rows, models, busy, onSet, one }) {
  const main = models[0];
  const tick = (n) => {
    const on = models.includes(n);
    if (on && models.length === 1) { alertBox(one); return; }
    onSet(on ? models.filter((m) => m !== n) : models.concat([n]));
  };
  return html`<div class="mlist">${rows.map((r) => {
    const on = models.includes(r.name), star = on && r.name === main;
    return html`<div key=${r.name} class=${"mrow" + (on ? " on" : "")}>
      <button class="mrow-t" role="checkbox" aria-checked=${on} disabled=${busy} onClick=${() => tick(r.name)}>
        <span class="mbox">${on ? ic("check", 15) : ""}</span>
        <span class="mrow-n"><b>${r.name}</b>${r.sub ? html`<span class="dim">${r.sub}</span>` : ""}</span></button>
      ${on ? html`<button class=${"mstar" + (star ? " on" : "")} aria-pressed=${star} aria-label=${t("vend.list.main")} disabled=${busy || star}
        onClick=${() => onSet([r.name].concat(models.filter((m) => m !== r.name)))}>${ic("star", 19)}${star ? html`<i>${t("vend.list.main")}</i>` : ""}</button>` : ""}
    </div>`;
  })}</div>`;
}

// one's own model through Ollama (stage M, step 6): no key — its address, checked by the computer. On, the card is its
// models: those that can take a task as the list, each with its context and, for a copy made with a context, the model it
// was made from; the server's others fold under it, each with why it doesn't fit — a base whose copy is there names it,
// one without gets "Make a copy with 32K" (the server makes it from the same weights). Settings open — the computer looks
// again on its own (a model made on the server since shows at once, 2026-11-05); a server that doesn't answer is a line
function LocalCard({ v, onRow }) {
  const [url, setUrl] = useState(null);             // null — as saved; a string — the address being changed
  const [busy, setBusy] = useState("");
  const [rest, setRest] = useState(!v.key);         // the server's other models shown
  const [down, setDown] = useState("");
  useEffect(() => {
    if (!v.key || !v.fit) return;                   // a computer from before the list has no quiet look
    api("vendor_local", { quiet: true }).then((r) => { if (r && r.vendor) onRow(r.vendor); setDown((r && r.down) || ""); }).catch(() => {});
  }, []);
  const found = (v.found && v.found.models) || [], kin = v.kin || {}, fit = v.fit || v.models;
  const check = async (on) => {
    setBusy("check");
    try {
      const r = await api("vendor_local", on ? { url: (url == null ? v.url : url).trim() } : { on: false });
      onRow(r.vendor); setUrl(null); setDown(""); haptic("success"); alertBox(r.words);
    } catch (e) { alertBox(e.message); }
    setBusy("");
  };
  const save = async (models) => {
    const was = v.models;
    onRow(Object.assign({}, v, { models }));        // at once; back if the computer says no
    setBusy("models");
    try { const r = await api("vendor_models", { vendor: v.id, models: models.join(", ") }); onRow(r.vendor || Object.assign({}, v, { models: r.models })); tick(); }
    catch (e) { onRow(Object.assign({}, v, { models: was })); alertBox(e.message); }
    setBusy("");
  };
  const copy = async (name) => {
    setBusy(name);
    try { const r = await api("vendor_copy", { model: name }); onRow(r.vendor); haptic("success"); alertBox(r.words); }
    catch (e) { alertBox(e.message); }
    setBusy("");
  };
  const sub = (x) => [x.ctx && ctxK(x.ctx), kin[x.name] && kin[x.name].from ? t("vend.list.from", { m: kin[x.name].from }) : prm(x.params),
    x.size && gb(x.size)].filter(Boolean).join(" · ");
  const why = (x) => (!x.tools ? t("vend.local.notools") : !x.ctx ? t("vend.local.noctx") : ctxK(x.ctx) + " · " + t("vend.local.small"));
  const rows = fit.map((n) => ({ name: n, sub: sub(found.find((x) => x.name === n) || { ctx: (v.ctx || {})[n] }) }));
  const others = found.filter((x) => !fit.includes(x.name));
  const edit = url != null || !v.key;
  const at = v.found && v.found.ts;
  // on, with a computer that has the panel (stage M, step 6.4): the card is a line — the models, the room and the rest
  // live in the panel (Resources → Local model), one place for them
  if (v.panel && v.key && url == null) return html`<div class="item static vend vl" key=${v.id}>
    <div class="vend-h"><b>${v.name}</b><span class="vend-st on">${t("vend.local.on")}</span></div>
    <div class="dim vl-sum">${t(v.models.length > 1 ? "lp.sum.n" : "lp.sum", { m: v.models[0], n: v.models.length - 1 })}</div>
    ${down && html`<div class="vl-down">${ic("alert", 15)}<span>${t("vend.list.down", { hm: at ? hhmm(toDate(at)) : "—" })}</span></div>`}
    <a class="vl-open" href="#/local"><span>${t("lp.open")}</span>${ic("chev", 17)}</a>
  </div>`;
  return html`<div class="item static vend vl" key=${v.id}>
    <div class="vend-h"><b>${v.name}</b><span class=${"vend-st" + (v.key ? " on" : "")}>${t(v.key ? "vend.local.on" : "vend.local.off")}</span></div>
    ${edit ? html`<div class="dim vend-m">${t("vend.local.url")}</div>
      <div class="keyrow wrap"><input ref=${plainField} inputmode="url" value=${url == null ? v.url : url} data-saved=${v.url} onInput=${(e) => setUrl(e.target.value)}/>
        <button class="btn" disabled=${!(url == null ? v.url : url).trim() || busy} onClick=${() => check(true)}>${t(v.key ? "vend.local.again" : "vend.local.check")}</button></div>`
    : html`<div class="vl-srv"><button class="vl-at" onClick=${() => setUrl(v.url)}>${[v.found && v.found.version && "Ollama " + v.found.version, v.url.replace(/^https?:\/\//, ""),
        at && t("vend.list.at", { hm: hhmm(toDate(at)) })].filter(Boolean).join(" · ")}</button>
      <button class=${"vl-re" + (busy === "check" ? " spin" : "")} aria-label=${t("vend.local.again")} disabled=${!!busy} onClick=${() => check(true)}>${ic("auto", 17)}</button></div>`}
    ${down && html`<div class="vl-down">${ic("alert", 15)}<span>${t("vend.list.down", { hm: at ? hhmm(toDate(at)) : "—" })}</span></div>`}
    ${v.key && rows.length > 0 && html`<div class="vl-lg dim">${t("vend.list.legend")}</div>
      <${ModelRows} rows=${rows} models=${v.models} busy=${!!busy} onSet=${save} one=${t("vend.list.one.local")}/>`}
    ${others.length > 0 && html`<button class="vl-fold" aria-expanded=${rest} onClick=${() => setRest(!rest)}>
        <span>${t("vend.list.rest", { n: others.length, models: plural(others.length, "model") })}</span>${ic("down", 17)}</button>
      ${rest && html`<div class="mlist rest">${others.map((x) => {
        const k = kin[x.name] && kin[x.name].copy, can = v.copy && x.tools && !k && (!x.max || x.max >= v.min);
        return html`<div key=${x.name} class="mrow off"><div class="mrow-t"><span class="mrow-n"><b>${x.name}</b>
          <span class="dim">${why(x)}${k ? " · " + t("vend.list.copy", { m: k }) : x.params ? " · " + prm(x.params) : ""}</span>
          ${can ? html`<button class="mmake" disabled=${!!busy} onClick=${() => copy(x.name)}>${ic("plus", 14)} ${busy === x.name ? t("vend.list.making") : t("vend.list.make", { ctx: ctxK(Math.min(v.copy, x.max || v.copy)) })}</button>` : ""}</span></div>
        </div>`;
      })}</div>`}`}
    ${v.key ? html`<div class="vl-foot"><button class="link" disabled=${!!busy} onClick=${() => check(false)}>${t("vend.local.turnoff")}</button>
      <${About} text=${t("vend.local.about")} label=${t("more")}/></div>`
    : html`<div class="dim small vend-la">${t("vend.local.about")}</div>`}
  </div>`;
}

// a cloud vendor (DeepSeek, GLM, Kimi): its key — checked by the computer with one tiny request and kept there, never
// shown again — and its models as the same list: Pult's own names for it (from the vendor's pages) and the ones the
// owner added; under it, with two or more ticked, the helpers' model — subagents run on it (before: the second of the line)
function CloudCard({ v, onRow }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState("");
  const [add, setAdd] = useState(null);             // null — no field; a string — the name being typed
  const [pf, setPf] = useState(false);              // the sheet of the helpers' model
  const [openPf, closePf] = useOverlay(pf, setPf);
  const saveKey = async (k) => {
    setBusy("key");
    try {
      const r = await api("vendor_key", { vendor: v.id, key: k.trim() });
      onRow(Object.assign({}, v, { key: r.key })); setKey(""); haptic("success");
      alertBox(r.warn || (r.key ? t("vend.key.saved", { name: v.name, m: r.model || v.models[0] }) : t("vend.key.removed", { name: v.name })));
    } catch (e) { alertBox(e.message); }
    setBusy("");
  };
  const save = async (models, fast) => {
    const was = { models: v.models, fast: v.fast };
    const f = fast !== undefined ? fast : models.includes(v.fast) ? v.fast : models[1] || models[0];
    onRow(Object.assign({}, v, { models, fast: f }));
    setBusy("models");
    try {
      const r = await api("vendor_models", Object.assign({ vendor: v.id, models: models.join(", ") }, v.known ? { fast: f } : {}));
      onRow(r.vendor || Object.assign({}, v, { models: r.models, fast: r.fast })); tick(); return true;
    }
    catch (e) { onRow(Object.assign({}, v, was)); alertBox(e.message); return false; }
    finally { setBusy(""); }
  };
  const known = v.known || [];
  const names = known.concat(v.models.filter((m) => !known.includes(m)));
  const usd = (x) => x.toLocaleString(locale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const price = (m) => { const p = (v.price || {})[m.replace(/\[1m\]$/, "")]; return p ? t("vend.list.price", { i: usd(p[0]), o: usd(p[1]) }) : ""; };
  const rows = names.map((m) => ({ name: m, sub: [/\[1m\]$/.test(m) && t("vend.list.window", { n: t("kilo.m", { n: 1 }) }), price(m),
    !known.includes(m) && t("vend.list.yours")].filter(Boolean).join(" · ") }));
  const added = async () => {
    const n = (add || "").trim();
    if (!n) return;
    if (names.includes(n)) { setAdd(null); if (!v.models.includes(n)) save(v.models.concat([n])); return; }
    if (await save(v.models.concat([n]))) setAdd(null);
  };
  return html`<div class="item static vend" key=${v.id}>
    <div class="vend-h"><b>${v.name}</b><span class=${"vend-st" + (v.key ? " on" : "")}>${v.key ? t("vend.key.on") : t("vend.key.off")}</span></div>
    <div class="keyrow"><input type="password" ref=${plainField} placeholder=${v.key ? t("vend.key.new") : t("vend.key.ph", { name: v.name })} value=${key} onInput=${(e) => setKey(e.target.value)}/>
      <button class="btn" disabled=${!key.trim() || !!busy} onClick=${() => saveKey(key)}>${t("voice.save")}</button></div>
    ${v.key ? html`<button class="link" disabled=${!!busy} onClick=${() => saveKey("")}>${t("vend.key.remove")}</button>` : ""}
    ${v.key ? html`<div class="vl-lg dim">${t("vend.list.legend")}</div>
    <${ModelRows} rows=${rows} models=${v.models} busy=${!!busy} onSet=${(ms) => save(ms)} one=${t("vend.list.one")}/>
    ${add == null ? html`<button class="vl-add" disabled=${!!busy || v.models.length >= 8} onClick=${() => setAdd("")}>${ic("plus", 16)} ${t("vend.list.add")}</button>`
    : html`<div class="keyrow"><input ref=${plainField} placeholder=${t("vend.list.add.ph", { name: v.name })} value=${add} onInput=${(e) => setAdd(e.target.value)}
        onKeyDown=${(e) => { if (e.key === "Enter") added(); }}/>
      <button class="btn" disabled=${!add.trim() || !!busy} onClick=${added}>${t("vend.list.add.btn")}</button></div>`}
    ${v.models.length > 1 && v.fast ? html`<button class="vl-fast" disabled=${!!busy} onClick=${openPf}><span class="dim">${t("vend.list.fast")}</span>
      <b>${v.fast}</b>${ic("down", 16)}</button>` : ""}` : ""}
    ${pf && html`<div class="backdrop" onClick=${closePf}></div><div class="card pick fixed">
      <div class="q-t pick-h">${t("vend.list.fast.h", { name: v.name })}<button class="x" aria-label=${t("close")} onClick=${closePf}>${ic("x", 18)}</button></div>
      ${v.models.map((m) => html`<button key=${m} class=${"opt" + (m === v.fast ? " on" : "")} onClick=${() => { closePf(); if (m !== v.fast) save(v.models, m); }}>${m}</button>`)}
      <div class="dim small">${t("vend.list.fast.about")}</div></div>`}
  </div>`;
}

// other vendors' models inside Claude Code (stage M, step 2): a card each — the cloud ones with their keys, one's own
// model with its address — and the model new projects get
function Vendors({ list, all, codex, onChange, onAll }) {
  const onRow = (row) => onChange((vs) => vs.map((x) => (x.id === row.id ? row : x)));     // a card's answer may come late
  // the model new projects get (stage M, 7.2; Q147 — before, "who does new tasks by default"): a project already there
  // keeps its own, changed in its settings
  const setAll = async (id) => {
    if ((all || "claude") === id) return;
    try { const r = await api("vendor_all", { vendor: id === "claude" ? null : id }); onAll(r.vendor); haptic("success"); }
    catch (e) { alertBox(e.message); }
  };
  const can = (codex && codex.ok ? [{ id: "codex", name: "Codex" }] : []).concat(list.filter((v) => v.key));
  return html`<h3>${t("vend.title")}</h3>
    ${can.length > 0 && html`<div class="lbl vend-all-h">${t("who.all")}</div>
    <div class="seg vend-all">${[{ id: "claude", name: "Claude" }, ...can].map((v) => html`<button key=${v.id} class=${(all || "claude") === v.id ? "on" : ""} onClick=${() => setAll(v.id)}>${v.short || v.name}</button>`)}</div>
    <div class="dim small vend-all-t">${t(all ? "who.all.vendor" : "who.all.claude")}</div>`}
    <div class="list">${list.map((v) => (v.local ? html`<${LocalCard} key=${v.id} v=${v} onRow=${onRow}/>` : html`<${CloudCard} key=${v.id} v=${v} onRow=${onRow}/>`))}</div>
    <div class="dim small">${t("vend.about")}</div>`;
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
  // a setting picked from a short list — the hour of the day's summary, the quiet hours, the wait after the app
  // (review 2026-11-11, block 2): the phone's own picker, the value on the right; values travel as JSON
  const valueRow = (k, label, hint, options) => {
    const now = JSON.stringify(d.prefs[k]);
    const opts = options.some(([v]) => JSON.stringify(v) === now) ? options : [...options, [d.prefs[k], String(d.prefs[k])]];
    return html`<div class="item sw-row"><label class="sw-h pick-h2"><b>${label}</b>
      <select class="pick-v" value=${now} onChange=${(e) => setChoice({ [k]: JSON.parse(e.target.value) })}>
        ${opts.map(([v, text]) => html`<option key=${JSON.stringify(v)} value=${JSON.stringify(v)}>${text}</option>`)}</select></label>
      <div class="dim">${hint}</div></div>`;
  };
  const hours = (a, b) => a + ":00–" + b + ":00";
  const calls = "digest" in d.prefs ? html`<div class="list">
    ${valueRow("digest", t("digest"), t("digest.short"), [[null, t("set.none")], ...[7, 8, 9, 10, 11, 12, 18, 19, 20, 21].map((h) => [h, t("digest.at", { h })])])}
    ${valueRow("quiet", t("quiet"), t("quiet.short"), [[null, t("set.none")], ...[[22, 7], [22, 8], [23, 7], [23, 8], [0, 8], [0, 9]].map((q) => [q, hours(q[0], q[1])])])}
    ${sw("remind", t("remind"), t("remind.short"))}
    ${valueRow("page_delay", t("pagedelay"), t("pagedelay.short"), [[0, t("pagedelay.now")], ...[2, 5, 10, 15].map((n) => [n, t("pagedelay.min", { n })])])}</div>` : "";
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
    ${"vcheck" in d.prefs ? html`<div class="list">${sw("vcheck", t("vcheck"), t("vcheck.short"), t("vcheck.about"))}${"ccfresh" in d.prefs ? sw("ccfresh", t("ccfresh"), t("ccfresh.short"), t("ccfresh.about")) : ""}</div>` : ""}
    ${"model" in d.prefs ? html`<h3>${t("model.pick")}</h3>
    <button class="field" onClick=${openPick}><span>${choiceText(d.prefs.model, d.prefs.effort, null, d.cc_models)}</span><span class="dim">${ic("down", 18)}</span></button>
    <div class="dim small">${t("def.about")}</div>
    ${pick && html`<${ChoicePick} model=${d.prefs.model} effort=${d.prefs.effort} def=${d.cc} models=${d.cc_models} top=${t("pick.as.cc.short")}
      note=${t("def.cc.note")} onClose=${closePick} onPick=${setChoice}/>`}` : ""}
    <h3>${t("notifications")}</h3><div class="list">${sw("pager", t("pager"), t("pager.short"), t("pager.about"))}${d.prefs.pager ? "" : sw("vehi", t("vehi"), t("vehi.about"))}${sw("brief", t("brief"), t("brief.short"), t("brief.about"))}${"hashtags" in d.prefs ? sw("hashtags", t("hashtags"), t("hashtags.short"), t("hashtags.about")) : ""}</div>
    ${calls}
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
      <div class="keyrow"><input ref=${plainField} maxlength="280" placeholder=${t("voice.words.ph")} value=${words === null ? d.stt.words : words} data-saved=${d.stt.words} onInput=${(e) => setWords(e.target.value)}/>
        <button class="btn" disabled=${words === null || words.trim() === d.stt.words || kbusy} onClick=${saveWords}>${t("voice.save")}</button></div>
    </div>` : ""}</div>
    ${d.vendors && html`<${Vendors} list=${d.vendors} all=${d.vendor_all} codex=${d.codex} onChange=${(f) => set((cur) => { const vs = f(cur.vendors);
      return Object.assign({}, cur, { vendors: vs, vendor_all: cur.vendor_all === "codex" || vs.some((x) => x.id === cur.vendor_all && x.key) ? cur.vendor_all : null }); })}
      onAll=${(v) => set(Object.assign({}, d, { vendor_all: v }))}/>`}
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
