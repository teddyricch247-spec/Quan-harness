"use client";

import Link from "next/link";
import { ChevronIcon } from "./icons";
import Sheet from "./Sheet";

export type MenuAction = "push" | "pull" | "checkpoints" | "deploy" | "secrets" | "sessions" | "rename";

/**
 * Phase Convert (C4, "Where do Push, Pull, Checkpoints, Deploy, Secrets, Sessions and Settings
 * live?"): one ⋯ menu. Deploy is also one tap away on the Preview tab; Push stays two taps for now
 * (C4 says to revisit with real usage). Project settings is a link, not a sheet — it keeps its URL
 * and its content.
 */
export default function ProjectMenuSheet({
  open,
  onClose,
  projectId,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  onSelect: (action: MenuAction) => void;
}) {
  const item = (action: MenuAction, label: string, hint?: string) => (
    <li key={action}>
      <button
        className="row"
        onClick={() => {
          onClose();
          onSelect(action);
        }}
      >
        <span className="flex-1">
          <span className="block">{label}</span>
          {hint && <span className="block text-xs text-muted">{hint}</span>}
        </span>
        <ChevronIcon />
      </button>
    </li>
  );

  return (
    <Sheet open={open} onClose={onClose} title="Project">
      <ul>
        {item("push", "Push", "Send the workspace to GitHub")}
        {item("pull", "Pull", "Make the workspace match GitHub")}
        {item("checkpoints", "Checkpoints", "Restore an earlier state")}
        {item("deploy", "Deploy")}
        {item("secrets", "Preview secrets", "Keys the running preview needs")}
        {item("sessions", "Sessions")}
        {item("rename", "Rename")}
        <li>
          <Link href={`/projects/${projectId}/settings`} className="row" onClick={onClose}>
            <span className="flex-1">
              <span className="block">Project settings</span>
              <span className="block text-xs text-muted">Credentials, connectors, limits, memory, schedules, delete</span>
            </span>
            <ChevronIcon />
          </Link>
        </li>
      </ul>
    </Sheet>
  );
}
