/** "just now", "5 min ago", "3 h ago", "2 d ago", else a short date. */
export function timeAgo(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const then = new Date(iso);
  const seconds = Math.round((now.getTime() - then.getTime()) / 1000);
  if (Number.isNaN(seconds)) return "";
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 14) return `${days} d ago`;
  return then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** "provider/model-name" → "model-name" — the tail of a provider/model id, for a chip. */
export function shortModel(model: string | null | undefined): string {
  if (!model) return "";
  const tail = model.split("/").pop() ?? model;
  return tail.length > 28 ? `${tail.slice(0, 27)}…` : tail;
}

/** "owner/repo" check for the import field — one slash, no spaces, both halves non-empty. */
export function looksLikeRepo(value: string): boolean {
  return /^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/.test(value.trim());
}
