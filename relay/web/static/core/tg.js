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
const alertBox = (s) => (tg && tg.showAlert ? tg.showAlert(s) : alert(s));
const confirmBox = (s) => new Promise((ok) => (tg && tg.showConfirm ? tg.showConfirm(s, ok) : ok(confirm(s))));

export { alertBox, confirmBox, haptic, tg, tick };
