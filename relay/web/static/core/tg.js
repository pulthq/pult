// Pult app — Telegram's WebApp: the theme, the language at start, vibration, its alert and confirm.
// Moved from app.js as it was (review 2026-10-27, 6.4).
import { setLang } from "../i18n.js";

const tg = window.Telegram && window.Telegram.WebApp;
if (tg) { tg.ready(); tg.expand(); }
// the app's own colours (the ones Telegram doesn't send, the chart's) follow Telegram's theme, not only the phone's —
// when Telegram sent one: outside it (the stand, a browser) its script says "light" anyway, and the phone decides
const scheme = () => { if (tg && tg.colorScheme && tg.themeParams && tg.themeParams.bg_color) document.documentElement.dataset.scheme = tg.colorScheme; };
scheme();
if (tg && tg.onEvent) tg.onEvent("themeChanged", scheme);
// the language: Telegram's right away, then Pult's own setting (overview / settings carry it)
setLang(String((tg && tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.language_code) || "en").startsWith("ru") ? "ru" : "en");
const haptic = (k) => tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred(k);
// a light tick under the finger: a slide has gone past its mark (stage Zh, step 3)
const tick = () => tg && tg.HapticFeedback && tg.HapticFeedback.selectionChanged();
// Telegram's popup takes a message of up to 256 characters and a title of up to 64, and throws past them
// (WebAppPopupParamInvalid): the box never shows and the tap does nothing. A longer text goes up as a popup with its
// first paragraph for the title and the rest cut to fit; whatever Telegram still refuses — the browser's own box
const MSG = 256, TITLE = 64;
const long = (s) => {
  const i = s.indexOf("\n\n"), fit = (m) => (m.length <= MSG ? m : m.slice(0, MSG - 1) + "…");
  return i > 0 && i <= TITLE ? { title: s.slice(0, i), message: fit(s.slice(i + 2)) } : { message: fit(s) };
};
const alertBox = (s) => {
  s = String(s);
  try {
    if (tg && s.length <= MSG && tg.showAlert) return tg.showAlert(s);
    if (tg && tg.showPopup) return tg.showPopup(Object.assign(long(s), { buttons: [{ type: "close" }] }));
  } catch (e) { /* the browser's box below */ }
  alert(s);
};
const confirmBox = (s) => new Promise((ok) => {
  s = String(s);
  try {
    if (tg && s.length <= MSG && tg.showConfirm) return tg.showConfirm(s, ok);
    if (tg && tg.showPopup) return tg.showPopup(Object.assign(long(s), { buttons: [{ id: "ok", type: "ok" }, { type: "cancel" }] }), (id) => ok(id === "ok"));
  } catch (e) { /* the browser's box below */ }
  ok(confirm(s));
});

export { alertBox, confirmBox, haptic, tg, tick };
