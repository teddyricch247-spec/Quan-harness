"""§14.9 — the pure rules of the agent's browser: when it is offered, what it may be pointed at, what the model is shown."""
import pytest

from app.services import visual_qa_rules as r
from app.services import tool_schemas


def _avail(**kw):
    base = dict(server_enabled=True, runtime_available=True, vision_confirmed=True, model_label="x/y")
    return r.decide_browser_availability(**{**base, **kw})


# --- availability ----------------------------------------------------------------------------------------------------


def test_available_only_when_the_server_the_runtime_and_the_model_all_say_yes():
    assert _avail().available and _avail().code == "ok" and not _avail().surface_error
    assert not _avail(server_enabled=False).available
    assert not _avail(runtime_available=False).available
    assert not _avail(vision_confirmed=False).available


def test_the_first_failing_condition_decides_the_reason_in_a_fixed_order():
    assert _avail(server_enabled=False, runtime_available=False, vision_confirmed=False).code == "server_off"
    assert _avail(runtime_available=False, vision_confirmed=False).code == "runtime_missing"
    assert _avail(vision_confirmed=False).code == "no_vision"


def test_a_server_that_has_the_browser_off_is_not_an_error_shown_to_anyone_but_the_others_are():
    assert _avail(server_enabled=False).surface_error is False
    for kw in ({"runtime_available": False}, {"vision_confirmed": False}):
        assert _avail(**kw).surface_error is True


def test_every_unavailable_state_tells_the_model_not_to_claim_a_visual_check_and_the_person_how_to_fix_it():
    for a in (_avail(server_enabled=False), _avail(runtime_available=False), _avail(vision_confirmed=False), r.vision_rejected_availability("x/y")):
        assert "do not claim" in a.model_notice and "visually" in a.model_notice
        assert a.reason and not a.available
    assert "x/y" in _avail(vision_confirmed=False).reason and "AGENT_VISION_MODELS" in _avail(vision_confirmed=False).reason
    assert "x/y" in r.vision_rejected_availability("x/y").reason


def test_the_prompt_notice_exists_only_when_the_browser_does_not():
    assert r.format_visual_qa_notice(_avail()) is None
    assert "no browser tools" in r.format_visual_qa_notice(_avail(vision_confirmed=False))


# --- parameters ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/about", "/search?q=a b", "/a/b#top", "/%2e%2e/x"])
def test_ordinary_paths_pass_through(path):
    assert r.normalize_path(path) == path


@pytest.mark.parametrize("bad", [
    "", "   ", None, 5, "about", "//evil.example.com/x", "https://evil.example.com/", "http://127.0.0.1/", "javascript:alert(1)",
    "file:///etc/passwd", "/a\\b", "/a\nb", "/a\x00b", "/" + "x" * 3000, "\\\\host\\share",
])
def test_anything_that_is_not_a_path_on_the_previews_own_origin_is_refused(bad):
    with pytest.raises(ValueError):
        r.normalize_path(bad)


def test_selector_and_text_limits():
    assert r.clean_selector("  button.go ") == "button.go"
    for bad in ("", "  ", None, "x" * 600):
        with pytest.raises(ValueError):
            r.clean_selector(bad)
    assert r.clean_typed_text("hello") == "hello" and r.clean_typed_text("") == ""
    with pytest.raises(ValueError):
        r.clean_typed_text("x" * 5000)
    with pytest.raises(ValueError):
        r.clean_typed_text(None)


# --- the allow-list --------------------------------------------------------------------------------------------------


FORBIDDEN = [".sprites.app", "preview.example.com", "api.myapp.dev"]


def test_operator_hosts_are_accepted_as_exact_hosts_or_one_level_wildcards():
    ok, bad = r.parse_allowed_hosts_setting("api.example.org, *.supabase.co ,API.Stripe.com", FORBIDDEN)
    assert ok == ["api.example.org", "*.supabase.co", "api.stripe.com"] and bad == []


@pytest.mark.parametrize("entry", [
    "127.0.0.1", "10.0.0.5", "[::1]", "169.254.169.254", "localhost", "foo.localhost", "intranet", "*", "*.com", "*.*.x.com",
    "https://a.example.org", "a.example.org:8080", "a.example.org/path", "user@a.example.org", "a b.example.org",
    "x.sprites.app", "*.sprites.app", "preview.example.com", "foo.preview.example.com", "api.myapp.dev", "-bad-.example.org",
])
def test_dangerous_or_malformed_entries_are_rejected_not_silently_widened(entry):
    ok, bad = r.parse_allowed_hosts_setting(entry, FORBIDDEN)
    assert ok == [] and len(bad) == 1 and bad[0][1]


def test_a_wildcard_over_a_forbidden_domain_is_rejected_too():
    ok, bad = r.parse_allowed_hosts_setting("*.example.com", ["preview.example.com"])        # would cover preview.example.com
    assert ok == [] and bad


def test_host_matching():
    pats = ["api.example.org", "*.supabase.co"]
    assert r.host_matches("api.example.org", pats) and r.host_matches("abc.supabase.co", pats) and r.host_matches("A.B.supabase.co", pats)
    assert not r.host_matches("supabase.co", pats)                     # a wildcard is the subdomains, not the apex
    assert not r.host_matches("evilapi.example.org", pats) and not r.host_matches("api.example.org.evil.com", pats)
    assert not r.host_matches("", pats)


def test_the_proxy_bypass_names_only_allowed_hosts_and_removes_chromiums_loopback_exemption():
    s = r.chromium_proxy_bypass(["abc.sprites.app", "fonts.googleapis.com", "abc.sprites.app", "*.supabase.co"])
    assert s.split(",") == ["abc.sprites.app", "fonts.googleapis.com", "*.supabase.co", "<-loopback>"]
    assert r.chromium_proxy_bypass([]) == "<-loopback>"


ORIGIN = "https://abc.sprites.app"


@pytest.mark.parametrize("url,expected", [
    ("https://abc.sprites.app/x?y=1", True),
    ("https://abc.sprites.app:443/", True),
    ("http://abc.sprites.app/", False),                    # a different scheme is a different origin: the token never goes over http
    ("https://abc.sprites.app:8443/", False),
    ("https://other.sprites.app/", False),                 # another project's Sprite
    ("https://fonts.googleapis.com/css", True),
    ("https://evil.example.com/", False),
    ("http://127.0.0.1:8000/", False), ("http://localhost/", False), ("http://169.254.169.254/latest/meta-data", False),
    ("file:///etc/passwd", False), ("ftp://x.com/", False), ("chrome://settings", False),
    ("data:text/plain;base64,AAAA", True), ("blob:https://abc.sprites.app/uuid", True), ("about:blank", True),
])
def test_request_allowed(url, expected):
    assert r.request_allowed(url, ORIGIN, r.DEFAULT_ALLOWED_CDN_HOSTS) is expected


def test_the_default_hosts_are_the_documented_font_and_script_cdns_only():
    assert set(r.DEFAULT_ALLOWED_CDN_HOSTS) == {
        "fonts.googleapis.com", "fonts.gstatic.com", "cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com", "cdn.tailwindcss.com", "code.jquery.com",
    }


def test_same_origin_compares_scheme_host_and_port():
    assert r.same_origin("https://a.x.app/p", "https://a.x.app") and not r.same_origin("https://a.x.app:444/", "https://a.x.app")
    assert not r.same_origin("not a url", "https://a.x.app") and r.origin_parts("data:x") is None


# --- what the model sees ---------------------------------------------------------------------------------------------


def test_console_output_is_bounded_newest_last_and_says_what_was_dropped():
    assert "No console output" in r.format_console([])
    out = r.format_console([{"type": "error", "text": "boom"}, {"type": "log", "text": "hi"}])
    assert out.splitlines() == ["[error] boom", "[log] hi"]
    many = [{"type": "log", "text": f"line {i}"} for i in range(200)]
    out = r.format_console(many)
    assert "(140 earlier entries omitted)" in out and "line 199" in out and "line 0\n" not in out
    assert len(r.format_console([{"type": "error", "text": "x" * 5000}])) < 700
    assert len(r.format_console([{"type": "log", "text": "y" * 400}] * 60)) <= r.MAX_CONSOLE_CHARS + 100


def test_screenshots_keep_only_the_most_recent_few_per_session_and_are_isolated_per_session():
    s = r.ScreenshotStore()
    for i in range(1, 7):
        s.put("A", i, f"data:A{i}")
    s.put("B", 100, "data:B")
    assert list(s.for_session("A")) == [4, 5, 6] and s.for_session("B") == {100: "data:B"}
    assert s.for_session("nobody") == {}
    s.drop_session("A")
    assert s.for_session("A") == {} and s.for_session("B")


def test_the_store_bounds_how_many_sessions_it_remembers():
    s = r.ScreenshotStore()
    for i in range(r.MAX_SESSIONS_HELD + 10):
        s.put(f"s{i}", 1, "d")
    assert s.for_session("s0") == {} and s.for_session(f"s{r.MAX_SESSIONS_HELD + 9}") == {1: "d"}
    s.put("s10", 2, "d")                                      # touching a session keeps it
    for i in range(1000, 1000 + r.MAX_SESSIONS_HELD - 1):
        s.put(f"t{i}", 1, "d")
    assert s.for_session("s10")


def test_the_five_browser_tools_match_the_spec_and_take_no_url():
    names = [t["name"] for t in tool_schemas.BROWSER_TOOL_SCHEMAS]
    assert names == ["browser_navigate", "browser_click", "browser_type", "browser_screenshot", "browser_get_console_logs"]
    assert tool_schemas.BROWSER_TOOL_SCHEMAS[0]["input_schema"]["required"] == ["path"]
