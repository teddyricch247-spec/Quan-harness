'use client';

import React, { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useApp } from '../context/AppContext';

// Wrap any protected page's content with this. Blocks the direct-URL hole
// (visiting /dashboard, /admin, /account, /keys, /usage while logged out
// used to render the full page immediately — nothing stopped it).
//
// Waits on `authChecked` (not just `isLoggedIn`) because isLoggedIn starts
// false on every load, logged-in or not, until supabase.auth.getSession()
// resolves — redirecting on isLoggedIn alone would bounce real logged-in
// users to /login for a frame on every refresh.
//
// This is a client-side guard only (this app's Supabase session lives in
// localStorage, not a cookie, so Next.js middleware can't see it without
// migrating to @supabase/ssr). It stops the "any page is reachable by
// typing the URL" hole and matches what the backend already enforces on
// every real API call — it is not, by itself, why the data was safe:
// app/auth.py's require_login/require_admin were already rejecting
// unauthenticated requests before this fix. Treat this as the second,
// now-present layer, not the only one.
export const RequireAuth: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isLoggedIn, authChecked } = useApp();
  const router = useRouter();

  useEffect(() => {
    if (authChecked && !isLoggedIn) {
      router.replace('/login');
    }
  }, [authChecked, isLoggedIn, router]);

  if (!authChecked || !isLoggedIn) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center text-sm text-ink-3">
        Checking your session…
      </div>
    );
  }

  return <>{children}</>;
};
