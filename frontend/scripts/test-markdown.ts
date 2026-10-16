// Run from frontend/:   npx tsx scripts/test-markdown.ts
// No test framework in this package, so this is a plain assert script, like scripts/test-docs.ts.
import assert from "node:assert/strict";
import { inlineText, parseInline, parseMarkdown, safeHref, splitTableRow } from "../lib/markdown";

let n = 0;
const t = (name: string, fn: () => void) => {
  fn();
  n++;
  console.log("ok", name);
};
const kinds = (src: string) => parseMarkdown(src).map((b) => b.t);

t("pipe table", () => {
  const [b] = parseMarkdown("| File | Change |\n|---|---|\n| `a.py` | fix |\n| b.py | add |");
  assert.equal(b.t, "table");
  if (b.t !== "table") return;
  assert.equal(b.head.length, 2);
  assert.equal(b.rows.length, 2);
  assert.equal(inlineText(b.head[0]), "File");
  assert.deepEqual(b.rows[0][0], [{ t: "code", v: "a.py" }]);
});
t("table without outer pipes", () => {
  const [b] = parseMarkdown("a | b\n--- | ---\n1 | 2");
  assert.equal(b.t, "table");
});
t("table alignment", () => {
  const [b] = parseMarkdown("| a | b | c | d |\n|:--|:-:|--:|---|\n| 1 | 2 | 3 | 4 |");
  assert.equal(b.t, "table");
  if (b.t === "table") assert.deepEqual(b.align, ["left", "center", "right", null]);
});
t("ragged rows are padded or cut to header width", () => {
  const [b] = parseMarkdown("| a | b |\n|---|---|\n| 1 |\n| 1 | 2 | 3 |");
  if (b.t !== "table") throw new Error("not a table");
  assert.deepEqual(b.rows.map((r) => r.length), [2, 2]);
});
t("escaped pipe stays inside the cell", () => {
  assert.deepEqual(splitTableRow("| a \\| b | c |"), ["a | b", "c"]);
});
t("header with no separator yet is plain text (streaming)", () => {
  assert.deepEqual(kinds("| a | b |"), ["p"]);
});
t("single-column table", () => {
  assert.deepEqual(kinds("| a |\n|---|\n| 1 |"), ["table"]);
});
t("a lone --- under a paragraph is a rule, not a table", () => {
  assert.deepEqual(kinds("text\n\n---\n\nmore"), ["p", "hr", "p"]);
});
t("table ends at blank line; paragraph follows", () => {
  assert.deepEqual(kinds("| a | b |\n|---|---|\n| 1 | 2 |\n\nDone."), ["table", "p"]);
});
t("table directly after a paragraph line", () => {
  assert.deepEqual(kinds("Results:\n| a | b |\n|---|---|\n| 1 | 2 |"), ["p", "table"]);
});
t("fenced code keeps contents verbatim, including pipes and #", () => {
  const [b] = parseMarkdown("```ts\nconst a = 1 | 2;\n# not a heading\n```");
  assert.deepEqual(b, { t: "code", lang: "ts", v: "const a = 1 | 2;\n# not a heading", open: false });
});
t("unclosed fence is open", () => {
  const [b] = parseMarkdown("```\nline");
  assert.equal(b.t === "code" && b.open, true);
});
t("table inside a fence is not a table", () => {
  assert.deepEqual(kinds("```\n| a |\n|---|\n```"), ["code"]);
});
t("headings", () => {
  const [h1, h3] = parseMarkdown("# One\n\n### Three ###");
  assert.equal(h1.t === "h" && h1.level, 1);
  assert.equal(h3.t === "h" && h3.level, 3);
  assert.equal(h3.t === "h" && inlineText(h3.c), "Three");
});
t("C# heading keeps its #", () => {
  const [h] = parseMarkdown("## Learn C#");
  assert.equal(h.t === "h" && inlineText(h.c), "Learn C#");
});
t("bullets and nesting", () => {
  const [l] = parseMarkdown("- a\n  - a1\n  - a2\n- b");
  assert.equal(l.t, "list");
  if (l.t !== "list") return;
  assert.equal(l.items.length, 2);
  assert.deepEqual(l.items[0].c.map((b) => b.t), ["p", "list"]);
});
t("ordered list keeps its start number and nests with 3 spaces", () => {
  const [l] = parseMarkdown("3. x\n   - y\n4. z");
  if (l.t !== "list") throw new Error("not a list");
  assert.equal(l.start, 3);
  assert.equal(l.items.length, 2);
});
t("blank line between items keeps one list", () => {
  const [l] = parseMarkdown("- a\n\n- b");
  assert.equal(l.t === "list" && l.items.length, 2);
});
t("list then paragraph", () => {
  assert.deepEqual(kinds("- a\n- b\n\nAfter"), ["list", "p"]);
});
t("task items", () => {
  const [l] = parseMarkdown("- [x] done\n- [ ] todo");
  if (l.t !== "list") throw new Error();
  assert.deepEqual(l.items.map((i) => i.checked), [true, false]);
});
t("bullet interrupts a paragraph; 2. does not", () => {
  assert.deepEqual(kinds("Intro\n- a"), ["p", "list"]);
  assert.deepEqual(kinds("Version\n2. next"), ["p"]);
});
t("quote", () => {
  const [q] = parseMarkdown("> a\n> b");
  assert.equal(q.t, "quote");
});
t("single newlines survive as line breaks", () => {
  assert.deepEqual(parseInline("a\nb"), [{ t: "text", v: "a" }, { t: "br" }, { t: "text", v: "b" }]);
});
t("inline: code, strong, em, del", () => {
  assert.deepEqual(parseInline("`x`"), [{ t: "code", v: "x" }]);
  assert.equal(parseInline("**b**")[0].t, "strong");
  assert.equal(parseInline("*i*")[0].t, "em");
  assert.equal(parseInline("~~d~~")[0].t, "del");
  assert.equal(parseInline("***x***")[0].t, "strong");
});
t("snake_case and 2 * 3 * 4 stay literal", () => {
  assert.deepEqual(parseInline("use my_var_name here"), [{ t: "text", v: "use my_var_name here" }]);
  assert.deepEqual(parseInline("2 * 3 * 4"), [{ t: "text", v: "2 * 3 * 4" }]);
});
t("underscore emphasis at a word boundary", () => {
  assert.equal(parseInline("_it_")[0].t, "em");
  assert.equal(parseInline("__bold__")[0].t, "strong");
});
t("markup inside code is not parsed", () => {
  assert.deepEqual(parseInline("`**x**`"), [{ t: "code", v: "**x**" }]);
});
t("unmatched backtick and star are literal", () => {
  assert.deepEqual(parseInline("a ` b"), [{ t: "text", v: "a ` b" }]);
  assert.deepEqual(parseInline("a * b"), [{ t: "text", v: "a * b" }]);
});
t("links: http only, javascript: is dropped to plain label", () => {
  assert.deepEqual(parseInline("[a](https://x.dev/p?q=1)"), [{ t: "link", href: "https://x.dev/p?q=1", c: [{ t: "text", v: "a" }] }]);
  assert.deepEqual(parseInline("[a](javascript:alert(1))"), [{ t: "text", v: "a" }]);
  assert.equal(safeHref("data:text/html,x"), null);
  assert.equal(safeHref("HTTPS://x.dev"), "HTTPS://x.dev");
});
t("bare url loses trailing punctuation", () => {
  const out = parseInline("see https://x.dev/a. Next");
  assert.deepEqual(out[1], { t: "link", href: "https://x.dev/a", c: [{ t: "text", v: "https://x.dev/a" }] });
  assert.deepEqual(out[2], { t: "text", v: ". Next" });
});
t("html is plain text, never markup", () => {
  assert.deepEqual(parseInline("<script>alert(1)</script>"), [{ t: "text", v: "<script>alert(1)</script>" }]);
});
t("escapes", () => {
  assert.deepEqual(parseInline("\\*not em\\*"), [{ t: "text", v: "*not em*" }]);
});
t("never throws on junk", () => {
  for (const s of ["", "|", "||\n||", "[", "[]()", "**", "```", "- ", "1.", ">", "#", "| a |\n|", "[a](", "~~", "_", "***", "\u0000"]) parseMarkdown(s);
});
t("realistic agent message", () => {
  const msg = [
    "Result: preview now reloads after each turn.",
    "",
    "| File | Change |",
    "|---|---|",
    "| `PreviewPanel.tsx` | auto-reload on `refreshSignal` |",
    "| `preview_rules.py` | `Cache-Control: no-store` |",
    "",
    "Verified: `npm run build` pass.",
    "",
    "Open:",
    "- deploy backend",
    "- hard refresh once",
  ].join("\n");
  assert.deepEqual(kinds(msg), ["p", "table", "p", "p", "list"]);
});

console.log(`\n${n} markdown checks passed`);
