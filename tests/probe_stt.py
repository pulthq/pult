"""Probe: Groq Whisper as Pult uses it (stage G2). Facts checked 2026-10-23 on the owner's key:
  1. a quiet start (the level rising over 0.4–1.2 s, as a phone's gain control does) loses the first syllable with
     either model and any prompt — "Посмотри логи" → "Смотри логи"; a pause before the words does no harm;
  2. over silence Whisper writes subtitle credits ("Продолжение следует...") and no_speech_prob doesn't tell —
     pult_stt.scrub must leave nothing;
  3. the prompt is refused above 896 bytes of UTF-8 (the docs say 224 tokens);
  4. both models answer in about 0.4 s and show the same daily request limit.
Checked 2026-11-21, after the owner's 125-s recording came back right for 36 s and made up after:
  5. a 2-minute dictation with thinking pauses of 8.5, 12 and 14 s, read whole, loses one or two sentences after a
     long pause — "0 100" or nothing in their place — with either model, with the prompt or without; cut into pieces at
     pauses the way the app cuts it (relay/web/static/core/voice.js, the same figures here), it loses none. Pauses as
     long after other sentences lost nothing: it depends on where the 30-s windows fall. Checked by hand the same day:
     36 s of speech followed by 90 s of quiet noise came back "…Например, DimaTorzok Продолжение следует…"; the speech
     going on 30 dB quieter came back whole.
Speech is macOS `say -v Milena`, made into webm/opus 32 kbit/s mono like the app's; pink noise, the phone band.
Run (≈55 requests, a fraction of the free daily limit): ~/.local/share/pult/venv/bin/python tests/probe_stt.py [5]
The key is read from ~/.config/pult/env and never printed."""
import array, asyncio, math, os, subprocess, sys, tempfile, time, wave
from pathlib import Path

import httpx

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))
import pult_i18n as I  # noqa: E402
import pult_stt as STT  # noqa: E402

KEY = next((x.split("=", 1)[1].strip().strip('"') for x in open(os.path.expanduser("~/.config/pult/env"))
            if x.startswith("PULT_STT_KEY=")), None)
MODELS = ("whisper-large-v3", "whisper-large-v3-turbo")
PHRASE = ("Посмотри логи демона на Орионе, потом сделай коммит и выложи новую версию на GitHub. "
          "Если тесты упадут, напиши мне в Телеграм, что именно сломалось.")
PROMPT = STT.fit(I.T("stt.prompt", "ru") + " " + I.T("stt.prompt.words", "ru", words="Орион"))
TMP = Path(tempfile.mkdtemp(prefix="pult-stt-"))
ONLY = sys.argv[1:]                                      # `5` — the dictation alone (≈15 requests)


def sh(*a):
    subprocess.run(a, check=True, capture_output=True)


def clip(fade, lead_ms):
    """The phrase from its first sound, its level rising over `fade` s, after `lead_ms` of quiet; noisy, phone band."""
    aiff = TMP / "phrase.aiff"
    if not aiff.exists():
        sh("say", "-v", "Milena", "-r", "245", "-o", str(aiff), PHRASE)
    out = TMP / ("p-%s-%d.webm" % (fade, lead_ms))
    f = ("silenceremove=start_periods=1:start_threshold=-45dB,afade=t=in:d=%s,highpass=f=300,lowpass=f=3400,"
         "adelay=%d:all=1,apad=pad_dur=0.4" % (fade, lead_ms))
    sh("ffmpeg", "-y", "-i", str(aiff), "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.10:d=60", "-filter_complex",
       "[0:a]%s,aresample=48000[s];[1:a]aresample=48000[n];[s][n]amix=inputs=2:duration=first:normalize=0" % f,
       "-ac", "1", "-c:a", "libopus", "-b:a", "32k", str(out))
    return out


def silence():
    out = TMP / "silence.webm"
    sh("ffmpeg", "-y", "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.02:d=1.5", "-ac", "1", "-c:a", "libopus", "-b:a", "32k", str(out))
    return out


# fact 5: a dictation like the owner's — the sentence, the pause after it (s), the word that shows it was heard. These
# very sentences, pauses and pace lost words read whole on 2026-11-21 with every model and prompt; the same pauses after
# other sentences lost none — it depends on where the 30-s windows fall, which is why the app cuts rather than hopes
DICTATION = [
    ("В рамках этого проекта хочу развить инструмент для саморазвития, который мне позволит как с точки зрения "
     "профессиональной, так, возможно, и в каких-то других направлениях развиваться.", 1.2, "саморазвит"),
    ("За основу предлагаю взять подход, который реализован в проекте по ЕГЭ и химии для детей, соседний проект.", 1.5, "химии"),
    ("То есть мне было бы удобно, если бы я, как по принципу Дуолинго, проходил бы различные направления в "
     "Telegram-боте, в вебапе.", 8.5, "различные"),
    ("Например, каждый день небольшой урок минут на десять, с вопросами и с проверкой ответов.", 1.0, "урок"),
    ("И чтобы был прогресс от нуля до ста процентов по каждому направлению.", 12.0, "прогресс"),
    ("Направления могут быть разные: английский язык, программирование на питоне, финансы, может быть, история.", 1.2,
     "английский"),
    ("Важно, чтобы бот напоминал мне заниматься, но не слишком навязчиво, допустим, один раз утром.", 14.0, "напоминал"),
    ("Ещё хочу, чтобы материалы для уроков готовил Claude, а я бы только проверял и правил.", 1.0, "материалы"),
    ("И чтобы можно было добавить новое направление одной командой, без программирования.", 2.5, "командой"),
    ("Посмотри, как устроен соседний проект, что из него можно взять, и предложи план.", 1.0, "предложи"),
    ("Сначала давай обсудим архитектуру, а уже потом начнём писать код.", 0.6, "архитектур"),
]
# the app's figures (relay/web/static/core/voice.js): its level meter — RMS of the last 2048 samples, every 50 ms
VOICE_DB, VOICE_MIN, PIECE_MAX, PIECE_DROP, PAUSE_DB = -50, 3, 28, 2, 30
PIECE_PAUSE = [(5, 3), (12, 1.2), (22, 0.6), (PIECE_MAX, 0.25)]


def dictation():
    """The dictation as the phone would record it: 48 kHz mono WAV (for the cutting) and webm/opus (to send)."""
    parts = []
    for i, (text, pause, _) in enumerate(DICTATION):
        aiff, wav_ = TMP / ("d%d.aiff" % i), TMP / ("d%d.wav" % i)
        sh("say", "-v", "Milena", "-r", "125", "-o", str(aiff), text)
        sh("ffmpeg", "-y", "-i", str(aiff), "-af", "aresample=48000,apad=pad_dur=%s" % pause, "-ac", "1", str(wav_))
        parts.append(wav_)
    (TMP / "d.txt").write_text("".join("file '%s'\n" % p for p in parts))
    sh("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(TMP / "d.txt"), "-c", "copy", str(TMP / "d-clean.wav"))
    sh("ffmpeg", "-y", "-i", str(TMP / "d-clean.wav"), "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.003:d=400:seed=1", "-filter_complex",
       "[1:a]aresample=48000[n];[0:a][n]amix=inputs=2:duration=first:normalize=0", "-ac", "1", "-c:a", "pcm_s16le",
       str(TMP / "d.wav"))
    sh("ffmpeg", "-y", "-i", str(TMP / "d.wav"), "-c:a", "libopus", "-b:a", "32k", str(TMP / "d.webm"))
    return TMP / "d.wav", TMP / "d.webm"


def app_pieces(wav_path):
    """Where the app cuts this recording: [(from s, to s)] of the pieces it sends (silence alone is dropped)."""
    w = wave.open(str(wav_path))
    sr, pcm = w.getframerate(), array.array("h", w.readframes(w.getnframes()))
    out, start, last, loud, peak, t = [], 0.0, None, 0, -200.0, 0.05
    while t * sr <= len(pcm):
        buf = pcm[max(0, int(t * sr) - 2048):int(t * sr)]
        db = 20 * math.log10(max(1e-10, math.sqrt(sum(x * x for x in buf) / len(buf)) / 32768))
        peak = max(peak, db)
        if db > VOICE_DB:
            loud += 1
            if db >= peak - PAUSE_DB:
                last = t
        n = t - start
        if not loud:
            cut = n >= PIECE_DROP
        else:
            need = next((p for upto, p in PIECE_PAUSE if n < upto), 0)
            cut = n >= PIECE_MAX or t - last >= need
        if cut:
            if loud >= VOICE_MIN:
                out.append((start, t))
            start, last, loud, peak = t, None, 0, -200.0
        t += 0.05
    if loud >= VOICE_MIN:
        out.append((start, len(pcm) / sr))
    return out


def missing(text):
    t = text.lower()
    return [w for _, _, w in DICTATION if w not in t]


async def main():
    if not KEY:
        sys.exit("no PULT_STT_KEY in ~/.config/pult/env")
    c = httpx.AsyncClient(timeout=60)

    async def raw(path, model, prompt=PROMPT):
        t = time.monotonic()
        r = await c.post(STT.BASE + "audio/transcriptions", headers={"Authorization": "Bearer " + KEY},
                         data={"model": model, "language": "ru", "response_format": "verbose_json", "temperature": "0",
                               **({"prompt": prompt} if prompt else {})},
                         files={"file": (path.name, path.read_bytes())})
        dt = time.monotonic() - t
        await asyncio.sleep(1.5)                                  # 20 requests a minute on the free tier
        return r, dt

    if ONLY == ["5"]:
        await dictation_facts(raw)
        return await c.aclose()
    print("1. a quiet start — the first word:")
    for fade in ("0.01", "0.4", "1.2"):
        for lead in (0, 700):
            p = clip(fade, lead)
            for m in MODELS:
                r, dt = await raw(p, m)
                text = r.json().get("text", "").strip() if r.status_code == 200 else "HTTP %d" % r.status_code
                print("   rise %-4s s, pause %3d ms, %-22s %.2f s  %s %s" % (
                    fade, lead, m, dt, "ok  " if text.lower().startswith("посмотри") else "LOST", text[:48]))
    print("2. silence — what Whisper writes, and what scrub leaves:")
    p = silence()
    for m in MODELS:
        for prompt in (PROMPT, None):
            r, _ = await raw(p, m, prompt)
            d = r.json()
            segs = d.get("segments") or [{}]
            print("   %-22s %-9s %-50r no_speech %.2f → left: %r" % (
                m, "prompt" if prompt else "no prompt", d.get("text", "").strip(), segs[0].get("no_speech_prob", -1),
                STT.scrub(" ".join(d.get("text", "").split()))[0]))
    print("3. the prompt's limit:")
    for extra in (0, 1):                                          # a Russian letter is two bytes
        prompt = "ж" * (STT.PROMPT_MAX // 2) + "." * extra
        r, _ = await raw(clip("0.01", 0), MODELS[0], prompt)
        print("   %d bytes → HTTP %d %s" % (len(prompt.encode()), r.status_code, r.json().get("error", {}).get("message", "")[:90]))
    print("4. limits:", {k: v for k, v in r.headers.items() if k.startswith("x-ratelimit")})
    print("   Pult's prompt: %d bytes — %r" % (len(PROMPT.encode()), PROMPT))
    await dictation_facts(raw)
    await c.aclose()


async def dictation_facts(raw):
    print("5. a dictation with thinking pauses — read whole, and in the app's pieces:")
    wav_path, webm = dictation()
    for m in MODELS:
        for prompt in (PROMPT, None):
            r, _ = await raw(webm, m, prompt)
            d = r.json()
            lost = [s for s in d.get("segments") or [] if s["end"] - s["start"] > 8 and len(s["text"].split()) < 3]
            print("   whole, %-22s %-9s lost: %-40s %s" % (m, "prompt" if prompt else "no prompt", missing(d.get("text", "")) or "none",
                  " | ".join("%.0f–%.0f s %r" % (s["start"], s["end"], s["text"].strip()) for s in lost)))
    cuts, words = app_pieces(wav_path), []
    for i, (a, b) in enumerate(cuts):
        piece = TMP / ("piece%d.webm" % i)
        sh("ffmpeg", "-y", "-i", str(wav_path), "-ss", "%.2f" % a, "-to", "%.2f" % b, "-c:a", "libopus", "-b:a", "32k", str(piece))
        r, _ = await raw(piece, MODELS[0])
        words.append(STT.scrub(" ".join(r.json().get("text", "").split()), PROMPT)[0])
    print("   pieces (%s): %d of them, %s — lost: %s" % (MODELS[0], len(cuts), " ".join("%.0f–%.0f" % c for c in cuts),
                                                         missing(" ".join(words)) or "none"))

asyncio.run(main())
