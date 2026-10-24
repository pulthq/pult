"""The app's microphone (stage G2) in headless Chrome with a fake microphone that plays a WAV, on the stand: a real tap
→ "Microphone…" → the recording starts once sound flows (the red dot), the dot breathes with the voice, "Stop" records
0.3 s more, the words land in the field, the computer logs the recording's figures; silence is not sent; a computer
before 0.14.2 (STAND_STT_OLD=1) still gets the recording. With a Groq key in ~/.config/pult/env the kept recording is
also recognized for real, with Pult's prompt — the first word must survive.
  STAND_LANG=ru STAND_STT=/tmp/rec HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out 2>&1 &
  ~/.local/share/pult/venv/bin/python tools/voice_check.py "$(grep '^SESS ' /tmp/stand.out | cut -d' ' -f2)" /tmp/rec [speech|silence]
Exit 1 on a failed check. Needs macOS `say` and ffmpeg for the WAV."""
import asyncio, json, os, re, subprocess, sys, tempfile
import aiohttp

URL, KEEP = sys.argv[1], sys.argv[2]
SOUND = sys.argv[3] if len(sys.argv) > 3 else "speech"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9337
PHRASE = "Посмотри логи демона на Орионе, потом сделай коммит."
failures = []


def verdict(name, ok, *info):
    print(("ok   " if ok else "FAIL ") + name, *info, flush=True)
    if not ok:
        failures.append(name)


def wav(path):
    """What the fake microphone plays, looped: 0.25 s of quiet, then the phrase from its first sound, then 2 s of quiet."""
    if SOUND == "silence":
        src = ["-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.0005:d=6"]
    else:
        aiff = path + ".aiff"
        subprocess.run(["say", "-v", "Milena", "-o", aiff, PHRASE], check=True)
        src = ["-i", aiff, "-af", "silenceremove=start_periods=1:start_threshold=-45dB,adelay=250:all=1,apad=pad_dur=2"]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *src, "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", path], check=True)


def seconds(path):
    out = subprocess.run(["ffmpeg", "-i", path, "-f", "null", "-"], capture_output=True, text=True).stderr
    t = re.findall(r"time=(\d+):(\d+):([\d.]+)", out)
    return int(t[-1][0]) * 3600 + int(t[-1][1]) * 60 + float(t[-1][2]) if t else 0


async def main():
    tmp = tempfile.mkdtemp(prefix="pult-voice-")
    sound = os.path.join(tmp, "mic.wav")
    wav(sound)
    before = sorted(os.listdir(KEEP))
    p = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--remote-debugging-port=%d" % PORT,
                          "--user-data-dir=" + os.path.join(tmp, "prof"), "--no-first-run",
                          "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                          # the sandboxed audio service can't read the WAV and hands out zeros
                          "--disable-features=AudioServiceSandbox,AudioServiceOutOfProcess",
                          "--use-file-for-fake-audio-capture=" + sound, "about:blank"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with aiohttp.ClientSession() as s:
            for _ in range(50):
                try:
                    async with s.get("http://127.0.0.1:%d/json/list" % PORT) as r:
                        tabs = [x for x in await r.json() if x.get("type") == "page"]
                        if tabs:
                            break
                except aiohttp.ClientError:
                    pass
                await asyncio.sleep(0.2)
            ws = await s.ws_connect(tabs[0]["webSocketDebuggerUrl"], max_msg_size=64 * 1024 * 1024)
            n, errors = 0, []

            async def cmd(method, **params):
                nonlocal n
                n += 1
                await ws.send_str(json.dumps({"id": n, "method": method, "params": params}))
                while True:
                    m = json.loads((await ws.receive()).data)
                    if m.get("method") == "Runtime.exceptionThrown":
                        errors.append(m["params"]["exceptionDetails"].get("exception", {}).get("description"))
                    if m.get("id") == n:
                        if "error" in m:
                            raise RuntimeError("%s: %s" % (method, m["error"]))
                        return m.get("result", {})

            async def js(expr):
                r = await cmd("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
                if "exceptionDetails" in r:
                    raise RuntimeError(r["exceptionDetails"])
                return r["result"].get("value")

            async def until(expr, tries=100, every=0.1):
                for _ in range(tries):
                    if await js(expr):
                        return True
                    await asyncio.sleep(every)
                return False

            async def tap(sel):                   # a real tap: the browser lets audio start only from one
                r = await js("(() => { const b = document.querySelector(%r).getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()" % sel)
                for kind in ("mousePressed", "mouseReleased"):
                    await cmd("Input.dispatchMouseEvent", type=kind, x=r[0], y=r[1], button="left", clickCount=1)

            await cmd("Page.enable")
            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=915, deviceScaleFactor=2, mobile=True)
            await cmd("Page.navigate", url=URL)
            verdict("the session shows the microphone", await until("!!document.querySelector('.clip.mic')", 150))
            await js("window.__alerts = []; window.alert = (s) => window.__alerts.push(String(s)); "
                     "const w = window.Telegram && window.Telegram.WebApp; if (w) w.showAlert = (s) => window.__alerts.push(String(s));")
            mic = ".clip.mic"
            await tap(mic)
            t0 = asyncio.get_event_loop().time()
            ok = await until("document.querySelector('.clip.mic').classList.contains('rec') && !document.querySelector('.clip.mic').classList.contains('wait')", 60, 0.02)
            live = asyncio.get_event_loop().time() - t0
            verdict("the recording starts once sound flows", ok, "%.2f s after the tap" % live)
            scales = set()
            for _ in range(40):                   # 2 s: the phrase
                scales.add(await js("(document.querySelector('.clip.mic .dot') || {style: {}}).style.transform || ''"))
                await asyncio.sleep(0.05)
            if SOUND == "speech":
                verdict("the dot breathes with the voice", len(scales - {""}) >= 3, sorted(scales)[:4])
            await asyncio.sleep(1.2)              # the phrase ends
            await tap(mic)
            t_stop = asyncio.get_event_loop().time()
            ta = "document.querySelector('.ctl textarea, textarea')"
            if SOUND == "silence":
                verdict("silence is not sent", await until("window.__alerts.length > 0", 50), await js("window.__alerts"))
                verdict("…and nothing reached the computer", sorted(os.listdir(KEEP)) == before)
            else:
                verdict("the words land in the field", await until("/recording \\d+ heard/.test(%s.value)" % ta, 80),
                        await js("%s.value" % ta))
                new = [x for x in sorted(os.listdir(KEEP)) if x not in before]
                verdict("the computer got one recording", len(new) == 1, new)
                if new:
                    rec = os.path.join(KEEP, new[0])
                    held = t_stop - t0 - live
                    got = seconds(rec)
                    verdict("…with 0.3 s after Stop", got >= held + 0.2, "%.2f s recorded, %.2f s from live to Stop" % (got, held))
                    key = next((x.split("=", 1)[1].strip().strip('"') for x in open(os.path.expanduser("~/.config/pult/env"))
                                if x.startswith("PULT_STT_KEY=")), None) if os.path.exists(os.path.expanduser("~/.config/pult/env")) else None
                    if key:
                        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
                        import pult_stt as STT, pult_i18n as I
                        text = await STT.Stt(key).transcribe(open(rec, "rb").read(), "audio/webm", language="ru",
                                                             prompt=I.T("stt.prompt", "ru") + " " + I.T("stt.prompt.words", "ru", words="Орион"))
                        verdict("Groq hears the first word", text.lower().startswith("посмотри"), repr(text))
            verdict("no errors in the page", not errors, errors[:3])
            if failures:
                print("alerts:", await js("window.__alerts"), "| audio:", await js("(async () => { const c = new AudioContext(); const st = c.state; await c.close(); return st; })()"))
    finally:
        p.terminate()
    sys.exit(1 if failures else 0)

asyncio.run(main())
