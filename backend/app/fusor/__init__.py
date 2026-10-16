from . import kael

# Dict key is the model's key in config.PRODUCTS (its public slug), same
# convention as app/critic/__init__.py. Only Kael Pro Beta has z tiers, so it is
# the only entry; asking for a fusor prompt for any other model is a KeyError.
_PROMPTS = {
    "kael-pro-beta": kael.FUSOR_PROMPT,
}


def build_fusor_message(product: str, drafts: list[str], boundary: str) -> dict:
    """The single trailing `system` message for the fusion (fourth) pass of
    a z tier — see fusor/kael.py's module docstring for what it asks the
    model to do and why. Mirrors critic.build_critic_message(): one
    plain system-role message, appended after the caller's original,
    unmodified payload, built by plain string replace (never str.format() —
    drafts are model output, very often code, so they can freely contain
    literal `{`/`}`).

    `drafts` is the already-rendered text of each surviving draft, in any
    order (response_api.render_draft_for_critic() turns a tool-call draft
    into a bracketed line first, same as for the critic). Each gets its own
    block, wrapped in `candidate_<boundary>_<n>` (n from 1). The numbers are
    labels only; the prompt tells the model they carry no ranking.

    `boundary` is a fresh token for the FUSION STEP only (two_pass_pipeline
    generates it with secrets.token_hex(), separately from the request-wide
    boundary the draft passes and the critic share). The request-wide one
    was visible to the draft passes inside <caller_system_prompt_...>, so a
    draft could in principle echo it into its own output and forge a
    closing tag; this one has never been in any earlier pass's context, so
    it cannot be echoed. A draft that contains a closing tag for a
    different token stays inert inside the real block.

    {count} is replaced first and {candidates} LAST, so draft text that
    happens to contain the literal text "{count}" is never rewritten."""
    blocks = []
    for n, text in enumerate(drafts, start=1):
        tag = f"candidate_{boundary}_{n}"
        blocks.append(f"<{tag}>\n{text}\n</{tag}>")
    content = (
        _PROMPTS[product]
        .replace("{count}", str(len(drafts)))
        .replace("{candidates}", "\n\n".join(blocks))
    )
    return {"role": "system", "content": content}
