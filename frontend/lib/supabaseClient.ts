"use client";

import { createClient } from "@supabase/supabase-js";

// §4 of the spec: "Signup ... calls Supabase Auth's signup endpoint directly from
// the frontend." This client is used for every auth action (signup, login,
// password reset, session refresh) — never for reading application tables
// directly; all of that goes through the backend API (lib/api.ts), which is the
// only thing that talks to the data model.
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL as string;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY as string;

if (!supabaseUrl || !supabaseAnonKey) {
  // Surfaced loudly rather than failing silently on every auth call — this is the
  // single most common "it doesn't work" cause for a fresh checkout.
  // eslint-disable-next-line no-console
  console.warn(
    "NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY are not set — copy " +
      "frontend/.env.local.example to frontend/.env.local and fill them in."
  );
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
