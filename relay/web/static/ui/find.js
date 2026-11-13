// Pult app — a search of tasks (review 2026-11-11, UX4; the owner's yes, Q180): a field on top of Projects — every
// project — and of a project's screen — that project. By the tasks' titles, their first requests and their tags; and,
// with search over everything (stage И, Q187), in what the owner and the models said and in the projects' documents:
// a place opens the task right there, a document — on its line. Before, an earlier task could only be scrolled to.
import { html, useEffect, useRef, useState } from "../vendor/htm-preact-3.1.1.js";
import { plural, t } from "../i18n.js";
import { api, conn, emit } from "../core/conn.js";
import { go, useKept } from "../core/nav.js";
import { agoShort, ic, plainField } from "./kit.js";

// the words asked for as one pattern: two letters and more, ё and е alike (the computer's index folds them the same way)
function wordsRx(q) {
  const words = String(q || "").split(/\s+/).filter((w) => w.length > 1);
  if (!words.length) return null;
  const esc = (w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/[её]/gi, "[её]");
  return new RegExp(words.sort((a, b) => b.length - a.length).map(esc).join("|"), "gi");
}

// the words asked for, marked in a title or a piece of text: plain text in, text and <mark>s out — nothing of it is
// read as markup
function marked(text, q) {
  const rx = wordsRx(q);
  const s = String(text || "");
  if (!rx) return [s];
  const out = [];
  let at = 0;
  for (const m of s.matchAll(rx)) {
    if (!m[0]) continue;
    if (m.index > at) out.push(s.slice(at, m.index));
    out.push(html`<mark>${m[0]}</mark>`);
    at = m.index + m[0].length;
  }
  if (at < s.length) out.push(s.slice(at));
  return out;
}

// the same words marked in a message already made into markup (md.js): only its text between tags, never inside one
// or an entity
function markHtml(h, q) {
  const rx = wordsRx(q);
  if (!rx) return h;
  return h.replace(/(<[^>]*>)|([^<]+)/g, (m, tag, text) => tag || text.replace(/(&[#\w]+;)|([^&]+)/g,
    (m2, ent, plain) => ent || plain.replace(rx, (w) => "<mark>" + w + "</mark>")));
}

// a real name as a link to a file: % and # stay themselves (the viewer reads #L<line> as the line)
const lit = (s) => s.replace(/[%#]/g, encodeURIComponent);

// a task where the words were said: its title, its project, the newest place; "N more places" shows the rest. A tap on
// a place opens the task at it, the words marked there
function Said({ g, q, pkey }) {
  const [all, setAll] = useState(false);
  const open = (x) => go("#/s/" + g.sid + "?at=" + x.at + "&q=" + encodeURIComponent(q));
  const shown = all ? g.places : g.places.slice(0, 1);
  return html`<div class="item said">
    <button class="said-h" onClick=${() => open(g.places[0])}>
      <div class="item-h"><b>${g.title}</b><span class="meta"><span class="dim nowrap">${agoShort(g.places[0].ts)}</span></span></div>
      <div class="ln">${pkey ? "" : html`<span class="found-p">${g.project}</span>`}${g.state ? html`<span class=${"found-s " + g.state}>${t("find.st." + g.state)}</span>` : ""}</div></button>
    ${shown.map((x) => html`<button key=${x.at} class="said-p" onClick=${() => open(x)}>
      <span class="said-who">${x.me ? t("find.me") : g.who}${all ? html` · <span class="nowrap">${agoShort(x.ts)}</span>` : ""}:</span> ${marked(x.snip, q)}</button>`)}
    ${g.n > 1 && !all ? html`<button class="link said-more" onClick=${() => setAll(true)}>${t("find.more_here", { n: g.n - 1, places: plural(g.n - 1, "place") })}</button>` : ""}
    ${all && g.n > g.places.length ? html`<div class="dim small said-cut">${t("find.cut_here", { n: g.n - g.places.length })}</div>` : ""}
  </div>`;
}

// a document where the words are: its name and folder, the place; a tap opens it on that line
function Doc({ d, q, pkey }) {
  const name = d.p.slice(d.p.lastIndexOf("/") + 1);
  const dir = d.p.slice(0, Math.max(0, d.p.lastIndexOf("/")));
  const x = d.places[0];
  return html`<button class="item said doc" onClick=${() => emit("file", { pkey: d.pkey, p: lit(d.p) + "#L" + x.line })}>
    <div class="item-h"><b>${ic("file", 15)} ${name}</b><span class="meta"><span class="dim nowrap">${agoShort(x.ts)}</span></span></div>
    <div class="ln">${pkey ? "" : html`<span class="found-p">${d.project}</span>`}${dir ? html`<span class="found-by">${dir}</span>` : ""}${d.n > 1 ? html`<span>${t("find.doc_n", { n: d.n, places: plural(d.n, "place") })}</span>` : ""}</div>
    <div class="said-p">${marked(x.snip, q)}</div></button>`;
}

// The field, and under it — what it found; with nothing asked, the screen's own content (children). What was asked
// and found stays for this window's life: Back from a task comes to the same list. A computer that can't search
// (no "find" among its caps) shows no field; one before stage И ("said") — the titles alone, as before
function Find({ pkey, children }) {
  const name = "find:" + (pkey || "");
  const [q, setQ] = useKept(name + ":q", "");
  const [mine, setMine] = useKept(name + ":m", false);
  const [found, setFound] = useKept(name + ":r", null);          // {q, mine, rows, more, said, docs…} — what the computer found
  const asked = useRef(0);
  const said = conn.caps.includes("said");
  useEffect(() => {
    const words = q.trim();
    if (words.length < 2) { if (found) setFound(null); return undefined; }
    if (found && found.q === words && !!found.mine === !!mine) return undefined;
    const n = ++asked.current;
    const args = Object.assign({ q: words }, pkey ? { pkey } : {}, said && mine ? { mine: true } : {});
    const timer = setTimeout(() => api("find", args)
      .then((r) => { if (n === asked.current) setFound(Object.assign({}, r, { q: words, mine })); })
      .catch(() => { if (n === asked.current) setFound({ q: words, mine, rows: [], more: false, err: true }); }), 250);
    return () => clearTimeout(timer);
  }, [q, pkey, mine]);
  if (!conn.caps.includes("find")) return children;
  const on = q.trim().length >= 2;
  const ready = on && found && found.q === q.trim() && !!found.mine === !!mine;
  const rows = ready ? (mine ? [] : found.rows) : null;
  const idx = ready && found.index;
  const saidRows = (ready && found.said) || [];
  const docs = (ready && !mine && found.docs) || [];
  const places = saidRows.reduce((n, g) => n + g.n, 0);
  const none = ready && !rows.length && !saidRows.length && !docs.length;
  // what the search in what was said can't say by itself: it is off, or still being built
  const note = !idx ? "" : idx.off ? t("find.idx.off") : idx.ready === false ? t("find.idx.wait") : "";
  const chips = said && on && !(idx && (idx.off || idx.none)) ? html`<div class="find-chips">
      ${[[false, t("find.all")], [true, t("find.mine")]].map(([v, label]) => html`<button key=${label} class=${"chip" + (!!mine === v ? " on" : "")} onClick=${() => setMine(v)}>${label}</button>`)}</div>` : "";
  return html`<div class="find"><label class="find-f">${ic("search", 18)}
      <input ref=${plainField} type="search" enterkeyhint="search" placeholder=${t(pkey ? "find.ph.p" : "find.ph")} value=${q} onInput=${(e) => setQ(e.target.value)}/>
      ${q ? html`<button class="find-x" aria-label=${t("find.clear")} onClick=${() => setQ("")}>${ic("x", 16)}</button>` : ""}</label>${chips}</div>
    ${!on ? children
      : rows == null ? html`<div class="empty small" data-wait="1">${t("find.wait")}</div>`
      : none ? html`<div class="empty small">${t(found.err ? "find.err" : found.said ? "find.none2" : "find.none")}</div>${note ? html`<div class="dim small center">${note}</div>` : ""}`
      : html`${rows.length ? html`<div class="list found">${rows.map((r) => html`<button key=${r.sid} class="item brow" onClick=${() => go("#/s/" + r.sid)}>
          <div class="item-h"><b>${marked(r.title, q)}</b><span class="meta"><span class="dim nowrap">${agoShort(r.last)}</span></span></div>
          <div class="ln">${pkey ? "" : html`<span class="found-p">${r.project}</span>`}${r.state ? html`<span class=${"found-s " + r.state}>${t("find.st." + r.state)}</span>` : ""}
            ${r.by === "tag" ? html`<span class="found-by">${t("find.by.tag")} ${marked(r.tags.join(" · "), q)}</span>`
              : r.by === "ask" ? html`<span class="found-by">${marked(r.ask, q)}</span>` : ""}</div></button>`)}</div>
        ${found.more ? html`<div class="dim small center">${t("find.more", { n: rows.length })}</div>` : ""}` : ""}
        ${saidRows.length ? html`<h3>${t("find.said", { n: places, places: plural(places, "place"), m: saidRows.length, tasks: plural(saidRows.length, "task_in") })}</h3>
          <div class="list found">${saidRows.map((g) => html`<${Said} key=${g.sid} g=${g} q=${q} pkey=${pkey}/>`)}</div>
          ${found.said_more ? html`<div class="dim small center">${t("find.said_more")}</div>` : ""}` : ""}
        ${docs.length ? html`<h3>${t("find.docs", { n: docs.length })}</h3>
          <div class="list found">${docs.map((d) => html`<${Doc} key=${d.p} d=${d} q=${q} pkey=${pkey}/>`)}</div>` : ""}
        ${note ? html`<div class="dim small center">${note}</div>` : ""}`}`;
}

export { Find, markHtml, marked };
