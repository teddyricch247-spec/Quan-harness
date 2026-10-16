from . import kael

# Same model-key-to-prompt dispatch pattern as app/critic/__init__.py. The dict
# key is the model's key in config.PRODUCTS (its public slug), not the file name.
_PROMPTS = {
    "kael-beta": kael.ROUTER_PROMPT,
    "kael-pro-beta": kael.ROUTER_PROMPT,
}


def build_router_message(product: str, boundary: str) -> dict:
    """The single trailing `system` message appended to the DRAFT pass
    only (see two_pass_pipeline._draft_body(), the only caller) —
    instructs the draft model to classify the difficulty of the request
    it's about to answer, using the same per-request random tag boundary
    critic.build_critic_message() already uses for its own <draft_...>
    wrapper (see that function's docstring for the full tag-injection
    threat model this reuses, and app/router/kael.py's module docstring
    for why this prompt is draft-only, never sent to the critic pass).

    `boundary`: the SAME per-request secrets.token_hex() value
    two_pass_pipeline.run_pipeline() already generates once and threads
    through prepare_input_items()/build_critic_message() — reused here
    rather than generating a second, separate token, since a single
    per-request value is simpler to reason about and to find in a trace
    than several independent ones would be (see run_pipeline()'s own
    comment on generating it once)."""
    tag = f"task_difficulty_{boundary}"
    content = _PROMPTS[product].replace("{tag}", tag)
    return {"role": "system", "content": content}
