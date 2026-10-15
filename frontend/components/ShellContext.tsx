"use client";

import { createContext, useContext } from "react";
import type { AttentionOut, Project } from "@/lib/types";

export type Surface = "chat" | "code";

export interface ShellValue {
  surface: Surface;
  openDrawer: () => void;
  closeDrawer: () => void;
  attention: AttentionOut;
  refreshAttention: () => void;
  // The Code project list, shared by the drawer and Code home so the two never disagree. `null`
  // until the first load finishes. Pages call refreshProjects() after anything that changes it
  // (create, rename, delete).
  projects: Project[] | null;
  projectsError: string | null;
  refreshProjects: () => void;
  email: string | null;
  emailConfirmed: boolean;
}

const Ctx = createContext<ShellValue | null>(null);

export const ShellProvider = Ctx.Provider;

export function useShell(): ShellValue {
  const value = useContext(Ctx);
  if (!value) throw new Error("useShell() must be used inside <AppShell>.");
  return value;
}
