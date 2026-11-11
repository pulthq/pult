// Pult app — what waits for your move, wherever you are in the app: the count on Home's tab and the line in a task
// about another task that waits (review 2026-11-11, UX1). Before, a new "your move" showed on Home alone: while a
// task was being read another one stood with its question, the app silent — and so was Telegram, the app being on screen.
import { html, useEffect, useState } from "../vendor/htm-preact-3.1.1.js";
import { t } from "../i18n.js";
import { api, conn, useLive } from "../core/conn.js";
import { go } from "../core/nav.js";
import { haptic } from "../core/tg.js";
import { ic } from "./kit.js";

// {n: tasks that wait for the owner's move (questions, permissions, outcomes that need them — not plain reports),
//  others: of them, not the task open now, top: the newest of those — {sid, project, what, ts}}. A computer before
// this says nothing of it (no "waiting" among its caps): nothing is asked, nothing shown
const useWaiting = (but) => useLive(() => (conn.caps.includes("waiting") ? api("waiting", but ? { but } : {}) : Promise.resolve(null)), [but])[0];

function WaitBadge() {
  const w = useWaiting();
  return w && w.n > 0 ? html`<span class="tbadge" aria-label=${t("wait.count", { n: w.n })}>${w.n > 99 ? "99+" : w.n}</span>` : null;
}

// the newest "your move" the owner put the line away at, and the newest the phone buzzed for — for this window's life
const seen = { put: 0, felt: 0 };
function WaitLine({ sid }) {
  const w = useWaiting(sid);
  const [, redraw] = useState(0);
  const top = w && w.others > 0 ? w.top : null;
  useEffect(() => { if (top && top.ts > seen.felt) { seen.felt = top.ts; haptic("warning"); } }, [top && top.ts]);
  if (!top || top.ts <= seen.put) return null;
  const one = w.others === 1;
  const open = () => go(one ? "#/s/" + top.sid : "#/");
  return html`<div class="wait-line"><button class="wl-go" onClick=${open}>
      <b>${one ? t("wait.one") : t("wait.many", { n: w.others })}</b>
      ${one && html`<span class="wl-what">${top.project} — ${t("wait." + top.what)}</span>`}<span class="wl-chev">${ic("chev", 16)}</span></button>
    <button class="wl-x" aria-label=${t("wait.hide")} onClick=${() => { seen.put = top.ts; redraw((x) => x + 1); }}>${ic("x", 16)}</button></div>`;
}

export { WaitBadge, WaitLine, seen, useWaiting };
