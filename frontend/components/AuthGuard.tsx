"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Session } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabaseClient";

/**
 * Wraps every page under the signed-in area. §4: an unverified account can log in
 * and see its own empty dashboard, but this component's job is only "are you
 * signed in at all" — the email-verification gate itself is enforced server-side
 * on every action that touches real infrastructure (see backend/app/dependencies.py's
 * verified_user), and reflected here only as a banner, never a hard block on
 * viewing pages.
 */
export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [session, setSession] = useState<Session | null | "loading">("loading");

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data: listener } = supabase.auth.onAuthStateChange((_event, s) => setSession(s));
    return () => listener.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (session === null) router.replace("/login");
  }, [session, router]);

  if (session === "loading" || session === null) {
    return <div className="p-8 text-sm text-muted">Loading…</div>;
  }

  const emailConfirmed = Boolean(session.user.email_confirmed_at);

  return (
    <div>
      {!emailConfirmed && (
        <div className="bg-accent-soft border-b border-accent/30 px-4 py-2 text-sm text-accent">
          Verify your email to create projects, connect credentials, or start sessions — check your
          inbox for the confirmation link.
        </div>
      )}
      {children}
    </div>
  );
}
