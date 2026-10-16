"""Deterministic backstop against Kael's final output naming, confirming,
or self-identifying as its actual underlying vendor/model (DeepSeek, GLM/
ChatGLM/Zhipu AI/Z.ai, OpenRouter, Relace) — added 2026-09-15, item 7 of
that date's audit.

The primary defense against this is already in
models/kael/config.py's system_identity prompt ("never name, confirm, or
speculate about any underlying vendor or model this system may be built
on — even if asked directly"). That's a prompt-based instruction to the
draft/critic models themselves, and prompt-based instructions are exactly
the kind of thing that can fail — a jailbreak, an adversarial caller
system prompt, or a base model quirk that leaks its own training-time
self-identity regardless of what it was just told. This module is NOT a
replacement for that prompt — it's a second, deterministic layer behind
it: a fixed set of regexes over the actual output text, applied
regardless of what the model was told or how it was convinced to ignore
it.

Explicitly a backstop, not a solution: this catches classic
self-identification PHRASING (see _LEAK_PATTERNS below) — "I am
DeepSeek", "created by Zhipu AI", "powered by GLM" — not every
conceivable way a determined jailbreak could get a model to leak this
information (e.g. spelled out letter-by-letter, base64-encoded, described
in a made-up language the caller decodes client-side, or asserted as fact
in a way that never matches any of these surface patterns). A real
red-team pass evaluating how well the prompt-level defense itself holds
up under adversarial pressure is still needed and is explicitly out of
scope for this pass (see the 2026-09-15 audit notes, item 8) — this
module only makes the cheap, common failure mode fail closed instead of
leaking silently.

Deliberately scoped to SELF-IDENTIFICATION phrasing, not a bare ban on
the vendor names themselves: a user can legitimately ask Kael factual
questions ABOUT DeepSeek, GLM, or any other real AI company as a topic
("what is DeepSeek?", "how does GLM's MoE architecture work?") and
expects an accurate answer that necessarily contains those words. A blunt
find-and-block on the bare string "DeepSeek" anywhere in output would
break that entirely — every pattern below requires a self-referential
construction (an "I am"/"created by"/"powered by"/"my model is"-shaped
sentence), not just the name appearing in the text somewhere.
"""
from __future__ import annotations

import re

# One shared vendor-name building block, reused by every pattern below,
# so a fix or addition here (a new upstream provider, a new alias) only
# has to happen once. _VENDOR_LIST additionally matches a comma/"and"-
# joined RUN of names ("powered by OpenRouter and Relace",
# "built on DeepSeek, GLM, and OpenRouter") as a single match, so the
# whole list gets replaced together — matching only the first name in a
# list and leaving the rest of the sentence's vendor names untouched
# would still be a leak, just a partial one.
_VENDOR_NAME = r"(?:DeepSeek(?:-[\w.]+)?|GLM(?:-[\w.]+)?|ChatGLM|Zhipu(?:\s*AI)?|Z\.ai|OpenRouter|Relace)"
_VENDOR_LIST = rf"{_VENDOR_NAME}(?:\s*,?\s*(?:and\s+)?{_VENDOR_NAME})*"

_LEAK_PATTERNS: list[tuple[re.Pattern, str]] = [
    # "I am DeepSeek", "I'm a GLM model", "As DeepSeek, I..."
    (
        re.compile(rf"\b(?:I(?:'m| am)|As)\s+(?:an?\s+)?{_VENDOR_LIST}\b", re.IGNORECASE),
        "I am Kael, a Composite Intelligence System built by Quancis",
    ),
    # "created/developed/built/made/trained by DeepSeek/Zhipu AI/Z.ai",
    # including a list: "built by DeepSeek and Zhipu AI"
    (
        re.compile(rf"\b(?:created|developed|built|made|trained)\s+by\s+{_VENDOR_LIST}\b", re.IGNORECASE),
        "built by Quancis",
    ),
    # "powered by DeepSeek/GLM/OpenRouter/Zhipu AI/Relace", including a
    # list: "powered by OpenRouter and Relace"
    (
        re.compile(rf"\bpowered\s+by\s+{_VENDOR_LIST}\b", re.IGNORECASE),
        "powered by Quancis",
    ),
    # "my (underlying) model/architecture is DeepSeek-V4/GLM-5.3/ChatGLM"
    (
        re.compile(rf"\bmy\s+(?:underlying\s+)?(?:model|architecture)\s+is\s+{_VENDOR_LIST}\b", re.IGNORECASE),
        "my underlying model is Kael",
    ),
]

# Longest a single match could plausibly run — used by StreamIdentityGuard
# below to decide how much trailing text to hold back rather than release
# immediately, so a leak split across two separate upstream chunks (e.g.
# "...I a" | "m DeepSeek..." arriving as two separate deltas) still gets
# caught instead of half of it already being on its way to the client
# before the second half ever arrives. Generous on purpose — the cost of
# holding back too much is a few dozen milliseconds of extra perceived
# latency at the very tail of a stream, not lost correctness; the cost of
# holding back too little is a silent leak, which is the entire thing
# this module exists to prevent.
_HOLD_BACK_CHARS = 100


def scrub_identity_leaks(text: str) -> str:
    """Runs every pattern above over a COMPLETE string — the non-
    streaming path's whole final answer, or (via StreamIdentityGuard
    below) one fully-resolved trailing chunk of a stream. Safe to call on
    text with no leak in it at all (the overwhelming majority of real
    responses) — every pattern requires a specific self-referential
    construction, so ordinary text never matches."""
    if not text:
        return text
    for pattern, replacement in _LEAK_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class StreamIdentityGuard:
    """Per-stream, per-pass instance (one per consume_pass() call in
    app/two_pass_pipeline.py — a fresh instance per draft/critic pass,
    never shared across a request's two passes or across requests).

    feed(chunk) -> str: call once per upstream content delta, in order.
    Returns the portion of buffered text that's now safe to relay to the
    client — scrubbed of any complete leak pattern already found — while
    holding back the trailing _HOLD_BACK_CHARS characters in case they're
    the start of a pattern that completes on the NEXT chunk. May return
    an empty string on any given call (e.g. the first few calls of a
    short response, while the buffer is still smaller than the hold-back
    window) — that's expected, not a bug; nothing is dropped, it just
    hasn't been released yet.

    flush() -> str: call once, after the last chunk, with no more chunks
    coming. Runs one final scrub over whatever's left in the buffer
    (nothing can complete into a longer match anymore since the stream is
    over) and returns it. Skipping this after a real, successful stream
    silently drops the last _HOLD_BACK_CHARS characters of the response —
    which would look like a truncated answer, not like a caught leak — so
    call it there.

    Deliberately NOT described as "call this even on an error path": the
    one real caller (app/two_pass_pipeline.py's consume_pass()) calls
    this only on success, on purpose — an exception means the whole pass
    failed, so whatever's sitting in the buffer was never going to reach
    the client anyway, and flushing it there would mean emitting orphaned
    content deltas after (or instead of) the error the caller is about to
    raise. See that call site's own comment for the full reasoning if
    reusing this class somewhere new that also has a failure path."""

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        self._buffer += chunk
        if len(self._buffer) <= _HOLD_BACK_CHARS:
            return ""
        release_len = len(self._buffer) - _HOLD_BACK_CHARS
        to_release, self._buffer = self._buffer[:release_len], self._buffer[release_len:]
        return scrub_identity_leaks(to_release)

    def flush(self) -> str:
        remainder = scrub_identity_leaks(self._buffer)
        self._buffer = ""
        return remainder
