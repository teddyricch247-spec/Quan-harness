"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { supabase } from "@/lib/supabaseClient";

const LINKS = [
  { href: "/projects", label: "Projects" },
  { href: "/connections", label: "Connections" },
  { href: "/platform-ops", label: "Platform Ops" },
  { href: "/account", label: "Account" },
];

export default function NavBar() {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  async function signOut() {
    await supabase.auth.signOut();
    router.replace("/login");
  }

  return (
    <header className="border-b border-line bg-white">
      <div className="max-w-5xl mx-auto px-4">
        <div className="h-14 flex items-center justify-between">
          <Link href="/projects" className="font-semibold tracking-tight">
            Quan Harness
          </Link>

          {/* Desktop nav */}
          <nav className="hidden sm:flex items-center gap-1">
            {LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                className={`px-3 py-1.5 rounded-md text-sm ${
                  pathname?.startsWith(l.href) ? "bg-paper font-medium" : "text-muted hover:text-ink"
                }`}
              >
                {l.label}
              </Link>
            ))}
            <button onClick={signOut} className="ml-2 btn-default text-sm py-1.5">
              Sign out
            </button>
          </nav>

          {/* Mobile: single hamburger, collapses to one column — §11.1/§11.2's
              mobile pattern applied to nav generally, not just the Workspace screen. */}
          <button
            className="sm:hidden btn-default py-1.5 px-3"
            onClick={() => setOpen((o) => !o)}
            aria-label="Menu"
          >
            {open ? "Close" : "Menu"}
          </button>
        </div>

        {open && (
          <nav className="sm:hidden flex flex-col gap-1 pb-3">
            {LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                onClick={() => setOpen(false)}
                className={`px-3 py-2 rounded-md text-sm ${
                  pathname?.startsWith(l.href) ? "bg-paper font-medium" : "text-muted"
                }`}
              >
                {l.label}
              </Link>
            ))}
            <button onClick={signOut} className="text-left px-3 py-2 rounded-md text-sm text-muted">
              Sign out
            </button>
          </nav>
        )}
      </div>
    </header>
  );
}
