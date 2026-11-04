// Memory of the computer running tasks, not this phone. A failed or stale reading is never a live warning.
import { api, useConn, useLive } from "../core/conn.js";
import { tg } from "../core/tg.js";
import { t } from "../i18n.js";
import { html } from "../vendor/htm-preact-3.1.1.js";
import { bytes, hhmm, useNow } from "./kit.js";

const memoryLevel = (m) => {
  if (!m || !Number.isFinite(m.mem_total) || m.mem_total <= 0 || !Number.isFinite(m.mem_used) || m.mem_used < 0) return null;
  const pct = Math.min(100, Math.round(m.mem_used / m.mem_total * 100));
  return { pct, level: pct >= 95 ? "bad" : pct >= 85 ? "warn" : "" };
};

function MemoryStatus() {
  const c = useConn(), now = useNow(5000);
  const [m, err] = useLive(() => document.hidden || tg && tg.isActive === false ? Promise.resolve(null)
    : api("memory").then((v) => v && { ...v, received: Date.now() / 1000 }), [], () => false, 10000);
  const status = memoryLevel(m);
  // an older daemon or an unsupported system still runs every other part of the app; and only memory running low is
  // worth a line on every screen — otherwise it is on Home's RAM tile and in Resources (the owner, 2026-11-04)
  if (!status || !status.level) return "";
  const stale = !c.ready || !!err || now - m.received > 30;
  return html`<aside class=${"memory-status " + (stale ? "stale" : status.level)} aria-label=${t("memory.title")}>
    <a href="#/load" title=${t("memory.title")}>${t("memory.amount", { used: bytes(m.mem_used), total: bytes(m.mem_total), pct: status.pct })}</a>
    ${stale ? html`<span>${t("memory.stale", { hm: Number.isFinite(m.now) ? hhmm(new Date(m.now * 1000)) : "—" })}</span>`
      : status.level && html`<span role="status">${t("memory." + status.level)}</span>`}
  </aside>`;
}

export { MemoryStatus, memoryLevel };
