"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import NavBar from "@/components/NavBar";
import AuthGuard from "@/components/AuthGuard";
import ConfirmTypedAction from "@/components/ConfirmTypedAction";
import ErrorBanner from "@/components/ErrorBanner";
import { supabase } from "@/lib/supabaseClient";
import { apiFetch, ApiError } from "@/lib/api";

function AccountManager() {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      setEmail(data.user?.email ?? null);
      setConfirmed(Boolean(data.user?.email_confirmed_at));
    });
  }, []);

  async function deleteAccount() {
    try {
      await apiFetch("/account", { method: "DELETE", body: JSON.stringify({ confirmation: "DELETE" }) });
      await supabase.auth.signOut();
      router.replace("/login");
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  return (
    <div className="max-w-lg space-y-6">
      <h1 className="text-lg font-semibold">Account</h1>
      <ErrorBanner message={error} />

      <section className="card space-y-1">
        <p className="text-sm">
          <span className="text-muted">Email:</span> {email}
        </p>
        <p className="text-sm">
          <span className="text-muted">Status:</span>{" "}
          {confirmed ? <span className="text-ok">Verified</span> : <span className="text-accent">Unverified</span>}
        </p>
        <p className="text-sm text-muted">Every account is a peer — no roles, no admin tier.</p>
      </section>

      <section className="card space-y-3 border-accent/40">
        <p className="font-medium text-sm text-accent">Delete account</p>
        <p className="text-sm text-muted">
          Cascades to every project, session, credential, and piece of memory owned by this account.
          Does not touch any real GitHub resource or any connector's own platform.
        </p>
        <ConfirmTypedAction requiredText="DELETE" onConfirm={deleteAccount} />
      </section>
    </div>
  );
}

export default function AccountPage() {
  return (
    <AuthGuard>
      <NavBar />
      <main className="max-w-5xl mx-auto px-4 py-6">
        <AccountManager />
      </main>
    </AuthGuard>
  );
}
