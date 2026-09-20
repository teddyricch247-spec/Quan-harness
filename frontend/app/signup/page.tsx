"use client";

import { useState } from "react";
import Link from "next/link";
import { supabase } from "@/lib/supabaseClient";
import ErrorBanner from "@/components/ErrorBanner";

export default function SignupPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    // §4: "Signup — email/password/confirmation, calls Supabase Auth's signup
    // endpoint directly from the frontend, which sends a verification email. The
    // account exists immediately but is unverified until the link is clicked."
    const { error } = await supabase.auth.signUp({ email, password });
    setBusy(false);
    if (error) {
      setError(error.message);
      return;
    }
    setSent(true);
  }

  if (sent) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="w-full max-w-sm text-center">
          <h1 className="text-lg font-semibold mb-2">Check your email</h1>
          <p className="text-sm text-muted mb-4">
            We sent a confirmation link to <span className="mono">{email}</span>. Your account exists
            already — you can log in now, but creating a project, connecting a credential, or starting a
            session all need that link clicked first.
          </p>
          <Link href="/login" className="btn-primary inline-flex">
            Go to login
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <h1 className="text-lg font-semibold mb-1">Create an account</h1>
        <p className="text-sm text-muted mb-6">No invite list — anyone can sign up.</p>
        <ErrorBanner message={error} />
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="label">Email</label>
            <input
              className="input"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div>
            <label className="label">Password</label>
            <input
              className="input"
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <button className="btn-primary w-full" disabled={busy}>
            {busy ? "Creating…" : "Sign up"}
          </button>
        </form>
        <div className="mt-4 text-sm text-muted">
          <Link href="/login" className="underline">
            Already have an account? Log in
          </Link>
        </div>
      </div>
    </div>
  );
}
