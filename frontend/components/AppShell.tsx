"use client";

import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Session } from "@supabase/supabase-js";
import { apiFetch, ApiError } from "@/lib/api";
import { useAttention } from "@/lib/useAttention";
import type { Project } from "@/lib/types";
import AuthGuard from "./AuthGuard";
import Drawer from "./Drawer";
import { ShellProvider, Surface } from "./ShellContext";

// Rendered without the shell (C6: "/login, /signup, /reset-password … rendered without the shell").
// "/" is the landing redirect and has nothing to show a drawer for.
const BARE_PREFIXES = ["/login", "/signup", "/reset-password"];

function isBare(pathname: string | null): boolean {
  if (pathname === "/") return true;
  return BARE_PREFIXES.some((p) => pathname === p || pathname?.startsWith(p + "/"));
}

/**
 * Phase Convert (C7): the shell every signed-in route lives in — AuthGuard, the drawer, and the
 * shared state the screens read through useShell() (the project list, attention counts, the
 * current surface). It replaces NavBar and the per-page <AuthGuard><NavBar/><main> wrappers.
 */
export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (isBare(pathname)) return <>{children}</>;
  return (
    <AuthGuard>{(session) => <Shell session={session}>{children}</Shell>}</AuthGuard>
  );
}

function Shell({ session, children }: { session: Session; children: React.ReactNode }) {
  const pathname = usePathname();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const { attention, refresh: refreshAttention } = useAttention(true);

  const surface: Surface = pathname?.startsWith("/ask") ? "chat" : "code";

  const refreshProjects = useCallback(() => {
    apiFetch<Project[]>("/projects")
      .then((list) => {
        setProjects(list);
        setProjectsError(null);
      })
      .catch((e: ApiError) => setProjectsError(e.message));
  }, []);

  useEffect(refreshProjects, [refreshProjects]);

  // Navigating anywhere closes the overlay drawer.
  useEffect(() => setDrawerOpen(false), [pathname]);

  const closeDrawer = useCallback(() => setDrawerOpen(false), []);
  const openDrawer = useCallback(() => setDrawerOpen(true), []);

  const value = useMemo(
    () => ({
      surface,
      openDrawer,
      closeDrawer,
      attention,
      refreshAttention,
      projects,
      projectsError,
      refreshProjects,
      email: session.user.email ?? null,
      emailConfirmed: Boolean(session.user.email_confirmed_at),
    }),
    [surface, openDrawer, closeDrawer, attention, refreshAttention, projects, projectsError, refreshProjects, session]
  );

  return (
    <ShellProvider value={value}>
      <div className="flex flex-1 min-h-0">
        <Drawer open={drawerOpen} onClose={closeDrawer} />
        <main className="flex-1 min-w-0 min-h-0 flex flex-col">{children}</main>
      </div>
    </ShellProvider>
  );
}

