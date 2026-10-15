"""§23.10 — preview secret values must not survive the boundaries they cross.
Pure; see app/services/secret_redaction.py."""
import base64
import urllib.parse

from app.services.secret_redaction import REDACTED, redact, redactable_values

KEY = "sk_live_abcDEF123456"


def test_exact_value_is_redacted():
    assert redact(f"token={KEY} ok", {"STRIPE_KEY": KEY}) == f"token={REDACTED} ok"


def test_url_encoded_and_base64_forms_are_redacted_too():
    value = "p@ss word/1234"
    text = f"a={urllib.parse.quote(value, safe='')} b={base64.b64encode(value.encode()).decode()} c={value}"
    out = redact(text, {"X": value})
    assert value not in out
    assert urllib.parse.quote(value, safe="") not in out
    assert base64.b64encode(value.encode()).decode() not in out
    assert out.count(REDACTED) == 3


def test_short_values_are_left_alone_so_logs_stay_readable():
    assert redact("count is 1 and 12", {"A": "1", "B": "12"}) == "count is 1 and 12"


def test_trivial_words_are_not_redacted_even_when_long_enough():
    # A person putting NODE_ENV=production in the panel must not turn every
    # "production" in a log into <secret-hidden>.
    assert redact("running in production mode", {"NODE_ENV": "production"}) == "running in production mode"
    assert redact("TRUE is not secret", {"FLAG": "True"}) == "TRUE is not secret"


def test_longest_value_wins_over_a_value_it_contains():
    out = redact("a=abcd1234xyz b=abcd1234", {"SHORT": "abcd1234", "LONG": "abcd1234xyz"})
    assert out == f"a={REDACTED} b={REDACTED}"


def test_empty_and_none_text_pass_through():
    assert redact("", {"A": KEY}) == ""
    assert redact(None, {"A": KEY}) is None


def test_accepts_a_plain_list_of_values_as_well_as_a_dict():
    assert redact(f"x {KEY}", [KEY]) == f"x {REDACTED}"
    assert KEY in redactable_values({"A": KEY})


def test_no_secrets_means_text_is_untouched():
    assert redact("nothing to hide", {}) == "nothing to hide"
