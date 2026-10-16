import type { Metadata } from 'next';
import { LoginPage } from '../../components/pages/LoginPage';

// This file was missing entirely — /login had no route, so Next.js
// rendered its default not-found fallback (inside AppShell's
// isStandalone shell, which strips the navbar/footer, making the
// generic "page could not be found" text look like an intentional,
// bare "custom" 404 rather than the built-in one). LoginPage itself
// was fully built in components/pages/LoginPage.tsx; it just had no
// app/ route pointing at it. Not wrapped in RequireAuth — this page is
// for signed-OUT visitors; LoginPage's own effect already redirects to
// /dashboard if isLoggedIn is true (e.g. a stale bookmark).
export const metadata: Metadata = {
  title: 'Sign in — Quancis',
  robots: { index: false, follow: false },
};

export default function Page() {
  return <LoginPage />;
}
