// PDF fonts: turning the bytes of a text string into characters, and measuring
// how wide they are (the width decides whether two pieces of text on a line are
// separate words). No library.
//
// A PDF font says what its codes mean in one of three ways, tried in this order:
//  1. a /ToUnicode map (a small CMap program): exact, and present in nearly every
//     modern PDF, including all fonts with 2-byte codes;
//  2. a simple font's /Encoding (WinAnsi, MacRoman or Standard, plus a
//     /Differences list of glyph names);
//  3. for a font with neither, the Standard encoding, which is right for plain
//     ASCII text.

import { Dict, Lexer, PdfDoc, PdfName, PdfObj, isDict, nameOf, numOf } from './pdfParse';

export interface Glyph {
  text: string;
  // Width in thousandths of the font size.
  width: number;
  // The one-byte code 32, the only code PDF's word spacing applies to.
  space: boolean;
  // The code could not be turned into a character.
  bad: boolean;
}

export interface FontInfo {
  decode(bytes: string): Glyph[];
}

// --- glyph names ---------------------------------------------------------------

const GLYPHS = (
  'space 20 exclam 21 quotedbl 22 numbersign 23 dollar 24 percent 25 ampersand 26 quotesingle 27 parenleft 28 parenright 29 ' +
  'asterisk 2A plus 2B comma 2C hyphen 2D period 2E slash 2F zero 30 one 31 two 32 three 33 four 34 five 35 six 36 seven 37 ' +
  'eight 38 nine 39 colon 3A semicolon 3B less 3C equal 3D greater 3E question 3F at 40 bracketleft 5B backslash 5C ' +
  'bracketright 5D asciicircum 5E underscore 5F grave 60 braceleft 7B bar 7C braceright 7D asciitilde 7E ' +
  'nbspace A0 nonbreakingspace A0 exclamdown A1 cent A2 sterling A3 currency A4 yen A5 brokenbar A6 section A7 dieresis A8 ' +
  'copyright A9 ordfeminine AA guillemotleft AB logicalnot AC sfthyphen AD softhyphen AD registered AE macron AF degree B0 ' +
  'plusminus B1 twosuperior B2 threesuperior B3 acute B4 mu B5 mu1 B5 paragraph B6 periodcentered B7 cedilla B8 onesuperior B9 ' +
  'ordmasculine BA guillemotright BB onequarter BC onehalf BD threequarters BE questiondown BF ' +
  'Agrave C0 Aacute C1 Acircumflex C2 Atilde C3 Adieresis C4 Aring C5 AE C6 Ccedilla C7 Egrave C8 Eacute C9 Ecircumflex CA ' +
  'Edieresis CB Igrave CC Iacute CD Icircumflex CE Idieresis CF Eth D0 Ntilde D1 Ograve D2 Oacute D3 Ocircumflex D4 Otilde D5 ' +
  'Odieresis D6 multiply D7 Oslash D8 Ugrave D9 Uacute DA Ucircumflex DB Udieresis DC Yacute DD Thorn DE germandbls DF ' +
  'agrave E0 aacute E1 acircumflex E2 atilde E3 adieresis E4 aring E5 ae E6 ccedilla E7 egrave E8 eacute E9 ecircumflex EA ' +
  'edieresis EB igrave EC iacute ED icircumflex EE idieresis EF eth F0 ntilde F1 ograve F2 oacute F3 ocircumflex F4 otilde F5 ' +
  'odieresis F6 divide F7 oslash F8 ugrave F9 uacute FA ucircumflex FB udieresis FC yacute FD thorn FE ydieresis FF ' +
  'OE 152 oe 153 Scaron 160 scaron 161 Ydieresis 178 Zcaron 17D zcaron 17E florin 192 circumflex 2C6 tilde 2DC dotlessi 131 ' +
  'Lslash 141 lslash 142 endash 2013 emdash 2014 quoteleft 2018 quoteright 2019 quotesinglbase 201A quotedblleft 201C ' +
  'quotedblright 201D quotedblbase 201E dagger 2020 daggerdbl 2021 bullet 2022 ellipsis 2026 perthousand 2030 ' +
  'guilsinglleft 2039 guilsinglright 203A fraction 2044 Euro 20AC trademark 2122 minus 2212 fi FB01 fl FB02 ff FB00 ffi FB03 ffl FB04 ' +
  'Alpha 391 Beta 392 Gamma 393 Delta 394 Epsilon 395 Zeta 396 Eta 397 Theta 398 Iota 399 Kappa 39A Lambda 39B Mu 39C Nu 39D Xi 39E ' +
  'Omicron 39F Pi 3A0 Rho 3A1 Sigma 3A3 Tau 3A4 Upsilon 3A5 Phi 3A6 Chi 3A7 Psi 3A8 Omega 3A9 ' +
  'alpha 3B1 beta 3B2 gamma 3B3 delta 3B4 epsilon 3B5 zeta 3B6 eta 3B7 theta 3B8 iota 3B9 kappa 3BA lambda 3BB nu 3BD xi 3BE ' +
  'omicron 3BF pi 3C0 rho 3C1 sigma 3C3 tau 3C4 upsilon 3C5 phi 3C6 chi 3C7 psi 3C8 omega 3C9 ' +
  'summation 2211 product 220F integral 222B radical 221A infinity 221E approxequal 2248 notequal 2260 lessequal 2264 ' +
  'greaterequal 2265 arrowright 2192 arrowleft 2190 arrowup 2191 arrowdown 2193 arrowboth 2194 partialdiff 2202 element 2208 ' +
  'emptyset 2205 intersection 2229 union 222A therefore 2234 proportional 221D similar 223C equivalence 2261 asteriskmath 2217 ' +
  'checkmark 2713 lozenge 25CA'
).split(' ');

const GLYPH_MAP = new Map<string, string>();
for (let i = 0; i < GLYPHS.length; i += 2) GLYPH_MAP.set(GLYPHS[i], String.fromCodePoint(parseInt(GLYPHS[i + 1], 16)));

export function glyphNameToText(name: string): string {
  const known = GLYPH_MAP.get(name);
  if (known !== undefined) return known;
  let m = /^uni([0-9A-Fa-f]{4})/.exec(name);
  if (m) return String.fromCharCode(parseInt(m[1], 16));
  m = /^u([0-9A-Fa-f]{4,6})$/.exec(name);
  if (m) {
    const cp = parseInt(m[1], 16);
    return cp <= 0x10ffff ? String.fromCodePoint(cp) : '';
  }
  if (name.length === 1) return name;
  if (name.includes('.')) return glyphNameToText(name.slice(0, name.indexOf('.')));
  if (name.includes('_')) return name.split('_').map(glyphNameToText).join('');
  return '';
}

// --- base encodings ------------------------------------------------------------

const decodeSingleBytes = (label: string): string[] | null => {
  try {
    const td = new TextDecoder(label);
    const out: string[] = [];
    for (let c = 0; c < 256; c++) {
      if (c < 32) {
        out.push('');
        continue;
      }
      const ch = td.decode(Uint8Array.of(c));
      const cp = ch.codePointAt(0) ?? 0;
      out.push(cp === 0xfffd || (cp >= 0x7f && cp <= 0x9f) ? '' : cp === 0xa0 ? ' ' : cp === 0xad ? '-' : ch);
    }
    return out;
  } catch {
    return null;
  }
};

const WIN_ANSI: string[] = decodeSingleBytes('windows-1252') ?? Array.from({ length: 256 }, (_, c) => (c >= 32 && c < 127 ? String.fromCharCode(c) : ''));
const MAC_ROMAN: string[] = decodeSingleBytes('macintosh') ?? WIN_ANSI;

// Adobe StandardEncoding: ASCII, with the typographic differences in the upper half.
const STANDARD_UPPER: Record<number, string> = {
  0x27: '\u2019', 0x60: '\u2018', 0xa1: '\u00a1', 0xa2: '\u00a2', 0xa3: '\u00a3', 0xa4: '\u2044', 0xa5: '\u00a5', 0xa6: '\u0192',
  0xa7: '\u00a7', 0xa8: '\u00a4', 0xa9: "'", 0xaa: '\u201c', 0xab: '\u00ab', 0xac: '\u2039', 0xad: '\u203a', 0xae: 'fi', 0xaf: 'fl',
  0xb1: '\u2013', 0xb2: '\u2020', 0xb3: '\u2021', 0xb4: '\u00b7', 0xb6: '\u00b6', 0xb7: '\u2022', 0xb8: '\u201a', 0xb9: '\u201e',
  0xba: '\u201d', 0xbb: '\u00bb', 0xbc: '\u2026', 0xbd: '\u2030', 0xbf: '\u00bf', 0xd0: '\u2014', 0xe1: '\u00c6', 0xe3: '\u00aa',
  0xe8: '\u0141', 0xe9: '\u00d8', 0xea: '\u0152', 0xeb: '\u00ba', 0xf1: '\u00e6', 0xf5: '\u0131', 0xf8: '\u0142', 0xf9: '\u00f8',
  0xfa: '\u0153', 0xfb: '\u00df',
};
const STANDARD: string[] = Array.from({ length: 256 }, (_, c) => STANDARD_UPPER[c] ?? (c >= 32 && c < 127 ? String.fromCharCode(c) : ''));

// --- widths of the standard fonts (for PDFs that do not list them) -------------

// Characters 32..126, in thousandths of an em.
const HELVETICA = [
  278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556,
  278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667,
  611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833,
  556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
];
const TIMES = [
  250, 333, 408, 500, 500, 833, 778, 180, 333, 333, 500, 564, 250, 333, 250, 278, 500, 500, 500, 500, 500, 500, 500, 500, 500, 500,
  278, 278, 564, 564, 564, 444, 921, 722, 667, 667, 722, 611, 556, 722, 722, 333, 389, 722, 611, 889, 722, 722, 556, 722, 667, 556,
  611, 722, 722, 944, 722, 722, 611, 333, 278, 333, 469, 500, 333, 444, 500, 444, 500, 444, 333, 500, 500, 278, 278, 500, 278, 778,
  500, 500, 500, 500, 333, 389, 278, 500, 500, 722, 500, 500, 444, 480, 200, 480, 541,
];

function standardWidth(baseFont: string): ((code: number) => number) | null {
  const f = baseFont.toLowerCase();
  if (/courier|mono|consolas|menlo|monaco/.test(f)) return () => 600;
  const table = /times|serif|georgia|garamond|palatino|cambria|bookman|minion/.test(f) && !/sans/.test(f)
    ? TIMES
    : /arial|helvet|sans|calibri|verdana|tahoma|segoe|roboto|lato|open|symbol|dejavu/.test(f)
      ? HELVETICA
      : null;
  if (!table) return null;
  return (code) => (code >= 32 && code <= 126 ? table[code - 32] : 556);
}

// --- ToUnicode CMaps -------------------------------------------------------------

export interface ToUnicode {
  map: Map<number, string>;
  // Bytes per code, from the CMap's codespace ranges (0 when it gives none).
  codeLen: number;
}

const codeOf = (s: string): number => {
  let v = 0;
  for (let i = 0; i < s.length; i++) v = v * 256 + (s.charCodeAt(i) & 255);
  return v;
};

// UTF-16BE bytes (one char per byte in `s`) to a string.
const utf16be = (s: string): string => {
  if (s.length === 1) return String.fromCharCode(s.charCodeAt(0));
  let out = '';
  for (let i = 0; i + 1 < s.length; i += 2) out += String.fromCharCode(((s.charCodeAt(i) & 255) << 8) | (s.charCodeAt(i + 1) & 255));
  return out;
};

export function parseToUnicode(text: string): ToUnicode {
  const map = new Map<number, string>();
  let codeLen = 0;
  const lx = new Lexer(text);
  for (let t = lx.next(); t; t = lx.next()) {
    if (t.t !== 'kw') continue;
    if (t.v === 'begincodespacerange') {
      for (;;) {
        const a = lx.next();
        if (!a || a.t !== 'str') break;
        lx.next();
        if (codeLen === 0 || a.v.length > codeLen) codeLen = a.v.length;
      }
    } else if (t.v === 'beginbfchar') {
      for (;;) {
        const src = lx.next();
        if (!src || src.t !== 'str') break;
        const dst = lx.next();
        if (!dst) break;
        if (dst.t === 'str') map.set(codeOf(src.v), utf16be(dst.v));
      }
    } else if (t.v === 'beginbfrange') {
      for (;;) {
        const lo = lx.next();
        if (!lo || lo.t !== 'str') break;
        const hi = lx.next();
        const dst = lx.next();
        if (!hi || hi.t !== 'str' || !dst) break;
        const from = codeOf(lo.v);
        const to = Math.min(codeOf(hi.v), from + 0xffff);
        if (dst.t === 'str') {
          const base = utf16be(dst.v);
          for (let c = from; c <= to; c++) {
            const k = c - from;
            map.set(c, k === 0 || base.length === 0 ? base : base.slice(0, -1) + String.fromCharCode(base.charCodeAt(base.length - 1) + k));
          }
        } else if (dst.t === '[') {
          for (let c = from; ; c++) {
            const item = lx.next();
            if (!item || item.t === ']') break;
            if (item.t === 'str' && c <= to) map.set(c, utf16be(item.v));
          }
        }
      }
    }
  }
  return { map, codeLen };
}

// --- building a font ----------------------------------------------------------------

function parseCidWidths(doc: PdfDoc, w: PdfObj): Map<number, number> {
  const widths = new Map<number, number>();
  const arr = doc.array(w);
  for (let i = 0; i < arr.length; ) {
    const first = doc.deref(arr[i]);
    const second = doc.deref(arr[i + 1] ?? null);
    if (typeof first !== 'number') {
      i++;
      continue;
    }
    if (Array.isArray(second)) {
      second.forEach((v, k) => widths.set(first + k, numOf(doc.deref(v))));
      i += 2;
    } else if (typeof second === 'number') {
      const width = numOf(doc.deref(arr[i + 2] ?? null));
      for (let c = first; c <= Math.min(second, first + 0xffff); c++) widths.set(c, width);
      i += 3;
    } else {
      i++;
    }
  }
  return widths;
}

function simpleEncoding(doc: PdfDoc, font: Dict, subtype: string): string[] {
  const enc = doc.deref(font.Encoding ?? null);
  const baseName = enc instanceof PdfName ? enc.name : isDict(enc) ? nameOf(doc.deref(enc.BaseEncoding ?? null)) : '';
  const base = baseName === 'WinAnsiEncoding' ? WIN_ANSI : baseName === 'MacRomanEncoding' ? MAC_ROMAN : baseName ? STANDARD : subtype === 'TrueType' ? WIN_ANSI : STANDARD;
  const table = base.slice();
  if (isDict(enc)) {
    let code = 0;
    for (const item of doc.array(enc.Differences ?? null)) {
      const v = doc.deref(item);
      if (typeof v === 'number') code = v;
      else if (v instanceof PdfName) {
        if (code >= 0 && code < 256) table[code] = glyphNameToText(v.name);
        code++;
      }
    }
  }
  return table;
}

const stripSubset = (name: string): string => name.replace(/^[A-Z]{6}\+/, '');

export async function buildFont(doc: PdfDoc, font: Dict): Promise<FontInfo> {
  const subtype = nameOf(doc.deref(font.Subtype ?? null));
  const baseFont = stripSubset(nameOf(doc.deref(font.BaseFont ?? null)));

  let toUni: ToUnicode | null = null;
  const toUniText = await doc.streamText(font.ToUnicode ?? null);
  if (toUniText !== null) toUni = parseToUnicode(toUniText);

  if (subtype === 'Type0') {
    const descendant = doc.dict(doc.array(font.DescendantFonts ?? null)[0] ?? null);
    const dw = numOf(doc.deref(descendant?.DW ?? null), 1000);
    const widths = descendant ? parseCidWidths(doc, descendant.W ?? null) : new Map<number, number>();
    const codeLen = toUni && toUni.codeLen > 0 ? toUni.codeLen : 2; // Identity-H and the other 2-byte CMaps
    return {
      decode(bytes: string): Glyph[] {
        const out: Glyph[] = [];
        for (let i = 0; i + codeLen <= bytes.length; i += codeLen) {
          const code = codeOf(bytes.slice(i, i + codeLen));
          const text = toUni?.map.get(code);
          out.push({ text: text ?? '', width: widths.get(code) ?? dw, space: false, bad: text === undefined });
        }
        return out;
      },
    };
  }

  const encoding = simpleEncoding(doc, font, subtype);
  const first = numOf(doc.deref(font.FirstChar ?? null));
  const widthList = doc.array(font.Widths ?? null).map((w) => numOf(doc.deref(w), NaN));
  const descriptor = doc.dict(font.FontDescriptor ?? null);
  const missing = numOf(doc.deref(descriptor?.MissingWidth ?? null), 0);
  const standard = standardWidth(baseFont);
  return {
    decode(bytes: string): Glyph[] {
      const out: Glyph[] = [];
      for (let i = 0; i < bytes.length; i++) {
        const code = bytes.charCodeAt(i) & 255;
        const mapped = toUni?.map.get(code);
        let text = mapped !== undefined ? mapped : encoding[code];
        if (code === 32 && !text) text = ' ';
        const listed = widthList[code - first];
        const width = Number.isFinite(listed) && listed !== undefined ? listed : standard ? standard(code) : missing || (code === 32 ? 278 : 500);
        out.push({ text, width, space: code === 32, bad: !text && code > 32 });
      }
      return out;
    },
  };
}

