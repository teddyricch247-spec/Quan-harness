"""The idle-watchdog's filler words, kept in their own dependency-free
module (no httpx, no config) so BOTH app/thinking_summarizer.py (which emits
them) and app/chat_history.py (which must never save them) can import the
same list.

Fillers are connection-liveness signal ("still working"), not content:
they go out on the same wire field as real thinking titles, so anything
that RECORDS titles (the in-app chat's saved `thinking` list, the
`pending` view of a running reply) has to recognise and skip them, or
"Thinking · N steps" counts every "Thinking" / "Considering" the watchdog
ever sent. Real titles are 10-30 word sentences, so they can never equal
one of these 1-4 word strings.

Phase keys are the same plain strings as thinking_summarizer.PHASE_DRAFTING,
PHASE_REVIEWING and PHASE_FUSING (a test pins that they stay equal).
"""

# One or two words each, on purpose — these exist purely to signal
# "still working" while a real title is in flight, not to compete with
# the real titles for the client's attention. Present participle, no
# punctuation, no capitalization beyond the first letter, so they sit
# visually consistent with the real titles they're standing in for.
FILLER_WORDS = [
    "Thinking",
    "Considering",
    "Weighing options",
    "Working through it",
    "Reasoning",
    "Analyzing",
    "Mulling it over",
]

# Last-resort fillers for a silent gap while the request is in a KNOWN
# phase — fixed, honest wording instead of the generic words above. Used
# only when no real title has reached the client for FILLER_INTERVAL_SECONDS
# (a slow or failed summarizer call, a short draft, the draft -> critic
# seam). Any other phase (thinking) uses FILLER_WORDS; the answering
# phase uses nothing at all.
PHASE_FILLER_WORDS = {
    "drafting": [
        "Working on the answer",
        "Writing out the response",
        "Putting the answer together",
        "Still writing it out",
    ],
    "reviewing": [
        "Checking the answer over",
        "Double-checking the details",
        "Looking it over",
    ],
    # z tiers only (2026-10-08): the silent seam between the first stage and
    # the final check. Wording stays neutral on purpose: customers see these
    # strings in a stream and must not learn how Kael works from them.
    "fusing": [
        "Pulling it together",
        "Refining the answer",
        "Weighing the strongest ideas",
    ],
}

# Wording used before 2026-10-08. Never sent any more (it named the internal
# steps), but chat rows saved earlier still contain it, so is_filler() must
# keep recognising it or old conversations would show those strings as steps.
LEGACY_FILLER_WORDS = [
    "Drafting the answer",
    "Still writing the draft",
    "Reviewing the draft",
    "Checking the draft over",
    "Looking over the draft",
]

_ALL_FILLERS = frozenset(
    {w for w in FILLER_WORDS}
    | {w for words in PHASE_FILLER_WORDS.values() for w in words}
    | set(LEGACY_FILLER_WORDS)
)


def is_filler(text) -> bool:
    """True when `text` is exactly one of the watchdog's filler strings
    (ignoring surrounding whitespace, which the wire separator adds)."""
    return isinstance(text, str) and text.strip() in _ALL_FILLERS
