"use client";

import Link from "next/link";
import NavBar from "@/components/NavBar";
import AuthGuard from "@/components/AuthGuard";

const ITEMS = [
  { href: "/connections/llm-providers", title: "LLM Providers", desc: "BYOK credentials for the agent." },
  { href: "/connections/github", title: "GitHub Connection", desc: "The sync credential used by Push/Pull. Never reachable by the agent." },
  { href: "/connections/connectors", title: "Connectors", desc: "MCP servers — the only way the agent reaches anything outside its own workspace." },
];

export default function ConnectionsPage() {
  return (
    <AuthGuard>
      <NavBar />
      <main className="max-w-5xl mx-auto px-4 py-6">
        <h1 className="text-lg font-semibold mb-1">Connections</h1>
        <p className="text-sm text-muted mb-6">
          Account-level. Nothing here grants any project anything by itself — grant access from a
          project's own Settings.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {ITEMS.map((i) => (
            <Link key={i.href} href={i.href} className="card hover:border-ink">
              <p className="font-medium text-sm">{i.title}</p>
              <p className="text-sm text-muted mt-1">{i.desc}</p>
            </Link>
          ))}
        </div>
      </main>
    </AuthGuard>
  );
}
