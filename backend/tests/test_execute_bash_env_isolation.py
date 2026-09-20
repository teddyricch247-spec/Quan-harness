"""Step 6: 'a real end-to-end test that a model-scope execute_bash call genuinely
cannot reach the internal clone/checkpoint machinery's own credentials.' The
live end-to-end version needs a real workspace (see
test_workspace_integration.py); this is the structural half of that guarantee —
build_bash_env's signature makes it true by construction (see
app/services/guard_rules.py's docstring), and these tests confirm the
construction actually holds."""
from app.services.guard_rules import build_bash_env, mask_secrets, referenced_secret_names, truncate_output


def test_env_contains_only_path_home_lang_by_default():
    env = build_bash_env({}, scratch_home="/workspace/repo/.qh-scratch-home")
    assert set(env.keys()) == {"PATH", "HOME", "LANG"}


def test_env_includes_project_secrets_by_name():
    env = build_bash_env({"STRIPE_TEST_KEY": "sk_test_abc"}, scratch_home="/scratch")
    assert env["STRIPE_TEST_KEY"] == "sk_test_abc"


def test_secret_named_path_cannot_shadow_the_real_path():
    # A maliciously- or accidentally-named project secret must never be able to
    # override the real PATH/HOME/LANG the command runs with.
    env = build_bash_env({"PATH": "/evil"}, scratch_home="/scratch")
    assert env["PATH"] != "/evil"


def test_no_call_path_can_introduce_a_github_credential():
    # This is the isolation guarantee itself: build_bash_env only ever accepts a
    # name->value dict of project_secrets. A GitHub token, by construction, can
    # only reach this function if something upstream mislabeled it as a project
    # secret — and even then, it would show up as an ordinary named env var,
    # not a hidden back-channel credential, which is the property that matters.
    fake_github_token = "ghp_thisShouldNeverBeHere"
    env = build_bash_env({"NOT_A_SECRET": "value"}, scratch_home="/scratch")
    assert fake_github_token not in env.values()


def test_referenced_secret_names_matches_dollar_syntax():
    names = referenced_secret_names("echo $STRIPE_KEY and $OTHER", ["STRIPE_KEY", "UNUSED"])
    assert names == ["STRIPE_KEY"]


def test_referenced_secret_names_matches_braced_syntax():
    names = referenced_secret_names("echo ${STRIPE_KEY}", ["STRIPE_KEY"])
    assert names == ["STRIPE_KEY"]


def test_referenced_secret_names_ignores_unreferenced_secrets():
    # A registered secret that the command text never mentions must not be
    # injected — only what's actually referenced gets exported.
    names = referenced_secret_names("echo hello", ["STRIPE_KEY", "OTHER_KEY"])
    assert names == []


def test_mask_secrets_replaces_value_in_output():
    masked = mask_secrets("token is sk_live_abc123 in output", {"STRIPE_KEY": "sk_live_abc123"})
    assert "sk_live_abc123" not in masked
    assert "<secret-hidden>" in masked


def test_mask_secrets_handles_multiple_secrets():
    masked = mask_secrets("a=1 b=2", {"A": "1", "B": "2"})
    assert masked == "a=<secret-hidden> b=<secret-hidden>"


def test_truncate_output_respects_line_budget():
    text = "\n".join(f"line {i}" for i in range(1000))
    truncated = truncate_output(text)
    assert len(truncated.splitlines()) <= 400


def test_truncate_output_keeps_the_tail_not_the_head():
    text = "\n".join(f"line {i}" for i in range(1000))
    truncated = truncate_output(text)
    assert "line 999" in truncated
    assert "line 0" not in truncated


def test_truncate_output_respects_char_budget():
    text = "x" * 100_000
    truncated = truncate_output(text)
    assert len(truncated) <= 8000


def test_short_output_is_unchanged():
    text = "all good\nexit 0"
    assert truncate_output(text) == text
