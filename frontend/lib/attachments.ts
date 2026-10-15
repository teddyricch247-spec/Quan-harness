"use client";

/**
 * Phase 6.1 (step 19) — picture attachments for the message box. The chat/message UI is not built yet; this is the
 * part of it that has to be right regardless of how it looks, so the box can be a thin shell over three calls:
 *
 *   const picked = await prepareImage(file);                 // shrink + re-encode in the browser
 *   const meta = await uploadAttachment(sessionId, picked);  // -> { id, filename, ... }
 *   await sendMessageWithAttachments(sessionId, text, [meta.id]);
 *
 * What prepareImage does, and why it is not optional:
 *   - longest side to MAX_SIDE (1568px — what the providers downscale to anyway, so nothing visible is lost and the
 *     upload stays small), and a hard size cap matching the server's (MAX_BYTES, 3 MiB);
 *   - it redraws the picture onto a canvas, which DROPS camera metadata (GPS position, device, timestamps) before
 *     anything leaves the browser. (An animated GIF becomes its first frame, for the same reason.)
 * The server re-checks everything from the file's own bytes; this only keeps honest uploads small and clean.
 *
 * Showing a picture back (a thumbnail in the transcript) can't be an <img src> pointing at the API: that request
 * would carry no Authorization header. attachmentObjectUrl fetches it with the token and returns a blob: URL —
 * call URL.revokeObjectURL on it when the thumbnail goes away.
 */
import { ApiError, apiFetch } from "./api";
import { supabase } from "./supabaseClient";

export const MAX_SIDE = 1568;
export const MAX_BYTES = 3 * 1024 * 1024;
export const MAX_IMAGES_PER_MESSAGE = 4;
export const ACCEPTED_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"] as const;
/** For <input type="file" accept=...>. HEIC is listed because phones hand it over and the browser can usually decode it. */
export const ACCEPT_ATTRIBUTE = [...ACCEPTED_TYPES, "image/heic", "image/heif"].join(",");

/** The metadata the server returns for an upload, and stores on the user's message event. Never the pixels. */
export interface AttachmentMeta {
  id: string;
  filename: string;
  media_type: (typeof ACCEPTED_TYPES)[number];
  width: number;
  height: number;
  byte_size: number;
}

export interface PreparedImage {
  filename: string;
  mediaType: "image/png" | "image/jpeg";
  base64: string; // bare base64, no data: prefix
  width: number;
  height: number;
  byteSize: number;
  /** a blob: URL for showing the picture in the message box before sending; revoke it when done */
  previewUrl: string;
}

export class ImageNotUsable extends Error {}

function canvasToBlob(canvas: HTMLCanvasElement, type: string, quality?: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new ImageNotUsable("That image couldn't be read."));
    reader.onload = () => {
      const result = String(reader.result);
      resolve(result.slice(result.indexOf(",") + 1));
    };
    reader.readAsDataURL(blob);
  });
}

export async function prepareImage(file: File): Promise<PreparedImage> {
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new ImageNotUsable("That file isn't an image this browser can open. Use PNG, JPEG, WebP or GIF.");
  }
  try {
    let scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    // PNG first (a screenshot's text stays sharp); if that is too big, JPEG; if that is still too big, smaller.
    for (let attempt = 0; attempt < 5; attempt++) {
      const width = Math.max(1, Math.round(bitmap.width * scale));
      const height = Math.max(1, Math.round(bitmap.height * scale));
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d");
      if (!context) throw new ImageNotUsable("This browser can't process images.");
      context.drawImage(bitmap, 0, 0, width, height);

      let blob = await canvasToBlob(canvas, "image/png");
      let mediaType: PreparedImage["mediaType"] = "image/png";
      if (!blob || blob.size > MAX_BYTES) {
        blob = await canvasToBlob(canvas, "image/jpeg", 0.85);
        mediaType = "image/jpeg";
      }
      if (blob && blob.size <= MAX_BYTES) {
        const stem = file.name.replace(/\.[^.]*$/, "") || "image";
        return {
          filename: `${stem}.${mediaType === "image/png" ? "png" : "jpg"}`,
          mediaType,
          base64: await blobToBase64(blob),
          width,
          height,
          byteSize: blob.size,
          previewUrl: URL.createObjectURL(blob),
        };
      }
      scale *= 0.75;
    }
    throw new ImageNotUsable("That image is too large to attach even after shrinking it.");
  } finally {
    bitmap.close();
  }
}

/** Uploads one prepared picture to a session. Throws ApiError (its message is a sentence for the person). */
export async function uploadAttachment(sessionId: string, image: PreparedImage): Promise<AttachmentMeta> {
  return apiFetch<AttachmentMeta>(`/sessions/${encodeURIComponent(sessionId)}/attachments`, {
    method: "POST",
    body: JSON.stringify({ filename: image.filename, media_type: image.mediaType, data_base64: image.base64 }),
  });
}

/** Sends a message that carries already-uploaded pictures. Pass the ids in the order they were attached. */
export async function sendMessageWithAttachments(sessionId: string, text: string, attachmentIds: string[]) {
  if (attachmentIds.length > MAX_IMAGES_PER_MESSAGE) {
    throw new ImageNotUsable(`At most ${MAX_IMAGES_PER_MESSAGE} images can be attached to one message.`);
  }
  return apiFetch<{ session_id: string; status: string }>(`/sessions/${encodeURIComponent(sessionId)}/messages`, {
    method: "POST",
    body: JSON.stringify({ text, attachment_ids: attachmentIds }),
  });
}

/** Same, for a message sent while a turn is running (the interrupt path). */
export async function sendInterruptWithAttachments(sessionId: string, text: string, attachmentIds: string[]) {
  return apiFetch<{ session_id: string; status: string }>(`/sessions/${encodeURIComponent(sessionId)}/interrupt`, {
    method: "POST",
    body: JSON.stringify({ text, attachment_ids: attachmentIds }),
  });
}

/** A blob: URL for a picture already on the server (a thumbnail in the transcript). Revoke it when finished. */
export async function attachmentObjectUrl(sessionId: string, attachmentId: string): Promise<string> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );
  if (!res.ok) throw new ApiError(res.status, res.status === 404 ? "That picture is no longer available." : res.statusText);
  return URL.createObjectURL(await res.blob());
}

/** The attachments on a user message/interrupt event's content, [] if none (the shape the server writes). */
export function attachmentsOf(content: Record<string, unknown>): AttachmentMeta[] {
  const items = content?.attachments;
  return Array.isArray(items) ? (items.filter((a) => a && typeof a === "object" && "id" in a) as AttachmentMeta[]) : [];
}
