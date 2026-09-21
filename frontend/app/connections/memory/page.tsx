"use client";

import { useEffect, useState } from "react";
import NavBar from "@/components/NavBar";
import AuthGuard from "@/components/AuthGuard";
import ErrorBanner from "@/components/ErrorBanner";
import { apiFetch, ApiError } from "@/lib/api";
import { BuildUserMemory } from "@/lib/types";

function AccountMemory() {
  const [memoryMd, setMemoryMd] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function load() {
    apiFetch<BuildUserMemory>("/account/memory")
      .then((m) => {
        setMemoryMd(m.memory_md);
        setLoaded(true);
      })
      .catch((e: ApiError) => setError(e.message));
  }

  useEffect(load, []);

  async function save() {
    setError(null);
    try {
      const updated = await apiFetch<BuildUserMemory>("/account/memory", {
        method: "PUT",
        body: JSON.stringify({ memory_md: memoryMd }),
      });
      setMemoryMd(updated.memory_md);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  async function clear() {
    setError(null);
    try {
      const cleared = await apiFetch<BuildUserMemory>("/account/memory", { method: "DELETE" });
      setMemoryMd(cleared.memory_md);
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  return (
    <div className="max-w-lg space-y-6">
      <h1 className="text-lg font-semibold">Memory</h1>
      <p className="text-sm text-muted">
        General preferences and working habits the agent has picked up on its own, across every
        project on this account — never anything project-specific. Written automatically after a
        session completes or gets stuck; most sessions leave this unchanged. You can view, edit, or
        clear it here at any time — the agent never sees or changes this directly.
      </p>
      <ErrorBanner message={error} />
      {saved && <p className="text-sm text-ok">Saved.</p>}

      <section className="card space-y-3">
        {!loaded ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : (
          <>
            <textarea
              className="input min-h-[240px] mono"
              value={memoryMd}
              onChange={(e) => setMemoryMd(e.target.value)}
              placeholder="Nothing recorded yet."
            />
            <div className="flex gap-2">
              <button className="btn-primary" onClick={save}>
                Save
              </button>
              <button className="btn-danger" onClick={clear} disabled={!memoryMd}>
                Clear
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

export default function AccountMemoryPage() {
  return (
    <AuthGuard>
      <NavBar />
      <main className="max-w-5xl mx-auto px-4 py-6">
        <AccountMemory />
      </main>
    </AuthGuard>
  );
}
