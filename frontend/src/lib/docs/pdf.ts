// Reads the text of a PDF in the browser, with no library.
//
// What it does, in order:
//  1. Loads the file forgivingly (pdfParse.ts) and walks the page tree.
//  2. Runs each page's content stream like a viewer would, tracking the text
//     matrix, so every piece of text gets a position and a size (pdfFonts.ts
//     turns the font's codes into characters and widths).
//  3. Rebuilds reading order from positions: pieces on the same baseline become
//     a line (with spaces where the gap is word-sized, tabs where it is column-
//     sized); two-column pages are read left column then right column; blank
//     lines go where the vertical gap says a paragraph ended.
//  4. Drops running headers, footers and page numbers (lines at the very top or
//     bottom of the page that repeat across pages).
//  5. Marks each page "[Page N]" so a model can cite pages.
//
// It reads the text layer only. A scanned PDF with no text layer has nothing to
// read and is refused with a clear message (no OCR runs here), and a
// password-protected PDF is refused too. Nothing is uploaded: it all happens in
// the browser.

import { DocError, isDocError } from './inflate';
import { buildFont, FontInfo } from './pdfFonts';
import {
  Dict,
  FILTER_UNSUPPORTED,
  Lexer,
  PdfDoc,
  PdfName,
  PdfObj,
  PdfStr,
  PdfStream,
  bytesToLatin1,
  decodeStream,
  isDict,
  loadPdf,
  nameOf,
  numOf,
  parseValue,
} from './pdfParse';

export interface PdfText {
  // The text of the pages read, each starting with its "[Page N]" marker.
  pages: string[];
  // Pages in the whole file (more than pages.length when reading stopped early).
  pageCount: number;
}

// --- geometry ------------------------------------------------------------------

type Matrix = [number, number, number, number, number, number];
const IDENTITY: Matrix = [1, 0, 0, 1, 0, 0];
const mul = (m: Matrix, n: Matrix): Matrix => [
  m[0] * n[0] + m[1] * n[2],
  m[0] * n[1] + m[1] * n[3],
  m[2] * n[0] + m[3] * n[2],
  m[2] * n[1] + m[3] * n[3],
  m[4] * n[0] + m[5] * n[2] + n[4],
  m[4] * n[1] + m[5] * n[3] + n[5],
];

interface Run {
  x: number;
  y: number;
  endX: number;
  endY: number;
  size: number;
  text: string;
  // The TJ array that produced this run asked for a word-sized gap before it.
  spaceBefore: boolean;
}

interface Line {
  y: number;
  x0: number;
  x1: number;
  size: number;
  text: string;
  runs: Run[];
}

// --- the page tree -----------------------------------------------------------------

interface PageInfo {
  contents: PdfObj;
  resources: Dict | null;
  width: number;
  height: number;
  rotate: number;
  originX: number;
  originY: number;
}

interface Inherited {
  resources: Dict | null;
  box: number[];
  rotate: number;
}

function collectPages(doc: PdfDoc): PageInfo[] {
  const pages: PageInfo[] = [];
  const seen = new Set<Dict>();
  const toInfo = (d: Dict, inh: Inherited): PageInfo => {
    const [llx, lly, urx, ury] = inh.box;
    const rot = (((inh.rotate % 360) + 360) % 360) as number;
    const w = Math.abs(urx - llx) || 612;
    const h = Math.abs(ury - lly) || 792;
    const sideways = rot === 90 || rot === 270;
    return {
      contents: d.Contents ?? null,
      resources: inh.resources,
      width: sideways ? h : w,
      height: sideways ? w : h,
      rotate: rot,
      originX: Math.min(llx, urx),
      originY: Math.min(lly, ury),
    };
  };
  const walk = (node: PdfObj, inh: Inherited, depth: number) => {
    const d = doc.dict(node);
    if (!d || seen.has(d) || depth > 40) return;
    seen.add(d);
    const boxArr = doc.array(d.MediaBox ?? null).map((v) => numOf(doc.deref(v), NaN));
    const next: Inherited = {
      resources: d.Resources !== undefined ? (doc.dict(d.Resources) ?? inh.resources) : inh.resources,
      box: boxArr.length === 4 && boxArr.every(Number.isFinite) ? boxArr : inh.box,
      rotate: d.Rotate !== undefined ? numOf(doc.deref(d.Rotate)) : inh.rotate,
    };
    const kids = doc.array(d.Kids ?? null);
    if (kids.length > 0 || nameOf(doc.deref(d.Type ?? null)) === 'Pages') {
      for (const k of kids) walk(k, next, depth + 1);
    } else {
      pages.push(toInfo(d, next));
    }
  };
  let catalog: Dict | null = null;
  for (const t of doc.trailers) {
    const root = doc.dict(t.Root ?? null);
    if (root) catalog = root;
  }
  if (!catalog) {
    for (const o of doc.objs.values()) {
      if (isDict(o) && nameOf(doc.deref(o.Type ?? null)) === 'Catalog') catalog = o;
    }
  }
  if (catalog) walk(catalog.Pages ?? null, { resources: null, box: [0, 0, 612, 792], rotate: 0 }, 0);
  if (pages.length === 0) {
    // A damaged page tree: fall back to every page object, in object order.
    const nums = [...doc.objs.keys()].sort((a, b) => a - b);
    for (const n of nums) {
      const o = doc.objs.get(n) ?? null;
      if (isDict(o) && nameOf(doc.deref(o.Type ?? null)) === 'Page' && !seen.has(o)) {
        seen.add(o);
        pages.push(toInfo(o, { resources: doc.dict(o.Resources ?? null), box: [0, 0, 612, 792], rotate: 0 }));
      }
    }
  }
  return pages;
}

// --- running a content stream --------------------------------------------------------

interface Ctx {
  doc: PdfDoc;
  fonts: Map<Dict, FontInfo>;
  good: number;
  bad: number;
  forms: number;
}

const FALLBACK_FONT: FontInfo = {
  decode(bytes: string) {
    return Array.from(bytes, (ch) => {
      const code = ch.charCodeAt(0) & 255;
      return { text: code >= 32 && code < 127 ? ch : '', width: code === 32 ? 278 : 500, space: code === 32, bad: code > 32 && code >= 127 };
    });
  },
};

async function fontFor(ctx: Ctx, resources: Dict | null, name: string): Promise<FontInfo> {
  const fontDict = resources ? ctx.doc.dict(resources.Font ?? null) : null;
  const fd = fontDict ? ctx.doc.dict(fontDict[name] ?? null) : null;
  if (!fd) return FALLBACK_FONT;
  let font = ctx.fonts.get(fd);
  if (!font) {
    try {
      font = await buildFont(ctx.doc, fd);
    } catch {
      font = FALLBACK_FONT;
    }
    ctx.fonts.set(fd, font);
  }
  return font;
}

interface GState {
  ctm: Matrix;
  font: FontInfo | null;
  size: number;
  tc: number;
  tw: number;
  tz: number;
  tl: number;
  rise: number;
}

const matrixOf = (stack: PdfObj[]): Matrix | null => {
  if (stack.length < 6) return null;
  const m = stack.slice(-6);
  return m.every((v) => typeof v === 'number' && Number.isFinite(v)) ? (m as Matrix) : null;
};

async function runContent(ctx: Ctx, content: string, resources: Dict | null, base: Matrix, runs: Run[], depth: number): Promise<void> {
  const lx = new Lexer(content);
  const stack: PdfObj[] = [];
  const saved: GState[] = [];
  let st: GState = { ctm: base, font: null, size: 0, tc: 0, tw: 0, tz: 1, tl: 0, rise: 0 };
  let tm: Matrix = IDENTITY;
  let tlm: Matrix = IDENTITY;
  let spaceNext = false;

  const num = (k: number): number => {
    const v = stack[stack.length - k];
    return typeof v === 'number' && Number.isFinite(v) ? v : 0;
  };

  const emit = (text: string, advance: number) => {
    if (text.length > 0) {
      const trm = mul(tm, st.ctm);
      const x = trm[4] + st.rise * trm[2];
      const y = trm[5] + st.rise * trm[3];
      runs.push({
        x,
        y,
        endX: x + advance * trm[0],
        endY: y + advance * trm[1],
        size: Math.hypot(trm[2], trm[3]) * st.size,
        text,
        spaceBefore: spaceNext,
      });
      spaceNext = false;
    }
    tm = mul([1, 0, 0, 1, advance, 0], tm);
  };

  const show = (bytes: string) => {
    if (!st.font) return;
    let text = '';
    let advance = 0;
    for (const g of st.font.decode(bytes)) {
      text += g.text;
      if (g.bad) ctx.bad++;
      else if (g.text.trim()) ctx.good++;
      advance += ((g.width / 1000) * st.size + st.tc + (g.space ? st.tw : 0)) * st.tz;
    }
    emit(text, advance);
  };

  const nextLine = () => {
    tlm = mul([1, 0, 0, 1, 0, -st.tl], tlm);
    tm = tlm;
  };

  for (let t = lx.next(); t; t = lx.next()) {
    if (t.t !== 'kw') {
      stack.push(parseValue(lx, t, false));
      if (stack.length > 96) stack.shift();
      continue;
    }
    const op = t.v;
    if (op === 'true' || op === 'false' || op === 'null') {
      stack.push(op === 'true' ? true : op === 'false' ? false : null);
      continue;
    }
    switch (op) {
      case 'q':
        saved.push({ ...st });
        break;
      case 'Q': {
        const g = saved.pop();
        if (g) st = g;
        break;
      }
      case 'cm': {
        const m = matrixOf(stack);
        if (m) st.ctm = mul(m, st.ctm);
        break;
      }
      case 'BT':
        tm = IDENTITY;
        tlm = IDENTITY;
        break;
      case 'Tf': {
        const name = stack[stack.length - 2];
        st.size = num(1);
        st.font = name instanceof PdfName ? await fontFor(ctx, resources, name.name) : null;
        break;
      }
      case 'Tc': st.tc = num(1); break;
      case 'Tw': st.tw = num(1); break;
      case 'Tz': st.tz = num(1) / 100; break;
      case 'TL': st.tl = num(1); break;
      case 'Ts': st.rise = num(1); break;
      case 'Td':
        tlm = mul([1, 0, 0, 1, num(2), num(1)], tlm);
        tm = tlm;
        break;
      case 'TD':
        st.tl = -num(1);
        tlm = mul([1, 0, 0, 1, num(2), num(1)], tlm);
        tm = tlm;
        break;
      case 'Tm': {
        const m = matrixOf(stack);
        if (m) {
          tm = m;
          tlm = m;
        }
        break;
      }
      case 'T*':
        nextLine();
        break;
      case 'Tj': {
        const s = stack[stack.length - 1];
        if (s instanceof PdfStr) show(s.s);
        break;
      }
      case "'": {
        nextLine();
        const s = stack[stack.length - 1];
        if (s instanceof PdfStr) show(s.s);
        break;
      }
      case '"': {
        st.tw = num(3);
        st.tc = num(2);
        nextLine();
        const s = stack[stack.length - 1];
        if (s instanceof PdfStr) show(s.s);
        break;
      }
      case 'TJ': {
        const arr = stack[stack.length - 1];
        if (Array.isArray(arr)) {
          for (const item of arr) {
            if (item instanceof PdfStr) show(item.s);
            else if (typeof item === 'number') {
              tm = mul([1, 0, 0, 1, (-item / 1000) * st.size * st.tz, 0], tm);
              if (item <= -200) spaceNext = true;
            }
          }
        }
        break;
      }
      case 'Do': {
        const nm = stack[stack.length - 1];
        if (!(nm instanceof PdfName) || !resources || depth >= 6 || ctx.forms >= 3000) break;
        const xobjects = ctx.doc.dict(resources.XObject ?? null);
        const xo = xobjects ? ctx.doc.deref(xobjects[nm.name] ?? null) : null;
        if (xo instanceof PdfStream && nameOf(ctx.doc.deref(xo.dict.Subtype ?? null)) === 'Form') {
          ctx.forms++;
          const matrix = ctx.doc.array(xo.dict.Matrix ?? null).map((v) => ctx.doc.deref(v));
          const fm: Matrix = matrix.length === 6 && matrix.every((v) => typeof v === 'number') ? (matrix as Matrix) : IDENTITY;
          const data = await decodeStream(ctx.doc, xo);
          if (data !== FILTER_UNSUPPORTED) {
            await runContent(ctx, bytesToLatin1(data), ctx.doc.dict(xo.dict.Resources ?? null) ?? resources, mul(fm, st.ctm), runs, depth + 1);
          }
        }
        break;
      }
      case 'ID': {
        // Inline image data is binary: skip to its EI.
        const re = /\sEI(?=\s|$)/g;
        re.lastIndex = lx.i;
        const m = re.exec(content);
        lx.i = m ? m.index + m[0].length : content.length;
        break;
      }
      default:
        break;
    }
    stack.length = 0;
  }
}

// --- from runs to lines ---------------------------------------------------------------

// Pieces of text that sit on one baseline, joined into text: a space where the gap
// is word-sized, a tab where it is column-sized.
function joinRuns(runs: Run[], size: number): string {
  let out = '';
  let prev: Run | null = null;
  for (const r of runs) {
    if (prev) {
      const gap = r.x - prev.endX;
      const touching = out.endsWith(' ') || out.endsWith('\t') || r.text.startsWith(' ');
      if (!touching) {
        if (gap > size * 3) out += '\t';
        else if (r.spaceBefore || gap > size * 0.16) out += ' ';
      }
    }
    out += r.text;
    prev = r;
  }
  return out.replace(/[ ]{2,}/g, ' ').trim();
}

function makeLine(runs: Run[]): Line {
  const sorted = runs.slice().sort((a, b) => a.x - b.x);
  const deduped: Run[] = [];
  for (const r of sorted) {
    const last = deduped[deduped.length - 1];
    // Fake bold draws the same text twice, a hair apart.
    if (last && last.text === r.text && Math.abs(last.x - r.x) < 0.4 * r.size && Math.abs(last.y - r.y) < 0.4 * r.size) continue;
    deduped.push(r);
  }
  let best = deduped[0];
  for (const r of deduped) if (r.text.length > best.text.length) best = r;
  return {
    y: best.y,
    x0: deduped[0].x,
    x1: Math.max(...deduped.map((r) => Math.max(r.endX, r.x))),
    size: best.size || 10,
    text: joinRuns(deduped, best.size || 10),
    runs: deduped,
  };
}

function buildLines(runs: Run[]): Line[] {
  const sorted = runs.filter((r) => r.text.trim().length > 0).sort((a, b) => b.y - a.y || a.x - b.x);
  const groups: { y: number; size: number; best: number; runs: Run[] }[] = [];
  for (const r of sorted) {
    const g = groups[groups.length - 1];
    const size = r.size || 10;
    if (g && Math.abs(r.y - g.y) <= 0.55 * Math.max(size, g.size)) {
      g.runs.push(r);
      if (r.text.length > g.best) {
        g.best = r.text.length;
        g.y = r.y;
        g.size = size;
      }
    } else {
      groups.push({ y: r.y, size, best: r.text.length, runs: [r] });
    }
  }
  return groups.map((g) => makeLine(g.runs)).filter((l) => l.text.length > 0);
}

// --- columns ---------------------------------------------------------------------------

// The x of a vertical gutter that splits the page into two columns of running text,
// or null when the page is one column, a table, or too sparse to tell.
function findGutter(lines: Line[]): number | null {
  if (lines.length < 10) return null;
  const left = Math.min(...lines.map((l) => l.x0));
  const right = Math.max(...lines.map((l) => l.x1));
  const span = right - left;
  if (span < 200) return null;
  const crossing = (x: number) => lines.reduce((n, l) => n + (l.runs.some((r) => r.x < x - 1 && Math.max(r.endX, r.x) > x + 1) ? 1 : 0), 0);
  let bestStart = -1;
  let bestLen = 0;
  let bestCross = Infinity;
  let runStart = -1;
  let runCross = Infinity;
  const lo = left + span * 0.2;
  const hi = left + span * 0.8;
  const flush = (end: number) => {
    if (runStart >= 0 && (runCross < bestCross || (runCross === bestCross && end - runStart > bestLen))) {
      bestCross = runCross;
      bestLen = end - runStart;
      bestStart = runStart;
    }
    runStart = -1;
  };
  let prevCross = -1;
  for (let x = lo; x <= hi; x += 2) {
    const c = crossing(x);
    if (c !== prevCross) {
      flush(x);
      runStart = x;
      runCross = c;
      prevCross = c;
    }
  }
  flush(hi);
  if (bestStart < 0 || bestLen < 8 || bestCross > lines.length * 0.15) return null;
  const gx = bestStart + bestLen / 2;
  let leftLines = 0;
  let rightLines = 0;
  let leftChars = 0;
  let rightChars = 0;
  for (const l of lines) {
    const lr = l.runs.filter((r) => Math.max(r.endX, r.x) <= gx);
    const rr = l.runs.filter((r) => r.x >= gx);
    if (lr.length) {
      leftLines++;
      leftChars += lr.reduce((n, r) => n + r.text.length, 0);
    }
    if (rr.length) {
      rightLines++;
      rightChars += rr.reduce((n, r) => n + r.text.length, 0);
    }
  }
  if (leftLines < 6 || rightLines < 6) return null;
  // Running text has long lines on both sides; a table has short cells.
  if (leftChars / leftLines < 22 || rightChars / rightLines < 22) return null;
  return gx;
}

// Lines in reading order, as streams: consecutive lines in a stream are vertically
// adjacent, and a blank line goes between streams.
function orderLines(lines: Line[]): Line[][] {
  const gx = findGutter(lines);
  if (gx === null) return [lines];
  const streams: Line[][] = [];
  let leftCol: Line[] = [];
  let rightCol: Line[] = [];
  let wide: Line[] = [];
  const flushBand = () => {
    if (leftCol.length) streams.push(leftCol);
    if (rightCol.length) streams.push(rightCol);
    leftCol = [];
    rightCol = [];
  };
  const flushWide = () => {
    if (wide.length) streams.push(wide);
    wide = [];
  };
  for (const l of lines) {
    if (l.runs.some((r) => r.x < gx - 1 && Math.max(r.endX, r.x) > gx + 1)) {
      flushBand();
      wide.push(l);
      continue;
    }
    flushWide();
    const lr = l.runs.filter((r) => r.x + (r.endX - r.x) / 2 < gx);
    const rr = l.runs.filter((r) => r.x + (r.endX - r.x) / 2 >= gx);
    if (lr.length) leftCol.push(makeLine(lr));
    if (rr.length) rightCol.push(makeLine(rr));
  }
  flushBand();
  flushWide();
  return streams;
}

function streamsToText(streams: Line[][]): string {
  const blocks: string[] = [];
  for (const stream of streams) {
    let out = '';
    stream.forEach((l, i) => {
      if (i > 0) {
        const prev = stream[i - 1];
        const pitch = prev.y - l.y;
        out += pitch > 1.55 * ((prev.size + l.size) / 2) ? '\n\n' : '\n';
      }
      out += l.text;
    });
    if (out.trim()) blocks.push(out);
  }
  return blocks.join('\n\n');
}

// --- headers and footers ------------------------------------------------------------------

const PAGE_NUMBER_RE = /^(?:page\s*)?(?:\d{1,4}|[ivxlc]{1,6})(?:\s*(?:of|\/)\s*\d{1,4})?$/i;
const edgeKey = (text: string): string => text.replace(/\d+/g, '#').replace(/\s+/g, ' ').trim().toLowerCase();

interface PageLines {
  lines: Line[];
  height: number;
  originY: number;
}

function dropRunningLines(pages: PageLines[]): void {
  const edge = (p: PageLines, l: Line): boolean => {
    const rel = (l.y - p.originY) / p.height;
    return rel > 0.92 || rel < 0.08;
  };
  const counts = new Map<string, number>();
  for (const p of pages) {
    const keys = new Set<string>();
    for (const l of p.lines) if (edge(p, l)) keys.add(edgeKey(l.text));
    for (const k of keys) counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const needed = Math.max(3, Math.ceil(pages.length * 0.4));
  for (const p of pages) {
    p.lines = p.lines.filter((l) => {
      if (!edge(p, l)) return true;
      const text = l.text.trim();
      if (PAGE_NUMBER_RE.test(text)) return false;
      return !(pages.length >= 4 && (counts.get(edgeKey(text)) ?? 0) >= needed);
    });
  }
}

// --- the entry point -----------------------------------------------------------------------

const LIGATURES: Record<string, string> = { '\ufb00': 'ff', '\ufb01': 'fi', '\ufb02': 'fl', '\ufb03': 'ffi', '\ufb04': 'ffl', '\ufb05': 'st', '\ufb06': 'st' };
const tidy = (s: string): string =>
  s
    .replace(/[\ufb00-\ufb06]/g, (c) => LIGATURES[c] ?? c)
    .replace(/\u00a0/g, ' ')
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\ufffd]/g, '')
    .replace(/[ \t]+$/gm, '');

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

export async function extractPdf(bytes: Uint8Array, options: { stopAfterChars?: number } = {}): Promise<PdfText> {
  const doc = await loadPdf(bytes);
  const pages = collectPages(doc);
  if (pages.length === 0) throw new DocError("Couldn't find any pages in this PDF.");
  const ctx: Ctx = { doc, fonts: new Map(), good: 0, bad: 0, forms: 0 };
  const stopAfter = options.stopAfterChars ?? Infinity;

  const read: PageLines[] = [];
  let chars = 0;
  for (let i = 0; i < pages.length; i++) {
    const page = pages[i];
    const runs: Run[] = [];
    ctx.forms = 0;
    try {
      const parts = Array.isArray(doc.deref(page.contents)) ? doc.array(page.contents) : [page.contents];
      const texts: string[] = [];
      for (const part of parts) {
        const t = await doc.streamText(part);
        if (t !== null) texts.push(t);
      }
      await runContent(ctx, texts.join('\n'), page.resources, IDENTITY, runs, 0);
    } catch (err) {
      if (isDocError(err)) throw err;
      // One broken page should not lose the others.
    }
    // To the page as it is displayed: origin at the bottom-left, rotation applied.
    const across: Run[] = [];
    const sideways: Run[] = [];
    for (const r of runs) {
      const x0 = r.x - page.originX;
      const y0 = r.y - page.originY;
      const dx = r.endX - r.x;
      const dy = r.endY - r.y;
      let p: [number, number, number, number];
      switch (page.rotate) {
        case 90: p = [y0, page.height - x0, dy, -dx]; break;
        case 180: p = [page.width - x0, page.height - y0, -dx, -dy]; break;
        case 270: p = [page.width - y0, x0, -dy, dx]; break;
        default: p = [x0, y0, dx, dy];
      }
      const shown: Run = { ...r, x: p[0], y: p[1], endX: p[0] + p[2], endY: p[1] + p[3] };
      (Math.abs(p[3]) > Math.abs(p[2]) ? sideways : across).push(shown);
    }
    // Text that runs up or down the page is a margin stamp or a rotated label, and
    // is left out, unless it is most of the page (a landscape page drawn sideways):
    // then it is turned upright and read as the page's text.
    const count = (list: Run[]) => list.reduce((n, r) => n + r.text.length, 0);
    let use = across;
    let height = page.height;
    let originY = 0;
    if (count(sideways) > count(across)) {
      use = sideways.map((r) =>
        r.endY > r.y
          ? { ...r, x: r.y, y: -r.x, endX: r.endY, endY: -r.endX }
          : { ...r, x: -r.y, y: r.x, endX: -r.endY, endY: r.endX }
      );
      height = page.width;
      originY = sideways.length > 0 && sideways[0].endY > sideways[0].y ? -page.width : 0;
    }
    const lines = buildLines(use);
    chars += lines.reduce((n, l) => n + l.text.length, 0);
    read.push({ lines, height, originY });
    if (chars > stopAfter) break;
    if (i % 4 === 3) await tick();
  }

  if (ctx.good + ctx.bad === 0 || chars < 20) {
    throw new DocError(
      'This PDF has no selectable text (it looks scanned or is made of pictures). Run OCR on it first, or paste the text.'
    );
  }
  if (ctx.bad > 0 && ctx.bad / (ctx.good + ctx.bad) > 0.4) {
    throw new DocError("This PDF's text uses an encoding that can't be read reliably. Export it again from the source, or paste the text.");
  }

  dropRunningLines(read);
  const out = read.map((p, i) => {
    const body = tidy(streamsToText(orderLines(p.lines))).trim();
    return body ? `[Page ${i + 1}]\n${body}` : `[Page ${i + 1}: no text]`;
  });
  return { pages: out, pageCount: pages.length };
}
