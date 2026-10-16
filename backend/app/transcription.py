"""Voice typing for the Playground's microphone button (added 2026-10-14).

What it is: the browser records a short clip, POSTs it to
POST /api/chat/transcribe (app/main.py), and gets back plain text, which the
page puts into the message box for the user to edit and send as an ordinary
message. The audio goes to the transcription model and nowhere else: it is
never sent to Kael, never saved to the database, never written to a log, and
nothing here keeps it after the request ends.

Not translation. The text is in the language that was spoken (the model
detects it). Kael reads any language, and a user who wants it translated can
ask in the message.

Upstream (internal; customers must never see these names, see AGENTS.md):
OpenRouter's dedicated speech-to-text endpoint, `POST /api/v1/audio/transcriptions`
(docs: openrouter.ai/docs/guides/overview/multimodal/stt, read 2026-10-14),
model `openai/whisper-large-v3` (config.TRANSCRIPTION_MODEL). It takes JSON
`{model, input_audio: {data: <base64>, format}}` and answers
`{text, usage: {seconds, cost, ...}}`. Its providers time out after 60 s per
request, which is why a clip is capped at two minutes and a few MB (the page
stops a recording at MAX_RECORDING_SECONDS).

Cost: priced per second of audio (about $0.11 per hour on OpenRouter's page,
2026-10-14), so a full two-minute clip costs well under a cent. Quancis
absorbs it: it is not billed to the customer's balance and not written to the
ledger, like the critic pass's extra input. Abuse is bounded by a signed-in
user, a positive balance and rate_limit.enforce_transcribe_rate_limit().

The pure parts (format sniffing, request body, response handling) are covered
by `python test_transcription.py`. httpx is imported inside transcribe() so
those tests need nothing installed.
"""
import base64

# The recording itself, decoded. A browser records speech with Opus or AAC at
# roughly 16-64 kbit/s, so two minutes is well under 1 MB; the cap leaves room
# for a high-bitrate recorder while still keeping a request small.
MAX_AUDIO_BYTES = 5 * 1024 * 1024
# Smaller than this is an empty or cut-off recording, not speech.
MIN_AUDIO_BYTES = 800
# Mirrors frontend/src/lib/voice.ts (VOICE_MAX_SECONDS). The server cannot
# measure a compressed clip's length cheaply; the byte cap is what it enforces.
MAX_RECORDING_SECONDS = 120
# Whisper can return a lot of text for a long clip; nothing sensible here is
# longer than the message box allows.
MAX_TRANSCRIPT_CHARS = 30_000

# Our whole upstream budget for one call. Below the provider's own 60 s limit
# plus the time to receive the answer.
UPSTREAM_TIMEOUT_SECONDS = 58.0


class TranscriptionError(Exception):
    """A failure with a message that is safe to show the user (it never names
    the upstream). `status` is the HTTP status to answer with, `code` the
    machine-readable reason."""

    def __init__(self, status: int, message: str, code: str):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


def sniff_audio_format(raw: bytes) -> str | None:
    """The `input_audio.format` value for `raw`, judged from its first bytes
    (the browser's own claim about the type is never trusted), or None if it
    is not one of the formats browsers record or upload for speech.

    webm: what Chrome, Edge, Firefox and Android record. mp4 / m4a: what Safari
    and iPhones record (sent as "m4a", the name the upstream documents). ogg:
    older Firefox. wav, mp3, flac: files, and a few recorders."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < 12:
        return None
    head = bytes(raw[:12])
    if head[:4] == b"\x1a\x45\xdf\xa3":  # EBML: webm (or Matroska)
        return "webm"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"fLaC":
        return "flac"
    if head[4:8] == b"ftyp":  # ISO base media: mp4 / m4a
        return "m4a"
    if head[:3] == b"ID3":
        return "mp3"
    # A bare MPEG audio frame: 11 sync bits, layer III.
    if head[0] == 0xFF and (head[1] & 0xE0) == 0xE0 and (head[1] & 0x06) == 0x02:
        return "mp3"
    return None


def build_request_body(raw: bytes, fmt: str, model: str) -> dict:
    """The JSON the upstream takes. Language is left out on purpose so the
    model detects it; a person can speak any language they like."""
    return {
        "model": model,
        "input_audio": {"data": base64.b64encode(raw).decode("ascii"), "format": fmt},
    }


def clean_transcript(text) -> str:
    """The transcript as shown in the message box: whitespace (including the
    odd leading space or stray line break the model adds) collapsed to single
    spaces, trimmed, and capped. '' when there is nothing."""
    if not isinstance(text, str):
        return ""
    return " ".join(text.split())[:MAX_TRANSCRIPT_CHARS].strip()


def _upstream_message(payload) -> str:
    err = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or "")[:300]
    return ""


def handle_response(status: int, payload) -> dict:
    """Turns the upstream's answer into {"text", "seconds", "cost"}, or raises
    TranscriptionError. Every user-facing message here is generic on purpose:
    the upstream's own error text goes to the server log only."""
    if status == 200 and isinstance(payload, dict) and isinstance(payload.get("text"), str):
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return {
            "text": clean_transcript(payload["text"]),
            "seconds": usage.get("seconds"),
            "cost": usage.get("cost"),
        }
    detail = _upstream_message(payload)
    print(f"[transcribe] upstream status={status} message={detail!r}")
    if status == 400 or status == 415 or status == 422:
        raise TranscriptionError(422, "That recording could not be read. Please try again.", "audio_unreadable")
    if status == 413:
        raise TranscriptionError(413, "That recording is too large. Try a shorter one.", "audio_too_large")
    if status == 429:
        raise TranscriptionError(429, "Voice typing is busy right now. Please try again in a moment.", "voice_busy")
    if status in (408, 504):
        raise TranscriptionError(504, "Turning that into text took too long. Try a shorter recording.", "voice_timeout")
    # 401 / 402 / 403 are OUR upstream account (bad key, no credit): an operator
    # problem the user cannot fix, logged above. Everything else is a failure on
    # their side. Either way the user sees the same thing.
    raise TranscriptionError(503, "Voice typing is unavailable right now. You can still type your message.", "voice_unavailable")


async def _post_json(url: str, headers: dict, body: dict) -> tuple[int, object]:
    import httpx  # here, not at the top: the pure helpers above need nothing installed

    timeout = httpx.Timeout(connect=8.0, read=UPSTREAM_TIMEOUT_SECONDS, write=15.0, pool=8.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=body)
    except httpx.TimeoutException:
        return 504, None
    except httpx.HTTPError as e:
        print(f"[transcribe] network error: {type(e).__name__}")
        return 502, None
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload


async def transcribe(raw: bytes, *, api_key: str, base_url: str, model: str, post=None) -> dict:
    """Transcribes one clip. Raises TranscriptionError (message safe to show).
    `post` is for tests: an async callable (url, headers, body) -> (status,
    payload) used instead of a real HTTP call."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < MIN_AUDIO_BYTES:
        raise TranscriptionError(422, "That recording was empty. Hold on a little longer and try again.", "audio_empty")
    if len(raw) > MAX_AUDIO_BYTES:
        raise TranscriptionError(413, "That recording is too large. Try a shorter one.", "audio_too_large")
    fmt = sniff_audio_format(bytes(raw))
    if fmt is None:
        raise TranscriptionError(415, "That recording is in a format voice typing cannot read.", "audio_format")
    if not api_key:
        print("[transcribe] no upstream API key configured")
        raise TranscriptionError(503, "Voice typing is unavailable right now. You can still type your message.", "voice_unavailable")
    url = f"{base_url.rstrip('/')}/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    status, payload = await (post or _post_json)(url, headers, build_request_body(bytes(raw), fmt, model))
    result = handle_response(status, payload)
    # Seconds and cost only: never the audio, never the text.
    print(f"[transcribe] ok seconds={result['seconds']} cost={result['cost']} chars={len(result['text'])}")
    return result
