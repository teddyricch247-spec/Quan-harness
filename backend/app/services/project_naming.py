"""
Phase Convert (C8.1) — a project's name when the person never typed one.

Deterministic on purpose. `routers/projects.py::create_project`'s own docstring promises that
project setup involves *no LLM*, and a name has to exist before the first turn does, so this is
plain string handling: the first few words of the prompt, cleaned, at most MAX_NAME_CHARS long. An
LLM-written title after the first completed turn is a possible later addition (C12 open question
4), not something this module does.

Pure — no imports from the rest of the app — so it is unit-testable without a database.
"""
import re

MAX_NAME_CHARS = 48
FALLBACK_NAME = "Untitled project"

# Leading markdown/quote noise a pasted prompt often starts with ("# Build a…", "> …", "- …").
_LEADING_NOISE = re.compile(r"^[\s#>*\-+`\"'“”‘’]+")
_URL = re.compile(r"https?://\S+")
# Anything outside letters, digits and a small set of harmless punctuation becomes a space.
_DISALLOWED = re.compile(r"[^\w\s\-.,'&/:+()]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_TRAILING_PUNCT = re.compile(r"[\s\-.,:;/&+(]+$")


def derive_project_name(prompt: str | None, fallback: str | None = None) -> str:
    """The name for a project created from `prompt`.

    `fallback` is used when the prompt yields nothing usable (empty, or only symbols) — callers
    pass the repository name for an import / create-new-repo project that has no prompt, since
    "owner/repo" is a far better name than "Untitled project" there. With no fallback the result is
    FALLBACK_NAME. Never raises, never returns an empty string, never exceeds MAX_NAME_CHARS.
    """
    cleaned = _clean_first_line(prompt)
    if not cleaned and fallback:
        cleaned = _clean_first_line(fallback)
    if not cleaned:
        return FALLBACK_NAME
    return _truncate_at_word(cleaned, MAX_NAME_CHARS) or FALLBACK_NAME


def _clean_first_line(text: str | None) -> str:
    if not text:
        return ""
    # The first non-empty line is the best summary of what someone asked for.
    first = next((line for line in text.splitlines() if line.strip()), "")
    first = _URL.sub(" ", first)
    first = _LEADING_NOISE.sub("", first)
    first = _DISALLOWED.sub(" ", first)
    first = _SPACES.sub(" ", first).strip()
    first = _TRAILING_PUNCT.sub("", first)
    if not first:
        return ""
    return first[0].upper() + first[1:]


def _truncate_at_word(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # Prefer ending on a word boundary; only hard-cut when the first word alone is too long.
    if text[limit] != " " and " " in cut:
        cut = cut[: cut.rfind(" ")]
    return _TRAILING_PUNCT.sub("", cut.rstrip())
