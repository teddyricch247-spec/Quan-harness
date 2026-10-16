// PDF file structure: reading objects, decoding streams, loading a document.
// No library. See pdfText.ts for turning pages into text.
//
// The file is read the forgiving way: instead of trusting the cross-reference
// table (which is missing, stale or wrong in a surprising number of real PDFs),
// every "N G obj" in the file is found by scanning, later copies of an object
// winning over earlier ones (that is how incremental updates work). Objects
// packed inside object streams are unpacked too. This reads PDFs that stricter
// readers reject.

import { DocError, inflate } from './inflate';

export class PdfName {
  constructor(readonly name: string) {}
}
export class PdfRef {
  constructor(
    readonly num: number,
    readonly gen: number
  ) {}
}
// A PDF string. `s` holds one character per byte (0-255), not decoded text.
export class PdfStr {
  constructor(readonly s: string) {}
}
export type Dict = { [key: string]: PdfObj };
export class PdfStream {
  constructor(
    readonly dict: Dict,
    readonly raw: Uint8Array
  ) {}
}
export type PdfObj = null | boolean | number | PdfName | PdfRef | PdfStr | PdfStream | Dict | PdfObj[];

export const isDict = (o: PdfObj): o is Dict =>
  typeof o === 'object' &&
  o !== null &&
  !Array.isArray(o) &&
  !(o instanceof PdfName) &&
  !(o instanceof PdfRef) &&
  !(o instanceof PdfStr) &&
  !(o instanceof PdfStream);

// --- tokens ------------------------------------------------------------------

export type Tok =
  | { t: 'num'; v: number }
  | { t: 'name'; v: string }
  | { t: 'str'; v: string }
  | { t: 'kw'; v: string }
  | { t: '[' }
  | { t: ']' }
  | { t: '<<' }
  | { t: '>>' };

const isWs = (c: number): boolean => c === 32 || c === 10 || c === 13 || c === 9 || c === 12 || c === 0;
const DELIMS = '()<>[]{}/%';
const NUMBER_RE = /^[+-]?(?:\d+\.?\d*|\.\d+)$/;

export class Lexer {
  constructor(
    readonly s: string,
    public i = 0
  ) {}

  next(): Tok | null {
    const s = this.s;
    const n = s.length;
    for (;;) {
      while (this.i < n && isWs(s.charCodeAt(this.i))) this.i++;
      if (this.i < n && s.charCodeAt(this.i) === 37) {
        while (this.i < n && s.charCodeAt(this.i) !== 10 && s.charCodeAt(this.i) !== 13) this.i++;
        continue;
      }
      break;
    }
    if (this.i >= n) return null;
    const c = s[this.i];
    switch (c) {
      case '/': {
        this.i++;
        let j = this.i;
        while (j < n && !isWs(s.charCodeAt(j)) && !DELIMS.includes(s[j])) j++;
        let name = s.slice(this.i, j);
        this.i = j;
        if (name.includes('#')) name = name.replace(/#([0-9a-fA-F]{2})/g, (_m, h: string) => String.fromCharCode(parseInt(h, 16)));
        return { t: 'name', v: name };
      }
      case '(':
        return { t: 'str', v: this.literalString() };
      case '<':
        if (s[this.i + 1] === '<') {
          this.i += 2;
          return { t: '<<' };
        }
        return { t: 'str', v: this.hexString() };
      case '>':
        if (s[this.i + 1] === '>') {
          this.i += 2;
          return { t: '>>' };
        }
        this.i++;
        return this.next();
      case '[':
        this.i++;
        return { t: '[' };
      case ']':
        this.i++;
        return { t: ']' };
      case '{':
      case '}':
      case ')':
        this.i++;
        return this.next();
      default:
        break;
    }
    let j = this.i;
    while (j < n && !isWs(s.charCodeAt(j)) && !DELIMS.includes(s[j])) j++;
    const word = s.slice(this.i, j);
    this.i = j;
    if (NUMBER_RE.test(word)) return { t: 'num', v: parseFloat(word) };
    return { t: 'kw', v: word };
  }

  private literalString(): string {
    const s = this.s;
    const n = s.length;
    this.i++; // the opening (
    let depth = 1;
    let out = '';
    while (this.i < n) {
      const ch = s[this.i++];
      if (ch === '\\') {
        const e = s[this.i++];
        switch (e) {
          case 'n': out += '\n'; break;
          case 'r': out += '\r'; break;
          case 't': out += '\t'; break;
          case 'b': out += '\b'; break;
          case 'f': out += '\f'; break;
          case '(': case ')': case '\\': out += e; break;
          case '\r': if (s[this.i] === '\n') this.i++; break;
          case '\n': break;
          default:
            if (e >= '0' && e <= '7') {
              let oct = e;
              for (let k = 0; k < 2 && s[this.i] >= '0' && s[this.i] <= '7'; k++) oct += s[this.i++];
              out += String.fromCharCode(parseInt(oct, 8) & 255);
            } else if (e !== undefined) {
              out += e;
            }
        }
      } else if (ch === '(') {
        depth++;
        out += ch;
      } else if (ch === ')') {
        depth--;
        if (depth === 0) break;
        out += ch;
      } else {
        out += ch;
      }
    }
    return out;
  }

  private hexString(): string {
    const s = this.s;
    let end = s.indexOf('>', this.i + 1);
    if (end < 0) end = s.length;
    let hex = s.slice(this.i + 1, end).replace(/[^0-9a-fA-F]/g, '');
    this.i = end + 1;
    if (hex.length % 2) hex += '0';
    let out = '';
    for (let k = 0; k < hex.length; k += 2) out += String.fromCharCode(parseInt(hex.slice(k, k + 2), 16));
    return out;
  }
}

const MAX_DEPTH = 40;

// Builds one value, starting from its first token. `refs` turns "12 0 R" into a
// reference (object files); content streams have none, so they skip the look-ahead.
export function parseValue(lx: Lexer, tok: Tok, refs: boolean, depth = 0): PdfObj {
  if (depth > MAX_DEPTH) return null;
  switch (tok.t) {
    case 'num': {
      if (refs && Number.isInteger(tok.v) && tok.v >= 0) {
        const save = lx.i;
        const t2 = lx.next();
        if (t2 && t2.t === 'num' && Number.isInteger(t2.v) && t2.v >= 0) {
          const t3 = lx.next();
          if (t3 && t3.t === 'kw' && t3.v === 'R') return new PdfRef(tok.v, t2.v);
        }
        lx.i = save;
      }
      return tok.v;
    }
    case 'name':
      return new PdfName(tok.v);
    case 'str':
      return new PdfStr(tok.v);
    case '[': {
      const arr: PdfObj[] = [];
      for (;;) {
        const t = lx.next();
        if (!t || t.t === ']') break;
        arr.push(parseValue(lx, t, refs, depth + 1));
      }
      return arr;
    }
    case '<<': {
      const d: Dict = {};
      for (;;) {
        const k = lx.next();
        if (!k || k.t === '>>') break;
        if (k.t !== 'name') continue;
        const v = lx.next();
        if (!v || v.t === '>>') break;
        d[k.v] = parseValue(lx, v, refs, depth + 1);
      }
      return d;
    }
    case 'kw':
      return tok.v === 'true' ? true : tok.v === 'false' ? false : null;
    default:
      return null;
  }
}

// --- helpers for reading values ----------------------------------------------

export const nameOf = (o: PdfObj): string => (o instanceof PdfName ? o.name : '');
export const numOf = (o: PdfObj, fallback = 0): number => (typeof o === 'number' && Number.isFinite(o) ? o : fallback);

// One character per byte, so offsets in the string are offsets in the file.
export function bytesToLatin1(bytes: Uint8Array): string {
  const parts: string[] = [];
  for (let i = 0; i < bytes.length; i += 8192) {
    parts.push(String.fromCharCode.apply(null, bytes.subarray(i, i + 8192) as unknown as number[]));
  }
  return parts.join('');
}

export function latin1ToBytes(s: string): Uint8Array {
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i) & 255;
  return out;
}

// --- stream filters ----------------------------------------------------------

function unpredict(data: Uint8Array, parms: Dict | null): Uint8Array {
  const predictor = parms ? numOf(parms.Predictor, 1) : 1;
  if (!parms || predictor < 10) return data; // 1 = none; the rare TIFF predictor (2) is not supported
  const colors = numOf(parms.Colors, 1);
  const bpc = numOf(parms.BitsPerComponent, 8);
  const columns = numOf(parms.Columns, 1);
  const bpp = Math.max(1, Math.ceil((colors * bpc) / 8));
  const rowBytes = Math.ceil((colors * bpc * columns) / 8);
  const rows = Math.floor(data.length / (rowBytes + 1));
  const out = new Uint8Array(rows * rowBytes);
  for (let r = 0; r < rows; r++) {
    const filter = data[r * (rowBytes + 1)];
    const src = r * (rowBytes + 1) + 1;
    const cur = r * rowBytes;
    const prev = cur - rowBytes;
    for (let i = 0; i < rowBytes; i++) {
      const x = data[src + i];
      const a = i >= bpp ? out[cur + i - bpp] : 0;
      const b = r > 0 ? out[prev + i] : 0;
      const c = r > 0 && i >= bpp ? out[prev + i - bpp] : 0;
      let v: number;
      switch (filter) {
        case 1: v = x + a; break;
        case 2: v = x + b; break;
        case 3: v = x + ((a + b) >> 1); break;
        case 4: {
          const p = a + b - c;
          const pa = Math.abs(p - a);
          const pb = Math.abs(p - b);
          const pc = Math.abs(p - c);
          v = x + (pa <= pb && pa <= pc ? a : pb <= pc ? b : c);
          break;
        }
        default: v = x;
      }
      out[cur + i] = v & 255;
    }
  }
  return out;
}

function asciiHex(data: Uint8Array): Uint8Array {
  const s = bytesToLatin1(data);
  const end = s.indexOf('>');
  let hex = s.slice(0, end < 0 ? s.length : end).replace(/[^0-9a-fA-F]/g, '');
  if (hex.length % 2) hex += '0';
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

function ascii85(data: Uint8Array): Uint8Array {
  const out: number[] = [];
  const group: number[] = [];
  const flush = (count: number) => {
    let value = 0;
    for (let k = 0; k < 5; k++) value = value * 85 + (group[k] ?? 84);
    for (let k = 0; k < count - 1; k++) out.push((value >>> (24 - 8 * k)) & 255);
    group.length = 0;
  };
  for (let i = 0; i < data.length; i++) {
    const c = data[i];
    if (c === 126) break; // ~>
    if (isWs(c)) continue;
    if (c === 122 && group.length === 0) {
      out.push(0, 0, 0, 0);
      continue;
    }
    if (c < 33 || c > 117) continue;
    group.push(c - 33);
    if (group.length === 5) flush(5);
  }
  if (group.length > 1) flush(group.length);
  return Uint8Array.from(out);
}

function runLength(data: Uint8Array): Uint8Array {
  const out: number[] = [];
  let i = 0;
  while (i < data.length) {
    const len = data[i++];
    if (len === 128) break;
    if (len < 128) {
      for (let k = 0; k <= len && i < data.length; k++) out.push(data[i++]);
    } else {
      const b = data[i++];
      for (let k = 0; k < 257 - len; k++) out.push(b);
    }
  }
  return Uint8Array.from(out);
}

export const FILTER_UNSUPPORTED = Symbol('unsupported filter');

// The decoded bytes of a stream, or FILTER_UNSUPPORTED when it uses a filter
// that is not text-bearing (pictures) or not implemented.
export async function decodeStream(doc: PdfDoc, st: PdfStream): Promise<Uint8Array | typeof FILTER_UNSUPPORTED> {
  const f = doc.deref(st.dict.Filter ?? st.dict.F ?? null);
  const filters: PdfObj[] = Array.isArray(f) ? f : f === null ? [] : [f];
  const p = doc.deref(st.dict.DecodeParms ?? st.dict.DP ?? null);
  const params: PdfObj[] = Array.isArray(p) ? p : p === null ? [] : [p];
  let data = st.raw;
  for (let i = 0; i < filters.length; i++) {
    const name = nameOf(doc.deref(filters[i]));
    const parmObj = doc.deref(params[i] ?? null);
    const parm = isDict(parmObj) ? parmObj : null;
    switch (name) {
      case 'FlateDecode':
      case 'Fl':
        data = unpredict(await inflate(data, 'deflate', { tolerant: true }), parm);
        break;
      case 'ASCIIHexDecode':
      case 'AHx':
        data = asciiHex(data);
        break;
      case 'ASCII85Decode':
      case 'A85':
        data = ascii85(data);
        break;
      case 'RunLengthDecode':
      case 'RL':
        data = runLength(data);
        break;
      case 'Crypt':
        break;
      default:
        return FILTER_UNSUPPORTED;
    }
  }
  return data;
}

// --- the document ------------------------------------------------------------

export class PdfDoc {
  objs = new Map<number, PdfObj>();
  trailers: Dict[] = [];

  deref(o: PdfObj): PdfObj {
    let cur = o;
    for (let n = 0; cur instanceof PdfRef && n < 24; n++) cur = this.objs.get(cur.num) ?? null;
    return cur instanceof PdfRef ? null : cur;
  }

  dict(o: PdfObj): Dict | null {
    const d = this.deref(o);
    if (isDict(d)) return d;
    if (d instanceof PdfStream) return d.dict;
    return null;
  }

  array(o: PdfObj): PdfObj[] {
    const a = this.deref(o);
    return Array.isArray(a) ? a : [];
  }

  async streamText(o: PdfObj): Promise<string | null> {
    const st = this.deref(o);
    if (!(st instanceof PdfStream)) return null;
    const data = await decodeStream(this, st);
    return data === FILTER_UNSUPPORTED ? null : bytesToLatin1(data);
  }
}

const OBJ_RE = /(\d+)[ \t\r\n\f\0]+(\d+)[ \t\r\n\f\0]+obj\b/g;

// Lets the page repaint between chunks of work, so a big PDF does not freeze it.
const breathe = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

export async function loadPdf(bytes: Uint8Array): Promise<PdfDoc> {
  const head = bytesToLatin1(bytes.subarray(0, Math.min(bytes.length, 1024)));
  if (!head.includes('%PDF-')) throw new DocError("This doesn't look like a valid PDF.");
  const s = bytesToLatin1(bytes);
  const doc = new PdfDoc();

  OBJ_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  let scanned = 0;
  while ((m = OBJ_RE.exec(s)) !== null) {
    if (++scanned % 2000 === 0) await breathe();
    const num = Number(m[1]);
    const lx = new Lexer(s, m.index + m[0].length);
    const first = lx.next();
    if (!first) break;
    let value: PdfObj;
    try {
      value = parseValue(lx, first, true);
    } catch {
      continue;
    }
    const afterValue = lx.i;
    const kw = lx.next();
    if (kw && kw.t === 'kw' && kw.v === 'stream' && isDict(value)) {
      let at = lx.i;
      if (s[at] === '\r' && s[at + 1] === '\n') at += 2;
      else if (s[at] === '\n' || s[at] === '\r') at += 1;
      let end = -1;
      const declared = value.Length;
      if (typeof declared === 'number' && declared >= 0 && at + declared <= s.length) {
        const probe = new Lexer(s, at + declared).next();
        if (probe && probe.t === 'kw' && probe.v === 'endstream') end = at + declared;
      }
      if (end < 0) {
        end = s.indexOf('endstream', at);
        if (end < 0) end = s.length;
        else {
          if (s[end - 1] === '\n') end--;
          if (s[end - 1] === '\r') end--;
        }
      }
      doc.objs.set(num, new PdfStream(value, bytes.subarray(at, end)));
      OBJ_RE.lastIndex = Math.max(end, OBJ_RE.lastIndex);
    } else {
      doc.objs.set(num, value);
      OBJ_RE.lastIndex = afterValue;
    }
  }

  // Trailers (classic files) say whether the file is encrypted and where the catalog is.
  const trailerRe = /trailer\b/g;
  while ((m = trailerRe.exec(s)) !== null) {
    const lx = new Lexer(s, m.index + m[0].length);
    const t = lx.next();
    if (t && t.t === '<<') {
      const d = parseValue(lx, t, true);
      if (isDict(d)) doc.trailers.push(d);
    }
  }

  // Objects packed inside object streams (the usual layout of PDF 1.5 and later).
  const packed: Array<[number, PdfStream]> = [];
  for (const [num, o] of doc.objs) {
    if (o instanceof PdfStream && nameOf(o.dict.Type ?? null) === 'ObjStm') packed.push([num, o]);
    if (o instanceof PdfStream && nameOf(o.dict.Type ?? null) === 'XRef') doc.trailers.push(o.dict);
  }
  for (const [, st] of packed) {
    await breathe();
    const raw = await decodeStream(doc, st);
    if (raw === FILTER_UNSUPPORTED) continue;
    const text = bytesToLatin1(raw);
    const count = numOf(st.dict.N);
    const first = numOf(st.dict.First);
    const hx = new Lexer(text);
    const pairs: Array<[number, number]> = [];
    for (let k = 0; k < count; k++) {
      const a = hx.next();
      const b = hx.next();
      if (!a || !b || a.t !== 'num' || b.t !== 'num') break;
      pairs.push([a.v, b.v]);
    }
    for (const [objNum, offset] of pairs) {
      if (doc.objs.has(objNum)) continue;
      const ox = new Lexer(text, first + offset);
      const t = ox.next();
      if (t) doc.objs.set(objNum, parseValue(ox, t, true));
    }
  }

  if (doc.trailers.some((t) => t.Encrypt !== undefined && t.Encrypt !== null)) {
    throw new DocError('This PDF is password-protected. Remove the password and attach it again.');
  }
  return doc;
}
