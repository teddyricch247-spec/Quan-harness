"""
A real tokenizer for every provider this system can be pointed at (§7: any
Anthropic/OpenAI/Google/OpenRouter/custom-endpoint model) would mean bundling
several incompatible tokenizer packages, none of which is guaranteed correct
for a `custom` provider's actual model anyway. Every current caller of this
(§17's 70%-of-context-window compaction trigger, §17's repo-map token budget)
only needs an estimate that's directionally right and cheap to compute, not
provider-exact — both are deliberately conservative triggers already (compact
at 70%, not 100%; the repo map degrades gracefully rather than hard-failing if
under-counted). The ~4-characters-per-token heuristic is the same rough
approximation most of these tokenizers land near for English text and code.

Same "honest fallback over an unverified heavy dependency" reasoning Phase 2
applied to tree-sitter (see /docs/PHASE2_NOTES.md) — install `tiktoken` (or a
provider-specific tokenizer selected by `llm_credentials.provider`) and swap
it in here if per-provider exactness ever matters more than this estimate's
simplicity.
"""

_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)
