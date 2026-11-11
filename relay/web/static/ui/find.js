// Pult app — a search of tasks (review 2026-11-11, UX4; the owner's yes, Q180): a field on top of Projects — every
// project — and of a project's screen — that project. By the tasks' titles, their first requests and their tags; not
// by what was said in them. Before, an earlier task could only be scrolled to, forty to a project.
import { html, useEffect, useRef } from "../vendor/htm-preact-3.1.1.js";
import { t } from "../i18n.js";
import { api, conn } from "../core/conn.js";
import { go, useKept } from "../core/nav.js";
import { agoShort, ic, plainField } from "./kit.js";

// the words asked for, marked in a title: plain text in, text and <mark>s out — nothing of the title is read as markup
function marked(text, q) {
  const words = q.toLowerCase().split(/\s+/).filter((w) => w.length > 1);
  const low = String(text || "").toLowerCase();
  const cuts = [];
  for (const w of words) for (let i = low.indexOf(w); i >= 0; i = low.indexOf(w, i + w.length)) cuts.push([i, i + w.length]);
  cuts.sort((a, b) => a[0] - b[0]);
  const out = [];
  let at = 0;
  for (const [a, b] of cuts) {
    if (a < at) continue;
    if (a > at) out.push(text.slice(at, a));
    out.push(html`<mark>${text.slice(a, b)}</mark>`);
    at = b;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}

// The field, and under it — what it found; with nothing asked, the screen's own content (children). What was asked
// and found stays for this window's life: Back from a task comes to the same list. A computer that can't search
// (no "find" among its caps) shows no field
function Find({ pkey, children }) {
  const name = "find:" + (pkey || "");
  const [q, setQ] = useKept(name + ":q", "");
  const [found, setFound] = useKept(name + ":r", null);          // {q, rows, more} — what the computer found for q
  const asked = useRef(0);
  useEffect(() => {
    const words = q.trim();
    if (words.length < 2) { if (found) setFound(null); return undefined; }
    if (found && found.q === words) return undefined;
    const n = ++asked.current;
    const timer = setTimeout(() => api("find", pkey ? { q: words, pkey } : { q: words })
      .then((r) => { if (n === asked.current) setFound({ q: words, rows: r.rows, more: r.more }); })
      .catch(() => { if (n === asked.current) setFound({ q: words, rows: [], more: false, err: true }); }), 250);
    return () => clearTimeout(timer);
  }, [q, pkey]);
  if (!conn.caps.includes("find")) return children;
  const on = q.trim().length >= 2;
  const rows = on && found && found.q === q.trim() ? found.rows : null;
  return html`<div class="find"><label class="find-f">${ic("search", 18)}
      <input ref=${plainField} type="search" enterkeyhint="search" placeholder=${t(pkey ? "find.ph.p" : "find.ph")} value=${q} onInput=${(e) => setQ(e.target.value)}/>
      ${q ? html`<button class="find-x" aria-label=${t("find.clear")} onClick=${() => setQ("")}>${ic("x", 16)}</button>` : ""}</label></div>
    ${!on ? children
      : rows == null ? html`<div class="empty small" data-wait="1">${t("find.wait")}</div>`
      : rows.length === 0 ? html`<div class="empty small">${t(found.err ? "find.err" : "find.none")}</div>`
      : html`<div class="list found">${rows.map((r) => html`<button key=${r.sid} class="item brow" onClick=${() => go("#/s/" + r.sid)}>
          <div class="item-h"><b>${marked(r.title, q)}</b><span class="meta"><span class="dim nowrap">${agoShort(r.last)}</span></span></div>
          <div class="ln">${pkey ? "" : html`<span class="found-p">${r.project}</span>`}${r.state ? html`<span class=${"found-s " + r.state}>${t("find.st." + r.state)}</span>` : ""}
            ${r.by === "tag" ? html`<span class="found-by">${t("find.by.tag")} ${marked(r.tags.join(" · "), q)}</span>`
              : r.by === "ask" ? html`<span class="found-by">${marked(r.ask, q)}</span>` : ""}</div></button>`)}</div>
        ${found.more ? html`<div class="dim small center">${t("find.more", { n: rows.length })}</div>` : ""}`}`;
}

export { Find, marked };
