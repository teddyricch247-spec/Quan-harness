// A small, strict ZIP reader: just enough to open the parts of a Word file
// (.docx is a zip of XML files). Reads the central directory, then inflates only
// the entries asked for. Handles stored and deflated entries; refuses
// password-protected and zip64 archives with a clear message.

import { DocError, inflate } from './inflate';

export interface ZipEntry {
  name: string;
  method: number;
  flags: number;
  compressedSize: number;
  size: number;
  localOffset: number;
}

const u16 = (b: Uint8Array, at: number): number => b[at] | (b[at + 1] << 8);
const u32 = (b: Uint8Array, at: number): number => (b[at] | (b[at + 1] << 8) | (b[at + 2] << 16) | (b[at + 3] << 24)) >>> 0;

const NOT_A_ZIP = "This file isn't a valid Office document.";

export function readZipDirectory(bytes: Uint8Array): Map<string, ZipEntry> {
  if (bytes.length < 22) throw new DocError(NOT_A_ZIP);
  // The end-of-central-directory record sits at the very end, before an optional comment.
  let eocd = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 22 - 0xffff); i--) {
    if (u32(bytes, i) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new DocError(NOT_A_ZIP);
  const count = u16(bytes, eocd + 10);
  const dirSize = u32(bytes, eocd + 12);
  const dirOffset = u32(bytes, eocd + 16);
  if (count === 0xffff || dirSize === 0xffffffff || dirOffset === 0xffffffff) {
    throw new DocError('This file is too large to open here.');
  }
  if (dirOffset + dirSize > bytes.length) throw new DocError(NOT_A_ZIP);

  const entries = new Map<string, ZipEntry>();
  const names = new TextDecoder('utf-8');
  let p = dirOffset;
  for (let n = 0; n < count; n++) {
    if (p + 46 > bytes.length || u32(bytes, p) !== 0x02014b50) throw new DocError(NOT_A_ZIP);
    const flags = u16(bytes, p + 8);
    const method = u16(bytes, p + 10);
    const compressedSize = u32(bytes, p + 20);
    const size = u32(bytes, p + 24);
    const nameLen = u16(bytes, p + 28);
    const extraLen = u16(bytes, p + 30);
    const commentLen = u16(bytes, p + 32);
    const localOffset = u32(bytes, p + 42);
    const name = names.decode(bytes.subarray(p + 46, p + 46 + nameLen));
    if (compressedSize === 0xffffffff || size === 0xffffffff || localOffset === 0xffffffff) {
      throw new DocError('This file is too large to open here.');
    }
    entries.set(name, { name, method, flags, compressedSize, size, localOffset });
    p += 46 + nameLen + extraLen + commentLen;
  }
  return entries;
}

export async function readZipEntry(bytes: Uint8Array, entry: ZipEntry, maxBytes = 48 * 1024 * 1024): Promise<Uint8Array> {
  if (entry.flags & 1) throw new DocError('This file is password-protected. Remove the password and attach it again.');
  const at = entry.localOffset;
  if (at + 30 > bytes.length || u32(bytes, at) !== 0x04034b50) throw new DocError(NOT_A_ZIP);
  const start = at + 30 + u16(bytes, at + 26) + u16(bytes, at + 28);
  const end = start + entry.compressedSize;
  if (end > bytes.length) throw new DocError('This file is damaged and could not be read.');
  const raw = bytes.subarray(start, end);
  if (entry.method === 0) return raw;
  if (entry.method === 8) return inflate(raw, 'deflate-raw', { maxBytes });
  throw new DocError('This file uses a compression this reader does not support.');
}

// The text of one entry (UTF-8), or null when the archive has no such entry.
export async function readZipText(bytes: Uint8Array, dir: Map<string, ZipEntry>, name: string): Promise<string | null> {
  const entry = dir.get(name);
  if (!entry) return null;
  const data = await readZipEntry(bytes, entry);
  return new TextDecoder('utf-8').decode(data);
}
