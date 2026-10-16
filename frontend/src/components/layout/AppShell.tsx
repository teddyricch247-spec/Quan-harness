'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ArrowLeft } from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { ROUTES, normalizePathname } from '../../lib/routes';
import { Navbar } from './Navbar';
import { Footer } from './Footer';
import { LegalBar } from './LegalBar';

export const AppShell: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isLoggedIn } = useApp();
  const pathname = normalizePathname(usePathname());

  // The sign in / sign up page is a standalone experience — no navbar,
  // no footer, no side menu. Just the auth card and a way back home.
  const isStandalone = pathname === ROUTES.login;

  if (isStandalone) {
    return (
      <div className="min-h-dvh flex flex-col bg-surface">
        <div className="w-full px-4 sm:px-6 lg:px-8 pt-6">
          <Link
            href={ROUTES.home}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-ink-3 hover:text-ink transition-colors cursor-pointer"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span>Home</span>
          </Link>
        </div>
        <main className="flex-1 w-full">{children}</main>
        <LegalBar />
      </div>
    );
  }

  // Terms of Service / Privacy Policy are bare documents — no navbar and
  // no footer/LegalBar at all (unlike the login standalone view above).
  // Covers both the canonical routes and their /terms and /privacy
  // aliases, since all four render the same underlying page component.
  const isBareLegalPage =
    pathname === ROUTES.terms ||
    pathname === ROUTES.privacy ||
    pathname === '/terms' ||
    pathname === '/privacy';

  if (isBareLegalPage) {
    return (
      <div className="min-h-dvh flex flex-col bg-white">
        <main className="flex-1 w-full">{children}</main>
      </div>
    );
  }

  // Matches the original rule: logged-in users only see the footer on
  // the docs pages (/docs and /docs/<slug>); signed-out visitors see it on
  // the docs pages and the marketing home page.
  const isDocs = pathname === ROUTES.docs || pathname.startsWith(`${ROUTES.docs}/`);
  const shouldShowFooter = isLoggedIn ? isDocs : (pathname === ROUTES.home || isDocs);

  // The header is position:fixed (it floats over the hero on the home
  // page and needs to keep floating over content as you scroll), so it
  // no longer reserves layout space. The home page's own hero already
  // has enough top padding to clear it; every other page needs the
  // offset added here instead.
  const isHome = pathname === ROUTES.home;

  // The Playground is a full-height app screen: the chat scrolls inside
  // itself and the page must not. It used to be sized with a hard-coded
  // calc(100dvh - 114px) that ignored the footer below it, so the whole page
  // scrolled by the footer's height and the input sat partly off-screen.
  // Here the shell is exactly one viewport tall, <main> takes whatever the
  // navbar offset and the slim legal strip leave, and the page fills it.
  const isPlayground = pathname === ROUTES.playground || pathname.startsWith(`${ROUTES.playground}/`);

  if (isPlayground) {
    return (
      <div className="h-dvh flex flex-col bg-white overflow-hidden">
        <Navbar />
        <main className="flex-1 min-h-0 w-full pt-[82px]">{children}</main>
        <LegalBar compact />
      </div>
    );
  }

  return (
    <div className="min-h-dvh flex flex-col bg-white">
      <Navbar />
      <main className={`flex-1 w-full ${isHome ? '' : 'pt-[114px]'}`}>{children}</main>
      {shouldShowFooter ? <Footer /> : <LegalBar />}
    </div>
  );
};
