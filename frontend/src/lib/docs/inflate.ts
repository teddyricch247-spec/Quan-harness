// Decompression for the PDF and Word readers (lib/docs/). No library: the
// browser's own DecompressionStream does the work.
//
// Everything in lib/docs/ runs in the user's browser. A document is read there,
// its text goes into the message (lib/textFiles.ts), and the file itself is never
// uploaded anywhere.

// An error whose message is fit to show the user as it is.
export class DocError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DocError';
  }
}

// True for a DocError even when it comes from another copy of this module (a
// lazily loaded chunk can carry its own), where `instanceof` would say no.
export const isDocError = (err: unknown): err is DocError => err instanceof Error && err.name === 'DocError';

export const canInflate = (): boolean => typeof DecompressionStream !== 'undefined';

// Hard stop on how much one compressed stream may expand to (a "zip bomb" guard).
export const MAX_INFLATED_BYTES = 64 * 1024 * 1024;

const concat = (chunks: Uint8Array[], total: number): Uint8Array => {
  if (chunks.length === 1) return chunks[0];
  const out = new Uint8Array(total);
  let at = 0;
  for (const c of chunks) {
    out.set(c, at);
    at += c.length;
  }
  return out;
};

// `deflate` is the zlib format (PDF streams), `deflate-raw` the bare format (zip
// entries). With `tolerant`, a stream that turns out damaged part-way returns
// what was decoded up to that point instead of failing: a PDF with one bad
// stream should still give its other text.
export async function inflate(
  data: Uint8Array,
  format: 'deflate' | 'deflate-raw',
  options: { maxBytes?: number; tolerant?: boolean } = {}
): Promise<Uint8Array> {
  if (!canInflate()) {
    throw new DocError("This browser can't open this kind of file. Update your browser and try again.");
  }
  const maxBytes = options.maxBytes ?? MAX_INFLATED_BYTES;
  const reader = new Blob([data as BlobPart]).stream().pipeThrough(new DecompressionStream(format)).getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.length;
      if (total > maxBytes) {
        void reader.cancel().catch(() => {});
        throw new DocError('This file expands to more data than can be read here.');
      }
      chunks.push(value);
    }
  } catch (err) {
    if (isDocError(err)) throw err;
    if (!options.tolerant) throw new DocError('This file is damaged and could not be read.');
  }
  return concat(chunks, total);
}
