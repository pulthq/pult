// Pult app — what can be taken back for a few seconds. "Reviewed" put a task off "Your move" for good, with one tap in
// a card's corner, right beside the field for an answer (review 2026-11-11, UX9). It still goes to the computer at
// once — a window closed right after the tap loses nothing — and a note at the bottom offers "Bring back" for AWAY_MS:
// the computer then lets the outcome wait again. A computer that can't (no "unseen" among its caps) gets no offer.
import { api, conn, emit, on } from "../core/conn.js";
import { alertBox, haptic } from "../core/tg.js";
import { t } from "../i18n.js";
import { useEffect, useState } from "../vendor/htm-preact-3.1.1.js";

const AWAY_MS = 5000, AWAY_KEEP = 8000;
const away = new Map();              // sid → a timer: put away here; the screens' own data may still have the card
const isAway = (sid) => away.has(sid);
// put a task's outcome away → whether it went; `back` — what the screen that had the card does when it is brought back
async function putAway(sid, back) {
  try { await api("seen", { sid }); } catch (e) { alertBox(e.message); return false; }
  haptic("success");
  clearTimeout(away.get(sid));
  away.set(sid, setTimeout(() => { away.delete(sid); emit("away"); }, AWAY_KEEP));
  emit("away");
  if (!conn.caps.includes("unseen")) return true;
  emit("toast", { text: t("away.done"), ms: AWAY_MS, label: t("away.back"), on: async () => {
    try {
      const r = await api("unseen", { sid });
      if (r && r.ok === false) { alertBox(r.note || t("failed")); return; }
      clearTimeout(away.get(sid));
      away.delete(sid);
      if (back) back();
      emit("away");
    } catch (e) { alertBox(e.message); }
  } });
  return true;
}
// a screen with cards of "Your move" draws again when one is put away or brought back
function useAway() {
  const [, bump] = useState(0);
  useEffect(() => on("away", () => bump((x) => x + 1)), []);
}

export { isAway, putAway, useAway };
