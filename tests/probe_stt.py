"""Probe: Groq Whisper as Pult uses it (stage G2). Facts checked 2026-10-23 on the owner's key:
  1. a quiet start (the level rising over 0.4–1.2 s, as a phone's gain control does) loses the first syllable with
     either model and any prompt — "Посмотри логи" → "Смотри логи"; a pause before the words does no harm;
  2. over silence Whisper writes subtitle credits ("Продолжение следует...") and no_speech_prob doesn't tell —
     pult_stt.scrub must leave nothing;
  3. the prompt is refused above 896 bytes of UTF-8 (the docs say 224 tokens);
  4. both models answer in about 0.4 s and show the same daily request limit.
Speech is macOS `say -v Milena`, made into webm/opus 32 kbit/s mono like the app's; pink noise, the phone band.
Run (≈40 short requests, a fraction of the free daily limit): ~/.local/share/pult/venv/bin/python tests/probe_stt.py
The key is read from ~/.config/pult/env and never printed."""
import asyncio, os, subprocess, sys, tempfile, time
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
    await c.aclose()

asyncio.run(main())
