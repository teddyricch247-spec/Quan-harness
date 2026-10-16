'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ChevronDown } from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { EXTERNAL, ROUTES, normalizePathname } from '../../lib/routes';
import { DOCS_NAV, DOCS_PAGES, docsHref, getDocsGroupTitle } from './nav';
import { OnThisPage } from './OnThisPage';

// The frame shared by every docs page (app/docs/layout.tsx): a persistent
// sidebar, a section picker on small screens, and "On this page" on wide ones.
// It is a layout, so it stays mounted while you move between docs pages and
// the sidebar keeps its scroll position.

const DocsNav: React.FC<{ activeSlug: string | null; onNavigate?: () => void }> = ({ activeSlug, onNavigate }) => (
  <nav aria-label="Documentation">
    {DOCS_NAV.map((group) => (
      <div key={group.title} className="mb-6">
        <p className="m-0 mb-2 px-3 text-xs font-medium text-ink-3">{group.title}</p>
        <ul className="m-0 list-none space-y-0.5 p-0">
          {group.pages.map((p) => {
            const isActive = p.slug === activeSlug;
            return (
              <li key={p.slug}>
                <Link
                  href={docsHref(p.slug)}
                  onClick={onNavigate}
                  aria-current={isActive ? 'page' : undefined}
                  className={`block rounded-xl px-3 py-1.5 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-blue ${
                    isActive ? 'bg-surface font-medium text-ink' : 'text-ink-2 hover:bg-surface hover:text-ink'
                  }`}
                >
                  {p.title}
                </Link>
              </li>
            );
          })}
        </ul>
      </div>
    ))}
  </nav>
);

export const DocsShell: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isLoggedIn } = useApp();
  const pathname = normalizePathname(usePathname());
  const [menuOpen, setMenuOpen] = useState(false);

  const active = DOCS_PAGES.find((p) => docsHref(p.slug) === pathname) ?? null;
  const activeSlug = active ? active.slug : null;
  const activeGroup = activeSlug ? getDocsGroupTitle(activeSlug) : undefined;

  // Close the mobile picker after navigating, and on Escape.
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [menuOpen]);

  return (
    <div className="mx-auto w-full max-w-[1280px] px-[clamp(20px,4vw,40px)] pb-[clamp(56px,9vh,96px)]">
      <div className="grid gap-x-12 lg:grid-cols-[232px_minmax(0,1fr)] xl:grid-cols-[232px_minmax(0,1fr)_196px]">
        {/* Sidebar (desktop) */}
        <aside className="hidden lg:block">
          <div className="sticky top-[104px] max-h-[calc(100dvh-128px)] overflow-y-auto pb-6 pr-2">
            <DocsNav activeSlug={activeSlug} />
            <div className="mt-2 space-y-3 border-t border-line-soft px-3 pt-5">
              <Link
                href={isLoggedIn ? ROUTES.keys : ROUTES.login}
                className="btn-pill btn-pill-dark !h-10 w-full !px-4 !text-[0.8125rem]"
              >
                {isLoggedIn ? 'Manage API keys' : 'Get an API key'}
              </Link>
              <a
                href={EXTERNAL.wwwDemos}
                className="block text-center text-[0.8125rem] text-ink-2 transition-colors hover:text-ink"
              >
                See Kael in action
              </a>
            </div>
          </div>
        </aside>

        {/* Page */}
        <div className="min-w-0">
          <div className="sticky top-[88px] z-30 -mx-[clamp(20px,4vw,40px)] mb-6 bg-white/90 px-[clamp(20px,4vw,40px)] pb-3 pt-1 backdrop-blur lg:hidden">
            <button
              type="button"
              aria-expanded={menuOpen}
              aria-controls="docs-mobile-nav"
              onClick={() => setMenuOpen((o) => !o)}
              className="flex h-11 w-full cursor-pointer items-center justify-between gap-3 rounded-full border border-line bg-white px-5 text-sm text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-blue"
            >
              <span className="min-w-0 truncate">
                <span className="text-ink-3">{activeGroup ? `${activeGroup} / ` : 'Docs / '}</span>
                <span className="font-medium">{active ? active.title : 'Documentation'}</span>
              </span>
              <ChevronDown
                className={`h-4 w-4 shrink-0 text-ink-3 transition-transform ${menuOpen ? 'rotate-180' : ''}`}
              />
            </button>
            {menuOpen && (
              <div
                id="docs-mobile-nav"
                className="mt-2 max-h-[65dvh] overflow-y-auto rounded-2xl border border-line bg-white p-3 shadow-[0_24px_60px_-30px_rgba(20,22,24,0.35)]"
              >
                <DocsNav activeSlug={activeSlug} onNavigate={() => setMenuOpen(false)} />
              </div>
            )}
          </div>

          {children}
        </div>

        {/* On this page (wide screens) */}
        <aside className="hidden xl:block">
          <div className="sticky top-[104px] max-h-[calc(100dvh-128px)] overflow-y-auto pb-6">
            <OnThisPage pathname={pathname} />
          </div>
        </aside>
      </div>
    </div>
  );
};
