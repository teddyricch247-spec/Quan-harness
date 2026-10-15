"use client";

import { useState } from "react";
import { supabase } from "@/lib/supabaseClient";

/** "Resend" for the confirmation email — used by the unverified-account banner and by Code home
 * when POST /projects answers `email_not_verified` (C4, "Flow B" failure table). */
export default function ResendVerification({ email }: { email: string | null | undefined }) {
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  if (!email) return null;

  async function resend() {
    setState("sending");
    const { error } = await supabase.auth.resend({ type: "signup", email: email as string });
    setState(error ? "error" : "sent");
  }

  return (
    <button onClick={resend} disabled={state === "sending" || state === "sent"} className="underline disabled:no-underline disabled:opacity-70">
      {state === "sent" ? "Sent — check your inbox" : state === "error" ? "Couldn't send — try again" : state === "sending" ? "Sending…" : "Resend"}
    </button>
  );
}
