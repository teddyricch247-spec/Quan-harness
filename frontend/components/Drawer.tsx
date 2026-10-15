"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { CHAT_ENABLED } from "@/lib/flags";
import { ChevronIcon, CloseIcon, PlusIcon } from "./icons";
import { useShell } from "./ShellContext";

const RECENT_LIMIT = 10;

/** The wordmark. The one place the red accent lives (C4, "Visual language"). */
export function Logo() {
  return (
    <span className="inline-flex items-center gap-2 font-semibold tracking-tight">
      <span className="inline-block w-3 h-3 rounded-[3px] bg-brand" aria-hidden="true" />
      Quan Harness
    </span>
  );
}

/**
 * Phase Convert (C4, "What does the drawer show?"): the current surface's recent list (projects in
 * Code, chats in Chat), "+ New project" / "+ New chat", "All …", and Settings in the footer. An
 * overlay below 900 px; pinned open at 250 px from 900 px up.
 */
export default function Drawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { surface, projects, projectsError } = useShell();
  const pathname = usePathname();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const recent = (projects ?? []).slice(0, RECENT_LIMIT);

  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-black/30 desk:hidden" onClick={onClose} aria-hidden="true" />}
      <aside
        aria-label="Navigation"
        className={`fixed z-40 inset-y-0 left-0 w-[290px] max-w-[85vw] bg-white border-r border-line flex flex-col transition-transform duration-150 desk:static desk:z-auto desk:translate-x-0 desk:w-[250px] desk:flex-none ${
          open ? "translate-x-0 visible" : "-translate-x-full invisible desk:visible"
        }`}
      >
        <div className="flex items-center justify-between pl-4 pr-2 min-h-[56px] pt-safe-top flex-none">
          <Link href="/" onClick={onClose}>
            <Logo />
          </Link>
          <button onClick={onClose} aria-label="Close menu" className="w-9 h-9 grid place-items-center rounded-lg hover:bg-paper desk:hidden">
            <CloseIcon />
          </button>
        </div>

        {surface === "code" || !CHAT_ENABLED ? (
          <>
            <div className="px-3 pb-2 flex-none">
              <Link href="/projects" onClick={onClose} className="btn-default w-full gap-2">
                <PlusIcon className="w-4 h-4" /> New project
              </Link>
            </div>
            <nav className="flex-1 min-h-0 overflow-y-auto" aria-label="Recent projects">
              {projectsError && <p className="px-4 py-2 text-xs text-accent">{projectsError}</p>}
              {projects === null && !projectsError && <p className="px-4 py-2 text-xs text-muted">Loading…</p>}
              {projects !== null && recent.length === 0 && <p className="px-4 py-2 text-sm text-muted">No projects yet.</p>}
              {recent.length > 0 && <p className="px-4 pt-2 pb-1 text-xs text-muted">Recent</p>}
              {recent.map((p) => {
                const active = pathname === `/projects/${p.id}` || pathname?.startsWith(`/projects/${p.id}/`);
                return (
                  <Link
                    key={p.id}
                    href={`/projects/${p.id}`}
                    onClick={onClose}
                    aria-current={active ? "page" : undefined}
                    className={`flex items-center gap-2 px-4 py-2.5 min-h-[44px] ${active ? "bg-soft" : "hover:bg-paper"}`}
                  >
                    <span className="flex-1 min-w-0">
                      <span className="block truncate text-sm">{p.name}</span>
                      {p.repo_full_name && <span className="block truncate text-xs text-muted mono">{p.repo_full_name}</span>}
                    </span>
                    <StatusDot status={p.status} />
                  </Link>
                );
              })}
              {projects !== null && projects.length > RECENT_LIMIT && (
                <Link href="/projects" onClick={onClose} className="flex items-center justify-between px-4 py-2.5 text-sm text-muted hover:bg-paper">
                  All projects <ChevronIcon />
                </Link>
              )}
            </nav>
          </>
        ) : (
          // Phase 7 slot: the chat list (+ New chat, recent chats, All chats) renders here once the
          // Chat surface exists. CHAT_ENABLED is false until then, so this branch is unreachable today.
          <nav className="flex-1 min-h-0 overflow-y-auto px-3" aria-label="Recent chats">
            <Link href="/ask" onClick={onClose} className="btn-default w-full gap-2">
              <PlusIcon className="w-4 h-4" /> New chat
            </Link>
          </nav>
        )}

        <div className="border-t border-line flex-none pb-safe-bottom">
          <Link
            href="/settings"
            onClick={onClose}
            aria-current={pathname === "/settings" ? "page" : undefined}
            className="flex items-center justify-between px-4 py-3 min-h-[48px] hover:bg-paper"
          >
            Settings <ChevronIcon />
          </Link>
        </div>
      </aside>
    </>
  );
}

/** running = green, waiting for an approval = amber, anything else shows nothing. */
export function StatusDot({ status }: { status: "idle" | "running" | "waiting_approval" | null | undefined }) {
  if (status === "running") return <span className="w-2 h-2 rounded-full bg-ok flex-none" role="img" aria-label="Running" />;
  if (status === "waiting_approval") return <span className="w-2 h-2 rounded-full bg-warn flex-none" role="img" aria-label="Waiting for your approval" />;
  return null;
}
