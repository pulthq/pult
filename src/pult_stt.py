#!/usr/bin/env python3
"""Pult: speech to text for voice messages — Groq's Whisper API (whisper-large-v3-turbo). It needs a key
(PULT_STT_KEY); without one, voice input is simply off. A recording goes to Groq and is kept nowhere on this
computer.

Facts (console.groq.com/docs/speech-to-text, checked 2026-10-18): POST /openai/v1/audio/transcriptions, multipart
file + model + language + prompt (≤ 224 tokens) + response_format; flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, webm;
a file of up to 25 MB on the free tier; the minimum billed length is 10 s.
"""
import httpx

BASE = "https://api.groq.com/openai/v1/"
MODEL = "whisper-large-v3-turbo"
MAX_BYTES = 20 * 1024 * 1024        # the Bot API hands out files up to 20 MB; Groq's free tier takes 25
KEY_CHARS = r"[A-Za-z0-9_\-]{20,200}"
# the file name tells Groq the container — by the MIME type the app or Telegram reports
EXT = {"audio/ogg": "ogg", "audio/oga": "ogg", "audio/opus": "ogg", "audio/webm": "webm", "video/webm": "webm",
       "audio/mp4": "m4a", "video/mp4": "mp4", "audio/x-m4a": "m4a", "audio/m4a": "m4a", "audio/aac": "m4a",
       "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/flac": "flac"}
KNOWN = ("flac", "mp3", "mp4", "mpeg", "mpga", "m4a", "ogg", "wav", "webm")


class SttError(Exception):
    """Why there are no words: a pult_i18n key and its arguments, so the owner reads it in their language."""

    def __init__(self, key, **kw):
        super().__init__(key)
        self.key = key
        self.kw = kw


def ext_of(kind):
    """'audio/webm;codecs=opus' → 'webm'; 'voice/file_3.oga' → 'ogg'; unknown → None."""
    s = str(kind or "").lower().split(";")[0].strip()
    if s in EXT:
        return EXT[s]
    tail = s.rsplit(".", 1)[-1] if "." in s else ""
    return "ogg" if tail == "oga" else tail if tail in KNOWN else None


class Stt:
    """One Groq account. Through the proxy first if one is set (PULT_PROXY); if that fails, directly — like Tg."""

    def __init__(self, key, proxy=None, transport=None):
        self.key = key
        t = httpx.Timeout(60, connect=10)
        if transport is not None:       # tests: one transport, or one per route
            self.clients = [httpx.AsyncClient(transport=x, timeout=t)
                            for x in (transport if isinstance(transport, (list, tuple)) else [transport])]
        else:
            self.clients = ([httpx.AsyncClient(proxy=proxy, timeout=t)] if proxy else []) + \
                           [httpx.AsyncClient(timeout=t)]
        self.cur = 0

    async def _send(self, method, path, **kw):
        last = None
        for k in range(len(self.clients)):
            i = (self.cur + k) % len(self.clients)
            try:
                r = await self.clients[i].request(method, BASE + path,
                                                  headers={"Authorization": "Bearer " + self.key}, **kw)
            except (httpx.ConnectError, httpx.ProxyError, httpx.ConnectTimeout, httpx.ReadError,
                    httpx.ReadTimeout) as e:
                last = e
                continue
            self.cur = i
            return r
        raise SttError("stt.e.net", why=type(last).__name__)

    @staticmethod
    def _fail(r):
        try:
            msg = (r.json().get("error") or {}).get("message")
        except ValueError:
            msg = None
        if r.status_code in (401, 403):
            raise SttError("stt.e.key")
        if r.status_code == 413:
            raise SttError("stt.e.big")
        if r.status_code == 429:
            raise SttError("stt.e.limit")
        raise SttError("stt.e.groq", msg=str(msg or "HTTP %d" % r.status_code)[:200])

    async def check(self):
        """Whether the key works — the cheapest call there is."""
        r = await self._send("GET", "models")
        if r.status_code != 200:
            self._fail(r)

    async def transcribe(self, blob, kind, language=None, prompt=None):
        """The words of a recording. kind — a MIME type or a file name; language — ISO-639-1 or None (Whisper
        guesses); prompt — vocabulary and punctuation to lean towards. Whitespace is squeezed."""
        ext = ext_of(kind)
        if not ext:
            raise SttError("stt.e.format", kind=str(kind)[:40])
        if len(blob) > MAX_BYTES:
            raise SttError("stt.e.big")
        data = {"model": MODEL, "response_format": "json", "temperature": "0"}
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt[:800]
        r = await self._send("POST", "audio/transcriptions", data=data,
                             files={"file": ("voice." + ext, blob, "application/octet-stream")})
        if r.status_code != 200:
            self._fail(r)
        try:
            text = r.json().get("text")
        except ValueError:
            raise SttError("stt.e.groq", msg="not JSON") from None
        return " ".join(str(text or "").split())
