from . import kael

# Dict key is the model's key in config.PRODUCTS (its public slug), not the file
# name. Both Kael models use the same critic prompt. (Aura Beta's own entry was
# removed with app/critic/aura.py; see backend/HISTORY.md.)
_PROMPTS = {
    "kael-beta": kael.CRITIC_PROMPT,
    "kael-pro-beta": kael.CRITIC_PROMPT,
}


def build_critic_message(product: str, draft_response: str, boundary: str) -> dict:
    """The single `system` message appended after the caller's original,
    unmodified payload for the critic (second) pass — used as-is for
    both a Chat-Completions caller and a Responses-shaped one (see
    two_pass_pipeline._critic_body(), the only caller): a plain
    system-role message is directly reusable as a Responses API `input`
    item the same way it's reusable as a Chat Completions `messages`
    item (confirmed: developers.openai.com's migrate-to-responses guide
    gives exactly this shape as its own reuse example), so no separate
    per-shape construction is needed here. (This used to be two
    functions — build_critic_message() and an alias,
    build_critic_message_responses(), kept separate specifically because
    the pass this fed could be either a literal Chat-Completions or a
    literal Responses-API UPSTREAM, back when that distinction existed
    — see two_pass_pipeline.py's module docstring for what changed on
    2026-09-08. Collapsed into one function once every upstream pass in
    this codebase spoke the same shape, which made the alias's entire
    reason for existing gone, not just unused.)

    draft_response is substituted in with a plain string replace, not
    str.format() — it's model-generated text (very often code), so it can
    freely contain literal `{`/`}` without needing any escaping.

    `boundary` (added 2026-09-13): a fresh, unpredictable-from-outside
    token for THIS call only — two_pass_pipeline.run_pipeline() generates
    one via secrets.token_hex() per request and threads it through both
    this function and response_api.prepare_input_items(), so the draft-
    wrapper tag and the caller-system-prompt wrapper tag are unique per
    request, never a fixed string an adversarial draft could predict and
    close early. See critic/kael.py's module docstring ("{tag} placeholder
    added 2026-09-13") for the full threat this closes. secrets, not
    random/uuid: this value only needs to be unguessable, not globally
    unique — secrets.token_hex() is the stdlib's own recommendation for
    exactly that (docs.python.org/3/library/secrets.html), unlike uuid4
    (unique but not documented as cryptographically unpredictable) or the
    random module (explicitly NOT suitable for anything security-facing,
    per its own docs)."""
    tag = f"draft_{boundary}"
    content = _PROMPTS[product].replace("{tag}", tag).replace("{draft_response}", draft_response)
    return {"role": "system", "content": content}
