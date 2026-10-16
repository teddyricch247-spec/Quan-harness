// Regression checks for the document readers (src/lib/docs/), the attach flow
// (src/lib/textFiles.ts) and the history window (src/lib/historyWindow.ts).
//
// Run from frontend/:   npx tsx scripts/test-docs.ts
//
// No fixtures on disk and no libraries: the PDF and Word files are built here,
// byte by byte, so what is being tested is visible. (Node's zlib is used only to
// compress test data.) Exits with a failure code if any check fails.

import { deflateRawSync, deflateSync } from 'node:zlib';
import { extractDocx } from '../src/lib/docs/docx';
import { extractPdf } from '../src/lib/docs/pdf';
import { firstMessageKaelReads } from '../src/lib/historyWindow';
import { buildMessageContent, parseMessageContent, prepareChatFile } from '../src/lib/textFiles';
import type { ChatMessage } from '../src/types';

let failures = 0;
const check = (name: string, ok: boolean) => {
  if (!ok) failures++;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}`);
};
const fails = async (fn: () => Promise<unknown>, needle: string): Promise<boolean> => {
  try {
    await fn();
    return false;
  } catch (e) {
    return e instanceof Error && e.message.includes(needle);
  }
};

// --- building PDFs -------------------------------------------------------------

const esc = (s: string) => s.replace(/[\\()]/g, (c) => `\\${c}`);
const text = (x: number, y: number, size: number, s: string) => `BT /F1 ${size} Tf ${x} ${y} Td (${esc(s)}) Tj ET\n`;

interface PdfOptions {
  compress?: boolean;
  objectStream?: boolean;
  rotate?: number;
  encrypted?: boolean;
}

function makePdf(pages: string[], opts: PdfOptions = {}): Uint8Array {
  const kids = pages.map((_, i) => `${4 + i * 2} 0 R`).join(' ');
  const font = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>';
  const packed: Array<[number, string]> = [
    [2, `<< /Type /Pages /Kids [${kids}] /Count ${pages.length} >>`],
    [3, font],
  ];
  const out: Buffer[] = [];
  const push = (s: string | Buffer) => out.push(typeof s === 'string' ? Buffer.from(s, 'latin1') : s);
  push('%PDF-1.5\n');
  push('1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n');
  if (opts.objectStream) {
    const header = packed.map(([n], i) => `${n} ${i === 0 ? 0 : packed.slice(0, i).reduce((a, p) => a + p[1].length + 1, 0)}`).join(' ');
    const data = `${header}\n${packed.map((p) => p[1]).join('\n')}`;
    push(`9 0 obj\n<< /Type /ObjStm /N ${packed.length} /First ${header.length + 1} /Length ${data.length} >>\nstream\n${data}\nendstream\nendobj\n`);
  } else {
    for (const [n, o] of packed) push(`${n} 0 obj\n${o}\nendobj\n`);
  }
  pages.forEach((content, i) => {
    const rotate = opts.rotate ? ` /Rotate ${opts.rotate}` : '';
    push(`${4 + i * 2} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]${rotate} /Resources << /Font << /F1 3 0 R >> >> /Contents ${5 + i * 2} 0 R >>\nendobj\n`);
    if (opts.compress) {
      const z = deflateSync(Buffer.from(content, 'latin1'));
      push(`${5 + i * 2} 0 obj\n<< /Filter /FlateDecode /Length ${z.length} >>\nstream\n`);
      push(z);
      push('\nendstream\nendobj\n');
    } else {
      push(`${5 + i * 2} 0 obj\n<< /Length ${content.length} >>\nstream\n${content}\nendstream\nendobj\n`);
    }
  });
  if (opts.encrypted) push('trailer\n<< /Root 1 0 R /Encrypt 99 0 R >>\n');
  else push('trailer\n<< /Root 1 0 R >>\n');
  push('%%EOF\n');
  return new Uint8Array(Buffer.concat(out));
}

// --- building Word files -----------------------------------------------------------

const crc = (() => {
  const table = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  return (b: Buffer) => {
    let c = 0xffffffff;
    for (const x of b) c = table[(c ^ x) & 255] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
})();

function makeZip(files: Record<string, string>): Uint8Array {
  const parts: Buffer[] = [];
  const central: Buffer[] = [];
  let offset = 0;
  for (const [name, content] of Object.entries(files)) {
    const raw = Buffer.from(content, 'utf8');
    const data = deflateRawSync(raw);
    const nameBuf = Buffer.from(name);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(8, 8);
    local.writeUInt32LE(crc(raw), 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(raw.length, 22);
    local.writeUInt16LE(nameBuf.length, 26);
    parts.push(local, nameBuf, data);
    const cd = Buffer.alloc(46);
    cd.writeUInt32LE(0x02014b50, 0);
    cd.writeUInt16LE(20, 4);
    cd.writeUInt16LE(20, 6);
    cd.writeUInt16LE(8, 10);
    cd.writeUInt32LE(crc(raw), 16);
    cd.writeUInt32LE(data.length, 20);
    cd.writeUInt32LE(raw.length, 24);
    cd.writeUInt16LE(nameBuf.length, 28);
    cd.writeUInt32LE(offset, 42);
    central.push(cd, nameBuf);
    offset += 30 + nameBuf.length + data.length;
  }
  const dir = Buffer.concat(central);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(Object.keys(files).length, 8);
  end.writeUInt16LE(Object.keys(files).length, 10);
  end.writeUInt32LE(dir.length, 12);
  end.writeUInt32LE(offset, 16);
  return new Uint8Array(Buffer.concat([...parts, dir, end]));
}

const W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"';
const wp = (t: string, ppr = '') => `<w:p>${ppr ? `<w:pPr>${ppr}</w:pPr>` : ''}<w:r><w:t xml:space="preserve">${t}</w:t></w:r></w:p>`;

function makeDocx(bodyXml: string): Uint8Array {
  return makeZip({
    '[Content_Types].xml': '<Types/>',
    'word/document.xml': `<?xml version="1.0"?><w:document ${W}><w:body>${bodyXml}</w:body></w:document>`,
    'word/styles.xml': `<w:styles ${W}><w:style w:type="paragraph" w:styleId="H1"><w:name w:val="heading 1"/></w:style></w:styles>`,
    'word/numbering.xml': `<w:numbering ${W}><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/></w:lvl></w:abstractNum><w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num><w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num></w:numbering>`,
    'word/_rels/document.xml.rels': '<Relationships><Relationship Id="rId5" Type="x" Target="https://example.com/a?b=1&amp;c=2" TargetMode="External"/></Relationships>',
  });
}

const fileOf = (bytes: Uint8Array, name: string, type = '') => new File([bytes as BlobPart], name, { type });

// --- the checks ------------------------------------------------------------------------

async function main() {
  // PDF: lines, paragraphs, escapes
  {
    const page = text(50, 700, 11, 'First line of a paragraph (with parens)') + text(50, 686, 11, 'second line of the same paragraph') + text(50, 640, 11, 'A new paragraph after a gap');
    for (const [label, opts] of [['plain', {}], ['compressed', { compress: true }], ['object stream', { objectStream: true }]] as const) {
      const r = await extractPdf(makePdf([page], opts));
      check(`pdf (${label}): lines and paragraph break`, r.pages[0] === '[Page 1]\nFirst line of a paragraph (with parens)\nsecond line of the same paragraph\n\nA new paragraph after a gap');
    }
  }
  // PDF: running headers and page numbers
  {
    const pages = [1, 2, 3, 4, 5].map((n) => text(50, 770, 9, 'Annual Report 2026') + text(50, 600, 11, `Unique body text number ${n}`) + text(300, 20, 9, `Page ${n}`));
    const r = await extractPdf(makePdf(pages));
    check('pdf: repeated header and page numbers are dropped', r.pages.every((p, i) => p === `[Page ${i + 1}]\nUnique body text number ${i + 1}`));
  }
  // PDF: two columns read left then right
  {
    let c = '';
    for (let i = 0; i < 12; i++) c += text(54, 700 - i * 12, 10, `left column line ${i} with enough words to be running text`);
    for (let i = 0; i < 12; i++) c += text(320, 700 - i * 12, 10, `right column line ${i} with enough words to be running text`);
    const body = (await extractPdf(makePdf([c]))).pages[0];
    check('pdf: two columns are read one after the other', body.indexOf('left column line 11') < body.indexOf('right column line 0'));
  }
  // PDF: a table keeps its rows
  {
    let c = '';
    for (let i = 0; i < 12; i++) c += text(50, 700 - i * 14, 10, `Item${i}`) + text(300, 700 - i * 14, 10, `${i * 3}`);
    const body = (await extractPdf(makePdf([c]))).pages[0];
    check('pdf: a short-cell table stays row by row', body.includes('Item3\t9') && body.indexOf('Item3') < body.indexOf('Item4'));
  }
  // PDF: rotated page drawn sideways reads as upright text
  {
    const c = 'BT /F1 12 Tf 0 1 -1 0 112 72 Tm (Sideways title line) Tj ET\nBT /F1 12 Tf 0 1 -1 0 127 72 Tm (Sideways second line) Tj ET\n';
    const body = (await extractPdf(makePdf([c], { rotate: 90 }))).pages[0];
    check('pdf: text drawn sideways on a rotated page is read upright', body.includes('Sideways title line') && body.indexOf('title') < body.indexOf('second'));
  }
  // PDF: refusals
  check('pdf: no text layer is refused with a reason', await fails(() => extractPdf(makePdf(['0.5 g 20 20 200 100 re f\n'])), 'no selectable text'));
  check('pdf: encrypted is refused', await fails(() => extractPdf(makePdf([text(50, 700, 11, 'secret secret secret')], { encrypted: true })), 'password'));
  check('pdf: not a pdf is refused', await fails(() => extractPdf(new Uint8Array([80, 75, 3, 4, 0, 0])), 'valid PDF'));

  // Word
  {
    const body =
      wp('Quarterly Report', '<w:pStyle w:val="H1"/>') +
      wp('Revenue &amp; costs: 12% &lt;year&gt;') +
      `<w:p><w:r><w:t xml:space="preserve">See </w:t></w:r><w:hyperlink r:id="rId5"><w:r><w:t>the page</w:t></w:r></w:hyperlink></w:p>` +
      wp('One', '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>') +
      wp('Two', '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>') +
      wp('Step', '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="2"/></w:numPr>') +
      wp('Step again', '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="2"/></w:numPr>') +
      `<w:tbl><w:tr><w:tc>${wp('A')}</w:tc><w:tc>${wp('B')}</w:tc></w:tr><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>${wp('wide')}</w:tc></w:tr></w:tbl>` +
      `<mc:AlternateContent><mc:Choice><w:p><w:r><w:t>boxed once</w:t></w:r></w:p></mc:Choice><mc:Fallback><w:p><w:r><w:t>boxed twice</w:t></w:r></w:p></mc:Fallback></mc:AlternateContent>` +
      `<w:p><w:r><w:delText>deleted words</w:delText></w:r><w:r><w:t>kept words</w:t></w:r></w:p>`;
    const text = (await extractDocx(makeDocx(body))).parts.join('');
    check('docx: heading, entities, link', text.startsWith('# Quarterly Report\n\nRevenue & costs: 12% <year>\n\nSee [the page](https://example.com/a?b=1&c=2)'));
    check('docx: bullets and numbers', text.includes('- One\n- Two') && text.includes('1. Step\n2. Step again'));
    check('docx: table with a merged cell', text.includes('| A | B |\n| --- | --- |\n| wide |  |'));
    check('docx: text box read once, deleted text left out', text.includes('boxed once') && !text.includes('boxed twice') && text.includes('kept words') && !text.includes('deleted words'));
    check('docx: not a word file is refused', await fails(() => extractDocx(makeZip({ 'a.txt': 'x' })), "isn't a Word document"));
    check('docx: not a zip is refused', await fails(() => extractDocx(new Uint8Array(40)), 'valid Office document'));
  }

  // Attach flow: a long PDF is cut at a page and says so
  {
    const pages = Array.from({ length: 120 }, (_, i) => {
      let c = '';
      for (let l = 0; l < 40; l++) c += text(50, 750 - l * 17, 10, `Page ${i + 1} line ${l} lorem ipsum dolor sit amet consectetur adipiscing`);
      return c;
    });
    const draft = await prepareChatFile(fileOf(makePdf(pages, { compress: true }), 'big.pdf', 'application/pdf'));
    const kept = Number(/pages 1\u2013(\d+) of 120/.exec(draft.note ?? '')?.[1]);
    check('attach: a long pdf is cut at a page boundary with a note', kept > 1 && kept < 120 && draft.chars <= 60_000 && draft.text.includes(`[Page ${kept}]`) && !draft.text.includes(`[Page ${kept + 1}]`));
    const parsed = parseMessageContent(buildMessageContent('summarise', [draft]));
    check('attach: the note travels in the block name', parsed.files[0].name === `big.pdf (${draft.note})` && parsed.text === 'summarise');
    const whole = await prepareChatFile(fileOf(makePdf([text(50, 700, 11, 'Short document with a little text in it')]), 'small.pdf'));
    check('attach: a short pdf is whole, with no note', whole.note === null && whole.text.includes('Short document'));
  }

  // History window
  {
    const m = (id: string, role: 'user' | 'assistant', content: string, extra: Partial<ChatMessage> = {}): ChatMessage => ({ id, role, content, timestamp: '', model: '', ...extra });
    const small = [m('msg_welcome', 'assistant', 'Hi'), m('1', 'user', 'a'), m('2', 'assistant', 'b')];
    check('history: a short chat is read whole', firstMessageKaelReads(small) === null);
    const over = [m('msg_welcome', 'assistant', 'Hi'), m('1', 'user', 'a'.repeat(250_000)), m('2', 'assistant', 'b'.repeat(100_000)), m('3', 'user', 'c'.repeat(100_000)), m('4', 'assistant', 'ok')];
    check('history: the oldest turns fall out of view first', firstMessageKaelReads(over) === 3);
    const failed = [m('msg_welcome', 'assistant', 'Hi'), m('1', 'user', 'x'.repeat(500_000)), m('2', 'assistant', '', { error: 'boom' })];
    check('history: a send that failed never counts', firstMessageKaelReads(failed) === null);
  }

  console.log(failures ? `\n${failures} CHECK(S) FAILED` : '\nALL CHECKS PASSED');
  process.exit(failures ? 1 : 0);
}

void main();
