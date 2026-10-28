// Pult — the Telegram Mini App. Claude Code sessions on the Mac: what waits for an answer, what is working, full
// transcripts, answers to questions and permission requests, new tasks, usage. Data comes from the Mac via the relay.
import { html, render, useState, useEffect } from "./vendor/htm-preact-3.1.1.js";
import { t } from "./i18n.js";
import { on, useConn } from "./core/conn.js";
import { back, useRoute } from "./core/nav.js";
import { tg } from "./core/tg.js";
import { UPD_RUN_MAX } from "./core/update.js";
import { Home } from "./screens/home.js";
import { NewProject, NewTask, Project, Projects } from "./screens/projects.js";
import { Resources } from "./screens/resources.js";
import { FileHost, Session, TurnFilesScreen } from "./screens/session.js";
import { Settings, ddmm } from "./screens/settings.js";
import { Tags } from "./screens/tags.js";
import { hhmm, ic } from "./ui/kit.js";
import { Load } from "./ui/load.js";
import { EditHost, ViewHost } from "./ui/pics.js";

// a short note at the bottom of the screen for a moment — an answer went — outliving the card it came from
function Toast() {
  const [m, setM] = useState(null);
  useEffect(() => on("toast", (text) => setM({ text, k: Date.now() })), []);
  useEffect(() => { if (!m) return undefined; const id = setTimeout(() => setM(null), 1800); return () => clearTimeout(id); }, [m]);
  return m ? html`<div class="toast" role="status" key=${m.k}>${m.text}</div>` : "";
}

function Banner() {
  const c = useConn();
  const upd = c.updating && Date.now() - c.updating < UPD_RUN_MAX && ["connecting", "offline", "auth", "nomac"].includes(c.state);
  const text = c.state === "denied" ? t(["expired", "out", "locked"].includes(c.why) ? "banner.denied." + c.why : "banner.denied")
    : upd ? t(c.updSrv ? "banner.srv" : "banner.updating")
    : ["connecting", "offline", "auth", "nomac"].includes(c.state) ? t("banner." + c.state) : "";
  const stale = c.fresh && ["offline", "nomac"].includes(c.state) ? " " + t("banner.stale", { hm: hhmm(new Date(c.fresh)) }) : "";
  const g = c.gone && c.state === "nomac" && !upd ? new Date(c.gone) : null;
  const gone = g ? " " + t("banner.gone", { when: g.toDateString() === new Date().toDateString() ? hhmm(g) : ddmm(c.gone / 1000) + ", " + hhmm(g) }) : "";
  // installing is no alarm: the calm colour, not the computer-offline red it had (2026-10-27)
  return text ? html`<div class=${"banner " + (upd ? "updating" : c.state)} role="status">${text}${gone}${stale}</div>` : "";
}

function App() {
  const r = useRoute();
  const [, relang] = useState(0);
  useEffect(() => { const off = on("lang", () => relang((x) => x + 1)); relang((x) => x + 1); return off; }, []);
  useEffect(() => {
    if (!tg || !tg.BackButton) return;
    if (r.name === "home") tg.BackButton.hide(); else tg.BackButton.show();
    tg.BackButton.onClick(back);
    return () => tg.BackButton.offClick(back);
  }, [r.name, r.id]);
  const screen = r.name === "s" ? html`<${Session} sid=${r.id}/>`
    : r.name === "f" ? html`<${TurnFilesScreen} sid=${r.id} turn=${r.q.get("t")}/>`
    : r.name === "p" ? html`<${Project} key=${r.id + "?" + (r.q.get("tag") || "") + "/" + (r.q.get("topic") || "")} pkey=${r.id} tag=${r.q.get("tag")} topic=${r.q.get("topic")}/>`
    : r.name === "tags" ? html`<${Tags} key=${r.id} pkey=${r.id} open=${r.q.get("open")}/>`
    : r.name === "projects" ? html`<${Projects}/>`
    : r.name === "new" ? html`<${NewTask} pkey=${r.q.get("pkey")}/>`
    : r.name === "newproject" ? html`<${NewProject}/>`
    : r.name === "usage" ? html`<${Resources}/>`
    : r.name === "load" ? html`<${Load}/>`
    : r.name === "settings" ? html`<${Settings}/>`
    : html`<${Home}/>`;
  const tab = (name, h, label, icon) => html`<a class=${(r.name === name ? "on" : "") + (name === "new" ? " new" : "")} href=${h}><span class="ti">${ic(icon, 22)}</span><span class="tl">${label}</span></a>`;
  return html`<${Banner}/><main class=${r.name === "s" ? "with-composer" : ""}>${screen}</main>
    ${r.name !== "s" && html`<nav class="tabs">${tab("home", "#/", t("tab.home"), "home")}${tab("projects", "#/projects", t("tab.projects"), "folder")}${tab("usage", "#/usage", t("tab.res"), "gauge")}${tab("new", "#/new", t("tab.new"), "plus")}</nav>`}
    <${EditHost}/><${ViewHost}/><${FileHost}/><${Toast}/>`;
}

render(html`<${App}/>`, document.getElementById("app"));
