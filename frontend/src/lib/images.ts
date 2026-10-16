// Pictures attached to a playground message.
//
// Every picture is shrunk in the browser before it is sent: longest side at
// most 1568 px, re-encoded as JPEG. That keeps a phone photo (often 4-8 MB) to a
// few hundred KB, which is faster to upload, cheaper for the model to read
// (pictures are billed as input tokens, and a bigger picture is not read any
// better past about this size), and well inside the backend's own limits
// (chat_history.MAX_IMAGE_BYTES, 3 MB each).
//
// The limits below mirror backend/app/chat_history.py. If they disagree, the
// backend wins: fix this file.

export const CHAT_IMAGE_MAX_PER_MESSAGE = 4;
export const CHAT_IMAGE_MAX_PER_CONVERSATION = 20;

// Longest side after shrinking, and the size (decoded bytes) a picture is
// squeezed under. Both are well under the backend's limits.
const MAX_SIDE_PX = 1568;
const TARGET_BYTES = 1_200_000;
// A file this big is refused before the browser tries to decode it.
const MAX_SOURCE_BYTES = 40 * 1024 * 1024;

export interface ChatImageDraft {
  // Local only: a key for the preview row.
  key: string;
  // base64 of the JPEG, no "data:" prefix: what the backend takes.
  data: string;
  mime: 'image/jpeg';
  // Object URL of the shrunken picture, for the preview. Release it with
  // releaseChatImage() when the draft is removed or sent.
  previewUrl: string;
  name: string;
}

export const releaseChatImage = (draft: Pick<ChatImageDraft, 'previewUrl'>): void => {
  try {
    URL.revokeObjectURL(draft.previewUrl);
  } catch {
    // Nothing to release.
  }
};

const isImageFile = (file: File): boolean => {
  if (file.type) return file.type.startsWith('image/');
  // Some browsers leave the type empty for HEIC/HEIF from a phone.
  return /\.(jpe?g|png|webp|gif|bmp|heic|heif|avif)$/i.test(file.name);
};

interface Decoded {
  source: CanvasImageSource;
  width: number;
  height: number;
  close: () => void;
}

// Decodes with the browser's own decoder (so whatever it can show, it can
// attach), applying the photo's EXIF rotation.
const decode = async (file: File): Promise<Decoded> => {
  if (typeof createImageBitmap === 'function') {
    try {
      const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
      return { source: bitmap, width: bitmap.width, height: bitmap.height, close: () => bitmap.close() };
    } catch {
      // Fall through to an <img>: some browsers reject options or formats here.
    }
  }
  const url = URL.createObjectURL(file);
  try {
    const el = new Image();
    el.decoding = 'async';
    el.src = url;
    await el.decode();
    return { source: el, width: el.naturalWidth, height: el.naturalHeight, close: () => URL.revokeObjectURL(url) };
  } catch {
    URL.revokeObjectURL(url);
    throw new Error(`${file.name || 'This file'} could not be read as a picture.`);
  }
};

const toJpegBlob = (canvas: HTMLCanvasElement, quality: number): Promise<Blob> =>
  new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error('The picture could not be prepared.'))),
      'image/jpeg',
      quality
    );
  });

const blobToBase64 = (blob: Blob): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('The picture could not be prepared.'));
    reader.onload = () => {
      const result = String(reader.result || '');
      const comma = result.indexOf(',');
      resolve(comma >= 0 ? result.slice(comma + 1) : '');
    };
    reader.readAsDataURL(blob);
  });

// Shrinks `file` to a JPEG draft ready to attach. Throws an Error whose message
// is fit to show the user.
export async function prepareChatImage(file: File): Promise<ChatImageDraft> {
  const name = file.name || 'picture';
  if (!isImageFile(file)) throw new Error(`${name} is not a picture.`);
  if (/svg/i.test(file.type) || /\.svg$/i.test(name)) throw new Error('SVG files cannot be attached. Use a PNG or JPEG.');
  if (file.size > MAX_SOURCE_BYTES) throw new Error(`${name} is too large (over ${MAX_SOURCE_BYTES / (1024 * 1024)} MB).`);

  const decoded = await decode(file);
  try {
    if (!decoded.width || !decoded.height) throw new Error(`${name} could not be read as a picture.`);
    let scale = Math.min(1, MAX_SIDE_PX / Math.max(decoded.width, decoded.height));
    let blob: Blob | null = null;
    // Up to a few passes: first by quality, then by size, until it is small enough.
    for (let pass = 0; pass < 6; pass++) {
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(decoded.width * scale));
      canvas.height = Math.max(1, Math.round(decoded.height * scale));
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('This browser cannot prepare pictures.');
      // JPEG has no transparency: put a transparent PNG/GIF on white, not black.
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(decoded.source, 0, 0, canvas.width, canvas.height);
      for (const quality of [0.88, 0.8, 0.7]) {
        blob = await toJpegBlob(canvas, quality);
        if (blob.size <= TARGET_BYTES) break;
      }
      if (blob && blob.size <= TARGET_BYTES) break;
      scale *= 0.8;
    }
    if (!blob || blob.size === 0) throw new Error(`${name} could not be prepared.`);
    const data = await blobToBase64(blob);
    if (!data) throw new Error(`${name} could not be prepared.`);
    const key = `img_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    return { key, data, mime: 'image/jpeg', previewUrl: URL.createObjectURL(blob), name };
  } finally {
    decoded.close();
  }
}

// The picture files in a file list or a paste/drop (everything else is ignored).
export const pictureFilesFrom = (files: FileList | File[] | null | undefined): File[] =>
  Array.from(files ?? []).filter(isImageFile);
