// Reads the text of a Word file (.docx) in the browser, with no library.
//
// A .docx is a zip of XML files. This opens the zip (zip.ts), then walks
// word/document.xml and keeps what matters to a reader and to a model:
//   - paragraphs in order; headings as "#" lines (from the style, or its outline level);
//   - bulleted and numbered lists, with their nesting, as "- " and "1. " lines;
//   - tables as pipe tables (merged cells kept in their columns);
//   - hyperlinks as [text](address);
//   - text boxes, but not their duplicate fallback copies; deleted tracked-change
//     text is left out, as Word hides it.
// Headers, footers, comments and images are not read.

import { DocError } from './inflate';
import { readZipDirectory, readZipText } from './zip';

export interface DocText {
  // The document in pieces that join, in order, into the full text. Each piece
  // already carries the line breaks that precede it, so a caller can cut the
  // document at a piece boundary (a paragraph, a list item, a whole table).
  parts: string[];
}

const ENTITIES: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" };
const decodeEntities = (s: string): string =>
  s.includes('&')
    ? s.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos);/gi, (m, e: string) => {
        if (e[0] === '#') {
          const code = e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
          return Number.isFinite(code) && code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : '';
        }
        return ENTITIES[e.toLowerCase()] ?? m;
      })
    : s;

const attrCache = new Map<string, RegExp>();
const attr = (attrs: string, key: string): string | null => {
  let re = attrCache.get(key);
  if (!re) {
    re = new RegExp(`(?:^|\\s)${key.replace(/[:.]/g, '\\$&')}\\s*=\\s*(?:"([^"]*)"|'([^']*)')`);
    attrCache.set(key, re);
  }
  const m = re.exec(attrs);
  return m ? decodeEntities(m[1] ?? m[2] ?? '') : null;
};

// One token of XML: a tag (with its attributes), or text.
const TOKEN_RE =
  /<!--[\s\S]*?-->|<\?[\s\S]*?\?>|<!\[CDATA\[([\s\S]*?)\]\]>|<(\/?)([A-Za-z_][\w:.-]*)((?:[^>"']|"[^"]*"|'[^']*')*?)(\/?)>|([^<]+)/g;

interface StyleInfo {
  name: string;
  basedOn: string | null;
  numId: string | null;
  ilvl: number;
  outline: number;
}

const parseStyles = (xml: string | null): Map<string, StyleInfo> => {
  const styles = new Map<string, StyleInfo>();
  if (!xml) return styles;
  const re = /<w:style\b([^>]*)>([\s\S]*?)<\/w:style>/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(xml)) !== null) {
    const id = attr(m[1], 'w:styleId');
    if (!id) continue;
    const body = m[2];
    const val = (tag: string): string | null => {
      const t = new RegExp(`<${tag}\\b([^>]*)/?>`).exec(body);
      return t ? attr(t[1], 'w:val') : null;
    };
    const outline = val('w:outlineLvl');
    styles.set(id, {
      name: (val('w:name') ?? '').toLowerCase(),
      basedOn: val('w:basedOn'),
      numId: val('w:numId'),
      ilvl: Number(val('w:ilvl') ?? 0) || 0,
      outline: outline === null ? -1 : Number(outline),
    });
  }
  return styles;
};

// Heading level (1-6) of a paragraph style, following "based on" links; 0 if it is not a heading.
const headingLevel = (styles: Map<string, StyleInfo>, styleId: string, outline: number): number => {
  if (outline >= 0 && outline <= 5) return outline + 1;
  let id: string | null = styleId;
  for (let hops = 0; id && hops < 6; hops++) {
    const s = styles.get(id);
    if (!s) break;
    const h = /^heading\s*([1-9])$/.exec(s.name);
    if (h) return Math.min(6, Number(h[1]));
    if (s.name === 'title') return 1;
    if (s.name === 'subtitle') return 2;
    if (s.outline >= 0 && s.outline <= 5) return s.outline + 1;
    id = s.basedOn;
  }
  return 0;
};

// numId -> level -> true when that level is a bullet (anything else counts as numbered).
const parseNumbering = (xml: string | null): Map<string, Map<number, boolean>> => {
  const result = new Map<string, Map<number, boolean>>();
  if (!xml) return result;
  const abstracts = new Map<string, Map<number, boolean>>();
  const absRe = /<w:abstractNum\b([^>]*)>([\s\S]*?)<\/w:abstractNum>/g;
  let m: RegExpExecArray | null;
  while ((m = absRe.exec(xml)) !== null) {
    const id = attr(m[1], 'w:abstractNumId');
    if (id === null) continue;
    const levels = new Map<number, boolean>();
    const lvlRe = /<w:lvl\b([^>]*)>([\s\S]*?)<\/w:lvl>/g;
    let l: RegExpExecArray | null;
    while ((l = lvlRe.exec(m[2])) !== null) {
      const ilvl = Number(attr(l[1], 'w:ilvl') ?? 0) || 0;
      const fmt = /<w:numFmt\b([^>]*)\/?>/.exec(l[2]);
      levels.set(ilvl, (fmt ? attr(fmt[1], 'w:val') : null) === 'bullet');
    }
    abstracts.set(id, levels);
  }
  const numRe = /<w:num\b([^>]*)>([\s\S]*?)<\/w:num>/g;
  while ((m = numRe.exec(xml)) !== null) {
    const numId = attr(m[1], 'w:numId');
    const ref = /<w:abstractNumId\b([^>]*)\/?>/.exec(m[2]);
    const abs = ref ? attr(ref[1], 'w:val') : null;
    if (numId !== null && abs !== null && abstracts.has(abs)) result.set(numId, abstracts.get(abs)!);
  }
  return result;
};

const parseRelationships = (xml: string | null): Map<string, string> => {
  const rels = new Map<string, string>();
  if (!xml) return rels;
  const re = /<Relationship\b([^>]*?)\/?>/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(xml)) !== null) {
    const id = attr(m[1], 'Id');
    const target = attr(m[1], 'Target');
    if (id && target && attr(m[1], 'TargetMode') === 'External') rels.set(id, target);
  }
  return rels;
};

interface Block {
  text: string;
  tight: boolean; // a list item that follows another: joined with one line break, not a blank line
}

interface Para {
  text: string;
  styleId: string;
  numId: string | null;
  ilvl: number;
  outline: number;
  link: { url: string; start: number } | null;
}

interface TableCtx {
  rows: string[][];
  row: string[] | null;
  cell: string[] | null;
  span: number;
}

const renderTable = (rows: string[][]): string => {
  const width = Math.max(1, ...rows.map((r) => r.length));
  const line = (r: string[]) => `| ${Array.from({ length: width }, (_, i) => r[i] ?? '').join(' | ')} |`;
  const out = [line(rows[0]), `| ${Array.from({ length: width }, () => '---').join(' | ')} |`];
  for (let i = 1; i < rows.length; i++) out.push(line(rows[i]));
  return out.join('\n');
};

export async function extractDocx(bytes: Uint8Array): Promise<DocText> {
  const dir = readZipDirectory(bytes);
  const documentXml = await readZipText(bytes, dir, 'word/document.xml');
  if (documentXml === null) throw new DocError("This isn't a Word document (.docx).");
  const styles = parseStyles(await readZipText(bytes, dir, 'word/styles.xml'));
  const numbering = parseNumbering(await readZipText(bytes, dir, 'word/numbering.xml'));
  const rels = parseRelationships(await readZipText(bytes, dir, 'word/_rels/document.xml.rels'));

  const blocks: Block[] = [];
  const paras: Para[] = [];
  const tables: TableCtx[] = [];
  const counters = new Map<string, number>();
  let inPPr = false;
  let inT = false;
  let skipDepth = 0; // inside <mc:Fallback>: a duplicate of the <mc:Choice> that was already read

  const endPara = () => {
    const para = paras.pop();
    if (!para) return;
    const text = para.text.replace(/\u00a0/g, ' ').replace(/[ \t]+\n/g, '\n').trim();
    if (!text) return;
    const style = styles.get(para.styleId);
    const level = headingLevel(styles, para.styleId, para.outline);
    let numId = para.numId;
    let ilvl = para.ilvl;
    if (numId === null && style?.numId) {
      numId = style.numId;
      ilvl = style.ilvl;
    }
    const table = tables[tables.length - 1];
    if (table && table.cell) {
      table.cell.push(text);
      return;
    }
    if (level > 0) {
      blocks.push({ text: `${'#'.repeat(level)} ${text}`, tight: false });
    } else if (numId !== null && numId !== '0') {
      const bullet = numbering.get(numId)?.get(ilvl) ?? true;
      let marker = '- ';
      if (!bullet) {
        const key = `${numId}/${ilvl}`;
        const next = (counters.get(key) ?? 0) + 1;
        counters.set(key, next);
        for (const k of [...counters.keys()]) {
          const [n, l] = k.split('/');
          if (n === numId && Number(l) > ilvl) counters.delete(k);
        }
        marker = `${next}. `;
      }
      blocks.push({ text: `${'  '.repeat(Math.min(ilvl, 6))}${marker}${text}`, tight: true });
    } else {
      blocks.push({ text, tight: false });
    }
  };

  const endTable = () => {
    const table = tables.pop();
    if (!table || table.rows.length === 0) return;
    const parent = tables[tables.length - 1];
    if (parent && parent.cell) {
      parent.cell.push(table.rows.map((r) => r.filter(Boolean).join(' / ')).join('; '));
    } else {
      blocks.push({ text: renderTable(table.rows), tight: false });
    }
  };

  TOKEN_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = TOKEN_RE.exec(documentXml)) !== null) {
    const cdata = m[1];
    const text = m[6];
    if (cdata !== undefined || text !== undefined) {
      const para = paras[paras.length - 1];
      if (inT && para && skipDepth === 0) para.text += cdata !== undefined ? cdata : decodeEntities(text);
      continue;
    }
    if (m[3] === undefined) continue; // a comment or processing instruction
    const closing = m[2] === '/';
    const name = m[3];
    const attrs = m[4] ?? '';
    const selfClosing = m[5] === '/';

    if (name === 'mc:Fallback') {
      if (!closing && !selfClosing) skipDepth++;
      else if (closing && skipDepth > 0) skipDepth--;
      continue;
    }
    if (skipDepth > 0) continue;

    const para = paras[paras.length - 1];
    const table = tables[tables.length - 1];
    switch (name) {
      case 'w:p':
        if (closing) endPara();
        else if (!selfClosing) paras.push({ text: '', styleId: '', numId: null, ilvl: 0, outline: -1, link: null });
        break;
      case 'w:pPr':
        inPPr = !closing && !selfClosing;
        break;
      case 'w:pStyle':
        if (para && inPPr) para.styleId = attr(attrs, 'w:val') ?? '';
        break;
      case 'w:numId':
        if (para && inPPr) para.numId = attr(attrs, 'w:val');
        break;
      case 'w:ilvl':
        if (para && inPPr) para.ilvl = Number(attr(attrs, 'w:val') ?? 0) || 0;
        break;
      case 'w:outlineLvl':
        if (para && inPPr) para.outline = Number(attr(attrs, 'w:val') ?? -1);
        break;
      case 'w:t':
        inT = !closing && !selfClosing;
        break;
      case 'w:tab':
        if (para && !inPPr && !closing) para.text += '\t';
        break;
      case 'w:br':
      case 'w:cr':
        if (para && !inPPr && !closing) para.text += '\n';
        break;
      case 'w:noBreakHyphen':
        if (para && !inPPr && !closing) para.text += '-';
        break;
      case 'w:hyperlink':
        if (!para) break;
        if (!closing && !selfClosing) {
          const url = rels.get(attr(attrs, 'r:id') ?? '');
          para.link = url ? { url, start: para.text.length } : null;
        } else if (closing && para.link) {
          const label = para.text.slice(para.link.start);
          if (label.trim()) para.text = `${para.text.slice(0, para.link.start)}[${label.trim()}](${para.link.url})`;
          para.link = null;
        }
        break;
      case 'w:tbl':
        if (closing) endTable();
        else if (!selfClosing) tables.push({ rows: [], row: null, cell: null, span: 1 });
        break;
      case 'w:tr':
        if (!table) break;
        if (closing) {
          if (table.row) table.rows.push(table.row);
          table.row = null;
        } else if (!selfClosing) table.row = [];
        break;
      case 'w:tc':
        if (!table) break;
        if (closing) {
          const cellText = (table.cell ?? []).join(' ').replace(/\|/g, '\\|').replace(/\s*\n\s*/g, ' ').trim();
          if (table.row) {
            table.row.push(cellText);
            for (let i = 1; i < table.span; i++) table.row.push('');
          }
          table.cell = null;
        } else if (!selfClosing) {
          table.cell = [];
          table.span = 1;
        }
        break;
      case 'w:gridSpan':
        if (table) table.span = Math.max(1, Math.min(50, Number(attr(attrs, 'w:val') ?? 1) || 1));
        break;
      default:
        break;
    }
  }
  // A damaged file can leave paragraphs or tables open: keep what was read.
  while (paras.length) endPara();
  while (tables.length) endTable();

  const parts: string[] = [];
  blocks.forEach((b, i) => {
    const sep = i === 0 ? '' : b.tight && blocks[i - 1].tight ? '\n' : '\n\n';
    parts.push(sep + b.text);
  });
  if (parts.length === 0) throw new DocError('This document has no text in it.');
  return { parts };
}
