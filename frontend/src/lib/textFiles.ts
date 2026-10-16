// Files attached to a playground message: text, code, PDF and Word (.docx).
//
// The browser reads the file (PDF and Word through lib/docs/) and puts its text in
// the message itself, one block per file:
//
//   <attached_file name="app.py">
//   ...the file's text...
//   </attached_file>
//
// followed by whatever the user typed. So an attached file is just part of the
// message's text: no new route, no database change, and it is saved, resent as
// history and shown after a reload like any other message. This file writes
// that format (buildMessageContent) and reads it back for display
// (parseMessageContent). backend/app/chat_files.py is the server's half: it
// checks the blocks, measures them and enforces the limits.
//
// Safety: a file can contain text that tries to give Kael orders. The model is
// told (models/kael/config.py, system_identity) that everything inside a block
// is the user's data, never instructions, and a file cannot close its own block
// early: any literal "<attached_file" / "</attached_file" in a file's text, or
// in the typed text, is rewritten to "&lt;attached_file" / "&lt;/attached_file"
// here, and the server refuses a message whose tags do not pair up. The typed
// text goes AFTER the blocks, so the last thing the model reads is the user's
// own request.
//
// Cost: attached text is resent with every later turn (like pictures), so each
// level has its own cap. The limits below mirror backend/app/chat_files.py. If
// they disagree, the backend wins: fix this file.

import { isDocError } from './docs/inflate';

export const CHAT_FILE_MAX_PER_MESSAGE = 3;
export const CHAT_FILE_MAX_CHARS = 60_000;
export const CHAT_FILE_MAX_CHARS_PER_MESSAGE = 80_000;
export const CHAT_FILE_MAX_CHARS_PER_CONVERSATION = 240_000;

// A file bigger than this is refused before it is read: even at 60,000
// characters a text file is rarely over a few hundred KB.
const MAX_SOURCE_BYTES = 1_000_000;
// PDF and Word files carry fonts, pictures and styling around their text.
const MAX_DOCUMENT_BYTES = 20_000_000;
const MAX_NAME_CHARS = 120;

export interface ChatFileDraft {
  // Local only: a key for the preview row.
  key: string;
  // Already safe to put inside the tag (see safeName).
  name: string;
  // Set when only part of a long document fits, e.g. "pages 1-23 of 64". It goes
  // into the block's name too, so the model knows the text is partial.
  note: string | null;
  // The file's text, cleaned (line endings, control codes) but not tag-escaped.
  text: string;
  chars: number;
}

// --- which files count as text ----------------------------------------------

const TEXT_EXTENSIONS = new Set([
  'txt', 'md', 'markdown', 'rst', 'log', 'csv', 'tsv', 'json', 'jsonl', 'ndjson', 'yaml', 'yml', 'toml',
  'ini', 'cfg', 'conf', 'properties', 'xml', 'html', 'htm', 'css', 'scss', 'sass', 'less', 'js', 'mjs',
  'cjs', 'jsx', 'ts', 'tsx', 'vue', 'svelte', 'astro', 'py', 'pyi', 'rb', 'php', 'java', 'kt', 'kts',
  'scala', 'groovy', 'gradle', 'c', 'h', 'cc', 'cpp', 'cxx', 'hpp', 'hh', 'cs', 'go', 'rs', 'swift', 'm',
  'mm', 'dart', 'lua', 'pl', 'pm', 'r', 'jl', 'ex', 'exs', 'erl', 'hs', 'clj', 'sql', 'graphql', 'gql',
  'proto', 'sh', 'bash', 'zsh', 'fish', 'bat', 'cmd', 'ps1', 'tf', 'tex', 'bib', 'srt', 'vtt', 'diff',
  'patch', 'gitignore', 'editorconfig', 'dockerfile', 'makefile', 'cmake', 'lock',
]);

// Files with no extension that are text.
const TEXT_FILE_NAMES = new Set([
  'dockerfile', 'makefile', 'readme', 'license', 'licence', 'changelog', 'procfile', 'gemfile', 'rakefile',
  'jenkinsfile', 'vagrantfile', 'codeowners', 'authors', 'notice',
]);

const TEXT_MIME_TYPES = new Set([
  'application/json', 'application/xml', 'application/javascript', 'application/x-javascript',
  'application/typescript', 'application/x-yaml', 'application/yaml', 'application/toml', 'application/sql',
  'application/x-sh', 'application/x-httpd-php', 'application/x-ndjson', 'application/ld+json',
]);

const extensionOf = (name: string): string => {
  const dot = name.lastIndexOf('.');
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : '';
};

// Types we know we cannot read yet, so the message can say so plainly instead of
// "not supported".
const KNOWN_BINARY: Record<string, string> = {
  doc: 'old Word files (.doc)', odt: 'OpenDocument files', rtf: 'RTF files',
  xls: 'Excel files', xlsx: 'Excel files', ods: 'Excel files',
  ppt: 'PowerPoint files', pptx: 'PowerPoint files', odp: 'PowerPoint files',
  mp3: 'audio files', wav: 'audio files', m4a: 'audio files', ogg: 'audio files', flac: 'audio files', aac: 'audio files',
  mp4: 'video files', mov: 'video files', avi: 'video files', mkv: 'video files', webm: 'video files',
  zip: 'zip files', gz: 'zip files', tar: 'zip files', rar: 'zip files', '7z': 'zip files',
};

export type DocumentKind = 'pdf' | 'docx';

// PDF and Word (.docx) files are read in the browser (lib/docs/). Judged by name
// and type; the content is checked again when it is read.
export const documentKind = (file: File): DocumentKind | null => {
  const ext = extensionOf((file.name || '').toLowerCase());
  const type = (file.type || '').toLowerCase();
  if (ext === 'pdf' || type === 'application/pdf') return 'pdf';
  if (ext === 'docx' || type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') return 'docx';
  return null;
};

// True when the file can be attached as text: plain text, code, PDF or Word.
export const isAttachableFile = (file: File): boolean => documentKind(file) !== null || isTextFileCandidate(file);

// True when the file looks like text or code, judged by its type and name (the
// content is checked again when it is read).
export const isTextFileCandidate = (file: File): boolean => {
  const name = (file.name || '').toLowerCase();
  const ext = extensionOf(name);
  if (ext && KNOWN_BINARY[ext]) return false;
  if (ext && TEXT_EXTENSIONS.has(ext)) return true;
  if (!ext && TEXT_FILE_NAMES.has(name)) return true;
  const type = (file.type || '').toLowerCase();
  if (type.startsWith('text/')) return true;
  if (TEXT_MIME_TYPES.has(type)) return true;
  // A dotfile such as ".env.example" or ".prettierrc".
  return name.startsWith('.') && !ext && !type;
};

// The files in a picker, paste or drop event as a plain array.
export const filesFrom = (files: FileList | File[] | null | undefined): File[] => Array.from(files ?? []);

// Why a file that is neither a picture nor text cannot be attached.
export const unsupportedFileMessage = (file: File): string => {
  const name = file.name || 'That file';
  const kind = KNOWN_BINARY[extensionOf((file.name || '').toLowerCase())];
  return kind
    ? `${name} can't be attached yet: ${kind} aren't supported. You can attach pictures, PDF and Word (.docx) files, and text or code files.`
    : `${name} can't be attached. You can attach pictures, PDF and Word (.docx) files, and text or code files.`;
};

// --- reading a file ---------------------------------------------------------

// A literal "<attached_file" or "</attached_file" in a file's text (or in typed
// text) is written as "&lt;attached_file" / "&lt;/attached_file" so it can never
// open or close a real block. Any letter case.
const escapeTags = (s: string): string => s.replace(/<(\/?)attached_file/gi, '&lt;$1attached_file');
const unescapeTags = (s: string): string => s.replace(/&lt;(\/?)attached_file/gi, '<$1attached_file');

// Characters that only get in the way: terminal colour codes in a log, and
// control codes other than tab and newline.
const ANSI_RE = /\u001b\[[0-9;?]*[ -/]*[@-~]/g;
// eslint-disable-next-line no-control-regex
const CONTROL_RE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g;

// What goes inside the tag's name="...": no quote, angle bracket, ampersand or
// control code (each becomes an underscore), trimmed and shortened.
export const safeName = (raw: string): string => {
  // eslint-disable-next-line no-control-regex
  const cleaned = (raw || '').replace(/[\u0000-\u001f"<>&]/g, '_').trim();
  const shortened = cleaned.length > MAX_NAME_CHARS ? `${cleaned.slice(0, MAX_NAME_CHARS - 1)}\u2026` : cleaned;
  return shortened || 'file';
};

const decodeText = (bytes: Uint8Array, name: string): string => {
  let encoding = 'utf-8';
  let start = 0;
  if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
    start = 3;
  } else if (bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xfe) {
    encoding = 'utf-16le';
    start = 2;
  } else if (bytes.length >= 2 && bytes[0] === 0xfe && bytes[1] === 0xff) {
    encoding = 'utf-16be';
    start = 2;
  }
  if (encoding === 'utf-8') {
    // A NUL byte early on means a binary file wearing a text name.
    const probe = Math.min(bytes.length, 8192);
    for (let i = 0; i < probe; i++) {
      if (bytes[i] === 0) throw new Error(`${name} doesn't look like a text file.`);
    }
  }
  const body = bytes.subarray(start);
  try {
    return new TextDecoder(encoding, { fatal: true }).decode(body);
  } catch {
    if (encoding !== 'utf-8') throw new Error(`${name} could not be read as text.`);
    // Not valid UTF-8. Older Windows files (a CSV saved from Excel, say) are
    // usually Windows-1252, which never fails to decode.
    return new TextDecoder('windows-1252').decode(body);
  }
};

const cleanText = (raw: string): string =>
  raw
    .replace(/\r\n?/g, '\n')
    .replace(ANSI_RE, '')
    .replace(CONTROL_RE, '')
    .trimEnd();

const fmt = (n: number): string => n.toLocaleString('en-US');

// Reads `file` into a draft ready to attach. Throws an Error whose message is
// fit to show the user.
export async function prepareChatFile(file: File): Promise<ChatFileDraft> {
  const label = file.name || 'This file';
  const kind = documentKind(file);
  if (kind) return prepareDocument(file, kind, label);
  if (file.size > MAX_SOURCE_BYTES) {
    throw new Error(`${label} is too large (over ${fmt(Math.round(MAX_SOURCE_BYTES / 1000))} KB). Attach a smaller file or the part you need.`);
  }
  let bytes: Uint8Array;
  try {
    bytes = new Uint8Array(await file.arrayBuffer());
  } catch {
    throw new Error(`${label} could not be read.`);
  }
  const text = cleanText(decodeText(bytes, label));
  if (!text.trim()) throw new Error(`${label} is empty.`);
  // Counted the way the server counts it: as it is sent, with any literal
  // "<attached_file" already rewritten (see escapeTags), so a file that passes
  // here is never refused there for a few characters.
  const chars = escapeTags(text).length;
  if (chars > CHAT_FILE_MAX_CHARS) {
    throw new Error(
      `${label} is too long (${fmt(chars)} characters). The limit is ${fmt(CHAT_FILE_MAX_CHARS)} per file. Attach the part you need.`
    );
  }
  return {
    key: `file_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    name: safeName(file.name),
    note: null,
    text,
    chars,
  };
}

// The longest run of whole pieces (pages, paragraphs) that fits `limit`
// characters as sent. `sizes[i]` is piece i's length including the separator
// before it. Returns how many pieces fit (0 when even the first does not).
const piecesThatFit = (sizes: number[], limit: number): number => {
  let used = 0;
  let count = 0;
  for (const size of sizes) {
    if (used + size > limit) break;
    used += size;
    count++;
  }
  return count;
};

// Reads a PDF or Word file into a draft. A document too long for one attachment is
// cut at a page (PDF) or paragraph (Word) boundary and says so in `note`.
async function prepareDocument(file: File, kind: DocumentKind, label: string): Promise<ChatFileDraft> {
  if (file.size > MAX_DOCUMENT_BYTES) {
    throw new Error(`${label} is too large (over ${fmt(Math.round(MAX_DOCUMENT_BYTES / 1_000_000))} MB). Attach a smaller file or the part you need.`);
  }
  let bytes: Uint8Array;
  try {
    bytes = new Uint8Array(await file.arrayBuffer());
  } catch {
    throw new Error(`${label} could not be read.`);
  }

  let parts: string[];
  let total = 1; // pages in the whole document (PDF), or 1
  try {
    // The readers are loaded only when a document is attached, not with the page.
    if (kind === 'pdf') {
      const { extractPdf } = await import('./docs/pdf');
      // Stop reading pages once there is plenty past the limit; the page count still comes back.
      const pdf = await extractPdf(bytes, { stopAfterChars: CHAT_FILE_MAX_CHARS * 2 });
      parts = pdf.pages.map((page, i) => (i === 0 ? page : `\n\n${page}`));
      total = pdf.pageCount;
    } else {
      const { extractDocx } = await import('./docs/docx');
      parts = (await extractDocx(bytes)).parts;
    }
  } catch (err) {
    if (isDocError(err)) throw new Error(`${label}: ${err.message}`);
    throw new Error(`${label} could not be read as a ${kind === 'pdf' ? 'PDF' : 'Word'} file.`);
  }

  const escaped = parts.map((part) => escapeTags(part));
  const fits = piecesThatFit(escaped.map((part) => part.length), CHAT_FILE_MAX_CHARS);
  let text: string;
  let note: string | null = null;
  if (fits === parts.length && (kind !== 'pdf' || parts.length === total)) {
    text = parts.join('');
  } else if (fits > 0) {
    text = parts.slice(0, fits).join('');
    note = kind === 'pdf' ? (fits === 1 ? `page 1 of ${total}` : `pages 1\u2013${fits} of ${total}`) : `first ${Math.max(1, Math.round((escaped.slice(0, fits).join('').length / escaped.join('').length) * 100))}%`;
  } else {
    // Even the first page or paragraph is longer than the limit: cut it at a line break.
    const cut = escaped[0].slice(0, CHAT_FILE_MAX_CHARS);
    const lastBreak = cut.lastIndexOf('\n');
    text = parts[0].slice(0, Math.max(1, lastBreak > CHAT_FILE_MAX_CHARS * 0.5 ? lastBreak : cut.length));
    note = kind === 'pdf' ? `start of page 1, of ${total}` : 'start of the document';
  }
  text = cleanText(text);
  if (!text.trim()) throw new Error(`${label} has no text in it.`);
  return {
    key: `file_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    name: safeName(file.name),
    note,
    text,
    chars: escapeTags(text).length,
  };
}

// Whether `incoming` fits next to the drafts already in the box and the files
// already in the conversation. Null when it fits, else a message for the user.
export function fileDoesNotFit(drafts: ChatFileDraft[], conversationChars: number, incoming: ChatFileDraft): string | null {
  if (drafts.length >= CHAT_FILE_MAX_PER_MESSAGE) {
    return `You can attach up to ${CHAT_FILE_MAX_PER_MESSAGE} files to one message.`;
  }
  const inBox = drafts.reduce((n, d) => n + d.chars, 0);
  if (inBox + incoming.chars > CHAT_FILE_MAX_CHARS_PER_MESSAGE) {
    return `${incoming.name} doesn't fit: the files in one message can hold ${fmt(CHAT_FILE_MAX_CHARS_PER_MESSAGE)} characters in total.`;
  }
  if (conversationChars + inBox + incoming.chars > CHAT_FILE_MAX_CHARS_PER_CONVERSATION) {
    return `A conversation can hold up to ${fmt(CHAT_FILE_MAX_CHARS_PER_CONVERSATION)} characters of attached files. Start a new conversation to attach more.`;
  }
  return null;
}

// --- the message format -----------------------------------------------------

// The name written into a block: the file's name, then the note about a partial
// document. A long file name is shortened first so the note is never the part cut.
const blockName = (f: ChatFileDraft): string => {
  if (!f.note) return f.name;
  const base = f.name.length > 80 ? `${f.name.slice(0, 79)}\u2026` : f.name;
  return `${base} (${f.note})`;
};

// The text of the message to send: one block per file, then what the user typed.
export function buildMessageContent(typed: string, files: ChatFileDraft[]): string {
  const blocks = files.map((f) => `<attached_file name="${blockName(f)}">\n${escapeTags(f.text)}\n</attached_file>`);
  const text = escapeTags(typed.trim());
  return [...blocks, text].filter((part) => part.length > 0).join('\n\n');
}

export interface ShownFile {
  name: string;
  text: string;
  chars: number;
}

export interface ParsedMessage {
  // What the user typed (the message without its file blocks).
  text: string;
  files: ShownFile[];
}

const BLOCK_RE = /<attached_file name="([^"<>&\u0000-\u001f]*)">\n([\s\S]*?)\n<\/attached_file>/g;

// Reads a message's text back into what the user typed and the files. Works on
// anything the server returns, whatever the order. A message without blocks
// comes back as it is.
export function parseMessageContent(content: string): ParsedMessage {
  if (!/attached_file/i.test(content)) return { text: content, files: [] };
  const files: ShownFile[] = [];
  const rest: string[] = [];
  let pos = 0;
  BLOCK_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = BLOCK_RE.exec(content)) !== null) {
    rest.push(content.slice(pos, m.index));
    pos = m.index + m[0].length;
    // `chars` is the length as sent (what the limits count), `text` what to show.
    files.push({ name: m[1] || 'file', text: unescapeTags(m[2]), chars: m[2].length });
  }
  rest.push(content.slice(pos));
  return { text: unescapeTags(rest.join('').replace(/\n{3,}/g, '\n\n')).trim(), files };
}

// Characters of attached-file text in one message (0 for a plain message).
export const attachedFileChars = (content: string): number =>
  /attached_file/i.test(content) ? parseMessageContent(content).files.reduce((n, f) => n + f.chars, 0) : 0;

// "820 chars", "3.4k chars", "46k chars".
export const formatChars = (n: number): string =>
  n < 1000 ? `${n} chars` : `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k chars`;
