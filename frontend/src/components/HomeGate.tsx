'use client';

import React, { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useApp } from '../context/AppContext';
import { HomePage } from './pages/HomePage';

// isLoggedIn defaults to false until the Supabase session resolves, so
// the server-rendered / statically-exported HTML for "/" is always the
// marketing HomePage — good for SEO and crawlers.
//
// Logged-in users used to get swapped to <DashboardPage /> in place here,
// which left the URL stuck on "/" while the dashboard was on screen —
// same bug class as the playground sessions issue: app state (auth)
// changing what's rendered without the URL reflecting it. Bookmarking,
// sharing, or refreshing "/" while logged in would all be ambiguous.
//
// Instead, once a session resolves we redirect to the real /dashboard
// route, so the URL always matches what's rendered.
export const HomeGate: React.FC = () => {
  const { isLoggedIn } = useApp();
  const router = useRouter();

  useEffect(() => {
    if (isLoggedIn) {
      router.replace('/dashboard');
    }
  }, [isLoggedIn, router]);

  // Briefly render nothing rather than the marketing page while a
  // logged-in session redirects to /dashboard, avoiding a flash of
  // homepage content for someone who's about to leave "/" anyway.
  if (isLoggedIn) {
    return null;
  }

  return <HomePage />;
};
