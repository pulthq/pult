// Pult app — pictures: attaching from the phone, the editor (turn, mirror, cut), a picture on the whole screen.
// Moved from app.js as it was (review 2026-10-27, 6.4).
import { api, emit, on } from "../core/conn.js";
import { useOverlay } from "../core/nav.js";
import { alertBox, haptic, tg } from "../core/tg.js";
import { t } from "../i18n.js";
import { html, useEffect, useRef, useState } from "../vendor/htm-preact-3.1.1.js";
import { ic, num } from "./kit.js";


// ---------- pictures from the phone ----------

// an edit: quarter turns clockwise, mirrored or not (after the turn), the frame in shares of the turned picture, and
// the frame's proportion (pixel width / height, null — free) with the chip that set it
const FULL = { x: 0, y: 0, w: 1, h: 1 };
const PLAIN = { rot: 0, flip: false, cut: FULL, ratio: null, rk: "free" };
const plain = (e) => !e || (!e.rot && !e.flip && !e.cut.x && !e.cut.y && e.cut.w === 1 && e.cut.h === 1);
const loadPic = (file) => new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = no; i.src = URL.createObjectURL(file); });
const turned = (img, e) => (e.rot % 2 ? [img.naturalHeight, img.naturalWidth] : [img.naturalWidth, img.naturalHeight]);
// the picture turned and mirrored, the frame `cut` cut out, at scale k → into canvas c. The browser turns a camera
// photo upright by its EXIF itself, before any of this
function paint(c, img, e, cut, k) {
  const [W, H] = turned(img, e);
  c.width = Math.max(1, Math.round(cut.w * W * k)); c.height = Math.max(1, Math.round(cut.h * H * k));
  const g = c.getContext("2d");
  g.imageSmoothingQuality = "high";
  g.scale(c.width / (cut.w * W), c.height / (cut.h * H));
  g.translate(-cut.x * W, -cut.y * H);
  if (e.flip) { g.translate(W, 0); g.scale(-1, 1); }
  g.translate(W / 2, H / 2); g.rotate(e.rot * Math.PI / 2);
  g.drawImage(img, -img.naturalWidth / 2, -img.naturalHeight / 2);
  return c;
}
// a picture and its edit → a JPEG no longer than 1600 px, as base64: a few hundred kilobytes instead of megabytes.
// Always from the original file: a frame cut out of the shrunk copy would blur the small print
async function bake(file, e, loaded) {
  const img = loaded || await loadPic(file);
  e = e || PLAIN;
  const [W, H] = turned(img, e);
  const c = paint(document.createElement("canvas"), img, e, e.cut, Math.min(1, 1600 / Math.max(e.cut.w * W, e.cut.h * H)));
  if (!loaded) URL.revokeObjectURL(img.src);
  const blob = await new Promise((ok, no) => c.toBlob((b) => (b ? ok(b) : no(new Error("toBlob"))), "image/jpeg", 0.88));
  const url = await new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = no; r.readAsDataURL(blob); });
  return { name: (file.name || "screenshot").replace(/\.[^.]+$/, "") + ".jpg", data: url.split(",")[1], preview: url,
    src: file, edit: plain(e) ? null : e };
}
const MAX_PICS = 3;
// a document from the app goes as it is, through the relay's one message (8 MB with base64): 5 MB in all; bigger files
// go to the project's topic in Telegram (up to 20 MB) — stage F
const DOC_MAX = 5 * 1048576;
const asB64 = (f) => new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1] || ""); r.onerror = no; r.readAsDataURL(f); });
function useAttach() {
  const [files, setFiles] = useState([]);
  const pick = async (e) => {
    const list = [...(e.target.files || [])].slice(0, MAX_PICS - files.length);
    e.target.value = "";
    const out = [];
    let docs = files.reduce((n, f) => n + (f.doc ? f.size : 0), 0);
    for (const f of list) {
      if (/^image\/(jpeg|png|gif|webp|heic|heif)$/.test(f.type)) {
        try { out.push(await bake(f)); continue; } catch (err) {
          // a HEIC photo this phone's WebView can't draw goes as a file, as it is (it was dropped — review 2026-10-27, П8)
          if (!/hei[cf]$/.test(f.type)) { alertBox(t("attach.failed")); continue; }
        }
      }
      if (docs + f.size > DOC_MAX) { alertBox(t("attach.big", { name: f.name, mb: num(f.size / 1048576, 1) })); continue; }
      try { out.push({ name: f.name, data: await asB64(f), doc: true, size: f.size }); docs += f.size; } catch (err) { alertBox(t("attach.failed")); }
    }
    setFiles((cur) => cur.concat(out).slice(0, MAX_PICS));
  };
  const edit = (f) => emit("edit", { f, done: (x) => setFiles((cur) => cur.map((y) => (y === f ? x : y))) });
  const drop = (f) => setFiles((cur) => cur.filter((y) => y !== f));
  // a thumbnail opens the pictures on the whole screen, Crop and Remove at the bottom
  const view = (i) => { const pics = files.filter((f) => !f.doc);
    emit("view", { items: pics.map((f) => ({ src: f.preview, f })), at: Math.max(0, pics.indexOf(files[i])), crop: edit, remove: drop }); };
  return { files, pick, view, remove: (i) => setFiles(files.filter((_, k) => k !== i)), clear: () => setFiles([]),
    payload: () => files.map((f) => ({ name: f.name, data: f.data })) };
}
const CLIP = html`<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>`;
// a picture and a file are two pickers, not one. Telegram on Android hands the page's file input to the system as it is
// (onShowFileChooser → createIntent): "pictures" opens the phone's gallery, "any file" its file manager. With one
// "any file" input (0.13.0) the owner's phone came back at once with nothing (2026-10-23: the app off the screen for a
// second), while pictures alone had worked for days. A form shows both buttons; the composer's paperclip opens a menu
// of the two
const PICKERS = [["pic", "image/*", "image"], ["file", undefined, "file"]];
// Telegram on Android now and then loses the gallery's answer. The page's file chooser then waits for it for good, and
// the webview opens no other till the window closes: Chromium opens choosers one by one, the next after the last one
// ended (ChromeClientImpl::OpenFileChooser). The owner's window was 3 h old and opened nothing, a reopened one picked at
// once (2026-10-28); a reload keeps the webview, and the wait with it. The page sees no picker open — the owner's
// gallery is a sheet over Telegram: no blur, nothing leaves the screen (the first rule, "no sign in 3 s — none
// opened", took every open picker for none, 0.18.18). It sees each one end: a file ("change") or closed empty
// ("cancel"). So the rule is Chromium's own: a tap while the last tap's picker never ended finds the queue locked —
// the app says so and offers to close the window, keeping the screen and the words typed for the next start
// (core/nav.js); and a "cancel" sooner than anyone could close a picker is Telegram refusing to open one. Only on
// Android, where Telegram loses the answers
const RETRY_MS = 1500;          // a second tap sooner than this is a double tap: the first one's picker is on its way
const REFUSED_MS = 500;         // no one closes a picker this fast
const onAndroid = () => !!(tg && /^android/.test(tg.platform || ""));
let lastPick = null;            // the last tap on a picker: {t0, done}
function pickerNote(kind, why, ms) {
  const since = tg.initDataUnsafe && tg.initDataUnsafe.auth_date;
  const cv = /Chrome\/(\d+)/.exec(navigator.userAgent || "");
  api("picker", { kind, opened: why === "picked" || why === "closed", ms, why,
    age: since ? Math.max(0, Math.round(Date.now() / 1000 - since)) : null, tgv: tg.version || "", cv: cv ? cv[1] : "" }).catch(() => {});
}
// → true: this tap must not ask Chromium for one more picker (it would only join the queue)
function watchPicker(el, kind, keep) {
  if (!onAndroid()) return false;
  const now = Date.now();
  if (lastPick && !lastPick.done) {
    if (now - lastPick.t0 < RETRY_MS) return true;
    lastPick.done = true;                        // said once: the next tap asks Chromium again
    pickerNote(kind, "stuck", now - lastPick.t0);
    stuck(keep);
    return true;
  }
  const me = lastPick = { t0: now, done: false };
  const end = (e) => {
    el.removeEventListener("change", end);
    el.removeEventListener("cancel", end);
    if (me.done) return;
    me.done = true;
    const ms = Date.now() - me.t0;
    if (e.type === "cancel" && ms < REFUSED_MS) { pickerNote(kind, "refused", ms); stuck(keep); } else pickerNote(kind, e.type === "change" ? "picked" : "closed", ms);
  };
  el.addEventListener("change", end);
  el.addEventListener("cancel", end);
  return false;
}
function stuck(keep) {
  const close = () => {
    try { localStorage.setItem("pult.reopen", JSON.stringify({ h: location.hash, at: Date.now(), k: keep && keep.k, text: (keep && keep.text) || "" })); } catch (e) {}
    tg.close();
  };
  if (!tg.showPopup || !(tg.isVersionAtLeast && tg.isVersionAtLeast("6.2"))) return alertBox(t("pick.stuck"));
  try {
    tg.showPopup({ title: t("pick.stuck.t"), message: t("pick.stuck"), buttons: [{ id: "close", type: "default", text: t("pick.close") }, { type: "cancel" }] },
      (id) => { if (id === "close") close(); });
  } catch (e) { /* Telegram's popup is open already: one is enough */ }
}
// keep — where the words typed live: {k: their draft's key, text}
function Attach({ a, disabled, wide, keep }) {
  const off = disabled || a.files.length >= MAX_PICS;
  const [open, setOpen] = useState(false);
  const [show, hide] = useOverlay(open, setOpen);
  const inputs = useRef({});
  // a label's tap and the menu's el.click() both come to the input as a click
  const watch = (k) => (e) => { if (watchPicker(e.currentTarget, k, keep)) e.preventDefault(); };
  if (wide) return html`<div class="attach-row">${PICKERS.map(([k, accept, icon]) => html`<label key=${k} class=${"clip wide" + (off ? " off" : "")}>
    ${k === "pic" ? ic(icon, 20) : CLIP}<span>${t("attach." + k)}</span>
    <input type="file" accept=${accept} multiple disabled=${off} onClick=${watch(k)} onChange=${a.pick}/></label>`)}</div>`;
  // the inputs stay out of the menu: it closes as the picker opens, and the files come back to an input still there
  const choose = (k) => { const el = inputs.current[k]; hide(); if (el) el.click(); };
  return html`<span class="attach">
    ${PICKERS.map(([k, accept]) => html`<input key=${k} ref=${(el) => { inputs.current[k] = el; }} type="file" accept=${accept} multiple disabled=${off} onClick=${watch(k)} onChange=${a.pick}/>`)}
    <button type="button" class=${"clip" + (off ? " off" : "")} aria-label=${t("attach")} disabled=${off} onClick=${open ? hide : show}>${CLIP}</button>
    ${open && html`<div class="backdrop" onClick=${hide}></div><div class="card attach-menu">
      ${PICKERS.map(([k, , icon]) => html`<button key=${k} class="opt" onClick=${() => choose(k)}>${ic(icon, 18)}<span>${t("attach." + k)}</span></button>`)}</div>`}</span>`;
}
function Thumbs({ a }) {
  return a.files.length ? html`<div class="thumbs">${a.files.map((f, i) => f.doc ? html`<div class="thumb doc" key=${i}>
    <span class="doc-n">${ic("file", 14)} ${f.name}</span>
    <button class="thumb-x" aria-label=${t("attach.remove")} onClick=${() => a.remove(i)}>${ic("x", 14)}</button></div>` : html`<div class="thumb" key=${i}>
    <button class="thumb-view" aria-label=${t("view.open")} onClick=${() => a.view(i)}><img src=${f.preview} alt=""/></button>
    <button class="thumb-x" aria-label=${t("attach.remove")} onClick=${() => a.remove(i)}>${ic("x", 14)}</button></div>`)}</div>` : "";
}

// ---------- the picture editor: turn, mirror, cut ----------

// Telegram's own editor is Telegram's: a Mini App gets a plain file picker. So the app has its own, like Telegram's
// crop screen: the whole picture, a frame with corners, the proportions under it. One finger: no pinch
const RATIOS = [["free"], ["orig"], ["1:1", 1], ["4:3", 4 / 3], ["16:9", 16 / 9]];
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
// the frame after dragging zone z (a corner, a side or "move") by dx, dy shares of the picture; q — the frame's
// width / height in shares while its proportion is fixed (then only corners pull); mw, mh — the smallest frame
function reframe(c, z, dx, dy, q, mw, mh) {
  if (z === "move") return { ...c, x: clamp(c.x + dx, 0, 1 - c.w), y: clamp(c.y + dy, 0, 1 - c.h) };
  const E = z.includes("e"), Wt = z.includes("w"), S = z.includes("s"), N = z.includes("n");
  const ax = E ? c.x : c.x + c.w, ay = S ? c.y : c.y + c.h;          // the side the finger isn't on stays put
  const maxW = E ? 1 - c.x : Wt ? ax : 1, maxH = S ? 1 - c.y : N ? ay : 1;
  let w = E ? c.w + dx : Wt ? c.w - dx : c.w, h = S ? c.h + dy : N ? c.h - dy : c.h;
  if (q) {
    w = Math.abs(w - c.w) >= Math.abs(h * q - c.w) ? w : h * q;      // whichever way the finger went further
    w = clamp(w, Math.max(mw, mh * q), Math.min(maxW, maxH * q));
    h = w / q;
  } else { w = clamp(w, mw, maxW); h = clamp(h, mh, maxH); }
  return { x: E ? ax : Wt ? ax - w : c.x, y: S ? ay : N ? ay - h : c.y, w, h };
}
// the display turned a quarter left / mirrored: the frame goes with the picture. A turn left of a mirrored picture is
// the mirror of a turn right
const turnLeft = (e) => ({ ...e, rot: (e.rot + (e.flip ? 1 : 3)) % 4, ratio: e.ratio && 1 / e.ratio,
  cut: { x: e.cut.y, y: 1 - e.cut.x - e.cut.w, w: e.cut.h, h: e.cut.w } });
const mirror = (e) => ({ ...e, flip: !e.flip, cut: { ...e.cut, x: 1 - e.cut.x - e.cut.w } });
const tick = () => tg && tg.HapticFeedback && tg.HapticFeedback.selectionChanged();
const ROT = html`<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="10" width="11" height="11" rx="2"/><path d="M8 6.5h5.5a5.5 5.5 0 0 1 5.5 5.5v1.5"/><path d="M10.5 4 8 6.5 10.5 9"/></svg>`;
const FLIP = html`<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v2M12 9.5v2M12 16v2M12 21.5v.5"/><path d="M9 6 3 18h6z"/><path d="M15 6l6 12h-6z" fill="currentColor"/></svg>`;

function Editor({ f, onDone, onClose }) {
  const [img, setImg] = useState(null);
  const [e, setE] = useState(f.edit || PLAIN);
  const [box, setBox] = useState(null);
  const [moving, setMoving] = useState(false);
  const [busy, setBusy] = useState(false);
  const stage = useRef(null), cv = useRef(null), drag = useRef(null);
  useEffect(() => {
    let alive = true, got = null;
    loadPic(f.src).then((i) => { got = i; if (alive) setImg(i); else URL.revokeObjectURL(i.src); })
      .catch(() => { if (alive) { alertBox(t("attach.failed")); onClose(); } });
    const fit = () => { const r = stage.current && stage.current.getBoundingClientRect(); if (r) setBox({ w: r.width, h: r.height }); };
    fit(); addEventListener("resize", fit);
    return () => { alive = false; removeEventListener("resize", fit); if (got) URL.revokeObjectURL(got.src); };
  }, []);
  const PAD = 24;                    // room around the picture for the corners
  let v = null;
  if (img && box) {
    const [W, H] = turned(img, e);
    const s = Math.min((box.w - 2 * PAD) / W, (box.h - 2 * PAD) / H);
    v = { W, H, s, dw: W * s, dh: H * s, ox: (box.w - W * s) / 2, oy: (box.h - H * s) / 2 };
  }
  useEffect(() => { if (v && cv.current) paint(cv.current, img, e, FULL, v.s * Math.min(3, devicePixelRatio || 1)); },
    [img, e.rot, e.flip, v && v.dw, v && v.dh]);
  const fr = v && { l: v.ox + e.cut.x * v.dw, t: v.oy + e.cut.y * v.dh, w: e.cut.w * v.dw, h: e.cut.h * v.dh };
  const q = v && e.ratio ? e.ratio * v.H / v.W : null;
  // what a finger at x, y (px in the stage) takes: a corner, a side (only while free), the frame itself or nothing
  const zone = (x, y) => {
    const C = 28, r = fr.l + fr.w, b = fr.t + fr.h;
    const near = (d, inner) => d > -C && d < Math.min(C, inner);   // d: how far inside the frame from that side
    const nx = near(x - fr.l, fr.w / 3) ? "w" : near(r - x, fr.w / 3) ? "e" : "";
    const ny = near(y - fr.t, fr.h / 3) ? "n" : near(b - y, fr.h / 3) ? "s" : "";
    if (nx && ny) return ny + nx;
    if (!q && nx && y > fr.t && y < b) return nx;
    if (!q && ny && x > fr.l && x < r) return ny;
    return x > fr.l && x < r && y > fr.t && y < b ? "move" : null;
  };
  const at = (ev) => { const r = stage.current.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; };
  const down = (ev) => {
    if (drag.current || !v || busy) return;
    const [x, y] = at(ev), z = zone(x, y);
    if (!z) return;
    try { stage.current.setPointerCapture(ev.pointerId); } catch (err) {}
    drag.current = { id: ev.pointerId, z, x, y, cut: e.cut };
    setMoving(true);
  };
  const move = (ev) => {
    const d = drag.current;
    if (!d || ev.pointerId !== d.id) return;
    const [x, y] = at(ev);
    const cut = reframe(d.cut, d.z, (x - d.x) / v.dw, (y - d.y) / v.dh, q, Math.min(1, 48 / v.dw), Math.min(1, 48 / v.dh));
    setE((cur) => ({ ...cur, cut }));
  };
  // where the finger lifted counts too: the last move may come merged into the lift
  const up = (ev) => {
    if (!drag.current || ev.pointerId !== drag.current.id) return;
    if (ev.type === "pointerup") move(ev);
    drag.current = null; setMoving(false);
  };
  // a proportion: the largest frame of it in the picture, around the frame's centre; 4:3 and 16:9 stand upright
  // while the frame does
  const upright = v && e.cut.w * v.W < e.cut.h * v.H;
  const setRatio = (k, R) => {
    tick();
    if (k === "free") return setE({ ...e, ratio: null, rk: k });
    if (k === "orig") return setE({ ...e, ratio: v.W / v.H, rk: k, cut: FULL });
    const ratio = upright ? 1 / R : R, qq = ratio * v.H / v.W;
    let w = Math.min(1, qq), h = w / qq;
    if (h > 1) { h = 1; w = qq; }
    const cx = e.cut.x + e.cut.w / 2, cy = e.cut.y + e.cut.h / 2;
    setE({ ...e, ratio, rk: k, cut: { x: clamp(cx - w / 2, 0, 1 - w), y: clamp(cy - h / 2, 0, 1 - h), w, h } });
  };
  const label = (k) => (k === "free" ? t("edit.free") : k === "orig" ? t("edit.orig") : upright ? k.split(":").reverse().join(":") : k);
  const done = async () => {
    setBusy(true);
    try { onDone(await bake(f.src, e, img)); } catch (err) { alertBox(t("attach.failed")); setBusy(false); }
  };
  return html`<div class="ed" role="dialog" aria-label=${t("edit.title")}>
    <div class="ed-top">${!plain(e) && html`<button class="ed-b" onClick=${() => { tick(); setE(PLAIN); }}>${t("edit.reset")}</button>`}</div>
    <div class="ed-stage" ref=${stage} onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${up}>
      ${v && html`<canvas ref=${cv} style=${{ left: v.ox + "px", top: v.oy + "px", width: v.dw + "px", height: v.dh + "px" }}/>
        <div class=${"ed-frame" + (moving ? " moving" : "")} style=${{ left: fr.l + "px", top: fr.t + "px", width: fr.w + "px", height: fr.h + "px" }}>
          <i class="nw"></i><i class="ne"></i><i class="sw"></i><i class="se"></i></div>`}
    </div>
    <div class="ed-ratios">${RATIOS.map(([k, R]) => html`<button key=${k} class=${"ed-r" + (e.rk === k ? " on" : "")} disabled=${!v}
      onClick=${() => setRatio(k, R)}>${label(k)}</button>`)}</div>
    <div class="ed-bar"><button class="ed-b" onClick=${onClose}>${t("edit.cancel")}</button>
      <button class="ed-i" aria-label=${t("edit.rotate")} disabled=${!v} onClick=${() => { tick(); setE(turnLeft(e)); }}>${ROT}</button>
      <button class="ed-i" aria-label=${t("edit.flip")} disabled=${!v} onClick=${() => { tick(); setE(mirror(e)); }}>${FLIP}</button>
      <button class="ed-b ok" disabled=${busy || !v} onClick=${done}>${t("done")}</button></div>
  </div>`;
}
// one editor for the whole app, over everything: the composer is its own layer and would hold it under the banner.
// Opened through the history like the other overlays — Back is "Cancel"; while it is open Telegram doesn't fold the
// window on a swipe down, or pulling the frame down would close the app
function EditHost() {
  const [job, setJob] = useState(null);
  const [show, hide] = useOverlay(!!job, (open) => { if (!open) setJob(null); });
  useEffect(() => on("edit", (x) => { setJob(x); show(); }), [show]);
  useNoFold(!!job);
  return job ? html`<${Editor} f=${job.f} onDone=${(x) => { job.done(x); haptic("success"); hide(); }} onClose=${hide}/>` : "";
}
// while a layer that takes the finger is open, Telegram doesn't fold the window on a swipe down
function useNoFold(open) {
  useEffect(() => {
    if (!open || !tg || !tg.disableVerticalSwipes || !(tg.isVersionAtLeast && tg.isVersionAtLeast("7.7"))) return;
    const was = tg.isVerticalSwipesEnabled;
    tg.disableVerticalSwipes();
    return () => { if (was) tg.enableVerticalSwipes(); };
  }, [open]);
}

// ---------- a picture on the whole screen ----------

// as in Telegram: a tap on a picture in the chat, or on a thumbnail before sending, opens it over everything. Two
// fingers or a double tap zoom, one finger drags the zoomed picture; at its own size a swipe sideways goes to the next
// picture and a swipe up or down closes, as does Back; a single tap hides the bars. Before sending the bottom bar has
// Crop (the editor) and Remove
const ZOOM_MAX = 5, ZOOM_TAP = 2.5, V_GAP = 16;
const CROP = html`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/></svg>`;
const TRASH = html`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 6h17M9 6V4h6v2M6 6l1 14a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-14"/></svg>`;
const inboxSrc = (a) => api("inbox", a.pkey ? { name: a.name, pkey: a.pkey } : { name: a.name })
  .then((d) => "data:image/" + (d.kind === "jpg" ? "jpeg" : d.kind) + ";base64," + d.data);
const dist = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1]);
const midOf = (p, q) => [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
const UNZOOMED = { s: 1, x: 0, y: 0 };

// job: items [{src} | {a: an inbox picture}, each with f — the attachment, before sending], at, crop(f), remove(f).
// then(fn) closes the viewer and runs fn once it is out of the history (Crop opens the editor in its place)
function Viewer({ job, onClose, then }) {
  const [items, setItems] = useState(() => job.items.map((x) => ({ ...x })));
  const [at, setAt] = useState(job.at || 0);
  const [box, setBox] = useState({ l: 0, t: 0, w: innerWidth, h: innerHeight });
  const [z, setZ] = useState(UNZOOMED);     // the current picture: zoom, and its middle's shift from the screen's, px
  const [pull, setPull] = useState({ x: 0, y: 0 });   // unzoomed, the finger pulls it sideways (next) or up/down (close)
  const [anim, setAnim] = useState(false);
  const [bare, setBare] = useState(false);
  const root = useRef(null), zr = useRef(UNZOOMED), g = useRef({ pts: new Map() });
  const put = (v) => { zr.current = v; setZ(v); };
  useEffect(() => {
    const fit = () => { const r = root.current && root.current.getBoundingClientRect(); if (r) setBox({ l: r.left, t: r.top, w: r.width, h: r.height }); };
    fit(); addEventListener("resize", fit);
    return () => { removeEventListener("resize", fit); clearTimeout(g.current.tap); };
  }, []);
  useEffect(() => {                      // a computer's keyboard: Esc closes, the arrows go through the pictures
    const key = (e) => { if (e.key === "Escape") onClose(); else if (e.key === "ArrowLeft") goTo(at - 1); else if (e.key === "ArrowRight") goTo(at + 1); };
    addEventListener("keydown", key);
    return () => removeEventListener("keydown", key);
  });
  // the pictures from the chat come from the computer: this one and its neighbours
  useEffect(() => {
    let alive = true;
    items.forEach((x, k) => {
      if (x.src || !x.a || x.asked || Math.abs(k - at) > 1) return;
      x.asked = true;
      inboxSrc(x.a).then((src) => alive && setItems((cur) => cur.map((y) => (y.a === x.a ? { ...y, src } : y)))).catch(() => {});
    });
    return () => { alive = false; };
  }, [at, items.length]);
  // a picture fills the screen by its longer side, small ones too
  const size = (x) => { if (!x || !x.nat) return null; const f = Math.min(box.w / x.nat[0], box.h / x.nat[1]); return [x.nat[0] * f, x.nat[1] * f]; };
  const held = (v) => {                  // a zoomed picture's edges don't leave the screen's
    const d = size(items[at]);
    if (!d || v.s <= 1) return UNZOOMED;
    const mx = Math.max(0, (d[0] * v.s - box.w) / 2), my = Math.max(0, (d[1] * v.s - box.h) / 2);
    return { s: v.s, x: clamp(v.x, -mx, mx), y: clamp(v.y, -my, my) };
  };
  const zoomAt = (p, s) => { const c = zr.current; return held({ s, x: p[0] - (p[0] - c.x) * s / c.s, y: p[1] - (p[1] - c.y) * s / c.s }); };
  const goTo = (k) => { setAnim(true); setPull({ x: 0, y: 0 }); if (k < 0 || k >= items.length || k === at) return; setAt(k); put(UNZOOMED); };
  const pos = (ev) => [ev.clientX - box.l - box.w / 2, ev.clientY - box.t - box.h / 2];     // from the screen's middle
  const down = (ev) => {
    if (ev.target.closest("button")) return;
    const G = g.current;
    try { root.current.setPointerCapture(ev.pointerId); } catch (err) {}
    G.pts.set(ev.pointerId, pos(ev));
    setAnim(false);
    if (G.pts.size === 1) Object.assign(G, { mode: null, p0: pos(ev), t0: Date.now(), z0: zr.current, moved: false });
    else if (G.pts.size === 2) {
      const [p, q] = [...G.pts.values()];
      Object.assign(G, { mode: "pinch", d0: dist(p, q) || 1, m0: midOf(p, q), z0: zr.current, moved: true });
      setPull({ x: 0, y: 0 });
    }
  };
  const move = (ev) => {
    const G = g.current;
    if (!G.pts.has(ev.pointerId)) return;
    G.pts.set(ev.pointerId, pos(ev));
    if (G.mode === "pinch") {
      if (G.pts.size < 2) return;
      const [p, q] = [...G.pts.values()], m = midOf(p, q), z0 = G.z0;
      const s = clamp(z0.s * dist(p, q) / G.d0, 0.6, ZOOM_MAX);
      put({ s, x: m[0] - (G.m0[0] - z0.x) * s / z0.s, y: m[1] - (G.m0[1] - z0.y) * s / z0.s });
      return;
    }
    if (G.pts.size !== 1) return;
    const p = pos(ev), dx = p[0] - G.p0[0], dy = p[1] - G.p0[1];
    if (!G.mode) {
      if (Math.hypot(dx, dy) < 8) return;
      G.moved = true;
      G.mode = zr.current.s > 1.01 ? "pan" : Math.abs(dx) > Math.abs(dy) ? "page" : "close";
    }
    if (G.mode === "pan") put(held({ ...G.z0, x: G.z0.x + dx, y: G.z0.y + dy }));
    else if (G.mode === "page") setPull({ x: (at === 0 && dx > 0) || (at === items.length - 1 && dx < 0) ? dx / 3 : dx, y: 0 });
    else setPull({ x: 0, y: dy });
  };
  const up = (ev) => {
    const G = g.current;
    if (!G.pts.has(ev.pointerId)) return;
    G.pts.delete(ev.pointerId);
    if (G.mode === "pinch") {
      if (G.pts.size === 1) { Object.assign(G, { mode: "pan", p0: [...G.pts.values()][0], z0: zr.current }); return; }
      if (G.pts.size) return;
      setAnim(true); put(held(zr.current)); G.mode = null;
      return;
    }
    if (G.pts.size) return;
    const p = pos(ev), dx = p[0] - G.p0[0], dy = p[1] - G.p0[1], quick = Date.now() - G.t0 < 250;
    if (G.mode === "pan") { setAnim(true); put(held(zr.current)); }      // the last finger of a pinch: shrunk springs back
    else if (G.mode === "page") goTo(dx < -box.w / 5 || (quick && dx < -40) ? at + 1 : dx > box.w / 5 || (quick && dx > 40) ? at - 1 : at);
    else if (G.mode === "close") { if (Math.abs(dy) > 90 || (quick && Math.abs(dy) > 40)) onClose(); else { setAnim(true); setPull({ x: 0, y: 0 }); } }
    else if (!G.moved) {
      const last = G.last;
      if (last && Date.now() - last.t < 300 && dist(p, last.p) < 30) {      // a double tap: zoom in there, or back out
        clearTimeout(G.tap); G.last = null; setAnim(true);
        put(zr.current.s > 1.01 ? UNZOOMED : zoomAt(p, ZOOM_TAP));
      } else {
        G.last = { t: Date.now(), p };
        G.tap = setTimeout(() => { G.last = null; setBare((b) => !b); }, 300);
      }
    }
    G.mode = null;
  };
  const wheel = (ev) => { ev.preventDefault(); setAnim(false); put(zoomAt(pos(ev), clamp(zr.current.s * Math.exp(-ev.deltaY / 300), 1, ZOOM_MAX))); };
  const drop = () => {
    const x = items[at];
    job.remove(x.f);
    if (items.length === 1) return onClose();
    setItems(items.filter((y) => y !== x)); setAt(Math.min(at, items.length - 2)); put(UNZOOMED);
  };
  const step = box.w + V_GAP;
  return html`<div ref=${root} class=${"viewer" + (anim ? " anim" : "") + (bare ? " bare" : "")} role="dialog" aria-label=${t("view.title")}
    onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${up} onWheel=${wheel}>
    <div class="v-bg" style=${{ opacity: 1 - Math.min(0.8, Math.abs(pull.y) / 300) }}></div>
    ${items.map((x, k) => {
      if (Math.abs(k - at) > 1) return "";
      const d = size(x), cur = k === at;
      return html`<div key=${x.src || (x.a ? x.a.name : "wait")} class="v-pic" style=${{ transform: "translate3d(" + ((k - at) * step + pull.x) + "px," + (cur ? pull.y : 0) + "px,0)" }}>
        ${x.src ? html`<img src=${x.src} alt="" draggable="false" onLoad=${(e) => { const n = [e.target.naturalWidth, e.target.naturalHeight]; setItems((all) => all.map((y) => (y === x ? { ...y, nat: n } : y))); }}
          style=${d ? { width: d[0] + "px", height: d[1] + "px", transform: cur ? "translate(" + z.x + "px," + z.y + "px) scale(" + z.s + ")" : "" } : { visibility: "hidden" }}/>`
          : html`<span class="v-wait">${ic("image", 40)}</span>`}</div>`;
    })}
    <div class="v-top"><button class="v-b" aria-label=${t("close")} onClick=${onClose}>${ic("x", 24)}</button>
      ${items.length > 1 ? html`<span class="v-n">${at + 1} / ${items.length}</span>` : ""}</div>
    ${job.crop && html`<div class="v-bar">
      <button class="v-b" onClick=${() => { const f = items[at].f; then(() => job.crop(f)); }}>${CROP}<span>${t("view.crop")}</span></button>
      <button class="v-b" onClick=${drop}>${TRASH}<span>${t("attach.remove")}</span></button></div>`}
    ${job.send && html`<div class="v-bar"><button class="v-b" disabled=${!items[at].src} onClick=${job.send}>${ic("send", 22)}<span>${t("fv.send")}</span></button></div>`}
  </div>`;
}
// one viewer for the whole app, over everything, like the editor; opened through the history — Back closes it
function ViewHost() {
  const [job, setJob] = useState(null);
  const after = useRef(null);
  const [show, hide] = useOverlay(!!job, (open) => { if (!open) setJob(null); });
  useEffect(() => on("view", (x) => { setJob(x); show(); }), [show]);
  useEffect(() => { if (!job && after.current) { const fn = after.current; after.current = null; fn(); } }, [job]);
  useNoFold(!!job);
  return job ? html`<${Viewer} job=${job} onClose=${hide} then=${(fn) => { after.current = fn; hide(); }}/>` : "";
}

// a picture the owner sent (from Telegram or the app): the chat shows it, not the path Claude got
// all — the pictures of the same message: the viewer goes through them
function Pic({ a, all }) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    if (!a.image || !a.inbox) return;
    let alive = true;
    inboxSrc(a).then((s) => alive && setSrc(s)).catch(() => {});
    return () => { alive = false; };
  }, [a.name]);
  const open = () => { const pics = (all || [a]).filter((x) => x.image && x.inbox);
    emit("view", { items: pics.map((x) => (x === a ? { a: x, src } : { a: x })), at: Math.max(0, pics.indexOf(a)) }); };
  if (src) return html`<img class="att" src=${src} alt="" onClick=${open}/>`;
  return html`<span class="att-chip">${ic(a.image ? "image" : "file", 14)} ${a.name.split("/").pop() || t("att.file")}</span>`;
}

export { Attach, EditHost, Pic, Thumbs, ViewHost, Viewer, useAttach, useNoFold };
