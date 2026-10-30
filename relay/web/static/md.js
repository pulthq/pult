// Pult: markdown of Claude's replies → HTML. Safe by design: all text is escaped first,
// only our own tags are inserted; web links are http(s) only and open through Telegram (data-ext); a link to a
// project file has no address at all — the app opens it over the screen (data-file), the computer decides what it shows.
// The app can give Claude commands, so foreign HTML from a reply must never run inside it.
// A link's words can't hide where it leads: unless they show that very address, it follows in brackets (a web page
// may talk Claude into writing a link). Non-Latin names stay in their xn-- form, so a look-alike letter doesn't pass.

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

export function hostOf(u) {
  try { const h = new URL(u).hostname; return h.startsWith("www.") ? h.slice(4) : h; } catch (e) { return ""; }
}
function link(t, u) {
  const h = hostOf(u), s = t.trim();
  const a = '<a href="' + esc(u) + '" data-ext>' + esc(t) + "</a>";
  return !h || hostOf(s.includes("://") ? s : "http://" + s) === h ? a : a + ' <span class="host">(' + esc(h) + ")</span>";
}

// a link in the app: a web page opens through Telegram; a link to a project file [name](path), as Claude writes them
// (stage F5), is a tap that opens it in the app. Any other scheme (mailto:, vscode:…) or a bare #anchor can't be
// opened on the phone: the name, and the target as code
const APP = {
  web: link,
  other: (t, u) => (!/^[a-z][\w+.-]+:(?!\/\/\/)/i.test(u) && !u.startsWith("#")
    ? '<a class="flink" role="link" tabindex="0" data-file="' + esc(u) + '">' + esc(t) + "</a>"
    : t === u || u.endsWith("/" + t) ? "<code>" + esc(u) + "</code>" : esc(t) + " <code>" + esc(u) + "</code>"),
};
// a link on the clipboard (stage Zh, step 3): a web page as a plain link; anything else opens nowhere it is pasted —
// its name and where it points, as Pult writes it in the topic (pult_render._inline)
const CLIP = {
  web: (t, u) => '<a href="' + esc(u) + '">' + esc(t) + "</a>",
  other: (t, u) => (t === u || u.endsWith("/" + t) ? "<code>" + esc(u) + "</code>" : esc(t) + " (<code>" + esc(u) + "</code>)"),
};

// one line's words: code, links, bold and italics; `links` says what a link becomes. The app's own is inline() — one
// argument, since blocks() hands it to map(), which passes the index second
const inline = (s) => spans(s, APP);
function spans(s, links) {
  const keep = [];
  const hold = (h) => "\u0000" + (keep.push(h) - 1) + "\u0000";
  s = s.replace(/\u0000/g, "");        // the placeholders' own mark never comes from the words (it showed "undefined")
  s = s.replace(/`([^`\n]+)`/g, (_, c) => hold("<code>" + esc(c) + "</code>"));
  s = s.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, t, u) => hold(links.web(t, u)));
  s = s.replace(/\[([^\]\n]+)\]\(([^\s)]+)\)/g, (_, t, u) => hold(links.other(t, u)));
  s = esc(s);
  s = s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  s = s.replace(/(^|[^\w*])\*(?!\s)([^*\n]+?)\*(?![\w*])/g, "$1<i>$2</i>");
  // a link's words may hold code — Claude writes [`app.js`](src/app.js) — so a placeholder can sit inside another: put
  // them back until none is left (one pass showed "�0�" for the name, review 2026-10-27). Each holds only older ones
  for (let k = 0; k < 8 && /\u0000\d+\u0000/.test(s); k++) s = s.replace(/\u0000(\d+)\u0000/g, (_, i) => keep[+i] ?? "");
  return s;
}

function table(rows) {
  const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
  const body = rows.filter((r) => !/^\s*\|?\s*:?-{2,}/.test(r));
  const [head, ...rest] = body;
  if (head === undefined) return "";   // separators alone: nothing to show (it threw, and the screen stopped updating)
  return '<div class="tbl"><table><thead><tr>' + cells(head).map((c) => "<th>" + c + "</th>").join("") +
    "</tr></thead><tbody>" + rest.map((r) => "<tr>" + cells(r).map((c) => "<td>" + c + "</td>").join("") + "</tr>").join("") +
    "</tbody></table></div>";
}

function blocks(text) {
  const lines = text.split("\n");
  const out = [];
  let para = [];
  const flush = () => { if (para.length) out.push("<p>" + para.map(inline).join("<br>") + "</p>"); para = []; };
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (/^\s*\|/.test(l) && /^\s*\|/.test(lines[i + 1] || "")) {
      flush();
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
      i--;
      out.push(table(rows));
    } else if (/^\s{0,3}#{1,6}\s+/.test(l)) {
      flush();
      out.push("<h4>" + inline(l.replace(/^\s*#+\s+/, "").replace(/\s*#+\s*$/, "")) + "</h4>");
    } else if (/^\s*([-*•]|\d+[.)])\s+/.test(l)) {
      flush();
      const ordered = /^\s*\d/.test(l);
      const items = [];
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) {
        items.push(inline(lines[i].replace(/^\s*([-*•]|\d+[.)])\s+/, "")));
        i++;
      }
      i--;
      const tag = ordered ? "ol" : "ul";
      out.push("<" + tag + ">" + items.map((x) => "<li>" + x + "</li>").join("") + "</" + tag + ">");
    } else if (/^\s*>\s?/.test(l)) {
      flush();
      const q = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ""));
      i--;
      out.push("<blockquote>" + q.map(inline).join("<br>") + "</blockquote>");
    } else if (!l.trim()) {
      flush();
    } else {
      para.push(l);
    }
  }
  flush();
  return out.join("");
}

export function md(src) {
  try {
    return String(src ?? "").split(/(```[\s\S]*?```)/g).map((p) => {
      if (p.startsWith("```") && p.endsWith("```") && p.length >= 6) {
        const body = p.slice(3, -3).replace(/^[\w+.-]*\n/, "").replace(/\n$/, "");
        return "<pre><code>" + esc(body) + "</code></pre>";
      }
      return blocks(p);
    }).join("");
  } catch (e) {
    // whatever the words, the screen goes on: md() runs inside a render, and an error there stopped the whole screen
    return "<p>" + esc(src).replace(/\n/g, "<br>") + "</p>";
  }
}

// ---------- Claude's words for the clipboard (stage Zh, step 3) ----------

// HTML the way Telegram itself puts a message on the clipboard (CustomHtml.toHtml in Telegram for Android): a <br> for
// every line break, runs of spaces kept with &nbsp;, only <b> <i> <code> <a> <pre> <blockquote> — what its paste turns
// back into formatting (CopyUtilities.fromHTML; <code> stays plain words there). Notes, mail and documents read the
// same. Telegram has no headings, lists or tables: a heading goes bold, a list keeps its marks as words, a table goes
// as a block of monospace — as Pult writes Claude's words in the topic (pult_render.md_to_html)
const spaced = (h) => h.replace(/ {2,}/g, (m) => "&nbsp;".repeat(m.length - 1) + " ");
const isRow = (l) => /^\s*\|/.test(l);
const isQuote = (l) => /^\s*>\s?/.test(l);

function clipLines(text) {
  const lines = text.split("\n");
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (isRow(l) && isRow(lines[i + 1] || "")) {
      const rows = [];
      while (i < lines.length && isRow(lines[i])) rows.push(spaced(esc(lines[i++])));
      i--;
      out.push("<pre>" + rows.join("<br>") + "</pre>");
    } else if (isQuote(l)) {
      const q = [];
      while (i < lines.length && isQuote(lines[i])) q.push(spaced(spans(lines[i++].replace(/^\s*>\s?/, ""), CLIP)));
      i--;
      out.push("<blockquote>" + q.join("<br>") + "</blockquote>");
    } else if (/^\s{0,3}#{1,6}\s+/.test(l)) {
      out.push("<b>" + spaced(spans(l.replace(/^\s*#+\s+/, "").replace(/\s*#+\s*$/, ""), CLIP)) + "</b>");
    } else {
      const m = /^(\s*)([-*•]|\d+[.)])\s+/.exec(l);       // a numbered item keeps its number, a dash becomes a bullet
      out.push(spaced(m ? m[1] + (/\d/.test(m[2]) ? m[2] : "•") + " " + spans(l.slice(m[0].length), CLIP) : spans(l, CLIP)));
    }
  }
  return out.join("<br>");
}

export function clip(src) {
  const text = String(src ?? "").replace(/\r\n?/g, "\n").replace(/^\n+|\s+$/g, "");
  try {
    return text.split(/(```[\s\S]*?```)/g).map((p) => {
      if (p.startsWith("```") && p.endsWith("```") && p.length >= 6) {
        const inner = p.slice(3, -3), m = /^([\w+.-]*)\n/.exec(inner);
        const body = (m ? inner.slice(m[0].length) : inner).replace(/\n$/, "");
        // the language goes with the block: Telegram names it over the code
        return "<pre" + (m && m[1] ? ' lang="' + esc(m[1]) + '"' : "") + ">" + spaced(esc(body)).replace(/\n/g, "<br>") + "</pre>";
      }
      return clipLines(p);
    }).join("");
  } catch (e) {
    return spaced(esc(text)).replace(/\n/g, "<br>");
  }
}

// your own words for the clipboard (2026-10-30): as you wrote them — the app shows them as typed, not read as markdown —
// in the same HTML: a <br> for every line break, runs of spaces kept
export const clipPlain = (src) => spaced(esc(String(src ?? "").replace(/\r\n?/g, "\n").replace(/^\n+|\s+$/g, ""))).replace(/\n/g, "<br>");
