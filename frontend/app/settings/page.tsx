"use client";

import Link from "next/link";
import { useEffect } from "react";
import { ChevronIcon } from "@/components/icons";
import TopBar from "@/components/TopBar";
import { clearReturnTo } from "@/lib/returnTo";

/**
 * Phase Convert (C6): the Settings hub — the one place everything that used to live in the top
 * navigation went. Every row is an existing page at its existing URL (so OAuth callbacks that land
 * on /connections/github keep working); only the entry point changed.
 */
const ROWS: { href: string; title: string; hint: string }[] = [
  { href: "/connections/llm-providers", title: "LLM Providers", hint: "Model keys the agent uses" },
  { href: "/connections/github", title: "GitHub", hint: "Repositories to import, push to and create" },
  { href: "/connections/connectors", title: "Connectors", hint: "External tools the agent can use" },
  { href: "/connections/memory", title: "Memory", hint: "What the agent remembers across sessions" },
  { href: "/account", title: "Account", hint: "Email, sign out, delete account" },
  { href: "/platform-ops", title: "Activity", hint: "Audit log and platform operations" },
];

export default function SettingsPage() {
  // Arriving at the hub means the person is browsing Settings, not mid-way through connecting
  // something for Code home — so the back arrows on its pages should go to the hub again.
  useEffect(() => clearReturnTo(), []);

  return (
    <>
      <TopBar title="Settings" />
      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-4 pb-10">
          <ul className="bg-white border border-line rounded-xl overflow-hidden">
            {ROWS.map((r) => (
              <li key={r.href} className="border-b border-line last:border-b-0">
                <Link href={r.href} className="flex items-center gap-3 px-4 py-3 min-h-[56px] hover:bg-paper">
                  <span className="flex-1 min-w-0">
                    <span className="block font-medium">{r.title}</span>
                    <span className="block text-xs text-muted">{r.hint}</span>
                  </span>
                  <ChevronIcon className="w-4 h-4 text-muted" />
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}
