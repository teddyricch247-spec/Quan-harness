"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabaseClient";
import { HOME_PATH } from "@/lib/flags";

// Phase Convert (C6): landing logic. `CHAT_ENABLED ? /ask : /projects` for a signed-in person.
export default function RootPage() {
  const router = useRouter();

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      router.replace(data.session ? HOME_PATH : "/login");
    });
  }, [router]);

  return <div className="p-8 text-sm text-muted">Loading…</div>;
}
