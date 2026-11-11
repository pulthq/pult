// Pult app — what a task changed (review 2026-11-11, block 5: the view alone): the list of changed files under a
// task's outcome, and one file's change line by line over the screen. Counted by the computer from git, since the
// commit the folder stood at when the task began; nothing here changes anything.
import { api, emit, on, useLive } from "../core/conn.js";
import { openLayer, useBackFor, useKept } from "../core/nav.js";
import { locale, plural, t } from "../i18n.js";
import { html, useEffect, useMemo, useRef, useState } from "../vendor/htm-preact-3.1.1.js";
import { Loading, dotted, hhmm, ic, toDate } from "../ui/kit.js";
import { useNoFold } from "../ui/pics.js";
import { FileView } from "./session.js";

const KEPT = 0, ADDED = 1, REMOVED = 2, GAP = 3;
const ROWS = 1500;                        // rows put on the screen at once, "More lines" adds as many
const last = (p) => p.slice(p.lastIndexOf("/") + 1);
const folderOf = (p) => p.slice(0, Math.max(0, p.lastIndexOf("/")));
const when = (ts) => { const d = toDate(ts); return d.toLocaleDateString(locale(), { day: "numeric", month: "short" }) + " " + hhmm(d); };
const filesN = (n) => n + " " + plural(n, "file");
// "+86 −12" in the two colours; a binary file and one too long to count have no numbers
const Counts = ({ f }) => html`<span class="chg-n">${f.add ? html`<span class="pl">+${f.add}</span>` : ""}${f.add && f.del ? " " : ""}${f.del ? html`<span class="mi">−${f.del}</span>` : ""}</span>`;
// what happened to the file, when it isn't a plain edit
const kind = (f) => (f.bin ? t("chg.bin") : f.st === "A" ? t("chg.st.A") : f.st === "D" ? t("chg.st.D") : f.st === "R" ? t("chg.st.R") : "");

function Row({ sid, f }) {
  const dir = folderOf(f.p), k = kind(f);
  return html`<button class=${"chg-row" + (f.lock ? " lock" : "")} disabled=${f.lock} onClick=${() => emit("diff", { sid, p: f.p })}>
    <span class="chg-p"><b>${last(f.p)}</b>${dir ? html`<span class="dim"> · ${dir}</span>` : ""}${f.was ? html`<span class="dim chg-was">${t("chg.was", { p: f.was })}</span>` : ""}</span>
    <span class="chg-r">${f.lock ? ic("lock", 15) : html`<${Counts} f=${f}/>`}${k ? html`<span class="dim">${k}</span>` : ""}</span>
  </button>`;
}

// the list: the task's own files — the ones its tools wrote and its turns touched; what else changed in the folder since
// the task began (commands, other tasks working beside it) is folded under them
function ChangesScreen({ sid }) {
  const [d, err] = useLive(() => api("changes", { sid }), [sid], (m) => !m.sid || m.sid === sid, 60000, "changes:" + sid);
  const [more, setMore] = useKept("chg.more:" + sid, false);
  if (!d) return html`<${Loading} err=${err}/>`;
  const shown = d.files.length + d.more.length;
  return html`<div class="chg">
    <div class="chg-h"><h2>${t("chg.title")}</h2>
      <a class="dim" href=${"#/s/" + sid}>${d.project}${d.title ? " · " + d.title : ""}</a>
      ${d.git && d.since ? html`<div class="dim small">${dotted([t("chg.since", { at: when(d.since) }),
        d.n ? html`<span>${filesN(d.n)} <${Counts} f=${d}/></span>` : null])}</div>` : ""}</div>
    ${!d.git ? html`<div class="empty">${t("chg.nogit")}</div>`
      : !shown ? html`<div class="empty">${t("chg.none")}</div>`
      : html`${d.files.length > 0 && html`<div class="list chg-list">${d.files.map((f) => html`<${Row} key=${f.p} sid=${sid} f=${f}/>`)}</div>`}
        ${d.more.length > 0 && html`<button class="chg-more" aria-expanded=${more} onClick=${() => setMore(!more)}>
            <span><b>${t("chg.more", { n: d.more.length })}</b><span class="dim small">${t("chg.more.about")}</span></span>
            <span class=${"chev" + (more ? " open" : "")}>${ic("chev", 16)}</span></button>
          ${more && html`<div class="list chg-list rest">${d.more.map((f) => html`<${Row} key=${f.p} sid=${sid} f=${f}/>`)}</div>`}`}
        ${d.cut && html`<div class="dim small chg-cut">${t("fv.dir_cut", { n: shown, total: d.total })}</div>`}`}
  </div>`;
}

// one file's change over the screen, like a file from a link: each one a step in the history, Back closes the top one
function DiffHost() {
  const [trail, setTrail] = useState([]);
  useEffect(() => on("diff", (x) => { openLayer(() => setTrail((tr) => tr.slice(0, -1))); setTrail((tr) => tr.concat([x])); }), []);
  const open = trail.length > 0;
  useNoFold(open);
  useBackFor(open);
  return trail.map((x, k) => html`<${DiffView} key=${k} job=${x}/>`);
}

// job: {sid, p, line} — line: a finding's place, in the file as it is now: that line in the middle, marked; when the
// pieces around the changes don't hold it, the whole file is asked for. A file that didn't change opens as it is
function DiffView({ job }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const [full, setFull] = useState(false);
  const [upto, setUpto] = useState(ROWS);
  const body = useRef(null);
  useEffect(() => {
    let alive = true;
    api("diff", { sid: job.sid, p: job.p, full }).then((x) => {
      if (!alive) return;
      // the line asked for lies between the pieces: the whole file has it
      if (job.line && !full && !x.same && !x.cut && x.rows.length && !x.rows.some((r) => r[2] === job.line)) { setFull(true); return; }
      const at = job.line ? x.rows ? x.rows.findIndex((r) => r[2] === job.line) : -1 : -1;
      if (at >= 0) setUpto((u) => Math.max(u, at + 200));
      setD(x);
      setErr("");
    }, (e) => alive && setErr(e.message));
    return () => { alive = false; };
  }, [full]);
  useEffect(() => {
    const el = job.line && body.current && body.current.querySelector(".dl.hit");
    if (el) el.scrollIntoView({ block: "center" });
  }, [d]);
  const rows = useMemo(() => (d && d.rows ? d.rows : []), [d]);
  if (d && d.same) return html`<${FileView} job=${{ sid: job.sid, p: job.p.replace(/[%#]/g, encodeURIComponent) + (job.line ? "#L" + job.line : ""), base: "" }}/>`;
  const close = () => history.back();
  const name = last(job.p), dir = folderOf(job.p);
  const k = d ? kind(d) : "";
  const sub = d && dotted([dir || null, d.add || d.del ? html`<${Counts} f=${d}/>` : null, k || null, d.was ? t("chg.was", { p: d.was }) : null]);
  const whole = d && !d.bin && (d.st === "M" || d.st === "R" || d.st === "T");      // a new or a removed file is whole already
  let view;
  if (err) view = html`<div class="empty">${err}</div>`;
  else if (!d) view = html`<div class="empty" data-wait="1">${t("loading")}</div>`;
  else if (d.bin) view = html`<div class="empty">${t("chg.bin.note")}</div>`;
  else if (!rows.length) view = html`<div class="empty">${t("chg.same")}</div>`;
  else {
    view = html`<div class="df-code">${rows.slice(0, upto).map((r, n) => r[0] === GAP
        ? html`<div class="dl gap" key=${n}>${t("chg.gap", { n: r[3], lines: plural(r[3], "line") })}</div>`
        : html`<div key=${n} class=${"dl " + (r[0] === ADDED ? "a" : r[0] === REMOVED ? "d" : "k") + (job.line && r[2] === job.line ? " hit" : "")}>
          <span class="n">${r[0] === REMOVED ? r[1] : r[2]}</span><span class="s">${r[0] === ADDED ? "+" : r[0] === REMOVED ? "−" : ""}</span><span class="c">${r[3] || " "}</span></div>`)}</div>
      ${rows.length > upto && html`<button class="link more2" onClick=${() => setUpto(upto + ROWS)}>${t("fv.more_lines", { n: rows.length - upto })}</button>`}
      ${d.cut && html`<div class="dim small fv-cut">${t("chg.cut")}</div>`}`;
  }
  return html`<div class="fv df" role="dialog" aria-label=${name}>
    <div class="fv-top">
      <button class="fv-b" aria-label=${t("fv.back")} onClick=${close}>${ic("back", 24)}</button>
      <div class="fv-h"><b>${name}</b>${sub && html`<div class="dim">${sub}</div>`}</div>
      ${whole && html`<button class="chip fv-t" onClick=${() => { setD(null); setFull(!full); }}>${t(full ? "chg.parts" : "chg.full")}</button>`}
    </div>
    <div ref=${body} class="fv-body">${view}</div>
    ${d && d.here && html`<div class="fv-bar"><button class="btn ghost wide" onClick=${() => emit("file", { sid: job.sid, p: job.p.replace(/[%#]/g, encodeURIComponent), base: "" })}>${ic("file", 18)} ${t("chg.open")}</button></div>`}
  </div>`;
}

export { ChangesScreen, DiffHost };
