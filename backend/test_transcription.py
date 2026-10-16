"""Plain-script tests for app/transcription.py (voice typing). No network:
the upstream call is replaced by a fake. stdlib only.

Run: python test_transcription.py
"""
import asyncio
import base64

from app import transcription as tr

failures = 0


def check(name, cond):
    global failures
    if cond:
        print(f"ok   {name}")
    else:
        failures += 1
        print(f"FAIL {name}")


def run(coro):
    return asyncio.run(coro)


def pad(head: bytes, n: int = 4000) -> bytes:
    return head + b"\x00" * (n - len(head))


WEBM = pad(b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01")
OGG = pad(b"OggS\x00\x02\x00\x00\x00\x00\x00\x00")
WAV = pad(b"RIFF\x24\x10\x00\x00WAVEfmt ")
FLAC = pad(b"fLaC\x00\x00\x00\x22\x10\x00\x10\x00")
MP4 = pad(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00")
MP3_ID3 = pad(b"ID3\x04\x00\x00\x00\x00\x00\x00\x00\x00")
MP3_FRAME = pad(b"\xff\xfb\x90\x64\x00\x00\x00\x00\x00\x00\x00\x00")

# --- format sniffing: the bytes decide ---
check("webm is recognised", tr.sniff_audio_format(WEBM) == "webm")
check("ogg is recognised", tr.sniff_audio_format(OGG) == "ogg")
check("wav is recognised", tr.sniff_audio_format(WAV) == "wav")
check("flac is recognised", tr.sniff_audio_format(FLAC) == "flac")
check("mp4 (Safari) is sent as m4a", tr.sniff_audio_format(MP4) == "m4a")
check("mp3 with an ID3 tag is recognised", tr.sniff_audio_format(MP3_ID3) == "mp3")
check("a bare mp3 frame is recognised", tr.sniff_audio_format(MP3_FRAME) == "mp3")
check("a picture is not audio", tr.sniff_audio_format(pad(b"\xff\xd8\xff\xe0")) is None)
check("text is not audio", tr.sniff_audio_format(b"hello world, this is not audio at all") is None)
check("a tiny blob is not audio", tr.sniff_audio_format(b"\x1a\x45\xdf\xa3") is None)
check("None is not audio", tr.sniff_audio_format(None) is None)
check("an ADTS/AAC-looking header is not claimed as mp3", tr.sniff_audio_format(pad(b"\xff\xf1\x50\x80\x00\x00\x00\x00\x00\x00\x00\x00")) is None)

# --- request body ---
body = tr.build_request_body(WEBM, "webm", "openai/whisper-large-v3")
check("body names the model", body["model"] == "openai/whisper-large-v3")
check("body carries the format", body["input_audio"]["format"] == "webm")
check("body carries base64 of the exact bytes", base64.b64decode(body["input_audio"]["data"]) == WEBM)
check("body leaves the language to auto-detect", "language" not in body)
check("base64 is raw, not a data URI", not body["input_audio"]["data"].startswith("data:"))

# --- transcript cleaning ---
check("whitespace is collapsed and trimmed", tr.clean_transcript("  Hello   there.\n\n How are you? ") == "Hello there. How are you?")
check("non-string gives empty", tr.clean_transcript(None) == "")
check("a transcript is capped", len(tr.clean_transcript("a " * 50_000)) <= tr.MAX_TRANSCRIPT_CHARS)
check("silence gives empty text", tr.clean_transcript("   ") == "")

# --- upstream answers ---
ok = tr.handle_response(200, {"text": " Hello world. ", "usage": {"seconds": 3.2, "cost": 0.000012}})
check("a good answer gives clean text", ok["text"] == "Hello world.")
check("usage is passed on for the log", ok["seconds"] == 3.2 and ok["cost"] == 0.000012)
check("a good answer without usage still works", tr.handle_response(200, {"text": "hi"})["text"] == "hi")
check("empty speech is an empty string, not an error", tr.handle_response(200, {"text": ""})["text"] == "")


def err(status, payload=None):
    try:
        tr.handle_response(status, payload)
    except tr.TranscriptionError as e:
        return e
    return None


e400 = err(400, {"error": {"message": "invalid audio"}})
check("400 becomes 'unreadable' (422)", e400 and e400.status == 422 and e400.code == "audio_unreadable")
check("429 becomes 'busy'", (err(429) or tr.TranscriptionError(0, "", "")).status == 429)
check("504 becomes 'timeout'", (err(504) or tr.TranscriptionError(0, "", "")).code == "voice_timeout")
check("408 becomes 'timeout'", (err(408) or tr.TranscriptionError(0, "", "")).code == "voice_timeout")
check("402 (our own upstream credit) is just 'unavailable'", (err(402, {"error": {"message": "Insufficient credits"}}) or tr.TranscriptionError(0, "", "")).code == "voice_unavailable")
check("401 (our key) is just 'unavailable'", (err(401) or tr.TranscriptionError(0, "", "")).code == "voice_unavailable")
check("500 is 'unavailable'", (err(500) or tr.TranscriptionError(0, "", "")).status == 503)
check("200 with no text field is an error", err(200, {"nope": 1}) is not None)
check("a non-JSON failure is an error", err(502, None) is not None)

# Customers must never see the upstream (AGENTS.md "Upstream is secret").
leaks = []
for status, payload in [
    (400, {"error": {"message": "OpenRouter says whisper-large-v3 by OpenAI via Groq failed"}}),
    (402, {"error": {"message": "Insufficient credits on your OpenRouter account"}}),
    (429, {"error": {"message": "DeepInfra rate limited"}}),
    (500, {"error": {"message": "Together AI exploded"}}),
    (504, None), (413, None), (401, None), (404, None),
]:
    e = err(status, payload)
    text = (e.message if e else "").lower()
    for word in ("openrouter", "whisper", "openai", "groq", "deepinfra", "together", "credits", "api key", "model"):
        if word in text:
            leaks.append((status, word))
check("no user-facing message names the upstream or echoes its error", leaks == [])

# --- the whole call, with the network replaced ---
calls = []


async def fake_post_ok(url, headers, body):
    calls.append((url, headers, body))
    return 200, {"text": " dictated words ", "usage": {"seconds": 4.0, "cost": 0.00001}}


async def fake_post_fail(url, headers, body):
    return 500, {"error": {"message": "boom, from OpenRouter"}}


async def fake_post_must_not_run(url, headers, body):
    raise AssertionError("the upstream must not be called")


res = run(tr.transcribe(WEBM, api_key="k-test", base_url="https://example.test/api/", model="m/x", post=fake_post_ok))
check("transcribe returns the text", res["text"] == "dictated words")
check("it posts to the transcription path under the base URL", calls[0][0] == "https://example.test/api/v1/audio/transcriptions")
check("it authenticates with the key", calls[0][1]["Authorization"] == "Bearer k-test")
check("it sends the sniffed format and the model", calls[0][2]["input_audio"]["format"] == "webm" and calls[0][2]["model"] == "m/x")


def expect(coro_factory, code):
    try:
        run(coro_factory())
    except tr.TranscriptionError as e:
        return e.code == code
    return False


check("an upstream failure surfaces as a safe error", expect(lambda: tr.transcribe(WEBM, api_key="k", base_url="https://x", model="m", post=fake_post_fail), "voice_unavailable"))
check("an empty/cut-off clip never reaches the upstream", expect(lambda: tr.transcribe(b"\x1a\x45\xdf\xa3" + b"\x00" * 100, api_key="k", base_url="https://x", model="m", post=fake_post_must_not_run), "audio_empty"))
check("a non-audio upload never reaches the upstream", expect(lambda: tr.transcribe(pad(b"\xff\xd8\xff\xe0"), api_key="k", base_url="https://x", model="m", post=fake_post_must_not_run), "audio_format"))
check("an oversized clip never reaches the upstream", expect(lambda: tr.transcribe(WEBM + b"\x00" * tr.MAX_AUDIO_BYTES, api_key="k", base_url="https://x", model="m", post=fake_post_must_not_run), "audio_too_large"))
check("a missing key never reaches the upstream", expect(lambda: tr.transcribe(WEBM, api_key="", base_url="https://x", model="m", post=fake_post_must_not_run), "voice_unavailable"))
check("a clip exactly at the cap is accepted", run(tr.transcribe(WEBM + b"\x00" * (tr.MAX_AUDIO_BYTES - len(WEBM)), api_key="k", base_url="https://x", model="m", post=fake_post_ok))["text"] == "dictated words")

check("a two-minute cap fits the 60 s upstream limit with room", tr.MAX_RECORDING_SECONDS <= 120 and tr.UPSTREAM_TIMEOUT_SECONDS < 60)

print()
if failures:
    print(f"{failures} CHECK(S) FAILED")
    raise SystemExit(1)
print("ALL CHECKS PASSED")
