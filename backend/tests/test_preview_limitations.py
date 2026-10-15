"""§23.8 — known preview limitations. See app/services/preview_limitations.py."""
from app.services import preview_limitations as pl
from app.services.preview_limitations import GuidanceContext

ORIGIN = "https://my-app-1a2b3c4d.preview.example.com"


# ---- classification ---------------------------------------------------------

def test_classifies_each_known_environment_kind():
    assert pl.classify_environment_issue("Error: Cannot connect to the Docker daemon at unix:///var/run/docker.sock") == "nested_container"
    assert pl.classify_environment_issue("Access to fetch at 'https://api.x.com' blocked by CORS policy") == "cors"
    assert pl.classify_environment_issue("Error 400: redirect_uri_mismatch") == "oauth"
    assert pl.classify_environment_issue("Error: connect ECONNREFUSED 127.0.0.1:5432") == "database"
    assert pl.classify_environment_issue("Can't reach database server at `db.example.com:5432` (P1001)") == "database"
    assert pl.classify_environment_issue("Error: Missing required environment variable STRIPE_SECRET_KEY") == "secrets"
    assert pl.classify_environment_issue("KeyError: 'DATABASE_URL'") == "secrets"


def test_ordinary_code_errors_are_not_classified_as_environment():
    for text in ("SyntaxError: Unexpected token", "ModuleNotFoundError: No module named 'flask'",
                 "TypeError: undefined is not a function", "error TS2304: Cannot find name 'foo'", "", None):
        assert pl.classify_environment_issue(text) is None, text


def test_lowercase_words_that_merely_end_in_key_or_token_are_not_secrets():
    # Regression: the name part of the "VAR_KEY is required" pattern was
    # case-insensitive, so "monkey ... missing" raised a bogus missing-secrets notice.
    for text in ("Cannot find module 'monkey': file is missing", "The turkey was undefined", "bad token stream, value missing"):
        assert pl.classify_environment_issue(text) is None, text
    assert pl.classify_environment_issue("STRIPE_KEY is required") == "secrets"
    assert pl.classify_environment_issue("API_TOKEN not set") == "secrets"


def test_more_specific_kinds_win_over_the_broad_secrets_pattern():
    text = "Cannot connect to the Docker daemon. DATABASE_URL is required"
    assert pl.classify_environment_issue(text) == "nested_container"


def test_classifier_only_reads_the_tail_of_a_huge_log():
    log = "Cannot connect to the Docker daemon\n" + ("x" * 50_000)
    assert pl.classify_environment_issue(log) is None  # the match is outside the analysed tail
    assert pl.classify_environment_issue(("x" * 50_000) + "\nblocked by CORS policy") == "cors"


# ---- Docker in commands (vs. a Dockerfile merely existing) --------------------

def test_mentions_docker_only_when_a_command_actually_invokes_it():
    for cmd in ("docker compose up", "docker-compose up -d && npm start", "docker run -p 3000:3000 app", "make && docker build .", "podman run x"):
        assert pl.mentions_docker(cmd), cmd
    for cmd in ("npm start", "node server.js", "python -m dockerfile_parse", "npm run build:docker-docs", "", None):
        assert not pl.mentions_docker(cmd), cmd


# ---- .env.example ------------------------------------------------------------

def test_env_example_names_are_extracted_without_values():
    text = "# comment\nDATABASE_URL=postgres://user:realpassword@host/db\nexport STRIPE_KEY=sk_live_1\n\n  NEXT_PUBLIC_X = 1\nDATABASE_URL=dup\nnot a var line\n"
    names = pl.parse_env_example_names(text)
    assert names == ["DATABASE_URL", "STRIPE_KEY", "NEXT_PUBLIC_X"]
    assert "realpassword" not in "".join(names)


def test_missing_names_exclude_configured_and_ordinary_process_vars():
    example = ["DATABASE_URL", "STRIPE_KEY", "PORT", "NODE_ENV", "BACKEND_URL", "OPENAI_API_KEY"]
    assert pl.missing_secret_names(example, ["STRIPE_KEY"]) == ["DATABASE_URL", "OPENAI_API_KEY"]
    assert pl.missing_secret_names([], []) == [] and pl.parse_env_example_names(None) == []


def test_env_example_name_count_is_capped():
    text = "\n".join(f"VAR_{i}=x" for i in range(1000))
    assert len(pl.parse_env_example_names(text)) == 200


# ---- guidance: honest about what can't be fixed --------------------------------

def test_every_kind_has_guidance_and_notify_only_actions():
    ctx = GuidanceContext(origin=ORIGIN, egress_ips=["1.2.3.0/24"], missing_names=["A"])
    allowed_actions = {None, "copy_origin", "copy_ips", "open_secrets"}  # every one is a button the PERSON clicks
    for kind in pl.KINDS:
        g = pl.guidance_for(kind, ctx)
        assert g["kind"] == kind and g["title"] and g["why"]
        assert g["can_fix"] in ("yes", "partly", "no")
        for opt in g["options"]:
            assert opt["action"] in allowed_actions


def test_cors_guidance_names_the_stable_origin_to_allowlist_once():
    g = pl.guidance_for("cors", GuidanceContext(origin=ORIGIN))
    assert ORIGIN in g["options"][0]["detail"] and "one-time" in g["options"][0]["detail"]


def test_oauth_says_plainly_it_often_cannot_be_fixed():
    g = pl.guidance_for("oauth", GuidanceContext(origin=ORIGIN))
    assert g["can_fix"] != "yes"
    assert "can't be fixed" in g["options"][0]["detail"]


def test_nested_container_is_marked_unfixable_and_distinguishes_a_mere_dockerfile():
    g = pl.guidance_for("nested_container", GuidanceContext())
    assert g["can_fix"] == "no" and "Dockerfile" in g["why"]


def test_database_guidance_lists_egress_ips_when_configured_and_admits_when_not():
    with_ips = pl.guidance_for("database", GuidanceContext(egress_ips=["203.0.113.5"]))
    assert "203.0.113.5" in with_ips["options"][0]["detail"] and with_ips["options"][0]["action"] == "copy_ips"
    without = pl.guidance_for("database", GuidanceContext())
    assert "hasn't been configured" in without["options"][0]["detail"] and without["options"][0]["action"] is None
    assert any(o["action"] == "open_secrets" for o in without["options"])  # the staging-DB route


def test_secrets_guidance_says_the_agent_cannot_see_them():
    g = pl.guidance_for("secrets", GuidanceContext(missing_names=["STRIPE_KEY"]))
    assert "STRIPE_KEY" in g["why"] and "can't see or use them" in g["options"][0]["detail"]


def test_notification_detail_key_changes_with_the_missing_set_so_dismissal_is_not_permanent_for_new_problems():
    a = pl.build_notification("secrets", GuidanceContext(missing_names=["A", "B"]))
    b = pl.build_notification("secrets", GuidanceContext(missing_names=["B", "A"]))
    c = pl.build_notification("secrets", GuidanceContext(missing_names=["A", "B", "C"]))
    assert a["detail_key"] == b["detail_key"] != c["detail_key"]


def test_notification_includes_the_diagnosis_text_when_given():
    n = pl.build_notification("database", GuidanceContext(), diagnosis_text="Postgres refused the connection.")
    assert n["body"].startswith("Postgres refused the connection.")


def test_standing_notes_cover_the_two_behaviours_that_would_otherwise_look_like_bugs():
    kinds = {n["kind"] for n in pl.extra_notes(GuidanceContext())}
    assert kinds == {"authorization_header", "websocket_limits"}
    assert len(pl.all_guidance(GuidanceContext())) == 7


# ---- secret name/value validation ----------------------------------------------

def test_secret_names_must_be_valid_environment_variable_names():
    assert pl.validate_secret_name("STRIPE_SECRET_KEY") is None and pl.validate_secret_name("_x1") is None
    for bad in ("", "1ABC", "has space", "A-B", "a.b", "x" * 129, "$(rm)"):
        assert pl.validate_secret_name(bad), bad


def test_harness_owned_names_cannot_be_overridden_by_a_secret():
    for reserved in ("PORT", "port", "BACKEND_URL", "PATH", "LD_PRELOAD", "QH_ANYTHING", "sprite_token"):
        msg = pl.validate_secret_name(reserved)
        assert msg and ("harness" in msg), reserved


def test_trailing_newline_is_stripped_from_single_line_values_only():
    assert pl.normalize_secret_value("sk_live_abc\n") == "sk_live_abc"
    assert pl.normalize_secret_value("sk_live_abc\r\n") == "sk_live_abc"
    pem = "-----BEGIN KEY-----\nabc\n-----END KEY-----\n"
    assert pl.normalize_secret_value(pem) == pem
