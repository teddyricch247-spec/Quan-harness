"""Files attached to a playground message: text, code, PDF and Word (added 2026-10-14).

No I/O and no FastAPI imports on purpose, so everything here is covered by
`python test_chat_files.py` without installing the web stack.

How an attached file travels
----------------------------
The browser reads the file (a PDF or Word file is read in the browser too, and
only its extracted text is sent) and puts the text in the message itself, one
block per file, wrapped like this (typed text, if any, goes AFTER the blocks):

    <attached_file name="app.py">
    ...the file's text...
    </attached_file>

So an attached file is just part of the user message's `content`. That is why
there is no database change and no new route: the message is saved, resent as
history and shown after a reload exactly like any other message. The browser
(frontend/src/lib/textFiles.ts) builds and parses the same format; this module
is the server's half: it checks the blocks and measures them.

Why the wrapper matters (prompt injection)
------------------------------------------
A file can contain text that tries to give Kael orders ("ignore everything
above..."). Two things keep that harmless:

1. models/kael/config.py `system_identity` tells the model that everything
   inside <attached_file> is the user's data, never instructions.
2. A file cannot close its own block early. The browser rewrites any literal
   `<attached_file` / `</attached_file` in a file's text (and in the typed
   text) to `&lt;attached_file` / `&lt;/attached_file`, and inspect() below
   REFUSES a message whose tags are not strictly open, close, open, close.
   So the "everything inside the tags is file data" promise is enforced here,
   not just hoped for. The typed text comes last on purpose: the last thing
   the model reads before answering is the user's own request, not a file.

Limits (the browser mirrors them: frontend/src/lib/textFiles.ts; if they
disagree, this file wins). Attached text is resent with EVERY later turn, like
pictures, so each level has its own cap.
"""
import re
from dataclasses import dataclass

# Files in one message, and characters of file text (not counting the
# wrapper). Per-message total sits below chat_history.MAX_MESSAGE_CHARS
# (100,000) so there is always room for the typed text and the wrappers.
MAX_FILES_PER_MESSAGE = 3
MAX_FILE_CHARS = 60_000
MAX_MESSAGE_FILE_CHARS = 80_000
# All attached text one conversation may hold. Every turn re-sends it, so a
# hard cap (like pictures) rather than dropping old files, which would change
# the start of the prompt each turn and defeat the upstream prompt cache.
# Below chat_history.HISTORY_MAX_CHARS (400,000) so history trimming does not
# silently drop a file while the conversation is still "under the cap".
MAX_CONVERSATION_FILE_CHARS = 240_000

MAX_FILE_NAME_CHARS = 120

TAG = "attached_file"

# Every opening or closing tag of ours, in any letter case, even when the rest
# of the tag is wrong. Used to prove the tags alternate.
_ANY_TAG_RE = re.compile(r"<(/?)" + TAG + r"(?![A-Za-z0-9_])", re.IGNORECASE)

# One well-formed block: opening tag with a name, a newline, the file text, a
# newline, the closing tag. The name has no quote, angle bracket, ampersand
# or control character (the browser replaces each with an underscore).
_BLOCK_RE = re.compile(
    r'<' + TAG + r' name="([^"<>&\x00-\x1f]*)">\n(.*?)\n</' + TAG + r'>',
    re.DOTALL,
)

# What the browser writes in place of a literal tag in file or typed text.
_ESC_TAG_RE = re.compile(r"&lt;(/?)" + TAG, re.IGNORECASE)
_BLOCK_GAP_RE = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class AttachedFile:
    name: str
    text: str  # as stored (tag-escaped); use unescape_tags() to show it
    start: int
    end: int


def find_attached_files(content) -> list[AttachedFile]:
    """The well-formed blocks in `content`, in order. Never raises: text that
    is not a block is simply not returned. (Whether the tags are well formed
    overall is inspect()'s job.)"""
    if not isinstance(content, str) or "<" not in content:
        return []
    return [AttachedFile(m.group(1), m.group(2), m.start(), m.end()) for m in _BLOCK_RE.finditer(content)]


def unescape_tags(text: str) -> str:
    """Turns the browser's `&lt;attached_file` back into `<attached_file`
    (for titles). A file that really contained `&lt;attached_file` comes back
    with a literal tag; that only affects how a title looks."""
    if not isinstance(text, str):
        return ""
    return _ESC_TAG_RE.sub(lambda m: "<" + m.group(1) + TAG, text)


def strip_attached_files(content: str) -> str:
    """`content` without its file blocks: what the user actually typed."""
    if not isinstance(content, str):
        return ""
    blocks = find_attached_files(content)
    if not blocks:
        return unescape_tags(content).strip()
    out: list[str] = []
    pos = 0
    for b in blocks:
        out.append(content[pos:b.start])
        pos = b.end
    out.append(content[pos:])
    return unescape_tags(_BLOCK_GAP_RE.sub("\n\n", "".join(out))).strip()


def file_chars(content) -> int:
    """Characters of attached-file text in one message (0 when it has none)."""
    return sum(len(b.text) for b in find_attached_files(content))


def inspect(content: str) -> list[AttachedFile]:
    """Validates the attached files in one outgoing message and returns them.

    Raises ValueError, with a message that is safe to show the user, when:
    the tags are not strictly open/close/open/close, a block is not in the
    exact form the browser writes, there are too many files, or one file or
    all of them are too long. A message with no tags passes and returns [].
    """
    if not isinstance(content, str):
        return []
    tags = list(_ANY_TAG_RE.finditer(content))
    if not tags:
        return []
    blocks = find_attached_files(content)
    expected_open = True
    ok = len(tags) == 2 * len(blocks)
    if ok:
        # Each tag must be exactly the start / end of one well-formed block.
        starts = {b.start for b in blocks}
        ends = {b.end - len("</" + TAG + ">") for b in blocks}
        for t in tags:
            is_close = bool(t.group(1))
            if is_close == expected_open or t.start() not in (ends if is_close else starts):
                ok = False
                break
            expected_open = not expected_open
    if not ok:
        raise ValueError("An attached file could not be read. Remove it and attach it again.")
    if len(blocks) > MAX_FILES_PER_MESSAGE:
        raise ValueError(f"You can attach up to {MAX_FILES_PER_MESSAGE} files to one message.")
    total = 0
    for b in blocks:
        n = len(b.text)
        if n > MAX_FILE_CHARS:
            raise ValueError(f"{_shown_name(b.name)} is too long ({n:,} characters). The limit is {MAX_FILE_CHARS:,} per file.")
        total += n
    if total > MAX_MESSAGE_FILE_CHARS:
        raise ValueError(f"The files in one message can hold {MAX_MESSAGE_FILE_CHARS:,} characters in total (this message has {total:,}).")
    return blocks


def _shown_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "A file"
    return name if len(name) <= MAX_FILE_NAME_CHARS else name[: MAX_FILE_NAME_CHARS - 1] + "\u2026"


def conversation_file_chars(stored: list[dict]) -> int:
    """Attached-file characters already in a conversation (its user messages)."""
    return sum(file_chars(m.get("content")) for m in stored if isinstance(m, dict) and m.get("role") == "user")


def conversation_limit_error(stored: list[dict], new_chars: int) -> str | None:
    """None when a message adding `new_chars` of file text fits the
    conversation's cap (or adds none: a conversation at its cap can still be
    talked to), else the message to show the user."""
    if new_chars <= 0:
        return None
    if conversation_file_chars(stored) + new_chars > MAX_CONVERSATION_FILE_CHARS:
        return (
            f"A conversation can hold up to {MAX_CONVERSATION_FILE_CHARS:,} characters of attached files. "
            "Start a new conversation to attach more."
        )
    return None


def first_file_name(content: str) -> str:
    """Name of the first attached file, or ''. For a title when the user sent
    files and no text."""
    blocks = find_attached_files(content)
    return _shown_name(blocks[0].name) if blocks and blocks[0].name.strip() else ""
