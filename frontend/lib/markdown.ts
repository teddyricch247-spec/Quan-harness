/**
 * A small, dependency-free Markdown parser for the agent's messages: Markdown text in, a typed tree
 * out. Pure (no React, no DOM, no HTML strings), so it can be tested on its own and the renderer
 * (components/Markdown.tsx) can never produce markup the tree didn't describe: there is no
 * dangerouslySetInnerHTML anywhere, so model output cannot inject HTML or script.
 *
 * Supported: paragraphs (single newlines kept as line breaks, which is how chat models write),
 * headings, bullet / numbered / task lists with nesting, block quotes, fenced code, horizontal rules,
 * GFM TABLES (alignment row, escaped pipes, ragged rows, missing outer pipes), and inline code,
 * bold, italic, strikethrough, links and bare URLs.
 *
 * Deliberately forgiving about half-finished text: an unclosed code fence is reported as `open`, a
 * header row with no separator row yet is plain text, a ragged table row is padded or cut to the
 * header's width. Nothing here throws.
 */

export type Inline =
  | { t: "text"; v: string }
  | { t: "code"; v: string }
  | { t: "strong"; c: Inline[] }
  | { t: "em"; c: Inline[] }
  | { t: "del"; c: Inline[] }
  | { t: "link"; href: string; c: Inline[] }
  | { t: "br" };

export type Align = "left" | "right" | "center" | null;

export interface ListItem {
  /** true / false for a "[x]" / "[ ]" task item, null for an ordinary one. */
  checked: boolean | null;
  c: Block[];
}

export type Block =
  | { t: "p"; c: Inline[] }
  | { t: "h"; level: 1 | 2 | 3 | 4 | 5 | 6; c: Inline[] }
  | { t: "code"; lang: string; v: string; open: boolean }
  | { t: "list"; ordered: boolean; start: number; items: ListItem[] }
  | { t: "quote"; c: Block[] }
  | { t: "hr" }
  | { t: "table"; align: Align[]; head: Inline[][]; rows: Inline[][][] };

// ---------------------------------------------------------------------------------------------
// Blocks
// ---------------------------------------------------------------------------------------------

const FENCE = /^ {0,3}(`{3,}|~{3,})\s*([^\s`]*)[^`]*$/;
const HEADING = /^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$/;
const HR = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
const QUOTE = /^ {0,3}>/;
const LIST = /^( {0,3})([-*+]|\d{1,9}[.)])[ \t]+(.*)$/;
const LIST_EMPTY = /^( {0,3})([-*+]|\d{1,9}[.)])[ \t]*$/;
const TABLE_SEP_CELL = /^:?-+:?$/;

export function parseMarkdown(src: string): Block[] {
  return parseBlocks(src.replace(/\r\n?/g, "\n").split("\n"));
}

function indentOf(line: string): number {
  let n = 0;
  for (const ch of line) {
    if (ch === " ") n += 1;
    else if (ch === "\t") n += 4;
    else break;
  }
  return n;
}

/** Strip up to `n` columns of leading whitespace. */
function dedent(line: string, n: number): string {
  let cols = 0;
  let i = 0;
  while (i < line.length && cols < n) {
    if (line[i] === " ") cols += 1;
    else if (line[i] === "\t") cols += 4;
    else break;
    i++;
  }
  return line.slice(i);
}

/** Split one table row into cells: outer pipes optional, `\|` is a literal pipe. */
export function splitTableRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  // A trailing pipe closes the last cell, unless it is escaped.
  if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
  const cells: string[] = [];
  let cur = "";
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (ch === "\\" && s[i + 1] === "|") {
      cur += "|";
      i++;
    } else if (ch === "|") {
      cells.push(cur.trim());
      cur = "";
    } else {
      cur += ch;
    }
  }
  cells.push(cur.trim());
  return cells;
}

/** The alignment of each column if `line` is a table delimiter row ("|---|:--:|"), else null. */
function tableAlignments(line: string): Align[] | null {
  if (!line.includes("-")) return null;
  const cells = splitTableRow(line);
  if (cells.length === 0) return null;
  const out: Align[] = [];
  for (const c of cells) {
    if (!TABLE_SEP_CELL.test(c)) return null;
    const left = c.startsWith(":");
    const right = c.endsWith(":");
    out.push(left && right ? "center" : right ? "right" : left ? "left" : null);
  }
  return out;
}

function isTableStart(lines: string[], i: number): boolean {
  const head = lines[i];
  const sep = lines[i + 1];
  if (head === undefined || sep === undefined) return false;
  if (!head.includes("|") && !sep.includes("|")) return false;
  const align = tableAlignments(sep);
  return align !== null && splitTableRow(head).length === align.length;
}

/** Does `line` start a block that ends a running paragraph? */
function startsBlock(lines: string[], i: number): boolean {
  const line = lines[i];
  if (FENCE.test(line) || HEADING.test(line) || HR.test(line) || QUOTE.test(line)) return true;
  const m = LIST.exec(line);
  if (m) return !/^\d/.test(m[2]) || /^1[.)]$/.test(m[2]); // only "1." may interrupt a paragraph
  return isTableStart(lines, i);
}

function parseBlocks(lines: string[]): Block[] {
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }

    const fence = FENCE.exec(line);
    if (fence) {
      const marker = fence[1];
      const closer = new RegExp(`^ {0,3}${marker[0] === "`" ? "`" : "~"}{${marker.length},}\\s*$`);
      const body: string[] = [];
      const fenceIndent = indentOf(line);
      i++;
      let closed = false;
      while (i < lines.length) {
        if (closer.test(lines[i])) {
          closed = true;
          i++;
          break;
        }
        body.push(dedent(lines[i], fenceIndent));
        i++;
      }
      out.push({ t: "code", lang: fence[2] ?? "", v: body.join("\n"), open: !closed });
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      out.push({ t: "h", level: heading[1].length as 1 | 2 | 3 | 4 | 5 | 6, c: parseInline(heading[2]) });
      i++;
      continue;
    }

    if (HR.test(line)) {
      out.push({ t: "hr" });
      i++;
      continue;
    }

    if (QUOTE.test(line)) {
      const inner: string[] = [];
      while (i < lines.length && lines[i].trim() && (QUOTE.test(lines[i]) || !startsBlock(lines, i))) {
        inner.push(lines[i].replace(/^ {0,3}> ?/, ""));
        i++;
      }
      out.push({ t: "quote", c: parseBlocks(inner) });
      continue;
    }

    if (isTableStart(lines, i)) {
      const align = tableAlignments(lines[i + 1]) as Align[];
      const width = align.length;
      const fit = (cells: string[]): Inline[][] => {
        const row = cells.slice(0, width).map((c) => parseInline(c));
        while (row.length < width) row.push([]);
        return row;
      };
      const head = fit(splitTableRow(lines[i]));
      i += 2;
      const rows: Inline[][][] = [];
      while (i < lines.length && lines[i].trim() && lines[i].includes("|") && !FENCE.test(lines[i]) && !HEADING.test(lines[i]) && !QUOTE.test(lines[i])) {
        rows.push(fit(splitTableRow(lines[i])));
        i++;
      }
      out.push({ t: "table", align, head, rows });
      continue;
    }

    const li = LIST.exec(line) ?? LIST_EMPTY.exec(line);
    if (li) {
      const parsed = parseList(lines, i);
      out.push(parsed.block);
      i = parsed.next;
      continue;
    }

    // Paragraph: runs until a blank line or the start of another block. Single newlines are kept.
    const para: string[] = [line.replace(/^ {1,3}/, "")];
    i++;
    while (i < lines.length && lines[i].trim() && !startsBlock(lines, i)) {
      para.push(lines[i].trim());
      i++;
    }
    out.push({ t: "p", c: parseInline(para.join("\n")) });
  }
  return out;
}

function parseList(lines: string[], start: number): { block: Block; next: number } {
  const first = (LIST.exec(lines[start]) ?? LIST_EMPTY.exec(lines[start])) as RegExpExecArray;
  const ordered = /^\d/.test(first[2]);
  const listIndent = first[1].length;
  const startNumber = ordered ? parseInt(first[2], 10) : 1;
  const items: ListItem[] = [];
  let i = start;

  while (i < lines.length) {
    const m = LIST.exec(lines[i]) ?? LIST_EMPTY.exec(lines[i]);
    if (!m || m[1].length > listIndent + 3 || /^\d/.test(m[2]) !== ordered) break;
    // Where this item's text begins, so nested lines can be dedented by that much.
    const markerWidth = m[1].length + m[2].length + 1;
    const body: string[] = [m[3] ?? ""];
    i++;
    let sawBlank = false;
    while (i < lines.length) {
      const l = lines[i];
      if (!l.trim()) {
        sawBlank = true;
        body.push("");
        i++;
        continue;
      }
      const ind = indentOf(l);
      const sibling = LIST.exec(l) ?? LIST_EMPTY.exec(l);
      if (ind > m[1].length) {
        // indented deeper than this item's marker: belongs to it (a nested list or a continuation)
        body.push(dedent(l, markerWidth));
        sawBlank = false;
        i++;
        continue;
      }
      if (!sawBlank && !sibling && !startsBlock(lines, i)) {
        body.push(l.trim()); // lazy continuation of the item's paragraph
        i++;
        continue;
      }
      break;
    }
    while (body.length > 1 && !body[body.length - 1].trim()) body.pop(); // blank lines that only separated items

    let checked: boolean | null = null;
    const task = /^\[([ xX])\][ \t]+/.exec(body[0]);
    if (task) {
      checked = task[1] !== " ";
      body[0] = body[0].slice(task[0].length);
    }
    items.push({ checked, c: parseBlocks(body) });

    // The next line continues the list only if it is a sibling marker (possibly after blank lines).
    let j = i;
    while (j < lines.length && !lines[j].trim()) j++;
    const next = j < lines.length ? (LIST.exec(lines[j]) ?? LIST_EMPTY.exec(lines[j])) : null;
    if (next && next[1].length <= listIndent + 3 && /^\d/.test(next[2]) === ordered) {
      i = j;
    } else {
      break;
    }
  }
  return { block: { t: "list", ordered, start: startNumber, items }, next: i };
}

// ---------------------------------------------------------------------------------------------
// Inline
// ---------------------------------------------------------------------------------------------

const ESCAPABLE = /[\\`*_{}[\]()#+\-.!|~>]/;
const WORD = /[A-Za-z0-9]/;
const URL_RE = /^https?:\/\/[^\s<>]+/;

/** http(s) and mailto only: a `javascript:` or `data:` target is never made clickable. */
export function safeHref(raw: string): string | null {
  const href = raw.trim();
  return /^(https?:\/\/|mailto:)/i.test(href) ? href : null;
}

function findCodeEnd(s: string, from: number, run: number): number {
  let j = from;
  while ((j = s.indexOf("`", j)) !== -1) {
    let k = 0;
    while (s[j + k] === "`") k++;
    if (k === run) return j;
    j += k;
  }
  return -1;
}

/** Index of the `]` matching an already-consumed `[` at `open`, or -1. */
function findBracketEnd(s: string, open: number): number {
  let depth = 0;
  for (let i = open; i < s.length; i++) {
    const ch = s[i];
    if (ch === "\\") i++;
    else if (ch === "`") {
      let k = 0;
      while (s[i + k] === "`") k++;
      const end = findCodeEnd(s, i + k, k);
      if (end !== -1) i = end + k - 1;
      else i += k - 1;
    } else if (ch === "[") depth++;
    else if (ch === "]" && --depth === 0) return i;
  }
  return -1;
}

export function parseInline(s: string): Inline[] {
  const out: Inline[] = [];
  let buf = "";
  const flush = () => {
    if (buf) {
      out.push({ t: "text", v: buf });
      buf = "";
    }
  };
  let i = 0;
  while (i < s.length) {
    const ch = s[i];

    if (ch === "\\" && i + 1 < s.length && ESCAPABLE.test(s[i + 1])) {
      buf += s[i + 1];
      i += 2;
      continue;
    }

    if (ch === "\n") {
      flush();
      out.push({ t: "br" });
      i++;
      continue;
    }

    if (ch === "`") {
      let run = 0;
      while (s[i + run] === "`") run++;
      const end = findCodeEnd(s, i + run, run);
      if (end !== -1) {
        let v = s.slice(i + run, end);
        if (v.length > 2 && v.startsWith(" ") && v.endsWith(" ")) v = v.slice(1, -1);
        flush();
        out.push({ t: "code", v });
        i = end + run;
        continue;
      }
      buf += "`".repeat(run);
      i += run;
      continue;
    }

    if (ch === "[") {
      const close = findBracketEnd(s, i);
      if (close !== -1 && s[close + 1] === "(") {
        // the destination runs to the matching ")", allowing one level of parentheses inside
        let depth = 0;
        let end = -1;
        for (let k = close + 1; k < s.length; k++) {
          if (s[k] === "(") depth++;
          else if (s[k] === ")" && --depth === 0) {
            end = k;
            break;
          } else if (s[k] === "\n") break;
        }
        if (end !== -1) {
          const dest = s.slice(close + 2, end).trim().replace(/\s+"[^"]*"$/, "");
          const href = safeHref(dest.replace(/^<|>$/g, ""));
          flush();
          const label = parseInline(s.slice(i + 1, close));
          if (href) out.push({ t: "link", href, c: label.length ? label : [{ t: "text", v: href }] });
          else out.push(...label);
          i = end + 1;
          continue;
        }
      }
    }

    if (ch === "h" && (s.startsWith("http://", i) || s.startsWith("https://", i)) && (i === 0 || !WORD.test(s[i - 1]))) {
      const m = URL_RE.exec(s.slice(i));
      if (m) {
        let url = m[0];
        // trailing punctuation belongs to the sentence, and so does a ")" with no "(" before it in the URL
        for (;;) {
          const last = url[url.length - 1];
          if (/[.,;:!?'"]/.test(last)) url = url.slice(0, -1);
          else if (last === ")" && (url.match(/\(/g)?.length ?? 0) < (url.match(/\)/g)?.length ?? 0)) url = url.slice(0, -1);
          else break;
        }
        if (url.length > "https://".length) {
          flush();
          out.push({ t: "link", href: url, c: [{ t: "text", v: url }] });
          i += url.length;
          continue;
        }
      }
    }

    if (ch === "*" || ch === "_" || ch === "~") {
      const handled = emphasis(s, i, ch);
      if (handled) {
        flush();
        out.push(handled.node);
        i = handled.next;
        continue;
      }
    }

    buf += ch;
    i++;
  }
  flush();
  return out;
}

function emphasis(s: string, i: number, ch: string): { node: Inline; next: number } | null {
  const before = i > 0 ? s[i - 1] : "";
  let run = 0;
  while (s[i + run] === ch) run++;

  if (ch === "~") {
    if (run !== 2) return null;
    return wrap(s, i, "~~", 2, "del");
  }
  // An underscore only opens at a word boundary, so snake_case_names stay plain text.
  if (ch === "_" && before && WORD.test(before)) return null;

  if (run >= 3) {
    const closing = ch.repeat(3);
    const end = findCloser(s, i + 3, closing, ch === "_");
    if (end !== -1) {
      const inner = s.slice(i + 3, end);
      if (inner.trim() && !/^\s/.test(inner) && !/\s$/.test(inner)) {
        return { node: { t: "strong", c: [{ t: "em", c: parseInline(inner) }] }, next: end + 3 };
      }
    }
  }
  if (run >= 2) return wrap(s, i, ch.repeat(2), 2, "strong") ?? (run === 2 ? null : wrap(s, i, ch, 1, "em"));
  return wrap(s, i, ch, 1, "em");
}

function findCloser(s: string, from: number, delim: string, underscore: boolean): number {
  let j = from;
  while ((j = s.indexOf(delim, j)) !== -1) {
    const prev = s[j - 1];
    const after = s[j + delim.length];
    const longer = after === delim[0]; // `**` inside `***`: leave it for the longer run to claim
    if (prev !== "\\" && !/\s/.test(prev ?? " ") && !(underscore && after && WORD.test(after)) && !(delim.length === 1 && longer)) return j;
    j += 1;
  }
  return -1;
}

function wrap(s: string, i: number, delim: string, len: number, kind: "strong" | "em" | "del"): { node: Inline; next: number } | null {
  const first = s[i + len];
  if (first === undefined || /\s/.test(first)) return null;
  const end = findCloser(s, i + len, delim, delim[0] === "_");
  if (end === -1) return null;
  const inner = s.slice(i + len, end);
  if (!inner.trim()) return null;
  return { node: { t: kind, c: parseInline(inner) }, next: end + len };
}

/** Plain text of a run of inline nodes (used for table cell titles and tests). */
export function inlineText(nodes: Inline[]): string {
  return nodes
    .map((n) => {
      switch (n.t) {
        case "text":
        case "code":
          return n.v;
        case "br":
          return "\n";
        default:
          return inlineText(n.c);
      }
    })
    .join("");
}
