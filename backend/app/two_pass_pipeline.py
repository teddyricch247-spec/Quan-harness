"""Shared two-pass (draft + critic) orchestration engine.

app/kael_pipeline.py (Kael Beta and Kael Pro Beta, both on
deepseek-v4.1-flash via OpenRouter) is a thin
model-specific wrapper around run_pipeline() below: it builds two
PassConfig objects (which model, which reasoning effort, which output
ceiling) from models/kael/config.py and hands them to this orchestration
code. Everything about HOW a two-pass request is run — balance checks,
hard ceilings, streaming relay, tool-call handling, billing, tracing,
error fallback — lives in exactly one place. See app/response_api.py for
the pure wire-format conversions this module is built on (that module
has no I/O and is unit-testable offline; this one is all I/O and isn't).

Kael Beta was the second product this engine ran (Aura Beta, "ultra",
was the first and, until Aura Beta's removal on 2026-09-08, ran
alongside it on the same run_pipeline() — same balance checks, same
streaming relay, same billing path, different PassConfig values). That
history is why this module is written generically (product/slug/
system_identity all passed in, nothing product-specific hardcoded) even
though Kael Beta is currently the only caller — see the top-level
README's removal note for what got deleted and why the generic shape
stayed.

------------------------------------------------------------------------
Behavior fixed 2026-08-20 (both products at the time, both had the bug)
------------------------------------------------------------------------
1. Every request now runs BOTH passes, full stop. Previously, whenever
   the draft chose to call a tool, the critic pass was skipped entirely
   and the draft's tool call went straight back as final — see
   app/critic/kael.py's docstring for how this made the critic prompt's
   own "which tool to call" review instruction dead text. The only thing
   that still skips the critic pass is the draft producing NOTHING
   reviewable at all (no text AND no tool call — an empty/filtered
   response). response_api.render_draft_for_critic() is what makes a
   tool-call draft reviewable: it renders the chosen tool + arguments
   into the same {draft_response} slot plain text used to go in, so the
   critic sees exactly what was decided and can either affirm it,
   correct the arguments, choose a different tool, or answer directly
   instead — genuinely reviewed, not rubber-stamped.

2. Thinking streamed for pass 1 from 2026-08-20 to 2026-08-26, now
   reverted. The draft pass still streams upstream internally (needed
   for its own responsiveness/timeout handling either way), but its
   `response.reasoning_text.delta` events are no longer relayed to the
   client at all — relay_reasoning=False on the pass-1 consume_pass()
   call below, same as pass 2 always had. Reverted because
   `delta.reasoning_content` is not a field most OpenAI-compatible
   clients read (confirmed against this project's own frontend —
   src/lib/api.ts's SSE parser only ever looks at
   `choices[0].delta.content`, never `.reasoning_content` — and Cursor,
   the other real-world caller this API needs to work inside, has the
   same gap: it doesn't surface `reasoning_content` deltas either). A
   caller that isn't reading a field doesn't perceive it as activity,
   so relaying reasoning content was solving nothing for the actual
   "is this connection dead?" problem it was meant to address, while
   adding real complexity. That problem is now handled at the
   transport level instead — see STREAM_KEEPALIVE_SECONDS and relay()
   below, which sends an SSE comment (invisible to any spec-compliant
   SSE/`data:`-line parser, never mixed into visible content) on ANY
   gap in the stream, draft or critic, reasoning or not, at most ~1
   second apart. That fixes the perceived-dead-connection problem for
   every silent stretch, not just the draft's, without a client needing
   to understand a non-standard field. The draft's own *content* deltas
   are still never shown — the draft's text is internal input to the
   critic, not a final answer, and showing it would mean the client
   sees the draft's answer and then the critic's different final
   answer as if they were one continuous response.

   Superseded in the specific sense of "raw reasoning_content is
   relayed live" — that stays off, unchanged, for the reason above — but
   NOT in the sense of "nothing about a pass's reasoning ever reaches
   the client": as of 2026-09-09, see app/thinking_summarizer.py.
   reasoning_content deltas from BOTH passes now feed a separate
   background process (ThinkingRelay) that condenses them into short,
   human-readable "thinking titles" and streams THOSE instead, on the
   exact same wire field (delta.reasoning_content /
   response.reasoning_text.delta) raw relay would have used. This is API
   -level behavior for every streaming caller, not specific to this
   project's own frontend — unlike raw reasoning_content, which no real
   caller this API needs to work with actually reads (see above), a
   short title is designed to be genuinely worth rendering, so this
   isn't reintroducing the problem fix #2 above solved; it's a different
   feature that happens to reuse the same field name.

3. What a caller sees in `usage` now always matches what they were
   billed. Previously the returned `usage` object was just whatever the
   LAST upstream call's own usage said — for a two-pass request that's
   the critic's self-reported input, which includes the entire draft
   response plus critic instructions baked into its own prompt, wildly
   overstating what the caller's own conversation cost. See
   response_api.billed_client_usage()'s docstring for the full
   explanation; every response this module returns is now built with
   that function, never with a raw upstream usage object.

Kael Beta remains billed on the same rule it always was — first-call
input (+ cache), last-call output, nothing from "the middle" (there is
no middle in a two-pass pipeline) — see app/billing.py's module
docstring. Fix #3 above changes what the *caller sees*, not what
billing.py *charges*; those two numbers simply didn't agree before, and
now they do, by construction (both are computed from
response_api.billed_client_usage() / response_api.client_usage() over
the same draft_usage/critic_usage pair).

------------------------------------------------------------------------
Difficulty routing, added 2026-09-13
------------------------------------------------------------------------
A second, new way to skip the critic pass, alongside (never replacing)
the "draft produced nothing reviewable" skip fix #1 above already
described. app/router/kael.py's ROUTER_PROMPT — a trailing `system`
message _draft_body() attaches to the DRAFT pass ONLY, built by
app/router/build_router_message(), never sent anywhere near
_critic_body() — instructs the draft model to open its response with a
one-word classification of how difficult the REQUEST itself was (not how
confident the model feels about its own answer — see that prompt's own
extensive framing of exactly that distinction, the thing this whole
feature is least allowed to get backwards), wrapped in a tag built from
this request's own random boundary token exactly the way critic.
build_critic_message()'s <draft_...> wrapper already is.

response_api.extract_difficulty_and_strip() reads that tag back out and
strips it, and MUST run — in both _run_nonstream() and _run_stream(),
each below — before draft_text is derived from draft_data for anything
else. Get that order right and the tag can never reach the critic prompt
(draft_text is what render_draft_for_critic() receives) and can never
reach a caller (draft_data is what a skip-critic branch, old or new,
reshape()s or emit_fallback()s directly). Get it wrong in either
direction and one of those two guarantees quietly breaks — see that
function's own docstring for the exact failure mode each ordering
mistake would cause.

The classification is exactly two possible values, "EASY" or "HARD",
matched case-sensitively against the model's own literal output — see
extract_difficulty_and_strip()'s own comment on _DIFFICULTY_TAG_TEMPLATE
for why the match is deliberately strict while a NON-match is
deliberately, unconditionally treated as "HARD": a missing tag, a
malformed tag, a wrong word, a wrong boundary, or the tag appearing
anywhere other than the very start of the response all fail safe to
"HARD" — i.e. to the exact behavior this pipeline always had before this
feature existed. Only an unambiguous, well-formed "EASY" skips the
critic; everything else, including every way this new mechanism could
itself fail or be gamed, falls through to being reviewed exactly as
before. Both skip-critic branches (this one and fix #1's empty-draft one
above) share the same billing shape (draft-only usage charged, no
critic call to bill for) and are told apart in tracing by
update_chat_trace()'s `draft_status` field — "skipped_empty" vs.
"skipped_easy\" — never conflated into one label.

------------------------------------------------------------------------
z tiers: concurrent drafts + fusor (added 2026-10-08)
------------------------------------------------------------------------
kael_pipeline.py's z-low/z-high tiers pass `fusor` (a PassConfig) and
`draft_count` (3) to run_pipeline(); every other tier passes neither and
runs EXACTLY the two-call path above, unchanged. With a fusor the request
is five calls:

    draft x3 (concurrent, never in a row) -> fusor -> critic

The critic is the same critic, reviewing the fused answer as it reviews a
single draft on the lower tiers. What the extra stage decides, in order:

  * Draft failures. The three drafts are gathered with _gather_drafts()
    (gather with return_exceptions=True plus the straggler rule below), so one
    slow or failed draft cannot sink the request. Only when ALL of them fail
    does the request fail, and then with the first failure's own error,
    exactly as a single failed draft does. Survivors carry on. A plain bug in
    one draft (an exception that is not an upstream failure) drops that draft
    the same way, and is logged; only when no draft succeeded is it re-raised.
  * Stragglers (2026-10-11). Once two drafts have come back whole, the rest get
    _straggler_grace() more seconds (half the second draft's time, between
    Z_STRAGGLER_MIN_SECONDS and Z_STRAGGLER_MAX_SECONDS) and are then cancelled
    (_DraftCut), so one slow draft no longer holds the request back until the
    480 s ceiling. With fewer than two whole drafts there is no deadline: then
    the slow draft is needed. The cut draft's tokens are upstream cost only.
  * Empty. If no survivor produced anything reviewable, the first draft's
    (empty) result goes down the existing skipped_empty path.
  * EASY (rewritten 2026-10-10). The difficulty tag (router/kael.py) is read
    from every draft, but a self-rated tag says nothing about whether the
    drafts agree, so the shortcut (fusor+critic skipped, one draft served,
    draft_status="skipped_easy") needs ALL of: every fired draft came back
    (a failed or empty draft is a missing vote, not an EASY one), every one
    is whole (not cut off at its output limit), every one says EASY, and every
    pair of answers is at least Z_EASY_MIN_AGREEMENT alike. The draft served is
    _pick_base()'s consensus pick, not simply the first. Anything less gets the
    full review. One HARD, or one unparseable tag (HARD), is enough to continue.
  * One survivor. Fusing one answer is pointless; it goes straight to the
    critic (the fusor call is skipped, not faked), even when that lone draft
    said EASY. The server log says "z DEGRADED" whenever fewer drafts than
    the tier promises took part.
  * Quick transient failures. A draft or the fusor that fails within
    Z_RETRY_MAX_ELAPSED_SECONDS with a caller-facing 429 or 502 is tried once
    more (_retry_fast_transient). Slow failures, 504 and the hard ceiling never
    are.
  * Fusion. Two or more survivors go to the fusor (fusor/kael.py). If the
    fusor call fails, times out, or returns nothing, _pick_base()'s draft
    goes to the critic instead (a whole draft over a cut-off one, and among
    three the one most like the others; ties to the earliest) — fusion is an
    upgrade, never a new way to fail a request that already has a usable
    draft. Billing still counts the first surviving draft's input. The critic's own
    failure still falls back to serving whatever it was given, which on a z
    tier is the fused answer (or the first draft, if fusion fell back).

Billing is unchanged by construction. billing.py charges FIRST-call input
and LAST-call output. All three drafts carry the same prompt, so the first
surviving draft's input is billed; the output is the critic's (or, when the
critic never finished, the fusor's, then the draft's). The fusor's own input
(which contains all the drafts) and the other drafts' tokens are upstream
cost Quancis absorbs, like the critic's input on every tier. A z request
therefore costs Quancis several times what it bills; see models/kael/
config.py and PLAN.md before pricing it. response_api.billed_client_usage()
composes the (draft input, fusor output) pair for the fusor-served fallback.

Streaming: only the critic's content is ever relayed, as before. The thinking
titles follow ONE draft at a time (_TitleLeader: the first to produce any
reasoning or text, then, when that draft ends, the one furthest along, with its
recent text replayed and ThinkingRelay.source_changed() called first), so three
concurrent reasoning streams never interleave into one title feed and the feed
does not go quiet when the leading draft finishes first; the fusor then runs in
its own "fusing" phase (thinking_summarizer.PHASE_FUSING) and the critic in
"reviewing".

Trace. On a z request the draft_status written to the trace ends in
"_x<took part>of<fired>" (for example "ok_text_x2of3", "skipped_easy_x3of3"), so
a request that ran with fewer drafts than promised can be found afterwards.

Time. GENERATION_HARD_CEILING_SECONDS (480 s) applies to each stage, per attempt,
not to a request: a request has two stages on Kael Beta and three on Kael Pro
Beta, so one can run for about 16 and 24 minutes. Public docs must not say a
request gets 8 minutes (frontend docs/facts.ts clientTimeoutMinutes).
"""
from __future__ import annotations

import asyncio
import inspect
import json
import random
import re
import secrets
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from . import billing, config, identity_guard, provider_routing, rate_limit
from . import response_api as ra
from . import anthropic_api as aa
from .critic import build_critic_message
from .fusor import build_fusor_message
from .router import build_router_message
from .supabase_client import last_user_text, log_usage, start_chat_trace, update_chat_trace
from .thinking_summarizer import PHASE_FUSING, PHASE_REVIEWING, ThinkingRelay

GENERATION_HARD_CEILING_SECONDS = 480.0

# Shared connection-failure retry for BOTH upstream call paths —
# _post_upstream() below (non-streamed) and consume_pass()'s own
# streaming connection attempt (added 2026-09-15 alongside
# _post_upstream()'s; see each function's own docstring for the full
# reasoning on why this is scoped to connection failures only, never
# timeouts or received error responses, and never anything after any
# content has actually started reaching the client). 3 total attempts,
# short fixed backoffs — this exists to smooth over a dropped TCP
# handshake or a momentary DNS blip, not to wait out a real outage; if
# OpenRouter's connection is actually down, failing after ~0.75s of
# retrying is the right call, not adding real user-facing latency hoping
# a longer wait fixes it.
_CONNECT_RETRY_ATTEMPTS = 3
_CONNECT_RETRY_BACKOFF_SECONDS = [0.25, 0.5]  # before attempt 2, before attempt 3 — len() must be _CONNECT_RETRY_ATTEMPTS - 1
# How long relay() (below) will go with nothing to send before it emits a
# bare SSE keep-alive comment. Was 15.0 until 2026-08-26 — too sparse for
# clients/proxies that consider a connection dead after a few seconds of
# silence (Cursor's own OpenAI-compatible client being the concrete case
# that motivated this — see module docstring, fix #2). 1 second is
# deliberately aggressive: a keep-alive comment is a few bytes on an
# already-open connection, not a real request, so there's no meaningful
# cost to sending it often, and the failure mode on the other side
# (a client giving up and showing "connection broken" mid-generation) is
# much worse than a chattier stream.
STREAM_KEEPALIVE_SECONDS = 1.0
# Real upstream calls run in a background task for the streaming path (see
# run_pipeline() below), tracked here purely so a task is never garbage-
# collected mid-flight just because nothing else holds a reference to it —
# the HTTP response itself is a thin relay reading off a queue, not the
# task itself.
_background_tasks: set[asyncio.Task] = set()

# Appended to every thinking title / filler on the wire. Each title is its own
# delta, and the in-app frontend treats one delta as one title (it trims it), but
# an API caller that simply concatenates `reasoning_content` (or the Anthropic
# `thinking_delta` text) used to get every title glued to the next one. A blank
# line between them reads as separate paragraphs after plain concatenation.
THINKING_TITLE_SEPARATOR = "\n\n"


async def _call_on_complete(on_complete, text: str, thinking: list[str]) -> None:
    """Calls the caller's on_complete(text). A callback that declares a
    `thinking` parameter also gets the list of real thinking titles the
    request actually sent (ThinkingRelay.titles) — the in-app chat saves
    that list, instead of whatever its stream consumer had read so far."""
    try:
        takes_thinking = "thinking" in inspect.signature(on_complete).parameters
    except (TypeError, ValueError):
        takes_thinking = False
    if takes_thinking:
        await on_complete(text, thinking=thinking)
    else:
        await on_complete(text)


@dataclass(frozen=True)
class PassConfig:
    """Everything needed to run ONE upstream call. Built fresh per-request
    by kael_pipeline.py from models/kael/config.py — never mutated,
    never shared across requests.

    Every pass this engine runs speaks Chat Completions upstream — see
    chat_completions_url below. That wasn't always true (see this
    module's own docstring, and response_api.py's module docstring, for
    the now-removed Responses-API-upstream path Aura Beta used exclusively
    and Kael Beta used before 2026-08-30); a `upstream_shape` field used
    to select between the two per-pass, removed along with the branch it
    selected on 2026-09-08, once Aura Beta's removal meant no PassConfig
    anywhere could construct the other value anymore. If a future product
    needs a literal Responses-shaped upstream again, that's a new field
    and a new branch to add back deliberately, not something to leave
    half-wired "just in case."

    Not to be confused with caller_shape (two_pass_pipeline.run_pipeline()'s
    own parameter): caller_shape is which shape the caller used to reach
    this API (Chat Completions or Responses — both still fully supported
    on the way OUT, see response_api.reshape()); this class is only ever
    about the way IN, to the model provider, which is Chat Completions,
    always, for every pass, as of the above."""

    provider: str  # "glm" | "openrouter" — determines the upstream URL, see chat_completions_url below
    base_url: str
    api_key: str
    model: str
    reasoning_effort: str
    max_output_tokens: int
    # provider_routing added 2026-08-31, alongside provider="openrouter"
    # (Kael Beta's upstream — deepseek-v4.1-flash for
    # draft and critic, via OpenRouter, routed speed-first, not pinned).
    # OpenRouter-only: this is OpenRouter's own request-body "provider"
    # routing object (order/allow_fallbacks/preferred_max_latency/
    # preferred_min_throughput — see response_api.build_chat_completions_
    # body()'s docstring for the field-name collision this causes with
    # THIS dataclass's own `provider` attribute above, which is a
    # different, unrelated namespace). None for every other provider.
    provider_routing: dict | None = None
    # session_id added 2026-10-05, OpenRouter-only: sent as the request's
    # top-level `session_id`, OpenRouter's sticky-routing key (keeps
    # follow-up turns on the host that holds the prompt cache). Set once
    # per request in run_pipeline() via dataclasses.replace(), because it
    # depends on the caller's conversation, not on product config — see
    # provider_routing.py for the full reasoning.
    session_id: str | None = None

    @property
    def chat_completions_url(self) -> str:
        """Full URL for this provider's Chat Completions endpoint —
        as of 2026-08-31 this is Kael Beta's OpenRouter passes (both of
        them); the GLM-direct branch below is kept working but unused by
        any current product config (see config.py's GLM_BASE_URL comment
        for why it's kept rather than deleted alongside the Responses-API
        branch this class used to also carry).

        OpenRouter's real path is the conventional {base_url}/v1/chat/
        completions — confirmed against OpenRouter's own docs
        (openrouter.ai/docs/guides/routing/provider-selection, fetched
        2026-08-31).

        GLM/Z.ai's real path is /paas/v4/chat/completions off a base of
        https://api.z.ai/api — confirmed directly against Z.ai's own
        OpenAPI spec at docs.z.ai/api-reference/llm/chat-completion
        (fetched 2026-08-30): `servers[0].url` is https://api.z.ai/api,
        and the one documented chat-completions path is
        /paas/v4/chat/completions — deliberately NOT the more common
        .../v1/chat/completions pattern, which is why this stays its own
        explicit branch rather than folding into the openrouter one
        above just because both are "chat_completions"-shaped."""
        if self.provider == "openrouter":
            return f"{self.base_url}/v1/chat/completions"
        return f"{self.base_url}/paas/v4/chat/completions"


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


class _LeadingTagStripper:
    """Streaming twin of response_api.extract_difficulty_and_strip(): removes
    the draft pass's leading <task_difficulty_{boundary}>EASY|HARD</...> tag
    from text arriving in arbitrary chunks, so the tag never reaches the
    thinking summarizer (and from there, a title). Same pattern as the real
    extraction (anchored, case-sensitive, closing tag optional), applied to
    the first characters only. Text that does not start with the tag passes
    through byte-for-byte. Anything still undecided is held back until the
    next feed(), or released by flush() when the stream just ends."""

    _MAX_HOLD = 256  # hard cap so a long run of leading whitespace can never hold text back forever

    def __init__(self, boundary: str) -> None:
        self._tag = f"task_difficulty_{boundary}"
        self._open = f"<{self._tag}>"
        self._close = f"</{self._tag}>"
        self._pattern = re.compile(ra._DIFFICULTY_TAG_TEMPLATE.format(tag=re.escape(self._tag)))
        self._buf = ""
        self._done = False
        self._drop_ws = False

    def _undecided(self, buf: str) -> bool:
        """True when buf could still become (or still be completing) a tag."""
        t = buf.lstrip()
        if self._open.startswith(t):
            return True
        if not t.startswith(self._open):
            return False
        rest = t[len(self._open):].lstrip()
        for word in ("EASY", "HARD"):
            if word.startswith(rest):
                return True
        return False

    def feed(self, text: str) -> str:
        if not text:
            return ""
        if self._done:
            if self._drop_ws:
                text = text.lstrip()
                if text:
                    self._drop_ws = False
            return text
        self._buf += text
        buf = self._buf
        m = self._pattern.match(buf)
        if m:
            rest = buf[m.end():]
            closed = self._close in buf[:m.end()]
            # No closing tag yet and nothing after the word / a partial closing tag: wait for more.
            if not closed and self._close.startswith(rest):
                return "" if len(buf) <= self._MAX_HOLD else self._release_plain()
            self._done, self._buf = True, ""
            self._drop_ws = not rest
            return rest
        if len(buf) <= self._MAX_HOLD and self._undecided(buf):
            return ""
        return self._release_plain()

    def _release_plain(self) -> str:
        out, self._buf, self._done = self._buf, "", True
        return out

    def flush(self) -> str:
        if self._done:
            return ""
        buf, self._buf, self._done = self._buf, "", True
        m = self._pattern.match(buf)
        return buf[m.end():] if m else buf


class _PassCallError(Exception):
    """An upstream call (draft or critic) failed outright — non-2xx
    status, connection error, or a client-side timeout below the hard
    ceiling. Carries enough to log it and, for a draft-pass failure
    specifically, to raise the equivalent HTTPException a single-pass
    proxy would have raised."""

    def __init__(self, http_status: int, log_message: str, client_payload: dict, latency_ms: int | None = None):
        self.http_status = http_status
        self.log_message = log_message
        self.client_payload = client_payload
        self.latency_ms = latency_ms
        super().__init__(log_message)


def _upstream_error(pcfg: PassConfig, http_status: int, text: str, payload: dict, latency_ms: int | None = None) -> _PassCallError:
    """Builds the _PassCallError for a non-2xx upstream response. One
    special case (added 2026-10-05): when the status means OpenRouter
    found NO provider at or under this pass's max_price (see
    provider_routing.is_no_provider_error), nothing ran and nothing was
    billed — log a loud NO_ELIGIBLE_PROVIDER line for the operator and
    hand the caller a clean 503 instead of OpenRouter's own error JSON.
    Every other status is mapped to a fixed vendor-free error (see
    provider_routing.client_error_for_upstream_status) — the upstream body
    is never passed to the caller."""
    # `text` (the raw upstream body) is deliberately NOT logged or stored: it can
    # quote the caller's prompt. See provider_routing.safe_upstream_summary().
    safe = provider_routing.safe_upstream_summary(http_status, payload)
    if provider_routing.is_no_provider_error(http_status):
        print(provider_routing.no_provider_log_line(pcfg.model, http_status, safe))
        return _PassCallError(503, safe, provider_routing.NO_PROVIDER_CLIENT_PAYLOAD, latency_ms=latency_ms)
    # Every other upstream failure (changed 2026-10-06): the caller gets a
    # fixed, vendor-free envelope — never the upstream body, whose text names
    # hosts/models/accounts — and a status that describes Kael, not our
    # upstream account. log_message (usage_logs / trace error_message / logs)
    # holds only the content-free `safe` summary: status, error code/type and
    # host name. The upstream free text is dropped because it can quote the
    # caller's prompt.
    if provider_routing.is_credential_or_credit_error(http_status):
        print(provider_routing.credential_or_credit_log_line(pcfg.model, http_status, safe))
    client_status, client_payload = provider_routing.client_error_for_upstream_status(http_status)
    if provider_routing.is_context_overflow(http_status, text):
        client_status, client_payload = provider_routing.CONTEXT_OVERFLOW_CLIENT_ERROR
    return _PassCallError(client_status, safe, client_payload, latency_ms=latency_ms)


class _NoProviderRetry(Exception):
    """Streaming-only control flow: carries the body for the one backup
    attempt out of consume_pass()'s `async with` blocks to its retry loop."""

    def __init__(self, body: dict):
        self.body = body
        super().__init__("retry on backup host")


def _fallback_body(pcfg: PassConfig, body: dict, err: "_PassCallError") -> dict | None:
    """The request body for the single backup-host attempt, or None when
    `err` is not a no-provider refusal or this pass has no usable routing
    object. Logs the retry. See provider_routing.fallback_routing()."""
    if err.client_payload is not provider_routing.NO_PROVIDER_CLIENT_PAYLOAD:
        return None
    fb = provider_routing.fallback_routing(pcfg.provider_routing)
    if fb is None:
        return None
    print(provider_routing.fallback_log_line(pcfg.model, err.log_message))
    return {**body, "provider": fb}


class _ProviderFailover(Exception):
    """Streaming-only control flow (added 2026-10-09): a pass ended in a
    mid-stream upstream failure before anything reached the client. Carries
    the body for the one silent re-run on the next-best host, out of
    consume_pass()'s first attempt to the wrapper that starts the second."""

    def __init__(self, body: dict, summary: str):
        self.body = body
        self.summary = summary
        super().__init__("retry on the next-best host")


def _failover_body(pcfg: PassConfig, body: dict, final_data: dict) -> tuple[dict, str] | None:
    """(request body, log description) for the one silent re-run of a pass
    that ended in a mid-stream failure (finish_reason "error" / an `error`
    chunk), or None when this failure is not one to retry (content_filter) or
    the pass has no routing / price ceiling to retry under. See
    provider_routing.failover_routing(). Does not log; the caller does."""
    if not provider_routing.is_failover_candidate(final_data):
        return None
    fo = provider_routing.failover_routing(pcfg.provider_routing, final_data)
    if fo is None:
        return None
    routing, how = fo
    return {**body, "provider": routing}, how


def _failed_pass_error(final_data: dict, first_failure: str | None = None) -> _PassCallError:
    """The _PassCallError for a pass that finished with status "failed". The
    log message names the finish reason, error code / type and host (never
    free text), and the first attempt's failure when this was the re-run."""
    detail = provider_routing.failed_pass_summary(final_data)
    if first_failure:
        detail = f"{detail}; first attempt: {first_failure}"
    return _PassCallError(502, f"pass failed ({detail})", {"error": {"message": "The upstream model reported a failure.", "type": "server_error"}})


def _NONSTREAM_PASS_BACKSTOP() -> float:
    """Outer wait_for budget for a non-streamed pass (added 2026-10-09).
    _post_upstream() applies GENERATION_HARD_CEILING_SECONDS to each attempt
    itself, so a silent failover re-run gets a full ceiling of its own; this
    is only the backstop around the pair (first attempt + one re-run), so it
    can never fire before a single attempt's own ceiling does. Read at call
    time so tests that shrink the ceiling shrink this too."""
    return GENERATION_HARD_CEILING_SECONDS * 2


async def _post_upstream(pcfg: PassConfig, body: dict, started: float) -> dict:
    """Non-streamed upstream call with ONE backup-host retry when OpenRouter
    refuses with a no-provider status (see provider_routing.py), and (added
    2026-10-09) ONE silent re-run on the next-best host when the response
    itself reports a provider failure (finish_reason "error"). Everything
    else — retries, errors, parsing — is _post_upstream_once().

    The hard ceiling (GENERATION_HARD_CEILING_SECONDS) is applied here, to
    EACH attempt, so a re-run after a failure 300 s in still gets its full
    budget. Callers wrap the whole call in _NONSTREAM_PASS_BACKSTOP()."""
    async def _once(b: dict) -> dict:
        return await asyncio.wait_for(_post_upstream_once(pcfg, b, started), timeout=GENERATION_HARD_CEILING_SECONDS)

    try:
        data = await _once(body)
    except _PassCallError as e:
        fb_body = _fallback_body(pcfg, body, e)
        if fb_body is None:
            raise
        data = await _once(fb_body)
    fo = _failover_body(pcfg, body, data)
    if fo is None:
        return data
    fo_body, how = fo
    first = provider_routing.failed_pass_summary(data)
    print(provider_routing.failover_log_line(pcfg.model, first, how))
    try:
        data2 = await _once(fo_body)
    except _PassCallError as e2:
        print(provider_routing.failover_exhausted_log_line(pcfg.model, first, e2.log_message))
        e2.log_message = f"{e2.log_message}; first attempt: {first}"
        raise
    if provider_routing.is_failover_candidate(data2):
        print(provider_routing.failover_exhausted_log_line(pcfg.model, first, provider_routing.failed_pass_summary(data2)))
        raise _failed_pass_error(data2, first)
    return data2


async def _post_upstream_once(pcfg: PassConfig, body: dict, started: float) -> dict:
    """Non-streamed POST to a provider's Chat Completions endpoint
    (pcfg.chat_completions_url). A "high"/"max" effort non-streamed
    response can legitimately take minutes; the real backstop against a
    truly hung call is the caller wrapping this in
    asyncio.wait_for(GENERATION_HARD_CEILING_SECONDS), not this
    function's own read timeout (set generously below that ceiling).

    The response body is a Chat-Completions-native `chat.completion`
    shape (from OpenRouter as of the 2026-08-31 switch — Kael Beta's only
    current caller of this function — or directly from GLM/Z.ai, still
    supported, see PassConfig.chat_completions_url), which this
    immediately runs through ra.chat_completion_to_responses_shape()
    before returning — so _run_nonstream() gets back the same
    Responses-shaped dict regardless of provider, and everything
    downstream of it (billing, tracing, reshape()) never needs to know or
    care which one actually ran. This function used to dispatch between
    two implementations (one for a literal Responses-API upstream, one
    for Chat Completions) — collapsed into one on 2026-09-08 once Aura
    Beta's removal meant the Responses-API branch had no caller left; see
    response_api.py's module docstring for that history.

    Retries (added 2026-09-15, item 5 of the audit — this function
    previously made exactly one attempt, full stop, so a single dropped
    TCP handshake failed the entire user-facing request even though an
    immediate second attempt would very likely have succeeded): up to
    _CONNECT_RETRY_ATTEMPTS total tries, but ONLY for httpx.ConnectError/
    httpx.ConnectTimeout — failures where the connection was never
    established, so the request body provably never reached OpenRouter/
    Z.ai and there is zero chance the upstream did any real (billable)
    generation work for the attempt being retried.

    Deliberately NOT retried, and this is a real judgment call worth
    stating plainly rather than quietly picking a side of: a read
    timeout (httpx.TimeoutException, no data came back before our own
    460s read timeout) or any response we DID receive, even a 5xx. Two
    separate reasons, either one enough on its own:
      1. Time budget: the read timeout above is already 460s against an
         asyncio.wait_for ceiling of GENERATION_HARD_CEILING_SECONDS
         (480s, see caller) — only ~20s of slack. A second full-length
         attempt after a real read timeout doesn't fit in what's left;
         it would just get killed mid-flight by the hard ceiling instead
         of failing cleanly with a specific "upstream timeout" message.
      2. Correctness: once we've sent the request and it's possible the
         model actually started generating (which we can't distinguish
         from "never started" once the TCP connection succeeded), a
         retry risks the upstream provider doing the same paid inference
         work twice for one user-facing request — Quancis would eat that
         extra upstream cost while the user is correctly billed only
         once, for whichever response we actually end up using. Without
         an idempotency-key mechanism confirmed to exist on OpenRouter's
         API (not verified as part of this pass), retrying anything past
         "did the connection even open" isn't provably safe, so it's
         left alone rather than assumed safe."""
    timeout = httpx.Timeout(connect=10.0, read=460.0, write=10.0, pool=10.0)
    attempt = 0
    while True:
        attempt += 1
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(pcfg.chat_completions_url, headers=_headers(pcfg.api_key), json=body)
            break
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            if attempt >= _CONNECT_RETRY_ATTEMPTS:
                raise _PassCallError(502, f"upstream connection failed after {attempt} attempt(s): {str(e)[:400]}", {"error": {"message": "Could not complete the request — please retry.", "type": "server_error", "code": "upstream_unreachable"}})
            await asyncio.sleep(_CONNECT_RETRY_BACKOFF_SECONDS[attempt - 1])
            continue
        except httpx.TimeoutException:
            raise _PassCallError(504, "upstream timeout", {"error": {"message": "The request timed out.", "type": "server_error", "code": "upstream_timeout"}})
        except httpx.HTTPError as e:
            raise _PassCallError(502, str(e)[:500], {"error": {"message": "Could not complete the request — please retry.", "type": "server_error", "code": "upstream_unreachable"}})
    if resp.status_code >= 400:
        raise _upstream_error(pcfg, resp.status_code, resp.text, ra.safe_json(resp), latency_ms=int((time.monotonic() - started) * 1000))
    data = ra.chat_completion_to_responses_shape(resp.json())
    print(provider_routing.describe_served_by("nonstream", pcfg.model, data.get("served_by"), data.get("usage")))
    return data


def _draft_body(pcfg: PassConfig, product: str, input_items: list[dict], tools, system_identity: str, stream: bool, boundary: str) -> dict:
    # Draft-pass-ONLY trailing message (added 2026-09-13) — see
    # app/router/kael.py's module docstring for why this never goes
    # anywhere near _critic_body() below. Reuses this request's own
    # boundary token, the same one build_critic_message()'s <draft_...>
    # wrapper and prepare_input_items()'s <caller_system_prompt_...>
    # wrapper already use — see run_pipeline()'s own comment on
    # generating it once per request.
    router_message = build_router_message(product, boundary)
    return ra.build_chat_completions_body(
        provider=pcfg.provider, model=pcfg.model, input_items=input_items, tools=tools,
        reasoning_effort=pcfg.reasoning_effort, max_output_tokens=pcfg.max_output_tokens,
        system_identity=system_identity, trailing_messages=[router_message], stream=stream,
        provider_routing=pcfg.provider_routing, session_id=pcfg.session_id,
    )


def _critic_body(pcfg: PassConfig, product: str, input_items: list[dict], draft_text, draft_calls, tools, system_identity: str, stream: bool, boundary: str) -> dict:
    rendered = ra.render_draft_for_critic(draft_text, draft_calls)
    critic_message = build_critic_message(product, rendered, boundary)
    return ra.build_chat_completions_body(
        provider=pcfg.provider, model=pcfg.model, input_items=input_items, tools=tools,
        reasoning_effort=pcfg.reasoning_effort, max_output_tokens=pcfg.max_output_tokens,
        system_identity=system_identity, trailing_messages=[critic_message], stream=stream,
        provider_routing=pcfg.provider_routing, session_id=pcfg.session_id,
    )


def _fusor_body(pcfg: PassConfig, product: str, input_items: list[dict], rendered_drafts: list[str], tools, system_identity: str, stream: bool, fusion_boundary: str) -> dict:
    """The fusion pass's request body. Same shape and message order as
    _critic_body(): master prompt first, the caller's conversation, then ONE
    trailing system message — here fusor/kael.py's prompt with every
    surviving draft in its own tag. No router message: that belongs to the
    draft passes. `tools` is passed through so the fusor can make the real
    call when the right answer is a tool call."""
    fusor_message = build_fusor_message(product, rendered_drafts, fusion_boundary)
    return ra.build_chat_completions_body(
        provider=pcfg.provider, model=pcfg.model, input_items=input_items, tools=tools,
        reasoning_effort=pcfg.reasoning_effort, max_output_tokens=pcfg.max_output_tokens,
        system_identity=system_identity, trailing_messages=[fusor_message], stream=stream,
        provider_routing=pcfg.provider_routing, session_id=pcfg.session_id,
    )


# ------------------------------------------------------------
# z tiers: pure decision logic shared by the streaming and non-streaming
# paths (see the module docstring's "z tiers" section). No I/O here, so the
# decisions are unit-testable on their own.
# ------------------------------------------------------------
@dataclass(frozen=True)
class _DraftResult:
    """One successful draft call, already digested: the difficulty tag is
    stripped from `data` (same order as the single-draft path — strip first,
    derive text from the CLEANED data), `usage_billed` has the injected
    overhead removed, and `text`/`calls` are what the draft actually said."""
    data: dict
    usage_billed: dict
    difficulty: str
    text: str | None
    calls: list

    @property
    def usable(self) -> bool:
        return self.text is not None or bool(self.calls)

    @property
    def complete(self) -> bool:
        """False when the draft was cut off (status "incomplete": it hit its
        output limit). A cut-off draft is still worth showing the fusor, which
        is told to look for exactly that, but it is never the one served or
        reviewed in place of a whole draft (see _pick_base)."""
        return self.data.get("status") != "incomplete"


class _DraftCut(Exception):
    """A draft that was still running when the straggler grace ran out and was
    cancelled on purpose (see _gather_drafts). It sits in the gathered list
    where that draft's result would have been, and counts as a lost draft, but
    it is not a fault: the other drafts had already come back whole."""


def _digest_draft_results(raw: list, boundary: str, injected_total_tokens: int, injected_prefix_tokens: int) -> tuple[list[_DraftResult], list[BaseException]]:
    """Splits the drafts' gathered output (see _gather_drafts) into
    (successful digested results in fire order, expected failures).

    Expected failures are a hard-ceiling timeout, a _PassCallError (the two a
    single draft handles) and a _DraftCut. An UNEXPECTED exception (a bug, not
    an upstream problem) in one draft no longer sinks the request when other
    drafts succeeded (changed 2026-10-11): it is logged and that draft is
    treated as lost, like any other, because three drafts exist so that one bad
    one cannot take the answer down with it. When NO draft succeeded and the
    only failures are unexpected ones, the first is re-raised, so a plain bug
    still surfaces exactly as it does on the single-draft path. Cancellation of
    the whole request (CancelledError, KeyboardInterrupt, SystemExit) is never
    swallowed."""
    results: list[_DraftResult] = []
    failures: list[BaseException] = []
    unexpected: list[BaseException] = []
    for item in raw:
        if isinstance(item, BaseException):
            if isinstance(item, (asyncio.TimeoutError, _PassCallError, _DraftCut)):
                failures.append(item)
                continue
            if not isinstance(item, Exception):
                raise item
            unexpected.append(item)
            print(f"[two_pass_pipeline] z draft hit an unexpected error (that draft is dropped): {type(item).__name__}: {item}"[:400])
            continue
        usage = ra.usage_from_responses(item.get("usage") or {})
        usage_billed = ra.remove_injected_input(usage, injected_total_tokens, injected_prefix_tokens)
        cleaned, difficulty = ra.extract_difficulty_and_strip(item, boundary)
        text, calls = ra.responses_output_text_and_calls(cleaned.get("output") or [])
        results.append(_DraftResult(cleaned, usage_billed, difficulty, text, calls))
    if unexpected and not results and not failures:
        raise unexpected[0]
    return results, failures


# z-tier tunables (added 2026-10-10, see the module docstring's "z tiers").
#
# Z_EASY_MIN_AGREEMENT: the EASY shortcut (skip fusor and critic) needs every
# draft's answer to resemble every other's at least this much (word-set
# Jaccard, 0 to 1). Self-rated difficulty says nothing about whether the drafts
# AGREE, and an unreviewed answer picked out of three that disagree is exactly
# the failure the z tiers exist to prevent. The check errs toward the review:
# a doubtful pair costs one fusor call and one critic call, never a wrong
# answer. A value above 1 turns the shortcut off for the z tiers.
Z_EASY_MIN_AGREEMENT = 0.5
# Z_RETRY_*: a draft or fusor call that FAILS FAST with one of these statuses
# is tried once more. The statuses are the ones _PassCallError carries (the
# CALLER-facing status, see provider_routing.client_error_for_upstream_status):
# 429 is an upstream rate limit, 502 is every other upstream failure (a 5xx, a
# dropped host, a failed connection). Fast means within
# Z_RETRY_MAX_ELAPSED_SECONDS, which in practice means the upstream refused the
# call before doing the work, so little or nothing was generated or billed.
# A slow failure is never retried (the time budget is gone and the work may
# have been done), and neither are 504 or the hard ceiling. This is a
# deliberate, z-only exception to _post_upstream_once()'s "never retry a
# response we received" rule: losing a draft or the fusor silently turns a z
# request into a lesser one, which costs the customer more than a retry costs
# us. An empty set turns it off.
Z_RETRY_STATUSES = frozenset({429, 502})
Z_RETRY_MAX_ELAPSED_SECONDS = 30.0
Z_RETRY_DELAY_SECONDS = 1.0

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _word_set(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _similarity(a: str, b: str) -> float:
    """Word-set Jaccard of two rendered drafts: 1.0 for identical text, 0.0
    when they share no word. Crude on purpose; it only has to tell "the same
    answer, worded alike" from "different answers"."""
    if a.strip() == b.strip():
        return 1.0
    wa, wb = _word_set(a), _word_set(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _rendered(r: "_DraftResult") -> str:
    return ra.render_draft_for_critic(r.text, r.calls)


def _drafts_agree(survivors: list["_DraftResult"]) -> bool:
    """True when every pair of drafts is at least Z_EASY_MIN_AGREEMENT alike."""
    texts = [_rendered(r) for r in survivors]
    return all(_similarity(texts[i], texts[j]) >= Z_EASY_MIN_AGREEMENT for i in range(len(texts)) for j in range(i + 1, len(texts)))


def _pick_base(survivors: list["_DraftResult"]) -> "_DraftResult":
    """The one draft to carry on with when the fusor is not used (the fusor
    failed, or the EASY shortcut applies). Never "whichever came first":
    cut-off drafts are passed over when a whole one exists, and among three or
    more the draft most like the others wins (the consensus pick, so a lone
    outlier is the last one chosen). Two drafts give no consensus signal, and
    ties go to the earliest, so the result is the same on every run."""
    pool = [r for r in survivors if r.complete] or survivors
    if len(pool) <= 2:
        return pool[0]
    texts = [_rendered(r) for r in pool]
    scores = [sum(_similarity(texts[i], texts[j]) for j in range(len(pool)) if j != i) for i in range(len(pool))]
    return pool[scores.index(max(scores))]


def _plan_fusion(results: list[_DraftResult], draft_count: int | None = None) -> tuple[str, list[_DraftResult]]:
    """Decides what happens after the concurrent drafts. `results` must be
    non-empty (the caller handles "every draft failed" first). `draft_count` is
    how many drafts were fired (default: len(results), for callers with no
    failures to report). Returns (verdict, survivors), where survivors are the
    drafts with something reviewable, in fire order:

      "empty"  no survivor — serve results[0] via the skipped_empty path
      "easy"   EVERY draft came back, whole, rated EASY and alike — serve
               _pick_base(survivors), no fusor/critic
      "single" one survivor, not EASY — critic reviews it, no fusor call
      "fuse"   anything else with two or more survivors — fusor, then critic

    EASY needs unanimity across all the drafts that were fired, not just the
    ones that survived: a failed or empty draft is a missing vote, and a
    missing vote is not an EASY vote (the router's own tie-breaker: anything
    not confidently easy is HARD). On top of that the drafts must be whole and
    must agree, because self-rated difficulty says nothing about whether
    three answers match. When any of that fails the request gets the full
    review, so a z request is never served unreviewed on a doubtful call."""
    survivors = [r for r in results if r.usable]
    if not survivors:
        return "empty", survivors
    fired = draft_count if draft_count is not None else len(results)
    if (
        len(survivors) == fired
        and all(r.difficulty == "EASY" and r.complete for r in survivors)
        and _drafts_agree(survivors)
    ):
        return "easy", survivors
    if len(survivors) == 1:
        return "single", survivors
    return "fuse", survivors


def _note_degraded(product: str, fired: int, survivors: int, where: str) -> None:
    """Server-log line for a z request that ran with fewer drafts than the tier
    promises. The caller is not told (the response shape is fixed); this is how
    an operator sees that z has been quietly running as less than z."""
    if survivors < fired:
        print(f"[two_pass_pipeline] z DEGRADED ({product}): {survivors} of {fired} drafts survived, {where}")


def _lost_drafts_line(product: str, fired: int, results: list, failures: list) -> str:
    """Server-log line for drafts that did not come back, saying how many were
    cut as stragglers (cancelled on purpose) and how many failed."""
    cut = sum(1 for f in failures if isinstance(f, _DraftCut))
    return f"[two_pass_pipeline] z draft stage ({product}): {len(failures)} of {fired} drafts lost ({cut} cut as stragglers), continuing with {len(results)}: {failures[0]!r}"[:400]


def _z_status(status: str, z_info: dict | None) -> str:
    """The trace's draft_status for a z request carries how many drafts took
    part: "ok_text" becomes "ok_text_x2of3" when two of three survived. Other
    tiers pass no z_info and keep the plain value."""
    if not z_info:
        return status
    return f"{status}_x{z_info['survivors']}of{z_info['fired']}"


async def _retry_fast_transient(make_call, *, label: str):
    """Runs `make_call()` (a zero-argument function returning an awaitable) and,
    if it raises a _PassCallError with a status in Z_RETRY_STATUSES within
    Z_RETRY_MAX_ELAPSED_SECONDS, waits a moment and runs it once more. Anything
    else (a slow failure, another status, a timeout, a success) passes through
    untouched, so this only ever converts a quick refusal into a second chance.
    Used for the z drafts and the fusor, where a lost call means a lost
    draft or a lost fusion."""
    t0 = time.monotonic()
    try:
        return await make_call()
    except _PassCallError as e:
        if e.http_status not in Z_RETRY_STATUSES or time.monotonic() - t0 > Z_RETRY_MAX_ELAPSED_SECONDS:
            raise
        print(f"[two_pass_pipeline] z {label} failed fast ({e.http_status}), trying once more")
    await asyncio.sleep(Z_RETRY_DELAY_SECONDS + random.uniform(0.0, Z_RETRY_DELAY_SECONDS / 2))
    return await make_call()


# Straggler grace (added 2026-10-11). Three drafts rarely finish together, and
# one that runs far longer than the other two used to hold the whole request
# back until the 480 s hard ceiling. Once two drafts have come back whole, the
# rest get a grace period (half the time the second one took, never less than
# Z_STRAGGLER_MIN_SECONDS, never more than Z_STRAGGLER_MAX_SECONDS) and are then
# cancelled on purpose. Relative on purpose: a request whose drafts take 20 s
# should not wait 90 s for a third, and one whose drafts take 300 s should not
# be cut after 15. A request that has fewer than two whole drafts never has a
# deadline, because then the slow draft is needed, not optional.
Z_STRAGGLER_FRACTION = 0.5
Z_STRAGGLER_MIN_SECONDS = 15.0
Z_STRAGGLER_MAX_SECONDS = 90.0


def _straggler_grace(elapsed: float) -> float:
    """Seconds the remaining drafts may keep running after the second draft
    came back, `elapsed` seconds into the stage."""
    return min(max(elapsed * Z_STRAGGLER_FRACTION, Z_STRAGGLER_MIN_SECONDS), Z_STRAGGLER_MAX_SECONDS)


def _draft_is_whole(data) -> bool:
    """True for a finished draft worth waiting for no longer: it said something
    and was not cut off at its output limit."""
    if not isinstance(data, dict) or data.get("status") == "incomplete":
        return False
    text, calls = ra.responses_output_text_and_calls(data.get("output") or [])
    return text is not None or bool(calls)


async def _gather_drafts(factories: list, *, is_whole=_draft_is_whole) -> list:
    """Runs the drafts concurrently, like gather(..., return_exceptions=True),
    but gives up on stragglers: after the second whole draft (`is_whole`) has
    come back, the drafts still running get _straggler_grace() more seconds and
    are then cancelled. Returns one entry per factory, in order: the draft's
    result, the exception it raised, or a _DraftCut for one cancelled here.

    The grace clock starts once, at the moment the second whole draft arrives.
    Cancelling the CALLER (a client that went away) cancels every draft, as
    gather() did."""
    tasks = [asyncio.ensure_future(make()) for make in factories]
    t0 = time.monotonic()
    pending = set(tasks)
    whole = 0
    deadline: float | None = None
    cut: set = set()
    try:
        while pending:
            timeout = None if deadline is None else max(deadline - time.monotonic(), 0.0)
            done, pending = await asyncio.wait(pending, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                if not t.cancelled() and t.exception() is None and is_whole(t.result()):
                    whole += 1
            if not done:
                cut = set(pending)  # the deadline passed with nothing new
                break
            if deadline is None and whole >= 2 and pending:
                deadline = time.monotonic() + _straggler_grace(time.monotonic() - t0)
    finally:
        leftovers = [t for t in tasks if not t.done()]
        for t in leftovers:
            t.cancel()
        if leftovers:
            await asyncio.wait(leftovers)
    out: list = []
    for t in tasks:
        if t in cut and t.cancelled():
            out.append(_DraftCut("cancelled as a straggler after two whole drafts had come back"))
        elif t.cancelled():
            out.append(asyncio.CancelledError())
        else:
            exc = t.exception()
            out.append(exc if exc is not None else t.result())
    return out


class _TitleLeader:
    """Decides which draft's thinking the title feed follows (z tiers, streaming).

    Three drafts think at once and their streams must never interleave into one
    feed, so the titles follow ONE draft: the first to say anything. Added
    2026-10-11: when that draft finishes or fails, the feed moves to the draft
    that is furthest along instead of going quiet until the fusor starts. The
    new source's recent text (a bounded backlog, BACKLOG_CHARS per draft, kept
    while it was not the leader) is replayed so its first title describes where
    it is now, and relay.source_changed() is called first so the old source's
    unfinished text gets its own title rather than being merged with the new
    source's. If no other draft has said anything yet, the next one that does
    becomes the leader.

    `relay` needs feed(text), feed_draft(text) and source_changed()."""
    BACKLOG_CHARS = 3000

    def __init__(self, relay, count: int):
        self._relay = relay
        self._leader: int | None = None
        self._finished: set[int] = set()
        self._backlog: dict[int, list[tuple[str, str]]] = {i: [] for i in range(count)}
        self._seen: dict[int, int] = {i: 0 for i in range(count)}

    @property
    def leader(self) -> int | None:
        return self._leader

    def reasoning(self, i: int, text: str) -> None:
        self._on(i, False, text)

    def draft_text(self, i: int, text: str) -> None:
        self._on(i, True, text)

    def _send(self, is_draft: bool, text: str) -> None:
        (self._relay.feed_draft if is_draft else self._relay.feed)(text)

    def _on(self, i: int, is_draft: bool, text: str) -> None:
        if not text or i in self._finished:
            return
        self._seen[i] += len(text)
        if self._leader is None:
            self._leader = i
        if self._leader == i:
            self._send(is_draft, text)
            return
        log = self._backlog[i]
        log.append((is_draft, text))
        total = sum(len(t) for _k, t in log)
        while log and total - len(log[0][1]) >= self.BACKLOG_CHARS:
            total -= len(log.pop(0)[1])

    def finished(self, i: int) -> None:
        """Draft i's call is over (it returned, failed or was cancelled)."""
        self._finished.add(i)
        self._backlog[i] = []
        if self._leader != i:
            return
        candidates = [j for j in self._backlog if j not in self._finished and self._seen[j] > 0]
        if not candidates:
            self._leader = None  # whoever speaks next takes over
            return
        successor = max(candidates, key=lambda j: (self._seen[j], -j))
        self._leader = successor
        self._relay.source_changed()
        backlog, self._backlog[successor] = self._backlog[successor], []
        for is_draft, text in backlog:
            self._send(is_draft, text)


def _fusion_outcome(fusor_data: dict, base: _DraftResult) -> tuple[dict, dict] | None:
    """(data, billed usage) to hand the critic as "the draft" after a
    fusion call, or None when the fusor produced nothing usable (the caller
    then falls back to `base`, the first surviving draft). Billed usage is
    the FIRST draft's input with the FUSOR's output: the last call that
    produced the answer being served, which is what billing.py's
    first-call-input / last-call-output rule needs if the critic then never
    finishes. When the critic does finish, billed_client_usage() takes its
    output instead and only the input half of this survives."""
    if fusor_data.get("status") == "failed":
        return None
    text, calls = ra.responses_output_text_and_calls(fusor_data.get("output") or [])
    if text is None and not calls:
        return None
    fusor_usage = ra.usage_from_responses(fusor_data.get("usage") or {})
    return fusor_data, ra.billed_client_usage(base.usage_billed, fusor_usage)


async def _nonstream_draft_failed(e: BaseException, *, product, draft: PassConfig, requestor, trace_id, started):
    """Logs a failed (or timed-out) draft stage and raises the HTTPException
    the caller gets. Shared by the single-draft stage and the z stage, which
    raises the FIRST failure's error when every draft failed."""
    if isinstance(e, asyncio.TimeoutError):
        reason = f"draft pass hard ceiling ({GENERATION_HARD_CEILING_SECONDS:.0f}s) hit"
        await log_usage(product, draft.model, requestor=requestor, status="error", error_message=reason)
        await update_chat_trace(trace_id, status="timeout", error_message=reason, duration_ms=int((time.monotonic() - started) * 1000))
        raise HTTPException(status_code=504, detail={"error": {"message": "The request timed out.", "type": "server_error", "code": "upstream_timeout"}})
    await log_usage(product, draft.model, requestor=requestor, latency_ms=e.latency_ms, status="error", error_message=e.log_message)
    await update_chat_trace(trace_id, status="upstream_error", upstream_status_code=e.http_status, error_message=e.log_message, duration_ms=int((time.monotonic() - started) * 1000))
    raise HTTPException(status_code=e.http_status, detail=e.client_payload)


async def _nonstream_single_draft_stage(*, product, system_identity, draft: PassConfig, input_items, tools, started, trace_id, requestor, boundary, injected_prefix_tokens, injected_total_tokens):
    """The ordinary one-draft stage (every tier except z-low/z-high), moved
    here unchanged from _run_nonstream() so the z stage can sit beside it.
    Returns (draft_data with the difficulty tag stripped, draft_usage_billed,
    difficulty)."""
    draft_body = _draft_body(draft, product, input_items, tools, system_identity, stream=False, boundary=boundary)
    try:
        draft_data = await asyncio.wait_for(_post_upstream(draft, draft_body, started), timeout=_NONSTREAM_PASS_BACKSTOP())
    except asyncio.TimeoutError as e:
        await _nonstream_draft_failed(e, product=product, draft=draft, requestor=requestor, trace_id=trace_id, started=started)
    except _PassCallError as e:
        await _nonstream_draft_failed(e, product=product, draft=draft, requestor=requestor, trace_id=trace_id, started=started)

    draft_usage = ra.usage_from_responses(draft_data.get("usage") or {})
    # draft_usage is the RAW upstream figure (kept for reference);
    # draft_usage_billed is what billing, the caller AND the usage_logs row use, so the
    # dashboard (which prices usage_logs rows) can never disagree with what was charged.
    draft_usage_billed = ra.remove_injected_input(draft_usage, injected_total_tokens, injected_prefix_tokens)
    # MUST run before responses_output_text_and_calls() in the caller — see
    # extract_difficulty_and_strip()'s own docstring for why this exact
    # order (strip first, derive draft_text from the CLEANED data
    # second) is what keeps the tag out of both the critic prompt and
    # anything a caller could receive, on every branch, including the
    # pre-existing empty-draft branch.
    draft_data, difficulty = ra.extract_difficulty_and_strip(draft_data, boundary)
    return draft_data, draft_usage_billed, difficulty


async def _nonstream_z_draft_stage(*, product, system_identity, draft: PassConfig, fusor: PassConfig, draft_count: int, input_items, tools, started, trace_id, requestor, boundary, fusion_boundary, injected_prefix_tokens, injected_total_tokens, z_info: dict | None = None):
    """The z-tier stage: draft_count concurrent drafts, then (when it is
    worth it) one fusor call. Returns the same triple as the single-draft
    stage — (data, usage_billed, difficulty) for "the draft" the rest of
    _run_nonstream() carries on with — so everything after it (empty and
    EASY branches, tracing, the critic, the fallbacks, billing) is shared
    and unchanged. See the module docstring's "z tiers" section for the
    decisions. `z_info`, when given, is filled with how many drafts were
    fired and how many took part (see _z_status)."""
    async def _one() -> dict:
        body = _draft_body(draft, product, input_items, tools, system_identity, stream=False, boundary=boundary)
        return await _retry_fast_transient(lambda: asyncio.wait_for(_post_upstream(draft, body, started), timeout=_NONSTREAM_PASS_BACKSTOP()), label="draft")

    raw = await _gather_drafts([_one] * draft_count)
    results, failures = _digest_draft_results(raw, boundary, injected_total_tokens, injected_prefix_tokens)
    if not results:
        await _nonstream_draft_failed(failures[0], product=product, draft=draft, requestor=requestor, trace_id=trace_id, started=started)
    if failures:
        print(_lost_drafts_line(product, draft_count, results, failures))
    verdict, survivors = _plan_fusion(results, draft_count)
    if z_info is not None:
        z_info.update(fired=draft_count, survivors=len(survivors))

    if verdict == "empty":
        return results[0].data, results[0].usage_billed, "HARD"
    if verdict == "easy":
        pick = _pick_base(survivors)
        return pick.data, pick.usage_billed, "EASY"
    if verdict == "single":
        _note_degraded(product, draft_count, len(survivors), "reviewing the lone draft without fusion")
        return survivors[0].data, survivors[0].usage_billed, "HARD"

    base = survivors[0]  # billing's "first call": the same prompt in every draft
    await update_chat_trace(trace_id, status="fusor_started", draft_status=f"ok_x{len(survivors)}of{draft_count}")
    rendered = [_rendered(r) for r in survivors]
    fusor_body = _fusor_body(fusor, product, input_items, rendered, tools, system_identity, stream=False, fusion_boundary=fusion_boundary)
    try:
        fusor_data = await _retry_fast_transient(lambda: asyncio.wait_for(_post_upstream(fusor, fusor_body, started), timeout=_NONSTREAM_PASS_BACKSTOP()), label="fusor")
    except (asyncio.TimeoutError, _PassCallError) as e:
        why = f"fusor pass hard ceiling ({GENERATION_HARD_CEILING_SECONDS:.0f}s) hit" if isinstance(e, asyncio.TimeoutError) else e.log_message
        fallback = _pick_base(survivors)
        print(f"[two_pass_pipeline] z DEGRADED ({product}): fusor failed, reviewing the consensus draft instead: {why}"[:400])
        return fallback.data, fallback.usage_billed, "HARD"
    fused = _fusion_outcome(fusor_data, base)
    if fused is None:
        fallback = _pick_base(survivors)
        print(f"[two_pass_pipeline] z DEGRADED ({product}): fusor returned nothing usable, reviewing the consensus draft instead")
        return fallback.data, fallback.usage_billed, "HARD"
    _note_degraded(product, draft_count, len(survivors), "fused the survivors")
    return fused[0], fused[1], "HARD"


# ============================================================
# Public entry point
# ============================================================
async def run_pipeline(
    *, product: str, slug: str, system_identity: str,
    draft: PassConfig, critic: PassConfig,
    input_items: list[dict], tools: list[dict] | None,
    client_wants_stream: bool, caller_shape: str,
    client_wants_usage_chunk: bool = False,
    requestor: dict, source: str = "api", on_complete=None,
    fusor: PassConfig | None = None, draft_count: int = 1, reasoning_tier: str | None = None,
):
    """`fusor`/`draft_count` (added 2026-10-08) are the z-tier switch: with a
    fusor the request runs draft_count concurrent drafts, a fusion call, then
    the critic (module docstring, "z tiers"); without one it is the plain
    two-call pipeline, unchanged. `reasoning_tier` is the caller-facing tier
    name, recorded in the trace in place of the draft's raw effort."""
    started = time.monotonic()
    request_started_at = datetime.now(timezone.utc)
    # See response_api.prepare_input_items()'s docstring for exactly what
    # this does (caller system/developer message tagging + the tagged
    # Kael-context item carrying the real date) and why it lives there. Called here, once — this is
    # the single point every entry path (chat_completions or native
    # responses) already funnels through before either pass is built, so
    # both passes inherit it automatically and identically, with no
    # duplicated logic in kael_pipeline.py. request_message_count/
    # last_user_message below
    # are computed AFTER this call so the trace reflects what actually
    # went upstream, not the caller's raw input (last_user_text() is
    # unaffected either way — see its own docstring — since it filters
    # for role=="user" and the item this appends is role=="system").
    # One unguessable-from-outside token for this request only, reused for
    # BOTH tag boundaries that wrap untrusted/less-trusted text this
    # request (the caller's own <caller_system_prompt_{boundary}> below,
    # and the critic pass's <draft_{boundary}> — see critic.
    # build_critic_message()'s docstring for the full threat model these
    # close). Generated once, here, rather than separately in each place
    # that needs it, so both tags agree — not that they need to match
    # each other for security (either alone is enough unpredictability),
    # but a single request-scoped value is simpler to reason about and to
    # find in a trace than two independent ones would be.
    boundary = secrets.token_hex(8)
    raw_input_items = input_items
    # One OpenRouter sticky-routing key for this conversation, shared by
    # the draft and critic pass (stickiness is tracked per model, so one
    # key is fine for two different models). Derived from the RAW input,
    # BEFORE prepare_input_items() adds this request's random tags — a key
    # built from tagged text would change every request and never stick.
    # See provider_routing.py.
    _session_id = provider_routing.derive_session_id(requestor.get("user_id"), raw_input_items)
    draft = replace(draft, session_id=_session_id)
    critic = replace(critic, session_id=_session_id)
    if fusor is not None:
        fusor = replace(fusor, session_id=_session_id)
        # A token for the fusion step ONLY. The request-wide `boundary`
        # below was visible to the draft passes (inside
        # <caller_system_prompt_...>), so a draft could echo it; this one is
        # never in any earlier pass's context. See fusor.build_fusor_message().
        fusion_boundary = secrets.token_hex(8)
    else:
        fusion_boundary = None
    input_items = ra.prepare_input_items(input_items, request_started_at, boundary)
    # Text Kael injects into the draft request (master prompt, context block,
    # wrapper tags, router instruction) is subtracted from the input tokens
    # callers see and are billed — see response_api.remove_injected_input().
    _prefix_chars, _total_chars = ra.injected_input_chars(raw_input_items, input_items, system_identity, [build_router_message(product, boundary)])
    injected_prefix_tokens = ra.estimate_injected_tokens(_prefix_chars)
    injected_total_tokens = ra.estimate_injected_tokens(_total_chars)
    trace_id = await start_chat_trace(
        source=source, product=product, model=f"{draft.model}+{critic.model}",
        stream=client_wants_stream, thinking_enabled=True, reasoning_effort=reasoning_tier or draft.reasoning_effort,
        request_message_count=len(input_items), last_user_message=last_user_text(input_items),
        user_id=requestor.get("user_id"), status="started",
        # The Playground conversation (None for API requests): lets the
        # database delete this row when the conversation is deleted.
        session_id=requestor.get("chat_session_id"),
    )

    if product in config.BILLED_PRODUCTS:
        try:
            await billing.check_balance_or_raise(requestor["user_id"])
        except billing.InsufficientBalanceError as e:
            await update_chat_trace(trace_id, status="upstream_error", error_message=f"billing: insufficient balance ({billing.format_usd(e.balance)})")
            raise HTTPException(status_code=402, detail={"error": {"message": f"Insufficient balance ({billing.format_usd(e.balance)}). Add funds to continue.", "type": "insufficient_balance", "code": "insufficient_balance"}})
        except billing.BillingUnavailableError as e:
            await update_chat_trace(trace_id, status="upstream_error", error_message=f"billing unavailable: {e}")
            raise HTTPException(status_code=500, detail={"error": {"message": "Could not verify account balance — please retry.", "type": "server_error", "code": "billing_unavailable"}})

        # Added 2026-09-13 — see rate_limit.py's "Product (billed
        # inference) endpoints" section for why this exists and what it
        # closes (a request-burst window check_balance_or_raise's own
        # docstring already admits it can't cover on its own). Checked
        # AFTER balance (no point limiting a request that was getting a
        # 402 anyway) and BEFORE start_product_request() marks a slot
        # used, so a caller who's over either limit never occupies one.
        rate_limit.enforce_product_rate_limit(requestor["user_id"])

    for pcfg in (draft, critic) + ((fusor,) if fusor is not None else ()):
        if not pcfg.api_key:
            await update_chat_trace(trace_id, status="upstream_error", error_message=f"missing API key for provider {pcfg.provider}")
            raise HTTPException(status_code=500, detail=ra.missing_key_error(pcfg.provider))

    if client_wants_stream:
        queue: asyncio.Queue = asyncio.Queue()
        # Generated here, not inside _run_stream, so relay()'s heartbeat
        # chunks (below) can carry the SAME id every real content chunk
        # uses — a client stitching a stream together by `id` shouldn't
        # see it change mid-response just because a keep-alive fired.
        response_id = f"chatcmpl-{product}-{uuid.uuid4().hex}"
        # Set by relay() below when the HTTP response is closed before the
        # stream finished (the caller disconnected). The two passes keep
        # running regardless — they are billed, and cancelling them would
        # let a caller get free compute by disconnecting — but the thinking
        # relay reads this flag and stops spending on summarizer calls.
        client_gone = asyncio.Event()
        if product in config.BILLED_PRODUCTS:
            # Paired with rate_limit.end_product_request() in _run_stream's
            # own finally block below (not here — the slot needs to stay
            # occupied for the request's real lifetime, which for a
            # streaming request is the background task's lifetime, not
            # this function's — run_pipeline() itself returns as soon as
            # the StreamingResponse is constructed, long before the work
            # is done).
            rate_limit.start_product_request(requestor["user_id"])
        task = asyncio.create_task(_run_stream(
            product=product, slug=slug, system_identity=system_identity, draft=draft, critic=critic,
            fusor=fusor, draft_count=draft_count, fusion_boundary=fusion_boundary,
            input_items=input_items, tools=tools, caller_shape=caller_shape,
            client_wants_usage_chunk=client_wants_usage_chunk,
            started=started, trace_id=trace_id, requestor=requestor, on_complete=on_complete,
            queue=queue, request_started_at=request_started_at, response_id=response_id,
            boundary=boundary, injected_prefix_tokens=injected_prefix_tokens, injected_total_tokens=injected_total_tokens,
            client_gone=client_gone,
        ))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        def _heartbeat() -> str:
            """Fired every STREAM_KEEPALIVE_SECONDS of silence — see that
            constant's comment for why 1s. Unlike the bare SSE comment
            (`: ...`) this used to be, this is a REAL `data:` event with a
            real (empty) delta, deliberately — a comment line is only
            guaranteed to reset a TRANSPORT-level idle timer (TCP/proxy);
            some OpenAI-compatible clients (Cursor's among them, per
            direct testing) instead watch for actual delta events at the
            APPLICATION layer to decide a response is still in flight,
            and a stream of nothing but comment lines doesn't satisfy
            that. So: a genuine chat.completion.chunk with
            `delta: {"content": ""}` — a real, spec-shaped event any
            OpenAI-format client already knows how to consume, but an
            EMPTY string, so appending it to accumulated text is a
            no-op (confirmed against this project's own frontend,
            src/lib/api.ts, whose `delta.length > 0` guard already
            skips empty strings — it neither renders nor fires
            onFirstToken for one). Deliberately `{"content": ""}` and
            not `{}` — a client that does
            `text += chunk.choices[0].delta.content` with no null-guard
            (common in minimal/hand-rolled parsers) would concatenate
            the literal string "undefined" onto the answer if `content`
            were simply absent; an explicit empty string can't do that.
            For a Responses-shaped caller there's no equally "real but
            empty" event in that API's own vocabulary to safely borrow
            (a real `response.output_text.delta` carries required
            fields — item_id, output_index, etc. — that a half-populated
            copy could fail a strict client's own schema check on), so
            this uses an unambiguously custom event name instead —
            `response.ping` is not a type any real Responses API caller
            defines a case for, so a switch/if-chain over known event
            types safely falls through to its default (this project's
            own consume_pass() elif-chain does exactly that for
            anything it doesn't recognize), while still being genuine
            bytes carrying a real `data:` line.

            An Anthropic-shaped caller doesn't need a borrowed or
            custom event at all — Anthropic's own protocol defines a
            real `ping` event for exactly this purpose (confirmed
            against docs.claude.com/en/docs/build-with-claude/streaming,
            2026-09-09), sent periodically by Anthropic's own servers
            regardless of whether anything else is happening — so this
            uses that real event verbatim rather than either of the
            other two shapes' approaches."""
            if caller_shape == "chat_completions":
                payload = {
                    "id": response_id, "object": "chat.completion.chunk", "model": slug,
                    "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": None}],
                }
                return f"data: {json.dumps(payload)}\n\n"
            if caller_shape == "anthropic":
                return "event: ping\ndata: {\"type\": \"ping\"}\n\n"
            return f"event: response.ping\ndata: {json.dumps({'type': 'response.ping'})}\n\n"

        async def relay():
            finished = False
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=STREAM_KEEPALIVE_SECONDS)
                    except asyncio.TimeoutError:
                        yield _heartbeat()
                        continue
                    if item is None:
                        finished = True
                        if caller_shape == "chat_completions":
                            yield "data: [DONE]\n\n"
                        # Responses-shape callers get no [DONE] sentinel — the
                        # stream already ended on a response.completed/
                        # incomplete/failed event (confirmed against
                        # DeepSeek's own Responses API streaming docs).
                        return
                    yield item
            finally:
                # Runs on a normal end too (finished is True then). Any other
                # way out — the caller disconnected, the response was
                # cancelled — means nobody is reading any more. The in-app
                # chat's pump task reads this generator to the very end
                # whether or not a browser is attached, so for it this
                # never fires early and its thinking titles keep being saved.
                if not finished:
                    client_gone.set()

        return StreamingResponse(relay(), media_type="text/event-stream")

    if product in config.BILLED_PRODUCTS:
        rate_limit.start_product_request(requestor["user_id"])
    try:
        return await _run_nonstream(
            product=product, slug=slug, system_identity=system_identity, draft=draft, critic=critic,
            fusor=fusor, draft_count=draft_count, fusion_boundary=fusion_boundary,
            input_items=input_items, tools=tools, caller_shape=caller_shape,
            started=started, trace_id=trace_id, requestor=requestor, on_complete=on_complete,
            request_started_at=request_started_at, boundary=boundary,
            injected_prefix_tokens=injected_prefix_tokens, injected_total_tokens=injected_total_tokens,
        )
    finally:
        if product in config.BILLED_PRODUCTS:
            rate_limit.end_product_request(requestor["user_id"])


# ============================================================
# Non-streaming path
# ============================================================
async def _run_nonstream(*, product, slug, system_identity, draft: PassConfig, critic: PassConfig, input_items, tools, caller_shape, started, trace_id, requestor, on_complete, request_started_at, boundary, injected_prefix_tokens: int = 0, injected_total_tokens: int = 0, fusor: PassConfig | None = None, draft_count: int = 1, fusion_boundary: str | None = None):
    z_info: dict | None = None  # filled by the z stage: drafts fired / drafts that took part (trace only)
    if fusor is None:
        draft_data, draft_usage_billed, difficulty = await _nonstream_single_draft_stage(
            product=product, system_identity=system_identity, draft=draft, input_items=input_items, tools=tools,
            started=started, trace_id=trace_id, requestor=requestor, boundary=boundary,
            injected_prefix_tokens=injected_prefix_tokens, injected_total_tokens=injected_total_tokens,
        )
    else:
        z_info = {}
        draft_data, draft_usage_billed, difficulty = await _nonstream_z_draft_stage(
            product=product, system_identity=system_identity, draft=draft, fusor=fusor, draft_count=draft_count,
            input_items=input_items, tools=tools, started=started, trace_id=trace_id, requestor=requestor,
            boundary=boundary, fusion_boundary=fusion_boundary,
            injected_prefix_tokens=injected_prefix_tokens, injected_total_tokens=injected_total_tokens,
            z_info=z_info,
        )
    draft_text, draft_calls = ra.responses_output_text_and_calls(draft_data.get("output") or [])

    if draft_text is None and not draft_calls:
        # Nothing reviewable at all — genuinely empty/filtered output
        # (this also naturally covers a draft whose ENTIRE response was
        # just the difficulty tag and nothing else: stripping it above
        # leaves an empty string here, which falls through to this same
        # branch rather than a new, separate "empty after stripping"
        # special case). This is the ONLY case that still skips the
        # critic pass for this reason; a tool call alone is no longer a
        # skip condition (see module docstring).
        latency_ms = int((time.monotonic() - started) * 1000)
        await log_usage(product, draft.model, requestor=requestor, latency_ms=latency_ms, status="success", stream=False, **draft_usage_billed)
        if product in config.BILLED_PRODUCTS:
            await billing.charge_for_request(requestor["user_id"], product, ra.client_usage(draft_usage_billed), None, at=request_started_at)
        await update_chat_trace(trace_id, status="done", draft_status=_z_status("skipped_empty", z_info), draft_finish_reason=ra.finish_reason(draft_data, False), content_char_count=0, duration_ms=latency_ms)
        return ra.reshape(draft_data, caller_shape, slug, billed_usage=draft_usage_billed)

    if difficulty == "EASY":
        # Difficulty routing (added 2026-09-13) — see app/router/kael.py
        # for the classification instructions and
        # response_api.extract_difficulty_and_strip() for how `difficulty`
        # above was derived and the tag already removed from draft_text/
        # draft_data before this point. "HARD", and any parse failure
        # (missing/malformed tag), fall through past this branch entirely
        # and continue into the critic pass exactly as every draft always
        # has — this is the ONLY new way to skip the critic, added
        # alongside the pre-existing empty-draft skip above, never
        # replacing it. Billing/logging/trace shape deliberately mirrors
        # that empty-draft branch exactly (draft-only usage charged,
        # draft-only reshape returned) — the only real differences are
        # the trace's draft_status label (distinguishing "genuinely
        # nothing to review" from "something to review, but the draft
        # itself judged the request too easy to warrant it") and that
        # on_complete fires here (the empty-draft branch above never
        # does, since there's no text to hand it).
        latency_ms = int((time.monotonic() - started) * 1000)
        await log_usage(product, draft.model, requestor=requestor, latency_ms=latency_ms, status="success", stream=False, **draft_usage_billed)
        if product in config.BILLED_PRODUCTS:
            await billing.charge_for_request(requestor["user_id"], product, ra.client_usage(draft_usage_billed), None, at=request_started_at)
        await update_chat_trace(trace_id, status="done", draft_status=_z_status("skipped_easy", z_info), draft_finish_reason=ra.finish_reason(draft_data, bool(draft_calls)), content_char_count=len(draft_text or ""), content_preview=draft_text or "", duration_ms=latency_ms)
        if on_complete and draft_text:
            await on_complete(draft_text)
        return ra.reshape(draft_data, caller_shape, slug, billed_usage=draft_usage_billed)

    await update_chat_trace(
        trace_id, status="critic_started",
        draft_status=_z_status("ok_tool_call" if draft_calls and not draft_text else ("ok_text_and_tool_call" if draft_calls else "ok_text"), z_info),
        draft_content_chars=len(draft_text or ""), draft_content_preview=draft_text or "", draft_finish_reason="stop",
    )

    critic_body = _critic_body(critic, product, input_items, draft_text, draft_calls, tools, system_identity, stream=False, boundary=boundary)
    try:
        critic_data = await asyncio.wait_for(_post_upstream(critic, critic_body, started), timeout=_NONSTREAM_PASS_BACKSTOP())
        if critic_data.get("status") == "failed":
            # Content-level failure comes back as HTTP 200 with
            # status="failed" in the body (the internal canonical shape's
            # analogue of Chat Completions' finish_reason="content_filter")
            # — _post_upstream only raises on non-2xx HTTP, so this needs
            # its own check.
            raise _PassCallError(502, f"critic pass returned status=failed ({provider_routing.failed_pass_summary(critic_data)})", {"error": {"message": "The critic pass failed.", "type": "server_error"}})
    except (asyncio.TimeoutError, _PassCallError) as e:
        is_timeout = isinstance(e, asyncio.TimeoutError)
        log_message = f"critic pass hard ceiling ({GENERATION_HARD_CEILING_SECONDS:.0f}s) hit" if is_timeout else e.log_message
        latency_ms = int((time.monotonic() - started) * 1000)
        await log_usage(product, draft.model, requestor=requestor, latency_ms=latency_ms, status="success", stream=False, error_message=f"critic pass failed, served draft: {log_message}"[:500], **draft_usage_billed)
        if product in config.BILLED_PRODUCTS:
            # Critic never produced a usable completion — draft is both
            # the first AND last call here.
            await billing.charge_for_request(requestor["user_id"], product, ra.client_usage(draft_usage_billed), None, at=request_started_at)
        await update_chat_trace(trace_id, status="done", error_message=f"critic pass failed, served draft: {log_message}"[:500], content_char_count=len(draft_text or ""), content_preview=draft_text or "", duration_ms=latency_ms)
        if on_complete and draft_text:
            await on_complete(draft_text)
        return ra.reshape(draft_data, caller_shape, slug, billed_usage=draft_usage_billed)

    latency_ms = int((time.monotonic() - started) * 1000)
    critic_usage = ra.usage_from_responses(critic_data.get("usage") or {})
    billed_usage = ra.billed_client_usage(draft_usage_billed, critic_usage)
    await log_usage(product, f"{draft.model}+{critic.model}", requestor=requestor, latency_ms=latency_ms, status="success", stream=False, **billed_usage)
    if product in config.BILLED_PRODUCTS:
        await billing.charge_for_request(requestor["user_id"], product, ra.client_usage(draft_usage_billed), ra.client_usage(critic_usage), at=request_started_at)
    final_text, final_calls = ra.responses_output_text_and_calls(critic_data.get("output") or [])
    await update_chat_trace(trace_id, status="done", finish_reason=ra.finish_reason(critic_data, bool(final_calls)), content_char_count=len(final_text or ""), content_preview=final_text or "", duration_ms=latency_ms)
    if on_complete and final_text:
        await on_complete(final_text)
    return ra.reshape(critic_data, caller_shape, slug, billed_usage=billed_usage)


# ============================================================
# Streaming path
# ============================================================
async def _run_stream(
    *, product, slug, system_identity, draft: PassConfig, critic: PassConfig,
    input_items, tools, caller_shape, client_wants_usage_chunk,
    started, trace_id, requestor, on_complete, queue: asyncio.Queue, request_started_at, response_id: str,
    boundary: str, injected_prefix_tokens: int = 0, injected_total_tokens: int = 0,
    client_gone: asyncio.Event | None = None,
    fusor: PassConfig | None = None, draft_count: int = 1, fusion_boundary: str | None = None,
):
    """Owns the entire two-pass pipeline for one streaming request, end to
    end. Both passes stream upstream, but only pass 2's (the critic's)
    content deltas are ever relayed to the client — pass 1's (the
    draft's) output, reasoning included, is buffered-only as of
    2026-08-26 (see module docstring, fix #2). Runs as a background task
    so the HTTP response can start (with keep-alives, at most
    STREAM_KEEPALIVE_SECONDS apart) immediately rather than staying
    silent for however long a "high"/"max" effort draft takes."""

    def emit_raw(s: str) -> None:
        queue.put_nowait(s)

    def emit_cc(chunk: dict) -> None:
        emit_raw(f"data: {json.dumps(chunk)}\n\n")

    async def emit_error(message: str) -> None:
        # Drains thinking_relay FIRST, before this function's own error
        # event goes out — otherwise a thinking title still in flight in
        # the background (see ThinkingRelay's own asyncio task) could
        # land in the queue AFTER this "the stream is over" event, which
        # is invalid on every caller_shape (nothing should stream after
        # an error/terminal event) and was caught by an end-to-end test
        # against a fast/instant mocked upstream, where the race is easy
        # to hit — a real upstream is usually slow enough relative to
        # ThinkingRelay's own flush timers that this would have been
        # rare in practice, not that rare is the same as impossible.
        # stop() is safe to call more than once (idempotent — see its
        # own docstring), so the outer `finally`'s own
        # `await thinking_relay.stop()` after this function returns is a
        # harmless no-op, not a double-drain bug. flush_tail=False: an error
        # is about to be sent, a title for the reasoning before it is moot,
        # and the client should not wait for one.
        await thinking_relay.stop(flush_tail=False)
        if caller_shape == "chat_completions":
            emit_cc({"error": {"message": message, "type": "server_error"}})
        elif caller_shape == "anthropic":
            emit_raw(aa._sse("error", {"type": "error", "error": {"type": "api_error", "message": message}}))
        else:
            emit_raw(f"data: {json.dumps({'type': 'error', 'error': {'message': message}})}\n\n")

    # One instance for the whole request, same lifetime as thinking_relay
    # below — see app/anthropic_api.py's AnthropicStreamState docstring.
    # Harmless to create even for a non-Anthropic caller_shape (it's
    # simply never invoked then) — no different from draft/critic
    # PassConfig objects existing for a request that ends up not using
    # every field on them.
    anthropic_state = aa.AnthropicStreamState(response_id, slug)
    anthropic_started = False

    def ensure_anthropic_started(input_tokens: int = 0) -> None:
        """Anthropic's message_start must be the very first event in the
        stream, before any content_block_start — called from every site
        that might be the first thing this response ever emits
        (emit_thinking, the content_delta relay below, emit_fallback)
        rather than assuming thinking titles always come first (a critic
        pass with no reasoning before its content is a real case where
        they wouldn't)."""
        nonlocal anthropic_started
        if not anthropic_started:
            emit_raw(anthropic_state.message_start(input_tokens=input_tokens))
            anthropic_started = True

    def emit_thinking(text: str) -> None:
        """The ONE place a thinking title (or filler word — see
        app/thinking_summarizer.py, this callback is what's passed as
        ThinkingRelay's emit_fn below) actually reaches the client. Reuses
        the exact same wire fields real raw reasoning relay would have
        used for the two OpenAI-compatible shapes (delta.reasoning_content
        for Chat-Completions, response.reasoning_text.delta for
        Responses), and Anthropic's own native `thinking` content block
        for an Anthropic-shaped caller — see app/anthropic_api.py's
        module docstring for why that's a closer fit than either other
        shape gets. API-level behavior for every streaming Kael Beta
        caller, not an in-app-chat-only feature."""
        # One title per delta, each ending in THINKING_TITLE_SEPARATOR so a
        # caller that concatenates the deltas still sees separate lines.
        text = text + THINKING_TITLE_SEPARATOR
        if caller_shape == "chat_completions":
            send_role_if_needed()
            emit_cc({"id": response_id, "object": "chat.completion.chunk", "model": slug_local, "choices": [{"index": 0, "delta": {"reasoning_content": text}, "finish_reason": None}]})
        elif caller_shape == "anthropic":
            ensure_anthropic_started()
            emit_raw(anthropic_state.thinking_delta(text))
        else:
            emit_raw(f"event: response.reasoning_text.delta\ndata: {json.dumps({'type': 'response.reasoning_text.delta', 'delta': text})}\n\n")
    # Known, disclosed limitation of the anthropic_started branch above:
    # Anthropic's real protocol only ever sends input_tokens once, on
    # message_start, and expects it to already be the real, final count
    # — but a thinking title can arrive during PASS 1, before the draft
    # call (which is what determines the actually-billed input token
    # count — see response_api.billed_client_usage()) has even finished,
    # so the true number simply isn't known yet at the moment
    # message_start has to go out. Sent as 0 rather than a guess; the
    # real, correct completion_tokens/output_tokens figure IS available
    # by finish() at the end (see below) since output is fully generated
    # by then — only this one field, on this one shape, at this one
    # protocol-mandated moment, is a known approximation, not the
    # request's real billed usage overall (which app/billing.py still
    # computes and charges correctly regardless of what any caller_shape
    # streams).

    # Created here, before the outer try/finally below, specifically so
    # `finally: await thinking_relay.stop()` can never hit a NameError —
    # even an exception on the very first line inside that try still
    # needs a real, already-started ThinkingRelay to tear down. Spans
    # BOTH passes (fed via reasoning_sink= on both consume_pass() calls
    # below) — see app/thinking_summarizer.py's module docstring,
    # "Crossing the draft -> critic seam," for why one instance covering
    # the whole request is what makes that transition invisible.
    thinking_relay = ThinkingRelay(
        emit_thinking,
        session_id=provider_routing.titles_session_id(draft.session_id),
        is_client_gone=client_gone.is_set if client_gone is not None else None,
    )
    thinking_relay.start()

    # True once the CRITIC pass has actually put answer content (text or a
    # tool-call delta) on the wire. Thinking titles do not count, and neither
    # does the draft, which is never relayed live. Decides what a critic
    # failure may do: before this is set the draft can still be served whole;
    # after it, appending the draft to a half-sent answer would be garbage.
    client_answer_started = False

    async def complete(text: str) -> None:
        """Hands a finished reply to on_complete (the in-app chat saves it
        there). Stops the thinking relay FIRST so the list of titles handed
        over is final, and is exactly what was streamed — before this, the
        saved list was whatever the stream's consumer had read so far, so
        the last titles could be missing."""
        if not (on_complete and text):
            return
        await thinking_relay.stop(flush_tail=False)
        await _call_on_complete(on_complete, text, list(thinking_relay.titles))

    slug_local = slug
    # response_id now comes from run_pipeline() (see its comment) so
    # relay()'s heartbeat chunks and this function's real content chunks
    # share one id for the whole response, rather than the heartbeat
    # inventing a second one nobody else uses.
    role_sent = False
    chunks_from_upstream = 0
    chunks_sent_to_client = 0
    reasoning_char_count = 0

    def send_role_if_needed() -> None:
        nonlocal role_sent
        if caller_shape == "chat_completions" and not role_sent:
            emit_cc({"id": response_id, "object": "chat.completion.chunk", "model": slug_local, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
            role_sent = True

    async def emit_fallback(data: dict, billed_usage: dict) -> None:
        """Fake-streams a complete (non-streamed) Responses payload — used
        when the critic pass never produced real streamed output. Not
        real token-by-token streaming, just enough structure for a
        client parsing the stream format to get one valid, complete
        message, with `usage` already the billed-consistent figure.

        Drains thinking_relay first, same reasoning as emit_error()
        above — this is also always a terminal emission (draft-only
        fallback IS the whole response), so nothing should follow it.

        Uses send_role_if_needed() rather than emitting its own role
        chunk unconditionally — role_sent is often ALREADY true by the
        time this runs now: emit_thinking()'s chat_completions branch
        calls send_role_if_needed() too (see above), and a thinking
        title from the draft pass is the common case for anything
        reaching this fallback at all (a critic failure/timeout only
        gets here after a full draft pass already streamed its
        thinking). The guard is what makes a second, redundant
        `delta: {role: assistant}` chunk never go out either way,
        regardless of which of the two paths set it first."""
        await thinking_relay.stop(flush_tail=False)
        if caller_shape == "chat_completions":
            cc = ra.to_chat_completion(data, slug, billed_usage=billed_usage)
            msg = cc["choices"][0]["message"]
            resp_id = cc["id"]
            send_role_if_needed()
            if msg.get("content"):
                emit_cc({"id": resp_id, "object": "chat.completion.chunk", "model": slug, "choices": [{"index": 0, "delta": {"content": msg["content"]}, "finish_reason": None}]})
            if msg.get("tool_calls"):
                tc = [{**t, "index": i} for i, t in enumerate(msg["tool_calls"])]
                emit_cc({"id": resp_id, "object": "chat.completion.chunk", "model": slug, "choices": [{"index": 0, "delta": {"tool_calls": tc}, "finish_reason": None}]})
            emit_cc({"id": resp_id, "object": "chat.completion.chunk", "model": slug, "choices": [{"index": 0, "delta": {}, "finish_reason": cc["choices"][0]["finish_reason"]}]})
            if client_wants_usage_chunk:
                emit_cc({"id": resp_id, "object": "chat.completion.chunk", "model": slug, "choices": [], "usage": cc["usage"]})
        elif caller_shape == "anthropic":
            msg = aa.to_anthropic_message(data, slug, billed_usage=billed_usage)
            ensure_anthropic_started(input_tokens=billed_usage.get("prompt_tokens", 0))
            # A fallback response is never streamed for real — the whole
            # thing is already known at once (this IS the complete
            # message, same as the non-stream path returns) — so unlike
            # the live thinking_delta()/text_delta() calls elsewhere,
            # this fires every content block in a tight, immediate
            # sequence rather than incrementally. Still spec-valid: even
            # a "fast-streamed" complete message still has to go through
            # real content_block_start/delta/stop events, just with no
            # meaningful delay between them.
            for block in msg["content"]:
                if block["type"] == "text" and block["text"]:
                    emit_raw(anthropic_state.text_delta(block["text"]))
                elif block["type"] == "tool_use":
                    emit_raw(anthropic_state.tool_use_block(block["id"], block["name"], json.dumps(block["input"])))
            # .finish() expects the RAW internal vocabulary
            # ("tool_calls"/"length"/"stop" — same as every other
            # finish_reason() call in this file) and does its own
            # Anthropic-shape translation internally, same table
            # to_anthropic_message() already used to build msg itself —
            # recompute it raw here rather than passing msg["stop_reason"]
            # back in, which is ALREADY translated and would silently
            # miss _STOP_REASON_MAP's lookup (its keys are the raw
            # vocabulary, not Anthropic's own values) and fall through to
            # the wrong default.
            has_calls = any(b["type"] == "tool_use" for b in msg["content"])
            emit_raw(anthropic_state.finish(ra.finish_reason(data, has_calls), msg["usage"]["output_tokens"], input_tokens=msg["usage"]["input_tokens"]))
        else:
            rebranded = ra.reshape(data, "responses", slug, billed_usage=billed_usage)
            emit_raw(f"event: response.completed\ndata: {json.dumps({'type': 'response.completed', 'response': rebranded})}\n\n")

    async def _consume_pass_attempt(pcfg: PassConfig, body: dict, *, relay_reasoning: bool, relay_content: bool, relay_lifecycle: bool, reasoning_sink=None, draft_text_sink=None, failover_ok: bool = False, prior_failure: str | None = None):
        """ONE attempt of consume_pass() below (which adds the hard ceiling
        and the silent mid-stream failover around it). `failover_ok`: may
        raise _ProviderFailover when the stream ends in a provider failure
        and nothing has reached the client yet. `prior_failure`: set on the
        re-run only; the first attempt's failure summary, kept in the error
        if this attempt fails too.

        Streams one upstream call (Chat Completions — OpenRouter as of
        2026-08-31; GLM/Z.ai direct follows the identical shape, see
        PassConfig.chat_completions_url) and relays SELECTED event types
        to the client per the flags above. Always returns the complete
        (data, has_sent_anything, final_event_type) regardless of what
        was relayed, since the caller needs the full output array either
        way (to build the critic body, or to compute final usage/text).

        No fine-grained lifecycle vocabulary exists on this wire shape
        (no response.output_item.added / response.content_part.added /
        etc. — Chat Completions only ever has content deltas,
        reasoning_content deltas, tool_calls deltas, and a terminal
        finish_reason), so relay_lifecycle has nothing extra to do here
        beyond what relay_reasoning/relay_content already relay below.
        Tool_calls deltas specifically are only relayed LIVE to a
        Chat-Completions-shaped caller (see that block's own comment for
        why no live equivalent exists to relay them AS to a
        Responses-shaped one) — either caller shape still gets the
        complete tool call, just a Responses-shaped caller only in the
        one terminal response.completed/incomplete event rather than
        incrementally. Content and reasoning deltas relay live to both
        caller shapes equally, no such gap. None of this affects a
        Chat-Completions-shaped caller either way, which is both the
        overwhelmingly common case and what this project's own frontend
        uses (src/lib/api.ts).

        reasoning_sink (added alongside app/thinking_summarizer.py): a
        plain callable, ThinkingRelay.feed(), fed with every raw
        reasoning_content delta as it arrives — completely independent
        of relay_reasoning above, which stays False for both passes and
        controls only VERBATIM raw relay (still off, see fix #2 in this
        module's own docstring). reasoning_sink never blocks this read
        loop; it just appends to a buffer a separate background task
        condenses into short titles on its own schedule — see that
        module for the full mechanism.

        This function used to also handle a literal Responses-API
        streaming shape (`event: response.*` / `data: {...}` framing,
        for DeepSeek/OpenAI upstream — every Aura Beta pass, and Kael
        Beta's own passes before 2026-08-30) as a second branch, selected
        on the now-removed PassConfig.upstream_shape. Removed on
        2026-09-08 along with the rest of that path once Aura Beta's
        deletion meant no PassConfig could select it anymore — see
        response_api.py's module docstring for the fuller history."""
        nonlocal chunks_from_upstream, chunks_sent_to_client, reasoning_char_count, client_answer_started

        sent_anything = False

        def _relay_content(text: str) -> None:
            """Shared by the live per-chunk relay below and the
            post-loop flush — one emission path so the three caller
            shapes (chat_completions/anthropic/responses) can't drift
            out of sync between the two call sites."""
            nonlocal chunks_sent_to_client, sent_anything, client_answer_started
            if not text:
                return
            client_answer_started = True
            thinking_relay.begin_answer()  # the real answer has started: no more thinking titles after this
            send_role_if_needed()
            if caller_shape == "chat_completions":
                emit_cc({"id": response_id, "object": "chat.completion.chunk", "model": slug_local, "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]})
            elif caller_shape == "anthropic":
                ensure_anthropic_started()
                emit_raw(anthropic_state.text_delta(text))
            else:
                emit_raw(f"event: response.output_text.delta\ndata: {json.dumps({'type': 'response.output_text.delta', 'delta': text})}\n\n")
            chunks_sent_to_client += 1
            sent_anything = True

        timeout = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)
        # started_relaying: true the moment ANYTHING (content, raw
        # reasoning, or a tool-call delta) has actually been relayed to
        # the client during the CURRENT connection attempt. Belt-and-
        # suspenders for the retry logic below: by construction,
        # httpx.ConnectError/ConnectTimeout can only be raised while
        # establishing the connection (client.stream()'s __aenter__),
        # strictly before resp.aiter_lines() ever yields a first line —
        # a connection that drops AFTER being established raises a
        # different exception class (ReadError/RemoteProtocolError/
        # ReadTimeout), never these two. So started_relaying should be
        # unreachably False every time the except clause below actually
        # fires. It's checked anyway, and retrying is refused if it's
        # ever somehow True, because being wrong about that would mean
        # re-sending a whole request whose first part the client already
        # received — silently duplicating content is a worse failure
        # mode than this defensive check ever being reached for nothing.
        #
        # acc and content_guard are (re)created at the top of EVERY
        # attempt, not once before the loop — caught on review
        # (2026-09-15): even though started_relaying's invariant above
        # means a retried attempt should never have sent anything to the
        # CLIENT, that alone doesn't guarantee `acc` (mutated
        # unconditionally on every chunk via accumulate_cc_chunk, line
        # below, regardless of whether that chunk was ever relayed) or
        # content_guard's internal buffer are still in a clean state —
        # a chunk that updated `acc` without ever setting
        # started_relaying (e.g. a reasoning chunk with no
        # reasoning_sink, or a content chunk content_guard.feed() chose
        # to hold back rather than release) would otherwise survive into
        # a retried attempt and get double-counted alongside that
        # attempt's own chunks. Resetting both fresh every attempt makes
        # this correct by construction instead of correct only if the
        # "can't happen after the loop starts" reasoning above is right
        # in every httpx version and edge case — cheap enough that
        # relying on that assumption instead isn't worth it.
        attempt = 0
        fallback_used = False
        while True:
            attempt += 1
            started_relaying = False
            acc = ra.new_cc_accumulator()
            content_guard = identity_guard.StreamIdentityGuard()
            # draft_text_sink (the thinking relay's feed_draft): the DRAFT pass's visible text,
            # minus its routing tag and scrubbed for identity leaks, reaches the summarizer so
            # a draft that writes its answer with little reasoning still gets real titles.
            # Fresh per attempt, same reason as acc/content_guard above.
            draft_tag_stripper = _LeadingTagStripper(boundary) if draft_text_sink is not None else None
            draft_text_guard = identity_guard.StreamIdentityGuard() if draft_text_sink is not None else None
            # Same for the raw reasoning that feeds the summarizer: it is never
            # shown to the client, but a title is written from it, and the draft
            # text (just above) was already guarded while the reasoning was not.
            reasoning_guard = identity_guard.StreamIdentityGuard() if reasoning_sink is not None else None
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("POST", pcfg.chat_completions_url, headers=_headers(pcfg.api_key), json=body) as resp:
                        if resp.status_code >= 400:
                            raw = await resp.aread()
                            err = _upstream_error(pcfg, resp.status_code, raw[:500].decode(errors="ignore"), ra.safe_json(resp))
                            # no-provider refusal: nothing ran, nothing was
                            # sent to the client yet -> one backup attempt
                            fb_body = None if fallback_used else _fallback_body(pcfg, body, err)
                            if fb_body is not None:
                                raise _NoProviderRetry(fb_body)
                            raise err
                        async for line in resp.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            payload = line[len("data:"):].strip()
                            if not payload or payload == "[DONE]":
                                continue
                            try:
                                chunk = json.loads(payload)
                            except json.JSONDecodeError:
                                continue
                            chunks_from_upstream += 1
                            acc = ra.accumulate_cc_chunk(acc, chunk)
                            choices = chunk.get("choices") or []
                            delta = (choices[0].get("delta") or {}) if choices else {}

                            # `reasoning_content` or OpenRouter's `reasoning` /
                            # `reasoning_details`, whichever this host sends.
                            reasoning_delta = ra.reasoning_text_from_delta(delta)
                            if reasoning_delta:
                                # Counted regardless of relay_reasoning (always
                                # False) or reasoning_sink being present — this is
                                # a trace metric of how much reasoning actually
                                # happened, not how much was relayed to the
                                # client in any form; the two are independent.
                                reasoning_char_count += len(reasoning_delta)
                                if reasoning_sink is not None:
                                    _safe_reasoning = reasoning_guard.feed(reasoning_delta)
                                    if _safe_reasoning:
                                        reasoning_sink(_safe_reasoning)
                            if relay_reasoning and reasoning_delta:
                                started_relaying = True
                                send_role_if_needed()
                                if caller_shape == "chat_completions":
                                    emit_cc({"id": response_id, "object": "chat.completion.chunk", "model": slug_local, "choices": [{"index": 0, "delta": {"reasoning_content": reasoning_delta}, "finish_reason": None}]})
                                else:
                                    emit_raw(f"event: response.reasoning_text.delta\ndata: {json.dumps({'type': 'response.reasoning_text.delta', 'delta': reasoning_delta})}\n\n")
                                chunks_sent_to_client += 1
                                sent_anything = True

                            content_delta = delta.get("content")
                            if reasoning_sink is not None and reasoning_guard is not None and (content_delta or delta.get("tool_calls")):
                                # Reasoning is over once the answer starts: release the
                                # guard's held-back tail NOW, so it reaches the summarizer
                                # before the answer text rather than after it.
                                _reasoning_tail = reasoning_guard.flush()
                                if _reasoning_tail:
                                    reasoning_sink(_reasoning_tail)
                            if draft_text_sink is not None and content_delta:
                                _sink_text = draft_text_guard.feed(draft_tag_stripper.feed(content_delta))
                                if _sink_text:
                                    draft_text_sink(_sink_text)
                            if relay_content and content_delta:
                                safe_delta = content_guard.feed(content_delta)
                                if safe_delta:
                                    started_relaying = True
                                    _relay_content(safe_delta)

                            # Bug fix (2026-08-31): this used to have no
                            # handling at all — a critic answer that chose to
                            # call a tool streamed NOTHING to a
                            # chat_completions-shaped caller (the common
                            # case): no live delta, and the final chunk this
                            # function's caller sends after the loop ends
                            # (_run_stream's success path) only ever carries
                            # an empty delta + finish_reason, never
                            # tool_calls. The client saw a stream that looked
                            # like it answered with nothing. Relayed here the
                            # same way content_delta is above: the raw
                            # `delta.tool_calls` fragment array passed
                            # through verbatim (index-keyed partial
                            # name/arguments, the same shape this app
                            # receives it in and any OpenAI-compatible client
                            # already knows how to accumulate itself), gated
                            # on relay_content since a tool call IS the
                            # answer, same category as content, not a
                            # separate concept — so the draft pass (always
                            # relay_content=False) still never leaks its own
                            # tool-call choice, exactly as it never leaked
                            # its own content.
                            #
                            # No live equivalent exists to relay this AS for
                            # a Responses-shaped caller on this wire shape —
                            # Chat Completions has nothing like
                            # response.function_call_arguments.delta to
                            # borrow, and synthesizing one risks failing a
                            # strict client's schema check on required
                            # fields (item_id, output_index, ...) this branch
                            # can't populate — same reasoning _heartbeat()'s
                            # own docstring gives for using response.ping
                            # rather than a half-populated real event type.
                            # Not a loss either way: cc_accumulator_to_
                            # responses_shape() below still assembles the
                            # complete tool call into `output`, which the one
                            # terminal response.completed/incomplete event a
                            # Responses-shaped caller gets already carries —
                            # only the live incremental relay is unavailable
                            # on this branch, same limitation already
                            # documented for relay_lifecycle above.
                            tool_call_deltas = delta.get("tool_calls")
                            if relay_content and tool_call_deltas and caller_shape == "chat_completions":
                                started_relaying = True
                                client_answer_started = True
                                thinking_relay.begin_answer()  # a tool call IS the real answer: no more thinking titles
                                send_role_if_needed()
                                emit_cc({"id": response_id, "object": "chat.completion.chunk", "model": slug_local, "choices": [{"index": 0, "delta": {"tool_calls": tool_call_deltas}, "finish_reason": None}]})
                                chunks_sent_to_client += 1
                                sent_anything = True
                break
            except _NoProviderRetry as r:
                body = r.body
                fallback_used = True
                attempt -= 1  # a backup attempt must not use up a connect retry
                continue
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                if started_relaying or attempt >= _CONNECT_RETRY_ATTEMPTS:
                    raise _PassCallError(502, f"upstream connection failed after {attempt} attempt(s) (mid_relay={started_relaying}): {str(e)[:400]}", {"error": {"message": "Could not complete the request — please retry.", "type": "server_error", "code": "upstream_unreachable"}})
                # Note on what ISN'T reset here: chunks_from_upstream/
                # chunks_sent_to_client (nonlocal, shared across both this
                # pass and the other one for the same request's trace
                # record) aren't rolled back on a retry the way acc/
                # content_guard above are. Left alone deliberately, not
                # missed: by the same "can't happen after the loop starts"
                # reasoning as those two, a retried attempt should never
                # have incremented them in the first place, so there's
                # nothing to roll back in practice — and unlike acc/
                # content_guard (customer-visible output, worth defending
                # even against a wrong assumption), these are internal
                # trace-only counters, where a phantom count in the
                # unreachable case would be a cosmetic debugging
                # inaccuracy, not a correctness bug a customer could ever
                # see. Not worth the real complexity of delta-tracking a
                # counter shared with the OTHER pass just to defend a
                # metrics field against an already-unreachable scenario.
                await asyncio.sleep(_CONNECT_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue
            except httpx.TimeoutException:
                # Same reasoning as _post_upstream's identical clause above
                # (see its docstring): whatever budget was left is gone
                # either way, and this specific exception type means we'd
                # already connected — never provably safe to retry.
                raise _PassCallError(504, "upstream timeout", {"error": {"message": "The request timed out.", "type": "server_error", "code": "upstream_timeout"}})
            except httpx.HTTPError as e:
                # Pre-existing gap fixed alongside the retry logic
                # (2026-09-15): before this, any httpx error here other
                # than a plain status code (a dropped connection mid-
                # stream, a protocol error) propagated as a raw,
                # unhandled httpx exception all the way up through
                # run_pipeline — not translated into a clean
                # _PassCallError the way _post_upstream's non-streaming
                # path already did. Same fix, same shape, applied here.
                raise _PassCallError(502, str(e)[:500], {"error": {"message": "Could not complete the request — please retry.", "type": "server_error", "code": "upstream_unreachable"}})
        # Only reached once the loop above has ended without raising —
        # i.e. the upstream stream completed normally. Deliberately not
        # in a try/finally: an exception anywhere in the loop (a
        # _PassCallError from a bad status, a network error) means this
        # whole pass failed, so whatever's still sitting in
        # content_guard's trailing buffer was never going to be shown to
        # the client anyway — relaying it here would mean emitting
        # orphaned content deltas after (or instead of) the error the
        # caller is about to raise, which is worse than just letting it
        # go unset. Flushing only matters, and only happens, on the path
        # where the response actually succeeded.
        #
        # Mid-stream failover (added 2026-10-09): the stream ended with a
        # provider failure (finish_reason "error" / an `error` chunk). If
        # nothing from THIS pass has reached the client, re-run it once on
        # the next-best host instead of failing: a draft never relays
        # anything, and a critic that has relayed nothing can still be
        # re-run cleanly. Checked BEFORE the tail flush below so a failed
        # attempt never emits anything. OpenRouter waives the charge for an
        # "error" finish, and `acc` is rebuilt per attempt, so nothing is
        # billed or counted twice.
        if failover_ok and not sent_anything:
            _probe = ra.cc_accumulator_to_responses_shape(acc)
            _fo = _failover_body(pcfg, body, _probe)
            if _fo is not None:
                _first = provider_routing.failed_pass_summary(_probe)
                print(provider_routing.describe_served_by("stream", pcfg.model, _probe.get("served_by"), _probe.get("usage")))
                print(provider_routing.failover_log_line(pcfg.model, _first, _fo[1]))
                raise _ProviderFailover(_fo[0], _first)
        if relay_content:
            final_delta = content_guard.flush()
            if final_delta:
                _relay_content(final_delta)
        if draft_text_sink is not None:
            _tail = draft_text_guard.feed(draft_tag_stripper.flush()) + draft_text_guard.flush()
            if _tail:
                draft_text_sink(_tail)
        if reasoning_sink is not None:
            _reasoning_tail = reasoning_guard.flush()
            if _reasoning_tail:
                reasoning_sink(_reasoning_tail)
        final_data = ra.cc_accumulator_to_responses_shape(acc)
        print(provider_routing.describe_served_by("stream", pcfg.model, final_data.get("served_by"), final_data.get("usage")))
        if final_data.get("status") == "failed":
            if prior_failure:
                print(provider_routing.failover_exhausted_log_line(pcfg.model, prior_failure, provider_routing.failed_pass_summary(final_data)))
            raise _failed_pass_error(final_data, prior_failure)
        final_event_type = "response.incomplete" if final_data.get("status") == "incomplete" else "response.completed"
        return final_data, sent_anything, final_event_type

    async def consume_pass(pcfg: PassConfig, body: dict, **kwargs):
        """One streamed pass under the hard ceiling, with ONE silent
        failover (added 2026-10-09). If the first attempt ends in a provider
        failure before anything reached the client, the pass is re-run once
        on the next-best host (the failed one goes in `provider.ignore`) and
        the caller never hears about the first failure. Only when that
        second attempt fails too does the failure surface (as the same
        _PassCallError a failed pass always raised).

        The ceiling applies to EACH attempt, not the pair: provider drops
        have been seen 80-315 s into a generation, so a shared 480 s budget
        would cut the re-run off before it could finish. A timeout is never
        failed over (see _post_upstream_once for why); it propagates as
        asyncio.TimeoutError exactly as before. Callers must NOT wrap this
        in their own wait_for."""
        try:
            return await asyncio.wait_for(_consume_pass_attempt(pcfg, body, failover_ok=True, **kwargs), timeout=GENERATION_HARD_CEILING_SECONDS)
        except _ProviderFailover as fo:
            retry = fo
        return await asyncio.wait_for(_consume_pass_attempt(pcfg, retry.body, failover_ok=False, prior_failure=retry.summary, **kwargs), timeout=GENERATION_HARD_CEILING_SECONDS)

    def _stream_stats() -> dict:
        """Counters for a trace row that ends in failure (added 2026-10-09:
        draft_failed() and the critic-failure rows used to leave
        chunks_from_upstream / reasoning_char_count at 0, hiding how far a
        failed run had got). Cumulative over every attempt of every pass of
        this request, including a silent failover re-run."""
        return dict(chunks_from_upstream=chunks_from_upstream, chunks_sent_to_client=chunks_sent_to_client, reasoning_char_count=reasoning_char_count, saw_reasoning=reasoning_char_count > 0)

    async def draft_failed(e: BaseException) -> None:
        """Terminal handling when the draft stage produced nothing at all
        (the single draft failed, or every one of a z tier's drafts did):
        log, trace, and tell the client. The caller then returns."""
        if isinstance(e, asyncio.TimeoutError):
            reason = f"draft pass hard ceiling ({GENERATION_HARD_CEILING_SECONDS:.0f}s) hit"
            await log_usage(product, draft.model, requestor=requestor, status="error", stream=True, error_message=reason)
            await update_chat_trace(trace_id, status="timeout", error_message=reason, duration_ms=int((time.monotonic() - started) * 1000), **_stream_stats())
            await emit_error("This is taking far longer than normal and was stopped. Please retry, maybe with a shorter prompt.")
            return
        await log_usage(product, draft.model, requestor=requestor, latency_ms=e.latency_ms, status="error", stream=True, error_message=e.log_message)
        await update_chat_trace(trace_id, status="upstream_error", upstream_status_code=e.http_status, error_message=e.log_message, duration_ms=int((time.monotonic() - started) * 1000), **_stream_stats())
        await emit_error((e.client_payload.get("error") or {}).get("message") or "The request to the upstream model failed.")

    z_info: dict = {}  # filled by draft_stage_z(): drafts fired / drafts that took part (trace only)

    async def draft_stage_single():
        """The ordinary one-draft stage, moved here unchanged. Returns
        (draft_data with the difficulty tag stripped, draft_usage_billed,
        difficulty), or None after draft_failed() has told the client."""
        draft_body = _draft_body(draft, product, input_items, tools, system_identity, stream=True, boundary=boundary)
        try:
            draft_data, _draft_sent_anything, _draft_final_evt_type = await consume_pass(draft, draft_body, relay_reasoning=False, relay_content=False, relay_lifecycle=False, reasoning_sink=thinking_relay.feed, draft_text_sink=thinking_relay.feed_draft)
        except (asyncio.TimeoutError, _PassCallError) as e:
            await draft_failed(e)
            return None

        draft_usage = ra.usage_from_responses(draft_data.get("usage") or {})
        # draft_usage is the RAW upstream figure (kept for reference);
        # draft_usage_billed is what billing, the caller AND the usage_logs row use, so the
        # dashboard (which prices usage_logs rows) can never disagree with what was charged.
        draft_usage_billed = ra.remove_injected_input(draft_usage, injected_total_tokens, injected_prefix_tokens)
        # See the identical comment in _nonstream_single_draft_stage() — same
        # required order (strip before deriving draft_text), same reason.
        draft_data, difficulty = ra.extract_difficulty_and_strip(draft_data, boundary)
        return draft_data, draft_usage_billed, difficulty

    async def draft_stage_z():
        """The z-tier stage (see the module docstring's "z tiers" section):
        draft_count concurrent drafts, then one fusor call when it is worth
        it. Same return contract as draft_stage_single(), so everything after
        it is shared. Raw content and reasoning are never relayed verbatim,
        same as the single draft; the thinking titles follow ONE draft at a
        time (_TitleLeader: the first to say anything, then, when it ends, the
        draft furthest along) so three concurrent reasoning streams never
        interleave into one feed."""
        titles = _TitleLeader(thinking_relay, draft_count)

        def _reasoning_sink(i: int):
            return lambda text: titles.reasoning(i, text)

        def _text_sink(i: int):
            return lambda text: titles.draft_text(i, text)

        async def _one(i: int) -> dict:
            body = _draft_body(draft, product, input_items, tools, system_identity, stream=True, boundary=boundary)
            try:
                data, _sent, _evt = await _retry_fast_transient(lambda: consume_pass(draft, body, relay_reasoning=False, relay_content=False, relay_lifecycle=False, reasoning_sink=_reasoning_sink(i), draft_text_sink=_text_sink(i)), label="draft")
            finally:
                titles.finished(i)  # returned, failed or cancelled: hand the titles on
            return data

        raw = await _gather_drafts([(lambda i=i: _one(i)) for i in range(draft_count)])
        results, failures = _digest_draft_results(raw, boundary, injected_total_tokens, injected_prefix_tokens)
        if not results:
            await draft_failed(failures[0])
            return None
        if failures:
            print(_lost_drafts_line(product, draft_count, results, failures))
        verdict, survivors = _plan_fusion(results, draft_count)
        z_info.update(fired=draft_count, survivors=len(survivors))

        if verdict == "empty":
            return results[0].data, results[0].usage_billed, "HARD"
        if verdict == "easy":
            pick = _pick_base(survivors)
            return pick.data, pick.usage_billed, "EASY"
        if verdict == "single":
            _note_degraded(product, draft_count, len(survivors), "reviewing the lone draft without fusion")
            return survivors[0].data, survivors[0].usage_billed, "HARD"

        base = survivors[0]  # billing's "first call": the same prompt in every draft
        thinking_relay.set_phase(PHASE_FUSING)
        await update_chat_trace(trace_id, status="fusor_started", draft_status=f"ok_x{len(survivors)}of{draft_count}")
        rendered = [_rendered(r) for r in survivors]
        fusor_body = _fusor_body(fusor, product, input_items, rendered, tools, system_identity, stream=True, fusion_boundary=fusion_boundary)
        try:
            fusor_data, _sent, _evt = await _retry_fast_transient(lambda: consume_pass(fusor, fusor_body, relay_reasoning=False, relay_content=False, relay_lifecycle=False, reasoning_sink=thinking_relay.feed), label="fusor")
        except (asyncio.TimeoutError, _PassCallError, httpx.HTTPError) as e:
            why = f"fusor pass hard ceiling ({GENERATION_HARD_CEILING_SECONDS:.0f}s) hit" if isinstance(e, asyncio.TimeoutError) else (e.log_message if isinstance(e, _PassCallError) else provider_routing.safe_exception_summary(e))
            fallback = _pick_base(survivors)
            print(f"[two_pass_pipeline] z DEGRADED ({product}): fusor failed, reviewing the consensus draft instead: {why}"[:400])
            return fallback.data, fallback.usage_billed, "HARD"
        fused = _fusion_outcome(fusor_data, base)
        if fused is None:
            fallback = _pick_base(survivors)
            print(f"[two_pass_pipeline] z DEGRADED ({product}): fusor returned nothing usable, reviewing the consensus draft instead")
            return fallback.data, fallback.usage_billed, "HARD"
        _note_degraded(product, draft_count, len(survivors), "fused the survivors")
        return fused[0], fused[1], "HARD"

    try:
        # ---- pass 1: draft — streamed upstream, raw content/reasoning
        # never relayed verbatim, but reasoning DOES feed thinking_relay
        # (see reasoning_sink= below and app/thinking_summarizer.py) ----
        # (raw reasoning relay turned off 2026-08-26 — see module
        # docstring fix #2. relay_reasoning stays a real parameter on
        # consume_pass, not deleted, so re-enabling raw relay for a
        # specific caller shape/product later is a one-line flip here,
        # not a rewrite — separate from reasoning_sink, which is always
        # on and unrelated to that flag.)
        stage = await (draft_stage_z() if fusor is not None else draft_stage_single())
        if stage is None:
            return  # draft_failed() already logged, traced and told the client
        draft_data, draft_usage_billed, difficulty = stage
        draft_text, draft_calls = ra.responses_output_text_and_calls(draft_data.get("output") or [])

        if draft_text is None and not draft_calls:
            latency_ms = int((time.monotonic() - started) * 1000)
            await log_usage(product, draft.model, requestor=requestor, latency_ms=latency_ms, status="success", stream=True, **draft_usage_billed)
            if product in config.BILLED_PRODUCTS:
                await billing.charge_for_request(requestor["user_id"], product, ra.client_usage(draft_usage_billed), None, at=request_started_at)
            await update_chat_trace(trace_id, status="done", draft_status=_z_status("skipped_empty", z_info), draft_finish_reason=ra.finish_reason(draft_data, False), content_char_count=0, duration_ms=latency_ms)
            await emit_fallback(draft_data, draft_usage_billed)
            return

        if difficulty == "EASY":
            # Difficulty routing (added 2026-09-13) — see the identical
            # branch (and its full comment) in _run_nonstream() above;
            # same reasoning applies here unchanged. emit_fallback() is
            # the SAME mechanism the empty-draft branch just above
            # already uses to serve a non-streamed draft as a
            # fake-streamed response — reused as-is here rather than
            # writing a second way to stream a draft-only answer to the
            # client. Draft content was never relayed live either way
            # (relay_content=False on the draft's own consume_pass()
            # call above — see this function's own module docstring), so
            # there is no "already-sent partial content" to reconcile
            # with what emit_fallback sends; this is exactly the same
            # situation the empty-draft branch is already in.
            latency_ms = int((time.monotonic() - started) * 1000)
            await log_usage(product, draft.model, requestor=requestor, latency_ms=latency_ms, status="success", stream=True, **draft_usage_billed)
            if product in config.BILLED_PRODUCTS:
                await billing.charge_for_request(requestor["user_id"], product, ra.client_usage(draft_usage_billed), None, at=request_started_at)
            await update_chat_trace(trace_id, status="done", draft_status=_z_status("skipped_easy", z_info), draft_finish_reason=ra.finish_reason(draft_data, bool(draft_calls)), content_char_count=len(draft_text or ""), content_preview=draft_text or "", duration_ms=latency_ms)
            await complete(draft_text)
            await emit_fallback(draft_data, draft_usage_billed)
            return

        await update_chat_trace(
            trace_id, status="critic_started",
            draft_status=_z_status("ok_tool_call" if draft_calls and not draft_text else ("ok_text_and_tool_call" if draft_calls else "ok_text"), z_info),
            draft_content_chars=len(draft_text or ""), draft_content_preview=draft_text or "", draft_finish_reason="stop",
        )

        # ---- pass 2: critic — content relayed live, raw reasoning still
        # only counted (never relayed verbatim) but also feeds
        # thinking_relay, same as pass 1 above — the same ThinkingRelay
        # instance, not a new one, which is what makes the transition
        # from draft to critic invisible in the thinking-title stream;
        # see app/thinking_summarizer.py ----
        critic_body = _critic_body(critic, product, input_items, draft_text, draft_calls, tools, system_identity, stream=True, boundary=boundary)
        thinking_relay.set_phase(PHASE_REVIEWING)
        try:
            critic_data, sent_content, critic_final_evt_type = await consume_pass(critic, critic_body, relay_reasoning=False, relay_content=True, relay_lifecycle=True, reasoning_sink=thinking_relay.feed)
        except asyncio.TimeoutError:
            latency_ms = int((time.monotonic() - started) * 1000)
            reason = f"critic pass hard ceiling ({GENERATION_HARD_CEILING_SECONDS:.0f}s) hit"
            if not client_answer_started:
                await log_usage(product, draft.model, requestor=requestor, latency_ms=latency_ms, status="success", stream=True, error_message=f"critic pass timed out, served draft: {reason}"[:500], **draft_usage_billed)
                if product in config.BILLED_PRODUCTS:
                    await billing.charge_for_request(requestor["user_id"], product, ra.client_usage(draft_usage_billed), None, at=request_started_at)
                await update_chat_trace(trace_id, status="done", upstream_status_code=None, error_message=f"critic pass timed out, served draft: {reason}"[:500], content_char_count=len(draft_text or ""), content_preview=draft_text or "", duration_ms=latency_ms, **_stream_stats())
                await complete(draft_text)
                await emit_fallback(draft_data, draft_usage_billed)
                return
            await log_usage(product, draft.model, requestor=requestor, status="error", stream=True, error_message=reason)
            await update_chat_trace(trace_id, status="timeout", error_message=reason, duration_ms=latency_ms, **_stream_stats())
            await emit_error("This is taking far longer than normal and was stopped partway through.")
            return
        except (_PassCallError, httpx.HTTPError) as e:
            is_pass_error = isinstance(e, _PassCallError)
            log_message = e.log_message if is_pass_error else provider_routing.safe_exception_summary(e)
            http_status = e.http_status if is_pass_error else None
            latency_ms = int((time.monotonic() - started) * 1000)
            if not client_answer_started:
                await log_usage(product, draft.model, requestor=requestor, latency_ms=latency_ms, status="success", stream=True, error_message=f"critic pass failed, served draft: {log_message}"[:500], **draft_usage_billed)
                if product in config.BILLED_PRODUCTS:
                    await billing.charge_for_request(requestor["user_id"], product, ra.client_usage(draft_usage_billed), None, at=request_started_at)
                await update_chat_trace(trace_id, status="done", upstream_status_code=http_status, error_message=f"critic pass failed, served draft: {log_message}"[:500], content_char_count=len(draft_text or ""), content_preview=draft_text or "", duration_ms=latency_ms, **_stream_stats())
                await complete(draft_text)
                await emit_fallback(draft_data, draft_usage_billed)
                return
            await log_usage(product, draft.model, requestor=requestor, status="error", stream=True, error_message=f"stream interrupted: {log_message}"[:500])
            await update_chat_trace(trace_id, status="interrupted", upstream_status_code=http_status, error_message=f"stream interrupted after the critic's answer had started: {log_message}"[:500], duration_ms=latency_ms, **_stream_stats())
            await emit_error("The connection to the upstream model was interrupted.")
            return
        except Exception as e:  # noqa: BLE001 — must never leave a trace
            # stuck at "critic_started" forever with no explanation, no
            # matter what goes wrong inside consume_pass() for the critic.
            latency_ms = int((time.monotonic() - started) * 1000)
            reason = f"unexpected error in critic pass: {provider_routing.safe_exception_summary(e)}"
            await log_usage(product, draft.model, requestor=requestor, status="error", stream=True, error_message=reason)
            await update_chat_trace(trace_id, status="interrupted", error_message=reason, duration_ms=latency_ms, **_stream_stats())
            await emit_error("Something went wrong generating this reply. Please retry.")
            return

        # ---- success ----
        latency_ms = int((time.monotonic() - started) * 1000)
        critic_usage = ra.usage_from_responses(critic_data.get("usage") or {})
        billed_usage = ra.billed_client_usage(draft_usage_billed, critic_usage)
        await log_usage(product, f"{draft.model}+{critic.model}", requestor=requestor, latency_ms=latency_ms, status="success", stream=True, **billed_usage)
        if product in config.BILLED_PRODUCTS:
            await billing.charge_for_request(requestor["user_id"], product, ra.client_usage(draft_usage_billed), ra.client_usage(critic_usage), at=request_started_at)
        final_text, final_calls = ra.responses_output_text_and_calls(critic_data.get("output") or [])
        await update_chat_trace(
            trace_id, status="done", chunks_from_upstream=chunks_from_upstream, chunks_sent_to_client=chunks_sent_to_client,
            saw_content=sent_content, saw_reasoning=reasoning_char_count > 0, reasoning_char_count=reasoning_char_count,
            finish_reason=ra.finish_reason(critic_data, bool(final_calls)),
            content_char_count=len(final_text or ""), content_preview=final_text or "", duration_ms=latency_ms,
        )
        await complete(final_text)
        # Drains thinking_relay FIRST, before any of the three terminal
        # emissions below — same race this module's own tests caught on
        # emit_error()/emit_fallback() above: content-delta relay during
        # the critic pass (text_delta()/reasoning_content chunks) already
        # happens live as consume_pass() reads each chunk, but a LAST
        # buffered-but-not-yet-flushed bit of critic reasoning (or,
        # rarely, still-in-flight draft reasoning on a very fast/short
        # response) could otherwise land in the queue after this
        # function's own finish_reason chunk / message_stop / response.
        # completed event, which is invalid on every caller_shape.
        # (complete() above already stopped it when there was a reply to
        # save; this covers the rest, and is a no-op the second time.)
        await thinking_relay.stop(flush_tail=False)
        if caller_shape == "chat_completions":
            emit_cc({"id": response_id, "object": "chat.completion.chunk", "model": slug_local, "choices": [{"index": 0, "delta": {}, "finish_reason": ra.finish_reason(critic_data, bool(final_calls))}]})
            if client_wants_usage_chunk:
                emit_cc({"id": response_id, "object": "chat.completion.chunk", "model": slug_local, "choices": [], "usage": ra.client_usage(billed_usage)})
        elif caller_shape == "anthropic":
            # Text content was already relayed live, incrementally, by
            # consume_pass()'s content_delta handling above (the
            # anthropic_state.text_delta() calls) — nothing to re-send
            # here. Tool calls were NOT relayed live (no caller_shape
            # gets that on this upstream except chat_completions — see
            # consume_pass()'s tool_call_deltas comment), so final_calls
            # (the complete, assembled calls) get their tool_use blocks
            # here, same "emitted whole, not incrementally" treatment
            # documented on AnthropicStreamState.tool_use_block().
            # ensure_anthropic_started() covers the one edge case where
            # NOTHING was relayed live at all before this point (a
            # critic response that is somehow only tool calls, with no
            # reasoning and no text before them — thinking_delta()/
            # text_delta() calls above would have already started it in
            # every other case).
            ensure_anthropic_started(input_tokens=billed_usage.get("prompt_tokens", 0))
            for call in final_calls:
                fn = call.get("function", {})
                emit_raw(anthropic_state.tool_use_block(call.get("id"), fn.get("name"), fn.get("arguments", "{}")))
            emit_raw(anthropic_state.finish(ra.finish_reason(critic_data, bool(final_calls)), billed_usage.get("completion_tokens", 0), input_tokens=billed_usage.get("prompt_tokens", 0)))
        else:
            # The one response.completed/incomplete event this stream ever
            # sends for a Responses-shaped caller — consume_pass()
            # deliberately withheld the raw one it saw from the critic
            # call (see that function's terminal-event branch) specifically
            # so this corrected version, with billed_usage in place of the
            # critic's own self-reported usage, is the only one a caller
            # sees.
            corrected = ra.reshape(critic_data, "responses", slug_local, billed_usage=billed_usage)
            emit_raw(f"event: {critic_final_evt_type}\ndata: {json.dumps({'type': critic_final_evt_type, 'response': corrected})}\n\n")
    except Exception as e:  # noqa: BLE001 — safety net for this function's
        # own bookkeeping calls (log_usage/billing/trace themselves raising),
        # same reasoning as _run_nonstream's callers getting a real
        # HTTPException — a background task has no caller to raise to, so
        # this must never surface as an unhandled task exception instead.
        print(f"[two_pass_pipeline] unexpected error in _run_stream ({product}): {type(e).__name__}: {e}")
        await emit_error("Something went wrong generating this reply. Please retry.")
    finally:
        # Nested so every step runs even if an earlier one raises: the stream
        # must always end (the None sentinel) and the caller's rate-limit slot
        # must always be released, whatever stop() did. Before this, a stop()
        # that raised skipped both: the response never closed and the slot
        # leaked.
        try:
            await thinking_relay.stop(flush_tail=False)
        except Exception as e:  # noqa: BLE001 — stop() is built not to raise; belt and braces
            print(f"[two_pass_pipeline] thinking_relay.stop() failed in cleanup ({product}): {type(e).__name__}: {e}")
        finally:
            try:
                if product in config.BILLED_PRODUCTS:
                    rate_limit.end_product_request(requestor["user_id"])
            finally:
                queue.put_nowait(None)
