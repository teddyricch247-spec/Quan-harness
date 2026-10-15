"""§23.7 — the Live Preview proxy's pure rules. See app/services/preview_rules.py."""
from app.services import preview_rules as r

BASE = "preview.example.com"
PUB = "https://my-app-1a2b3c4d.preview.example.com"


# ---- subdomains & host classification --------------------------------------

def test_new_subdomain_is_a_valid_dns_label_and_matches_the_db_check():
    sub = r.new_subdomain("My Cool App!! (v2)", "1a2b3c4d5e6f7788")
    assert sub == "my-cool-app-v2-1a2b3c4d"
    assert r.is_valid_subdomain(sub) and len(sub) <= 42


def test_new_subdomain_falls_back_when_name_has_no_usable_characters():
    sub = r.new_subdomain("日本語", "abcdef0123456789")
    assert sub == "p-abcdef012345" and r.is_valid_subdomain(sub)


def test_long_names_are_truncated_to_a_valid_label():
    sub = r.new_subdomain("a" * 200, "1a2b3c4d")
    assert r.is_valid_subdomain(sub) and len(sub) <= 42


def test_classify_host_recognises_a_preview_host_ignoring_port_and_case():
    assert r.classify_host("My-App-1a2b3c4d.Preview.Example.com:443", BASE) == ("preview", "my-app-1a2b3c4d")


def test_classify_host_other_hosts_are_not_ours():
    assert r.classify_host("api.example.com", BASE) == ("other", None)
    assert r.classify_host("quan-harness.onrender.com", BASE) == ("other", None)
    assert r.classify_host("evilpreview.example.com", BASE) == ("other", None)  # suffix match must be on a dot boundary
    assert r.classify_host(None, BASE) == ("other", None)


def test_malformed_hosts_under_the_preview_domain_never_fall_through_to_the_api():
    # The wildcard DNS points at the same backend as the API: these MUST be
    # answered by the proxy (404), never passed to the API's own routes.
    assert r.classify_host("a.b.preview.example.com", BASE) == ("preview_invalid", None)
    assert r.classify_host("-bad.preview.example.com", BASE) == ("preview_invalid", None)
    assert r.classify_host("preview.example.com", BASE) == ("preview_invalid", None)
    assert r.classify_host("UPPER_score.preview.example.com", BASE) == ("preview_invalid", None)


def test_empty_base_domain_disables_classification():
    assert r.classify_host("x.preview.example.com", "") == ("other", None)


def test_ipv6_literal_is_never_a_preview_host():
    assert r.classify_host("[::1]:8000", BASE) == ("other", None)


# ---- upstream validation (the Sprites token must only go to Sprites hosts) ---

def test_valid_sprite_url_is_accepted_and_normalised():
    assert r.validate_upstream_origin("https://qh-abc-org1.sprites.app/some/path?x=1", ".sprites.app") == "https://qh-abc-org1.sprites.app"


def test_upstream_must_be_https():
    try:
        r.validate_upstream_origin("http://x.sprites.app", ".sprites.app")
    except ValueError:
        return
    raise AssertionError


def test_upstream_host_must_be_under_the_suffix_on_a_dot_boundary():
    for bad in ("https://evil.com", "https://sprites.app.evil.com", "https://notsprites.app", "https://sprites.app"):
        try:
            r.validate_upstream_origin(bad, ".sprites.app")
        except ValueError:
            continue
        raise AssertionError(bad)


def test_upstream_with_credentials_or_odd_port_is_rejected():
    for bad in ("https://u:p@x.sprites.app", "https://x.sprites.app:8443"):
        try:
            r.validate_upstream_origin(bad, ".sprites.app")
        except ValueError:
            continue
        raise AssertionError(bad)


def test_websocket_url_uses_wss_and_keeps_the_query():
    assert r.websocket_upstream_url("https://x.sprites.app", "/ws", "a=1") == "wss://x.sprites.app/ws?a=1"
    assert r.websocket_upstream_url("https://x.sprites.app", "", "") == "wss://x.sprites.app/"


# ---- request headers --------------------------------------------------------

def test_request_filter_drops_authorization_host_hop_by_hop_and_spoofable_forwarding():
    hdrs = [
        ("Host", "x.preview.example.com"), ("Authorization", "Bearer user-token"), ("Connection", "keep-alive, X-Custom"),
        ("X-Custom", "gone"), ("Keep-Alive", "timeout=5"), ("X-Forwarded-Host", "attacker.com"), ("X-Forwarded-For", "1.2.3.4"),
        ("Accept", "text/html"), ("User-Agent", "ua"),
    ]
    names = {n.lower() for n, _ in r.filter_request_headers(hdrs)}
    assert names == {"accept", "user-agent"}


def test_request_filter_removes_only_the_harness_cookie():
    out = dict(r.filter_request_headers([("Cookie", "qh_preview=SECRETJWT; sid=abc; theme=dark")]))
    assert out["Cookie"] == "sid=abc; theme=dark"
    assert "qh_preview" not in out["Cookie"]


def test_request_filter_drops_cookie_header_when_only_harness_cookie_present():
    assert r.filter_request_headers([("Cookie", "qh_preview=x")]) == []


def test_read_cookie_finds_the_harness_cookie():
    assert r.read_cookie("a=1; qh_preview=tok; b=2") == "tok"
    assert r.read_cookie("a=1") is None and r.read_cookie(None) is None


def test_forwarded_headers_tell_the_app_its_public_host():
    assert dict(r.forwarded_headers("x.preview.example.com")) == {"X-Forwarded-Host": "x.preview.example.com", "X-Forwarded-Proto": "https"}


# ---- response headers -------------------------------------------------------

def _sanitize(headers, ancestors=("https://app.example.com",)):
    return r.sanitize_response_headers(headers, upstream_hostname="qh-abc.sprites.app", public_origin_value=PUB, frame_ancestors=list(ancestors))


def test_set_cookie_domain_is_stripped_so_an_app_cannot_toss_cookies_onto_siblings():
    out = _sanitize([("Set-Cookie", "sid=1; Domain=.preview.example.com; Path=/; HttpOnly")])
    cookie = next(v for n, v in out if n.lower() == "set-cookie")
    assert "domain" not in cookie.lower()
    assert "HttpOnly" in cookie and "Path=/" in cookie


def test_set_cookie_is_rewritten_to_work_inside_a_cross_site_iframe_over_https():
    out = _sanitize([("Set-Cookie", "sid=1; SameSite=Lax; Secure")])
    cookie = next(v for n, v in out if n.lower() == "set-cookie")
    assert "SameSite=Lax" not in cookie
    assert cookie.count("Secure") == 1 and "SameSite=None" in cookie and "Partitioned" in cookie


def test_app_cannot_overwrite_the_harness_session_cookie():
    out = _sanitize([("Set-Cookie", "qh_preview=forged; Path=/"), ("Set-Cookie", "ok=1")])
    cookies = [v for n, v in out if n.lower() == "set-cookie"]
    assert len(cookies) == 1 and cookies[0].startswith("ok=1")


def test_plain_http_preview_keeps_samesite_untouched_but_still_strips_domain():
    out = r.sanitize_response_headers(
        [("Set-Cookie", "sid=1; Domain=x.test; SameSite=Lax")], upstream_hostname="u.sprites.app",
        public_origin_value="http://localhost:8000", frame_ancestors=[])
    cookie = next(v for n, v in out if n.lower() == "set-cookie")
    assert "domain" not in cookie.lower() and "SameSite=Lax" in cookie and "Partitioned" not in cookie


def test_x_frame_options_removed_and_frame_ancestors_replaced_with_the_harness_frontend_only():
    out = _sanitize([("X-Frame-Options", "DENY"), ("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")])
    assert not any(n.lower() == "x-frame-options" for n, _ in out)
    csps = [v for n, v in out if n.lower() == "content-security-policy"]
    assert "default-src 'self'" in csps[0] and "frame-ancestors" not in csps[0]  # app's own policy kept, its frame-ancestors dropped
    assert csps[-1] == "frame-ancestors https://app.example.com"


def test_frame_ancestors_is_none_when_no_frontend_origin_is_known():
    out = _sanitize([], ancestors=())
    assert ("Content-Security-Policy", "frame-ancestors 'none'") in out


def test_csp_that_is_only_frame_ancestors_is_dropped_not_left_empty():
    out = _sanitize([("Content-Security-Policy", "frame-ancestors 'self'")])
    csps = [v for n, v in out if n.lower() == "content-security-policy"]
    assert csps == ["frame-ancestors https://app.example.com"]


def test_location_pointing_at_the_internal_sprite_url_is_rewritten_to_the_public_origin():
    out = _sanitize([("Location", "https://qh-abc.sprites.app/dashboard?x=1#top")])
    assert ("Location", f"{PUB}/dashboard?x=1#top") in out


def test_relative_and_external_locations_are_left_alone():
    out = _sanitize([("Location", "/login"), ("Content-Location", "https://other.example.org/x")])
    assert ("Location", "/login") in out and ("Content-Location", "https://other.example.org/x") in out


def test_response_gets_noindex_and_loses_hop_by_hop_headers():
    out = _sanitize([("Transfer-Encoding", "chunked"), ("Connection", "close"), ("Content-Type", "text/html")])
    names = {n.lower() for n, _ in out}
    assert "transfer-encoding" not in names and "connection" not in names and "content-type" in names
    assert ("X-Robots-Tag", "noindex, nofollow") in out


def test_frame_ancestor_sources_normalises_and_drops_junk():
    assert r.frame_ancestor_sources(["https://app.example.com/path", "http://localhost:3000", "*", "garbage", "https://app.example.com"]) == [
        "https://app.example.com", "http://localhost:3000"]


def test_session_cookie_attributes():
    https = r.build_session_cookie("tok", 3600, secure=True)
    assert "HttpOnly" in https and "Secure" in https and "SameSite=None" in https and "Partitioned" in https and "Domain" not in https
    assert "Secure" not in r.build_session_cookie("tok", 3600, secure=False)


# ---- retry / backoff --------------------------------------------------------

def test_only_safe_methods_are_retried():
    assert r.is_retryable("GET", 502) and r.is_retryable("head", 503) and r.is_retryable("GET", None, connect_error=True)
    assert not r.is_retryable("POST", 502) and not r.is_retryable("GET", 404) and not r.is_retryable("PUT", None, connect_error=True)


def test_backoff_is_bounded_by_the_total_budget():
    delays = r.backoff_delays(20)
    assert abs(sum(delays) - 20) < 1e-9 and max(delays) <= 6.0 and delays[0] == 0.5
    assert r.backoff_delays(0) == []


def test_error_page_escapes_html():
    page = r.error_page_html("<b>x</b>", "a & <script>", refresh_seconds=3)
    assert "<script>" not in page and "&lt;script&gt;" in page and 'http-equiv="refresh" content="3"' in page
