"""
Phase 6.1 (Implementation Order step 19) — image input on user messages. The PURE half: what counts as an
acceptable image, which attached images are shown to the model on a given call, and the wording of the
notes that stand in for the ones that aren't. No I/O, standard library only, so every rule here is
unit-tested directly (tests/test_image_input.py).

How the pieces fit (the I/O halves are elsewhere):
  * POST /sessions/{id}/attachments (routers/agent.py) decodes the upload, runs `sniff_image` on the BYTES,
    and stores it via repositories/session_attachments.py. The client's own claim about the file (its name,
    its MIME type) is never trusted: the type and dimensions come from the file's header.
  * The message that follows names the attachment ids. agent_loop appends the user `message` event with the
    attachments' METADATA only (id, filename, type, size) — the pixels live in `session_attachments`, never in
    `session_events`, exactly like a browser screenshot (a database row per image in the event log would be
    re-sent to every client and counted into every token estimate).
  * Each loop iteration agent_loop asks `select_attachment_ids_for_context` which images to load, loads them,
    and hands message_builder a {attachment id: data URI} map. Anything not in the map is rendered as a
    one-line note instead, so the model is never silently told nothing about a picture that exists.

Why the image count is capped in context (MAX_IMAGES_IN_CONTEXT): every image is re-sent on every iteration
of every later turn. The newest few are what the person is talking about; older ones are replaced by a note.
(Compaction, §17.1, drops them too once it condenses the part of the log they sit in.)

Why an unknown file is rejected rather than "best-effort passed on": a provider that cannot parse an image
rejects the whole request, and the image then sits in the transcript, so every later call would fail the same
way. Validating the header here keeps a corrupt or mislabelled upload from ever reaching a provider.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass

# --- limits ----------------------------------------------------------------------------------------------
# 3 MiB per image. The provider limit is higher (5 MB), but the picture is also stored as base64 text in a
# database row and sent through the database's HTTP gateway; the smaller cap keeps that path far from any
# request-size limit. A client that resizes first (the frontend helper does: 1568 px longest side) is nowhere
# near it. The same number is in db/migrations/0013_session_attachments.sql's CHECK constraints.
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_IMAGES_PER_MESSAGE = 4
MAX_PENDING_PER_SESSION = 12      # uploaded but not yet attached to a message
MAX_DIMENSION = 8000              # pixels, either side — the common provider ceiling
MAX_IMAGES_IN_CONTEXT = 6         # most recent attached images actually sent on a model call
IMAGE_TOKEN_ESTIMATE = 1600       # rough per-image cost for the pre-call compaction estimate (real counts replace it)
STALE_PENDING_SECONDS = 3600      # an upload never attached to a message is deleted after this long

ALLOWED_MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
_MEDIA_ALIASES = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg", "image/x-png": "image/png"}


class ImageRejected(ValueError):
    """Raised for an upload that must not be stored. `code` is stable (the router returns it; tests pin it);
    the message is written for the person who attached the file."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ImageInfo:
    media_type: str
    width: int
    height: int
    byte_size: int


def normalize_media_type(declared: str | None) -> str | None:
    if not declared:
        return None
    value = declared.split(";")[0].strip().lower()
    return _MEDIA_ALIASES.get(value, value)


def safe_filename(name: str | None) -> str:
    """A display name only (it is never used as a path). Keeps the last path component, drops control and
    bidirectional-override characters, caps the length."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[\x00-\x1f\x7f\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", base).strip()
    if not base:
        return "image"
    return base[:100]


# --- reading the header ----------------------------------------------------------------------------------


def _png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def _gif_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 10 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    return struct.unpack("<HH", data[6:10])


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i, n = 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker in (0x01, *range(0xD0, 0xD9)):  # standalone markers carry no length
            i += 2
            continue
        (length,) = struct.unpack(">H", data[i + 2 : i + 4])
        if length < 2:
            return None
        # SOF0..SOF15, excluding DHT (C4), JPG (C8) and DAC (CC): these hold the frame size.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if i + 9 > n:
                return None
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        i += 2 + length
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    kind = data[12:16]
    if kind == b"VP8 ":  # lossy
        if data[23:26] != b"\x9d\x01\x2a":
            return None
        width, height = struct.unpack("<HH", data[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if kind == b"VP8L":  # lossless
        if data[20] != 0x2F:
            return None
        (bits,) = struct.unpack("<I", data[21:25])
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if kind == b"VP8X":  # extended: 24-bit canvas size minus one
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    return None


_READERS = (
    ("image/png", _png_size),
    ("image/jpeg", _jpeg_size),
    ("image/gif", _gif_size),
    ("image/webp", _webp_size),
)


def sniff_image(data: bytes, declared_media_type: str | None = None) -> ImageInfo:
    """Validate an upload from its bytes. Raises ImageRejected with a stable `code`:
    empty | too_large | unsupported_type | media_type_mismatch | unreadable | bad_dimensions."""
    if not data:
        raise ImageRejected("empty", "That file is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageRejected(
            "too_large",
            f"That image is {len(data) / 1024 / 1024:.1f} MB; the limit is {MAX_IMAGE_BYTES // 1024 // 1024} MB. "
            "Resize or crop it and try again.",
        )
    detected: str | None = None
    size: tuple[int, int] | None = None
    for media_type, reader in _READERS:
        try:
            result = reader(data)
        except (struct.error, IndexError):
            result = None
        if result is not None:
            detected, size = media_type, result
            break
    if detected is None:
        # Distinguish "an image format we don't take" from "not an image / damaged".
        if data[:4] in (b"II*\x00", b"MM\x00*") or data[4:12] in (b"ftypheic", b"ftypheix", b"ftypavif", b"ftypmif1"):
            raise ImageRejected("unsupported_type", "That image format isn't supported. Use PNG, JPEG, WebP or GIF.")
        if data[:5] == b"<?xml" or data[:4] == b"<svg":
            raise ImageRejected("unsupported_type", "SVG files can't be attached. Use PNG, JPEG, WebP or GIF.")
        raise ImageRejected("unreadable", "That file isn't a readable PNG, JPEG, WebP or GIF image.")
    declared = normalize_media_type(declared_media_type)
    if declared is not None and declared != detected:
        raise ImageRejected(
            "media_type_mismatch",
            f"The file says it is {declared} but its contents are {detected}. Re-export it and try again.",
        )
    width, height = size  # type: ignore[misc]
    if width < 1 or height < 1 or width > MAX_DIMENSION or height > MAX_DIMENSION:
        raise ImageRejected(
            "bad_dimensions",
            f"That image is {width}×{height}px; each side must be between 1 and {MAX_DIMENSION}px.",
        )
    return ImageInfo(media_type=detected, width=width, height=height, byte_size=len(data))


# --- what the model is shown -----------------------------------------------------------------------------

_USER_EVENT_TYPES = ("message", "user_interrupt")


def attachments_of(event: dict) -> list[dict]:
    """The attachment metadata dicts on a user message / interrupt event, [] for anything else."""
    if event.get("event_type") not in _USER_EVENT_TYPES or event.get("role") != "user":
        return []
    items = (event.get("content") or {}).get("attachments")
    return [a for a in items if isinstance(a, dict) and a.get("id")] if isinstance(items, list) else []


def count_attachments(events: list[dict]) -> int:
    return sum(len(attachments_of(e)) for e in events)


def select_attachment_ids_for_context(events: list[dict], max_images: int = MAX_IMAGES_IN_CONTEXT) -> list[str]:
    """The ids of the (at most `max_images`) most recently attached images in `events` — newest first. Only
    these are loaded and sent; every other attachment is represented by a note in message_builder."""
    chosen: list[str] = []
    for event in reversed(events):
        for attachment in reversed(attachments_of(event)):
            if len(chosen) >= max_images:
                return chosen
            chosen.append(attachment["id"])
    return chosen


def attachment_label(attachment: dict) -> str:
    return safe_filename(attachment.get("filename"))


def shown_note(attachments: list[dict]) -> str:
    names = ", ".join(attachment_label(a) for a in attachments)
    return f"[{len(attachments)} image{'s' if len(attachments) != 1 else ''} attached: {names}]"


def withheld_note(attachments: list[dict]) -> str:
    names = ", ".join(attachment_label(a) for a in attachments)
    return (
        f"[{len(attachments)} image{'s' if len(attachments) != 1 else ''} attached but not shown to you "
        f"(an earlier picture, or this model can't read images): {names}. Don't describe what you can't see.]"
    )


def no_vision_message(model_label: str) -> str:
    """Person-facing. Shown when someone tries to attach an image and the project's model isn't confirmed to
    read images — the same wording and the same two fixes as the browser tools' (visual_qa_rules)."""
    return (
        f"Quan Harness couldn't confirm that {model_label} accepts image input, so the picture wasn't attached. "
        "Choose a vision-capable model under Connections → LLM Providers, or — if you know this model does "
        "accept images — list it in AGENT_VISION_MODELS on the server."
    )


def rejected_by_provider_message(model_label: str) -> str:
    return (
        f"The provider rejected the attached image(s) from {model_label}, so they were left out of this turn "
        "and won't be sent again in this conversation. Choose a vision-capable model under Connections → "
        "LLM Providers, or remove it from AGENT_VISION_MODELS if you listed it there."
    )


def earlier_images_left_out_message(model_label: str) -> str:
    return (
        f"Pictures attached earlier in this conversation were left out of this turn because {model_label} isn't "
        "confirmed to accept image input. Choose a vision-capable model under Connections → LLM Providers."
    )
