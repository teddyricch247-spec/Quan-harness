// Pure (no Supabase, no fetch) so the error contract can be exercised on its own.

/** Reads FastAPI's `detail` in either shape: a string, `{code, message}`, or a validation list. */
export function parseErrorDetail(body: unknown, fallback: string): { message: string; code?: string } {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return { message: detail };
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const d = detail as { code?: unknown; message?: unknown };
    if (typeof d.message === "string") {
      return { message: d.message, code: typeof d.code === "string" ? d.code : undefined };
    }
  }
  if (Array.isArray(detail)) {
    // 422 validation errors: [{loc, msg, type}, …]
    const msgs = detail.map((e) => (e as { msg?: string }).msg).filter(Boolean);
    if (msgs.length) return { message: msgs.join("; ") };
  }
  return { message: body ? JSON.stringify(body) : fallback };
}
