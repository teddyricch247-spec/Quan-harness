'use client';

import React from 'react';
import Link from 'next/link';
import { ROUTES } from '../../lib/routes';

// A minimal, always-present legal strip (Terms + Privacy) for every page
// that doesn't already render the full marketing <Footer/> (which has its
// own copy of these same two links). Rendered by AppShell so Terms of
// Service and Privacy Policy are reachable from literally every screen in
// the app — dashboard, playground, keys, usage, account, admin, and the
// standalone auth page — not just the marketing home/docs pages. This
// matters both for users and because these are the exact URLs registered
// on the Google OAuth consent screen; Google expects them to be
// discoverable from within the app itself, not just linked from Console.
// `compact` is a single slim row for full-height app screens (the Playground)
// where the default two-line, py-4 strip would eat a visible slice of the chat.
export const LegalBar: React.FC<{ compact?: boolean }> = ({ compact = false }) => {
  return (
    <footer className="border-t border-line bg-white shrink-0">
      <div className={`mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 flex items-center justify-center gap-3 sm:gap-4 text-[11px] text-ink-3 ${compact ? 'py-1.5' : 'py-4 flex-col sm:flex-row gap-2'}`}>
        <span>© {new Date().getFullYear()} Quancis</span>
        <div className="flex items-center gap-3">
          <Link href={ROUTES.terms} className="hover:text-accent-blue transition-colors cursor-pointer">
            Terms of Service
          </Link>
          <span className="text-ink-3/40">•</span>
          <Link href={ROUTES.privacy} className="hover:text-accent-blue transition-colors cursor-pointer">
            Privacy Policy
          </Link>
        </div>
      </div>
    </footer>
  );
};
