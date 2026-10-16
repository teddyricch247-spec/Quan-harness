import Link from 'next/link';
import { BrandMark } from '../components/BrandMark';
import { ROUTES } from '../lib/routes';

// Root-level not-found.tsx: Next.js renders this for ANY route under
// this app that doesn't resolve to a page (unknown URL, typo'd link,
// or — until it was added — /login itself). Without this file, Next
// falls back to its own generic "This page could not be found" text,
// which still renders inside the root layout's AppShell (so it
// inherits the site's fonts/background and, on routes AppShell treats
// as "standalone" like /login, loses the navbar too) — the combination
// reads as an intentional, custom-but-broken page rather than a plain
// 404. This gives it real content and a real way back instead.
export default function NotFound() {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center gap-6 px-6 text-center">
      <BrandMark size={48} />
      <div className="space-y-2">
        <h1 className="text-2xl font-bold text-ink">Page not found</h1>
        <p className="text-sm text-ink-3">
          The page you&apos;re looking for doesn&apos;t exist or may have moved.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <Link
          href={ROUTES.home}
          className="rounded-2xl bg-ink px-5 py-2.5 text-sm font-bold text-white shadow-md hover:bg-ink transition-colors"
        >
          Go home
        </Link>
        <Link
          href={ROUTES.dashboard}
          className="rounded-2xl border border-line bg-white px-5 py-2.5 text-sm font-bold text-ink shadow-none hover:bg-surface transition-colors"
        >
          Go to dashboard
        </Link>
      </div>
    </div>
  );
}
