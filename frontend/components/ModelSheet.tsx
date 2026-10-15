"use client";

import Link from "next/link";
import type { LlmCredential } from "@/lib/types";
import { shortModel } from "@/lib/format";
import { CheckIcon } from "./icons";
import Sheet from "./Sheet";

/**
 * The model chip's sheet. Used twice, with different meanings (C4):
 *  - Code home: picks the model for the project about to be created. The caller maps "the account
 *    default" to *sending nothing*, so the backend falls back to it exactly as `llm_client` does.
 *  - Workspace: changes the *project's* credential (PATCH /projects/{id}) — the same setting as
 *    Project settings, for every session. `note` says so on screen. (PATCH cannot clear a
 *    credential back to "use the default" — null means "no change" — so this always sends an id.)
 *
 * `selectedId` is the credential currently in effect (the account default when nothing is chosen);
 * `onPick` always receives a real credential id.
 */
export default function ModelSheet({
  open,
  onClose,
  credentials,
  selectedId,
  onPick,
  note,
  onLeaveToConnect,
}: {
  open: boolean;
  onClose: () => void;
  credentials: LlmCredential[];
  selectedId: string | null; // null = nothing chosen, so the account default is in effect
  onPick: (credentialId: string) => void;
  note: string;
  onLeaveToConnect?: () => void;
}) {
  const defaultId = credentials.find((c) => c.is_default)?.id ?? null;
  const effective = selectedId ?? defaultId;

  return (
    <Sheet open={open} onClose={onClose} title="Model">
      <p className="px-4 py-3 text-sm text-muted">{note}</p>
      {credentials.length === 0 && <p className="px-4 pb-3 text-sm">No model key is connected yet.</p>}
      <ul>
        {credentials.map((c) => (
          <li key={c.id}>
            <button
              className="row"
              onClick={() => {
                onPick(c.id);
                onClose();
              }}
              aria-pressed={effective === c.id}
            >
              <span className="flex-1 min-w-0">
                <span className="block truncate">{c.label}</span>
                <span className="block truncate text-xs text-muted mono">{shortModel(c.model)}</span>
              </span>
              {c.is_default && <span className="text-xs text-muted">Default</span>}
              {effective === c.id && <CheckIcon />}
            </button>
          </li>
        ))}
      </ul>
      <Link href="/connections/llm-providers" onClick={onLeaveToConnect} className="row text-sm">
        {credentials.length === 0 ? "Connect a model key" : "Add or manage keys"}
      </Link>
    </Sheet>
  );
}
