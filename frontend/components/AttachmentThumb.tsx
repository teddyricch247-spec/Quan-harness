"use client";

import { useEffect, useState } from "react";
import { attachmentObjectUrl } from "@/lib/attachments";

/**
 * Phase 6.1: one picture a person sent, shown in the transcript. The API needs the Bearer token, so this can't be an
 * <img src> pointing at it — attachmentObjectUrl fetches it with the token and hands back a blob: URL, revoked when
 * the thumbnail goes away. A picture that has expired (or was never kept) shows its file name instead.
 */
export default function AttachmentThumb({ sessionId, id, filename, width, height }: { sessionId: string; id: string; filename: string; width: number; height: number }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    let made: string | null = null;
    attachmentObjectUrl(sessionId, id).then(
      (u) => {
        if (!live) {
          URL.revokeObjectURL(u);
          return;
        }
        made = u;
        setUrl(u);
      },
      () => {
        if (live) setFailed(true);
      }
    );
    return () => {
      live = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [sessionId, id]);

  if (failed) return <span className="text-[11px] opacity-70 border border-white/30 rounded-lg px-2 py-1 truncate max-w-[160px]">{filename}</span>;
  if (!url) return <span className="inline-block w-24 h-24 rounded-lg bg-white/10" role="img" aria-label={`Loading ${filename}`} />;
  return <img src={url} alt={filename} width={width || undefined} height={height || undefined} className="max-h-48 max-w-full w-auto h-auto rounded-lg object-contain bg-white/10" />;
}
