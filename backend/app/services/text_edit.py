"""
§14.2's str_replace matching rule and §22's automatic syntax check — extracted to
a pure module (no app.config/httpx/workspace_service imports) so it's unit
testable without a real workspace. app/services/file_tools.py imports everything
here. See backend/tests/test_str_replace_logic.py and test_syntax_check.py.
"""


class StrReplaceMatchError(ValueError):
    def __init__(self, count: int):
        self.count = count
        super().__init__(f"old_str matched {count} times in the file — expected exactly 1.")


def apply_str_replace(content: str, old_str: str, new_str: str) -> str:
    """§14.2: 'Fails loudly — no fuzzy matching, no whitespace tolerance, no
    partial-match fallback — if old_str doesn't appear exactly once.'"""
    count = content.count(old_str)
    if count != 1:
        raise StrReplaceMatchError(count)
    return content.replace(old_str, new_str, 1)


_PY_EXT = (".py",)
_JS_TS_EXT = (".ts", ".tsx", ".js", ".jsx")


def check_syntax(path: str, content: str) -> str | None:
    """Returns None if the file is syntactically fine (or not a checkable type at
    all); otherwise a short human-readable description of what's broken, meant
    to be attached to the tool result per §22 ('the model sees "here's what your
    edit did, and here's what's now syntactically broken because of it" in one
    place'). Runs entirely locally against the content already in hand.

    §22 also calls for a language-agnostic tree-sitter pass ahead of these
    per-language checks. That requires the optional `tree-sitter` +
    `tree-sitter-languages` packages (not in requirements.txt by default — see
    /docs/PHASE2_NOTES.md); when they're not installed, `_tree_sitter_check`
    below returns None immediately and the per-language checks are what's
    actually catching syntax errors, which is exactly the fallback §22 itself
    allows ('fall back to a lighter parser-level syntax check instead of
    skipping JS/TS entirely')."""
    tree_sitter_finding = _tree_sitter_check(path, content)
    if tree_sitter_finding:
        return tree_sitter_finding

    if path.endswith(_PY_EXT):
        return _check_python(content)
    if path.endswith(_JS_TS_EXT):
        return check_js_ts_heuristic(content)
    return None


def _check_python(content: str) -> str | None:
    try:
        compile(content, "<edit>", "exec")
    except SyntaxError as exc:
        return f"Python syntax error at line {exc.lineno}: {exc.msg}"
    return None


def _tree_sitter_check(path: str, content: str) -> str | None:
    try:
        import tree_sitter_languages  # type: ignore
    except ImportError:
        return None
    lang_name = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".js": "javascript",
        ".jsx": "javascript",
    }.get(_ext(path))
    if lang_name is None:
        return None
    try:
        parser = tree_sitter_languages.get_parser(lang_name)
        tree = parser.parse(content.encode("utf-8"))
    except Exception:  # noqa: BLE001 — a missing grammar shouldn't block the edit
        return None
    if tree.root_node.has_error:
        return "tree-sitter: this edit leaves the file with a parse error (broken syntax)."
    return None


def _ext(path: str) -> str:
    idx = path.rfind(".")
    return path[idx:] if idx != -1 else ""


# A real, if intentionally simple, parser-level check: walks the source tracking
# string/template-literal/comment state so brackets inside strings don't get
# miscounted, and reports genuine imbalance — not a style linter, just "does this
# parse at the bracket-matching level." See backend/tests/test_syntax_check.py.
_PAIRS = {")": "(", "]": "[", "}": "{"}
_OPENERS = set(_PAIRS.values())


def check_js_ts_heuristic(content: str) -> str | None:
    stack: list[str] = []
    i = 0
    n = len(content)
    in_string: str | None = None  # one of "'", '"', "`", or None
    in_line_comment = False
    in_block_comment = False

    while i < n:
        ch = content[i]
        nxt = content[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch in ("'", '"', "`"):
            in_string = ch
            i += 1
            continue
        if ch in _OPENERS:
            stack.append(ch)
        elif ch in _PAIRS:
            if not stack or stack[-1] != _PAIRS[ch]:
                return f"Unbalanced '{ch}' — no matching '{_PAIRS[ch]}' open at this point."
            stack.pop()
        i += 1

    if in_string:
        return f"Unterminated string/template literal (opened with {in_string})."
    if stack:
        return f"Unclosed '{stack[-1]}' — reached end of file still inside it."
    return None
