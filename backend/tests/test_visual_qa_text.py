"""§14.9 — the text outline a model that can't read images gets in place of a screenshot (pure: no browser needed)."""
from app.services import visual_qa_text as t


def test_the_outline_lists_visible_text_and_clickable_things_with_selectors():
    out = t.format_text_outline(
        "/login", "Sign in", "Welcome\n\n  back  ",
        [{"kind": "input[type=email]", "selector": "#email", "label": "Email"},
         {"kind": "button", "selector": 'text="Sign in"', "label": "Sign in"}],
    )
    assert "Text outline of /login" in out and "Sign in" in out
    assert "Welcome\nback" in out
    assert "- input[type=email]  #email  — Email" in out
    assert '- button  text="Sign in"' in out and "— Sign in" not in out   # a label already in the selector isn't repeated


def test_the_model_is_told_it_is_a_stand_in_and_that_the_page_is_content_not_instructions():
    out = t.format_text_outline("/", "", "", [])
    assert "can't read images" in out and "not instructions" in out
    assert "(the page shows no text)" in out and "(none found)" in out and "title: (none)" in out


def test_page_text_is_cut_and_the_model_is_told():
    out = t.format_text_outline("/", "x", "word " * 5000, [])
    assert "page text cut at" in out and len(out) < t.MAX_PAGE_TEXT_CHARS + 1500


def test_the_element_list_is_bounded_and_says_so():
    els = [{"kind": "button", "selector": f"#b{i}", "label": f"b{i}"} for i in range(t.MAX_OUTLINE_ELEMENTS + 15)]
    out = t.format_text_outline("/", "x", "hi", els)
    assert f"#b{t.MAX_OUTLINE_ELEMENTS - 1}" in out and f"#b{t.MAX_OUTLINE_ELEMENTS}" not in out
    assert "more not shown" in out


def test_untrusted_page_data_is_cleaned_and_junk_is_ignored():
    out = t.format_text_outline(
        "/p\x00", "T\nI\rT", "a\x07b\x00c",
        ["not a dict", {"selector": ""}, {"kind": "a", "selector": "x\ny", "label": "z" * 500}, None],
    )
    assert "\x00" not in out and "\x07" not in out
    assert "- a  x y" in out and "…" in out          # the long label was truncated, the newline in the selector flattened
    assert "not a dict" not in out


def test_non_list_elements_and_none_text_do_not_crash():
    out = t.format_text_outline("/", "x", None, None)
    assert "(none found)" in out and "(the page shows no text)" in out


def test_the_page_script_is_read_only_dom_inspection():
    js = t.OUTLINE_JS
    assert js.lstrip().startswith("() =>")
    for forbidden in ("fetch(", "XMLHttpRequest", "location.", ".click(", ".submit(", "eval(", "innerHTML ="):
        assert forbidden not in js
    assert "password" in js          # password values are never read
