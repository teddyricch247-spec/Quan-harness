"""Pure helpers for the playground conversation routes (/api/chat/*) in app/main.py.

"Playground conversation" is the product term. The routes and tables keep
their historical names (/api/chat/sessions, chat_sessions, chat_messages).

No I/O and no FastAPI imports on purpose, so everything here is covered by
`python test_chat_history.py` without installing the web stack.

What lives here and why (all of it was inline in main.py, or missing, before
2026-10-04):

* parse_session_id: a session id in a URL is untrusted text. Anything that is
  not a UUID is "not found" without a database round trip.
* clean_title / auto_title: titles are single-line, trimmed, length-capped.
  A whitespace-only title used to be accepted and rendered as an empty row.
* build_model_messages: what is actually sent to the model for one turn.
  Previously the whole stored history was sent, unbounded, and the history
  read itself was capped by PostgREST's default row limit (1000), which cut
  off the NEWEST messages of a long chat. It now (1) takes the newest rows,
  (2) merges consecutive same-role messages (old rows can contain two user
  messages in a row from sends that failed before 2026-10-04), (3) drops the
  oldest messages once a message-count or character budget is exceeded, and
  (4) never starts the conversation with an assistant message.
* clean_images / image parts: pictures attached to a message (added
  2026-10-11). Validated and size-capped here; build_model_messages turns a
  message that has pictures into a Chat-Completions content-parts list
  (text part + image_url parts), the same shape the public API already accepts.
* SessionGate: one reply at a time per chat. Two tabs sending to the same
  session used to interleave and each build its history without the other's
  turn. In-memory and per process, like rate_limit.py: it assumes the single
  instance the rest of the backend already assumes (see AGENTS.md).
"""
import asyncio
import base64
import binascii
import datetime
import json
import re
import time
import uuid

from . import chat_files
from .thinking_fillers import is_filler

# A user message above this is rejected with a 400 (the frontend's textarea
# has the same cap, lib/api.ts CHAT_MESSAGE_MAX_CHARS). The largest message in
# the live database at the time of writing was ~75k characters.
MAX_MESSAGE_CHARS = 100_000

MAX_TITLE_CHARS = 200
AUTO_TITLE_CHARS = 60
DEFAULT_TITLE = "New conversation"
# Titles written before 2026-10-06 (DB column default, old frontend fallback).
# They are shown as DEFAULT_TITLE and count as "never titled".
LEGACY_DEFAULT_TITLES = frozenset({"new chat", "untitled chat", "new session"})

# Budget for the history sent to the model on one turn (after merging). The
# newest message is always kept. The oldest messages fall off first.
HISTORY_MAX_MESSAGES = 200
HISTORY_MAX_CHARS = 400_000

# How many stored rows a send reads from the database: a little above
# HISTORY_MAX_MESSAGES so merging consecutive same-role rows cannot leave the
# window short of its message budget.
HISTORY_FETCH_LIMIT = 300

# How many rows GET /api/chat/sessions/{id} returns for display (newest).
DISPLAY_MAX_MESSAGES = 1000

_WS_RE = re.compile(r"\s+")

# --- Pictures attached to a playground message (2026-10-11) ----------------
# The browser shrinks every picture before sending (lib/images.ts: longest
# side 1568 px, JPEG), so a normal picture is a few hundred KB. These limits
# are the server's own, for a client that does not.
MAX_IMAGES_PER_MESSAGE = 4
MAX_IMAGE_BYTES = 3 * 1024 * 1024            # one picture, decoded
MAX_MESSAGE_IMAGE_BYTES = 8 * 1024 * 1024    # all pictures of one message, decoded
# Total pictures one conversation may hold. A hard cap rather than "keep the
# newest N": every picture stays in the history sent to the model, so the
# start of the prompt never changes between turns and the upstream prompt
# cache keeps hitting. Dropping the oldest picture would shift everything
# after it on every new picture.
MAX_IMAGES_PER_CONVERSATION = 20
# All pictures of one conversation, decoded. Every later turn re-reads and
# re-sends them all, so a count alone is not enough: 20 pictures of 3 MB each
# would be ~80 MB per turn. The page shrinks pictures to ~1.2 MB at most, so
# 24 MB is far above normal use (20 x 1.2 MB) and only stops oversized uploads.
MAX_CONVERSATION_IMAGE_BYTES = 24 * 1024 * 1024
# What one picture counts for against HISTORY_MAX_CHARS when the history is
# trimmed. Not a token count, just a weight so pictures cannot be free.
IMAGE_HISTORY_CHAR_COST = 4_000
IMAGE_ONLY_TITLE = "Image"


def parse_session_id(value) -> str | None:
    """Canonical lowercase UUID string, or None if `value` is not a UUID."""
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        return None


def clean_title(raw, max_chars: int = MAX_TITLE_CHARS) -> str:
    """Single line, whitespace collapsed, trimmed, capped. "" if nothing
    printable is left (the caller decides whether that is an error)."""
    if not isinstance(raw, str):
        return ""
    text = _WS_RE.sub(" ", raw).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text


def is_default_title(title) -> bool:
    """True for an empty title, DEFAULT_TITLE, or a pre-rename default."""
    text = clean_title(title).lower()
    return (not text) or text == DEFAULT_TITLE.lower() or text in LEGACY_DEFAULT_TITLES


def display_title(title) -> str:
    """Title as shown to the user: legacy / empty defaults become DEFAULT_TITLE."""
    return DEFAULT_TITLE if is_default_title(title) else clean_title(title)


_MD_LEAD_RE = re.compile(r"^[#>*+\-\s]+")


def auto_title(first_message: str, has_images: bool = False) -> str:
    """Title for a playground conversation, from its first user message.

    Lines are joined into one (as before), but code-fence lines and leading
    markdown markers (# > - * +) are dropped, so a message that opens with a
    code block does not become a title like "```python". Cut at a word
    boundary with an ellipsis when longer than AUTO_TITLE_CHARS. A first
    message that is only pictures (no text) is titled IMAGE_ONLY_TITLE."""
    if not isinstance(first_message, str):
        return DEFAULT_TITLE
    # Attached text files (2026-10-14) are part of the message text. They must
    # not become the title: it is what the user typed, else the first file's
    # name, else (pictures only) "Image".
    file_name = chat_files.first_file_name(first_message)
    first_message = chat_files.strip_attached_files(first_message)
    if not first_message.strip():
        if file_name:
            return clean_title(file_name, AUTO_TITLE_CHARS) or DEFAULT_TITLE
        if has_images:
            return IMAGE_ONLY_TITLE
    parts = []
    for line in first_message.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            continue
        stripped = _MD_LEAD_RE.sub("", stripped).strip()
        if stripped:
            parts.append(stripped)
            if sum(len(x) + 1 for x in parts) > AUTO_TITLE_CHARS * 2:
                break
    text = clean_title(" ".join(parts) or first_message)
    if not text:
        return DEFAULT_TITLE
    if len(text) <= AUTO_TITLE_CHARS:
        return text
    cut = text[: AUTO_TITLE_CHARS - 1]
    if " " in cut and not text[AUTO_TITLE_CHARS - 1].isspace():
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:-") + "\u2026"


def sniff_image_mime(raw: bytes) -> str | None:
    """The image type of `raw` from its first bytes, or None if it is not one
    of the four types the model is sent. The browser's own claim about the
    type is never trusted: the bytes decide."""
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_data_url(image: dict) -> str:
    return f"data:{image['mime']};base64,{image['data']}"


def clean_images(raw, max_images: int = MAX_IMAGES_PER_MESSAGE) -> list[dict]:
    """Validates the `images` list of a message send. Each entry is either
    {"data": <base64>, "mime": ...} or a "data:image/...;base64,..." string.
    Returns [{"mime", "data" (base64, no prefix), "bytes" (decoded size)}] with
    the mime taken from the bytes themselves. None / [] -> []. Raises
    ValueError with a message that is safe to show the user."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("images must be a list.")
    if len(raw) > max_images:
        raise ValueError(f"You can attach up to {max_images} pictures to one message.")
    out: list[dict] = []
    total = 0
    for item in raw:
        data = item.get("data") if isinstance(item, dict) else item
        if not isinstance(data, str) or not data.strip():
            raise ValueError("One of the pictures is empty or unreadable.")
        data = data.strip()
        if data.startswith("data:"):
            head, sep, data = data.partition(",")
            if not sep or ";base64" not in head:
                raise ValueError("One of the pictures is not valid base64.")
        data = "".join(data.split())
        # Reject on the encoded size first, so a huge string is never decoded.
        if len(data) * 3 // 4 > MAX_IMAGE_BYTES + 3:
            raise ValueError(f"One of the pictures is too large (the limit is {MAX_IMAGE_BYTES // (1024 * 1024)} MB each).")
        try:
            decoded = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("One of the pictures is not valid base64.")
        if not decoded:
            raise ValueError("One of the pictures is empty or unreadable.")
        if len(decoded) > MAX_IMAGE_BYTES:
            raise ValueError(f"One of the pictures is too large (the limit is {MAX_IMAGE_BYTES // (1024 * 1024)} MB each).")
        mime = sniff_image_mime(decoded)
        if mime is None:
            raise ValueError("Only JPEG, PNG, WebP or GIF pictures can be attached.")
        total += len(decoded)
        if total > MAX_MESSAGE_IMAGE_BYTES:
            raise ValueError(f"The pictures in one message can be {MAX_MESSAGE_IMAGE_BYTES // (1024 * 1024)} MB in total.")
        out.append({"mime": mime, "data": data, "bytes": len(decoded)})
    return out


def _message_content(text: str, images: list[dict]):
    """A message's `content` for the model: the plain string when there are no
    pictures (exactly as before), else a Chat-Completions parts list. The text
    part is left out when the message is only pictures."""
    if not images:
        return text
    parts: list[dict] = []
    if text.strip():
        parts.append({"type": "text", "text": text})
    for image in images:
        parts.append({"type": "image_url", "image_url": {"url": image_data_url(image)}})
    return parts


def build_model_messages(
    stored: list[dict],
    new_user_content: str,
    max_messages: int = HISTORY_MAX_MESSAGES,
    max_chars: int = HISTORY_MAX_CHARS,
    new_images: list[dict] | None = None,
) -> list[dict]:
    """Messages for one model call: stored history (oldest first, rows with
    `role` and `content`, and optionally `images` = [{"mime", "data"}]) plus the
    new user turn, normalised and trimmed. See the module docstring for the
    four things this guarantees. A message with pictures is sent as a content
    parts list (see _message_content); one without is a plain string, as before."""
    merged: list[dict] = []
    rows = [m for m in stored if isinstance(m, dict)] + [{"role": "user", "content": new_user_content, "images": new_images or []}]
    for row in rows:
        role = row.get("role")
        content = row.get("content")
        images = [i for i in (row.get("images") or []) if isinstance(i, dict) and i.get("data") and i.get("mime")] if role == "user" else []
        if role not in ("user", "assistant") or not isinstance(content, str) or (not content.strip() and not images):
            continue
        if merged and merged[-1]["role"] == role:
            merged[-1]["text"] = f"{merged[-1]['text']}\n\n{content}" if merged[-1]["text"].strip() and content.strip() else (merged[-1]["text"] or content)
            merged[-1]["images"].extend(images)
        else:
            merged.append({"role": role, "text": content, "images": list(images)})

    def weight(m: dict) -> int:
        return len(m["text"]) + IMAGE_HISTORY_CHAR_COST * len(m["images"])

    total = sum(weight(m) for m in merged)
    start = 0
    while len(merged) - start > 1 and (len(merged) - start > max_messages or total > max_chars):
        total -= weight(merged[start])
        start += 1
    trimmed = merged[start:]

    # Never open with an assistant turn (dropping the oldest messages can
    # leave one first). The final message is the new user turn, so this loop
    # always stops.
    while len(trimmed) > 1 and trimmed[0]["role"] == "assistant":
        trimmed.pop(0)
    return [{"role": m["role"], "content": _message_content(m["text"], m["images"])} for m in trimmed]


class SessionGate:
    """One in-flight reply per chat session. try_acquire() is False while a
    reply for that session is still being generated. An entry older than
    `stale_after` seconds is treated as released, so a path that fails to call
    release() can never lock a chat forever."""

    def __init__(self, stale_after: float = 900.0):
        self._stale_after = stale_after
        self._busy: dict[str, float] = {}

    def try_acquire(self, session_id: str) -> bool:
        now = time.monotonic()
        started = self._busy.get(session_id)
        if started is not None and now - started < self._stale_after:
            return False
        self._busy[session_id] = now
        return True

    def release(self, session_id: str) -> None:
        self._busy.pop(session_id, None)


# ---------------------------------------------------------------------------
# Detached generation jobs (added for the playground reload fix)
# ---------------------------------------------------------------------------
# The reply for a playground message is produced by a background task inside
# the pipeline that does not depend on the browser staying connected. What did
# depend on it: the user's message and the reply are saved together only when
# the reply finishes, and the one-reply-per-chat lock was released the moment
# the browser disconnected. So after going offline or reloading, the page found
# neither the message nor a reply, and the chat was open for a second, duplicate
# send while the first was still running.
#
# A GenerationJob is the server-side record of one in-flight reply: the user's
# message, the thinking titles Kael has streamed so far, the answer text so far
# and the outcome. It is fed by a pump task that keeps reading the pipeline's
# stream whether or not any browser is still attached, and it is what
# GET /api/chat/sessions/{id} reports as `pending`. In memory and per process,
# like SessionGate and rate_limit.py (single backend instance, see AGENTS.md).

# Every tier any model accepts. Which of these a given conversation may use
# depends on its model (config.PRODUCTS[...]["reasoning_tiers"]); callers pass
# that subset to clean_reasoning_effort().
VALID_REASONING_EFFORTS = ("low", "high", "max", "z-low", "z-high")

# A failed job stays visible this long so a reload after a failure shows the
# error (with Retry) instead of a chat that silently lost the message.
FAILED_JOB_TTL_SECONDS = 600.0
# Same ceiling as SessionGate / the 15-minute request limit.
JOB_STALE_SECONDS = 900.0

MAX_THINKING_ENTRIES = 300
MAX_THINKING_ENTRY_CHARS = 500


def clean_reasoning_effort(raw, allowed: tuple[str, ...] = VALID_REASONING_EFFORTS) -> str | None:
    """None when absent (the model then uses its own default tier); the
    lowercase tier when it is one of `allowed`; raises ValueError for anything
    else. `allowed` is the tiers of the conversation's model."""
    if raw is None:
        return None
    if not isinstance(raw, str) or raw.strip().lower() not in allowed:
        raise ValueError("reasoning_effort must be one of: " + ", ".join(allowed) + ".")
    return raw.strip().lower()


def clean_thinking(raw) -> list[str]:
    """Normalises a thinking list read from (or headed to) storage: strings
    only, trimmed, length- and count-capped, and without the idle-watchdog's
    filler words ("Thinking", "Reviewing the draft", ...): those are a
    liveness signal sent on the same wire field as real titles, not steps,
    and counting them inflated "Thinking · N steps". Applied on the way in
    AND out, so replies saved before this also read back without them.
    Anything that is not a list yields []."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip() and not is_filler(item):
            out.append(item.strip()[:MAX_THINKING_ENTRY_CHARS])
        if len(out) >= MAX_THINKING_ENTRIES:
            break
    return out


class GenerationJob:
    def __init__(self, session_id: str, content: str, started_at: datetime.datetime, reasoning_effort: str | None = None, image_count: int = 0):
        self.session_id = session_id
        self.content = content
        # How many pictures the message carried. Only the count is kept here (the
        # pictures themselves go to the model and, with the reply, to the
        # database); a page that reloads mid-reply shows "N pictures".
        self.image_count = max(int(image_count or 0), 0)
        self.started_at = started_at
        self.reasoning_effort = reasoning_effort
        self.thinking: list[str] = []
        self.text = ""
        self.status = "running"  # running | done | error
        self.error: dict | None = None  # {"message", "type", "code", "status"}
        self.saved = False  # the exchange reached the database
        self.finished_monotonic: float | None = None
        self._started_monotonic = time.monotonic()
        # Live consumer (the browser that sent the message). Unbounded on
        # purpose: if that browser is gone nobody reads it, and a reply is a
        # few hundred small chunks at most.
        self.queue: asyncio.Queue = asyncio.Queue()

    # -- feeding ---------------------------------------------------------
    def feed(self, chunk) -> None:
        """Takes one chunk exactly as the pipeline yielded it (an SSE event as
        str or bytes), records what the playground needs from it and queues the
        chunk, untouched, for the attached browser."""
        raw = chunk.decode("utf-8", "replace") if isinstance(chunk, (bytes, bytearray)) else str(chunk)
        for line in raw.split("\n"):
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                parsed = json.loads(payload)
            except ValueError:
                continue
            if not isinstance(parsed, dict):
                continue
            err = parsed.get("error")
            if isinstance(err, dict):
                self.fail(err.get("message") or "The reply was interrupted. Please try again.",
                          type_=err.get("type"), code=err.get("code"))
                continue
            choices = parsed.get("choices")
            delta = choices[0].get("delta") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
            if not isinstance(delta, dict):
                continue
            title = delta.get("reasoning_content")
            if isinstance(title, str) and title.strip():
                self.add_thinking(title)
            text = delta.get("content")
            if isinstance(text, str) and text:
                self.text += text
        self.queue.put_nowait(chunk)

    def add_thinking(self, title: str) -> None:
        title = title.strip()[:MAX_THINKING_ENTRY_CHARS]
        # Idle fillers share the wire field with real titles but are not
        # steps (see clean_thinking): never recorded.
        if is_filler(title):
            return
        if title and (not self.thinking or self.thinking[-1] != title) and len(self.thinking) < MAX_THINKING_ENTRIES:
            self.thinking.append(title)

    def fail(self, message: str, *, type_: str | None = None, code: str | None = None, status: int | None = None) -> None:
        if self.status == "error":
            return
        self.status = "error"
        self.error = {"message": message, "type": type_, "code": code, "status": status}

    def finish(self) -> None:
        if self.status == "running":
            if self.saved:
                # The exchange is in the database: that is the record, whatever
                # this job managed to parse out of the stream.
                self.status = "done"
            elif not self.text.strip():
                self.fail("Kael returned an empty reply. Please try again.", type_="server_error", code="empty_reply")
            else:
                self.fail("Kael replied, but the reply could not be saved. Please send your message again.", type_="server_error", code="not_saved")
        self.finished_monotonic = time.monotonic()
        self.queue.put_nowait(None)

    # -- reading ---------------------------------------------------------
    def is_stale(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if self.status == "running":
            return now - self._started_monotonic >= JOB_STALE_SECONDS
        if self.finished_monotonic is None:
            return True
        return now - self.finished_monotonic >= FAILED_JOB_TTL_SECONDS

    def view(self) -> dict:
        """What GET /api/chat/sessions/{id} reports as `pending`."""
        return {
            "status": self.status,
            "content": self.content,
            "image_count": self.image_count,
            "started_at": self.started_at.isoformat(),
            "thinking": list(self.thinking),
            "answer": self.text,
            "reasoning_effort": self.reasoning_effort,
            "error": self.error if self.status == "error" else None,
        }


class GenerationJobs:
    """One in-flight reply per chat (replaces SessionGate for the playground
    route) plus the record of it. A finished-with-error job is kept for
    FAILED_JOB_TTL_SECONDS so a reload can show the failure, but never blocks a
    new send; a successful job is dropped as soon as its pump ends, because the
    saved exchange is then the record."""

    def __init__(self):
        self._jobs: dict[str, GenerationJob] = {}

    def try_start(self, session_id: str, content: str, started_at: datetime.datetime, reasoning_effort: str | None = None, image_count: int = 0) -> GenerationJob | None:
        existing = self._jobs.get(session_id)
        if existing is not None and existing.status == "running" and not existing.is_stale():
            return None
        job = GenerationJob(session_id, content, started_at, reasoning_effort, image_count)
        self._jobs[session_id] = job
        return job

    def get(self, session_id: str) -> GenerationJob | None:
        job = self._jobs.get(session_id)
        if job is not None and job.is_stale():
            self._jobs.pop(session_id, None)
            return None
        return job

    def discard(self, session_id: str, job: GenerationJob | None = None) -> None:
        """Drops the job (only if it is still `job`, when given)."""
        current = self._jobs.get(session_id)
        if current is not None and (job is None or current is job):
            self._jobs.pop(session_id, None)


def pending_for_display(job: GenerationJob | None, messages: list[dict]) -> dict | None:
    """The `pending` block for GET /api/chat/sessions/{id}, or None. A job is
    hidden once its exchange is among `messages` (the user row of a saved
    exchange carries exactly job.started_at), so the page never shows a turn
    both as saved history and as in progress during the instant between the
    save and the job being dropped."""
    if job is None:
        return None
    for m in messages:
        created = m.get("created_at") if isinstance(m, dict) else None
        if not isinstance(created, str):
            continue
        try:
            when = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=datetime.timezone.utc)
        if when >= job.started_at:
            return None
    return job.view()


def _parse_ts(value) -> datetime.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        when = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    return when


def is_untouched(session: dict) -> bool:
    """True for a playground conversation row that never received a message:
    it still has a default title and last_message_at was never moved past
    created_at (a stored first message moves it). A cheap pre-filter only; the
    caller confirms with the messages table before hiding or deleting."""
    if not isinstance(session, dict) or not is_default_title(session.get("title")):
        return False
    created = _parse_ts(session.get("created_at"))
    last = _parse_ts(session.get("last_message_at"))
    if created is None or last is None:
        return False
    return abs((last - created).total_seconds()) < 2.0


def age_seconds(session: dict, now: datetime.datetime | None = None) -> float | None:
    """Seconds since the conversation was created; None if unknown."""
    created = _parse_ts(session.get("created_at")) if isinstance(session, dict) else None
    if created is None:
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (now - created).total_seconds()
