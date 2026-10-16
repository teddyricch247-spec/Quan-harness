'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useApp } from '../../context/AppContext';
import { EXTERNAL, ROUTES, normalizePathname } from '../../lib/routes';
import { BrandMark } from '../BrandMark';
import {
  ArrowUpRight,
  Bot,
  Gamepad2,
  Key,
  LayoutDashboard,
  BookOpen,
  BarChart3,
  Sparkles,
  LogIn,
  LogOut,
  Settings,
  ShieldCheck,
  Tag,
  X,
} from 'lucide-react';

export const Navbar: React.FC = () => {
  const { isLoggedIn, logout, user } = useApp();
  const pathname = normalizePathname(usePathname());
  const [menuOpen, setMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  const isAdmin = user?.role === 'admin';
  const isHome = pathname === ROUTES.home;

  // The hero on the home page is dark, so the header starts transparent
  // with light text there and crosses over to the glass pill once the
  // page scrolls past the hero. Every other page has no dark hero, so
  // the header is always in the "scrolled" glass-pill state.
  useEffect(() => {
    if (!isHome) {
      setScrolled(true);
      return;
    }
    setScrolled(window.scrollY > 40);
    const onScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, [isHome]);

  useEffect(() => {
    document.body.style.overflow = menuOpen ? 'hidden' : '';
    return () => {
      document.body.style.overflow = '';
    };
  }, [menuOpen]);

  const isNavLinkActive = (href: string) =>
    pathname === href ||
    ((href === ROUTES.playground || href === ROUTES.docs) && pathname.startsWith(`${href}/`));

  const navLinks = isLoggedIn
    ? [
        { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
        { id: 'playground', label: 'Playground & Chat', icon: Bot },
        { id: 'keys', label: 'API Keys', icon: Key },
        { id: 'pricing', label: 'Pricing', icon: Tag },
        { id: 'docs', label: 'Docs & API', icon: BookOpen },
        { id: 'usage', label: 'Usage & Cost', icon: BarChart3 },
        ...(isAdmin ? [{ id: 'admin', label: 'Admin Analytics', icon: ShieldCheck }] : []),
      ]
    : [
        { id: 'home', label: 'Overview', icon: Sparkles },
        { id: 'playground', label: 'Playground', icon: Bot },
        { id: 'pricing', label: 'Pricing', icon: Tag },
        { id: 'docs', label: 'Docs & API', icon: BookOpen },
      ];

  const logoHref = isLoggedIn ? ROUTES.dashboard : ROUTES.home;
  const headerLight = isHome && !scrolled;

  return (
    <>
      <header
        className={`fixed left-1/2 -translate-x-1/2 z-[100] flex items-center justify-between transition-all duration-700 ease-out ${
          scrolled
            ? 'site-header-glass top-3.5 w-[calc(100%-32px)] max-w-[1240px] h-[60px] rounded-full pl-6 pr-3.5 bg-white/[0.23]'
            : 'top-0 w-full h-[76px] px-[clamp(20px,5vw,48px)] bg-transparent'
        } ${menuOpen ? 'opacity-0 pointer-events-none' : 'opacity-100'}`}
      >
        <Link
          href={logoHref}
          className={`flex items-center gap-2 font-semibold text-[1.0625rem] tracking-[-0.015em] cursor-pointer ${
            headerLight ? 'text-white' : 'text-ink'
          }`}
        >
          <BrandMark size={26} />
          <span>uancis</span>
        </Link>

        <button
          onClick={() => setMenuOpen(true)}
          aria-label="Open menu"
          aria-expanded={menuOpen}
          className={`relative w-11 h-11 -mr-2.5 flex flex-col items-center justify-center gap-[7px] cursor-pointer ${
            headerLight ? 'text-white' : 'text-ink'
          }`}
        >
          <span className="block w-[22px] h-[2px] rounded-full bg-current" />
          <span className="block w-[22px] h-[2px] rounded-full bg-current" />
        </button>
      </header>

      {/* Slide-in glass drawer */}
      <div
        className={`fixed inset-0 z-[200] transition-[visibility] ${
          menuOpen ? 'visible' : 'invisible delay-700'
        }`}
      >
        <div
          onClick={() => setMenuOpen(false)}
          className={`absolute inset-0 bg-[rgba(20,22,24,0.18)] backdrop-blur-[3px] transition-opacity duration-500 ${
            menuOpen ? 'opacity-100' : 'opacity-0'
          }`}
        />

        <aside
          role="dialog"
          aria-modal="true"
          aria-label="Site navigation"
          className={`menu-panel-glass absolute top-0 right-0 h-full w-[min(420px,92vw)] border-l border-white/60 shadow-[-40px_0_100px_-30px_rgba(20,22,24,0.20)] flex flex-col transition-transform duration-700 ease-out ${
            menuOpen ? 'translate-x-0' : 'translate-x-full'
          }`}
        >
          <div className="flex-none flex items-center justify-between px-7 py-5 border-b border-line-soft">
            <span className="flex items-center gap-2 font-semibold text-[1.0625rem] tracking-[-0.015em] text-ink">
              <BrandMark size={24} />
              uancis
            </span>
            <button
              onClick={() => setMenuOpen(false)}
              aria-label="Close menu"
              className="w-10 h-10 grid place-items-center rounded-full text-ink-2 hover:bg-surface hover:text-ink transition-colors cursor-pointer"
            >
              <X className="h-[18px] w-[18px]" strokeWidth={1.7} />
            </button>
          </div>

          <div className="flex-1 flex flex-col justify-center px-7 py-8 overflow-y-auto">
            <nav className="flex flex-col gap-1">
              {navLinks.map((link, i) => {
                const href = ROUTES[link.id as keyof typeof ROUTES];
                const isActive = isNavLinkActive(href);
                return (
                  <Link
                    key={link.id}
                    href={href}
                    onClick={() => setMenuOpen(false)}
                    className={`flex items-center gap-3 py-2 text-[1.5rem] font-medium tracking-[-0.03em] transition-opacity cursor-pointer ${
                      menuOpen ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-8'
                    } ${isActive ? 'text-accent-blue' : 'text-ink hover:opacity-55'}`}
                    style={{ transitionDelay: menuOpen ? `${0.1 + i * 0.06}s` : '0s', transitionDuration: '0.5s' }}
                  >
                    <link.icon className="h-5 w-5 flex-none opacity-60" strokeWidth={1.7} />
                    {link.label}
                  </Link>
                );
              })}
              {/* Kael demos live on the public www site, so this is a plain
                  link out (same tab), shown signed in or out. */}
              <a
                href={EXTERNAL.wwwDemos}
                onClick={() => setMenuOpen(false)}
                className={`flex items-center gap-3 py-2 text-[1.5rem] font-medium tracking-[-0.03em] text-ink transition-opacity cursor-pointer hover:opacity-55 ${
                  menuOpen ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-8'
                }`}
                style={{ transitionDelay: menuOpen ? `${0.1 + navLinks.length * 0.06}s` : '0s', transitionDuration: '0.5s' }}
              >
                <Gamepad2 className="h-5 w-5 flex-none opacity-60" strokeWidth={1.7} />
                Kael Demos
                <ArrowUpRight className="h-4 w-4 flex-none opacity-45" strokeWidth={1.7} aria-hidden="true" />
              </a>
            </nav>
          </div>

          <div className="flex-none px-7 py-5 border-t border-line-soft flex flex-col gap-2.5">
            {isLoggedIn ? (
              <>
                <Link
                  href={ROUTES.account}
                  onClick={() => setMenuOpen(false)}
                  className={`flex items-center gap-3 p-3 rounded-2xl border transition-colors cursor-pointer ${
                    pathname === ROUTES.account
                      ? 'border-accent-blue-border bg-accent-blue-soft'
                      : 'border-line hover:bg-surface'
                  }`}
                >
                  <div className="h-9 w-9 flex-none rounded-full bg-accent-blue text-white grid place-items-center text-[0.9375rem] font-medium">
                    {user?.name ? user.name.split(' ').map((n) => n[0]).join('').substring(0, 2).toUpperCase() : 'Q'}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-[0.9375rem] font-semibold text-ink truncate">
                      {user?.name || 'Account'}
                      {isAdmin && (
                        <span className="px-1.5 py-px rounded-md bg-accent-blue-soft border border-accent-blue-border text-accent-blue text-[0.625rem] font-semibold uppercase tracking-wider">
                          Admin
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-ink-3 truncate">{user?.email || 'developer@quancis.space'}</div>
                  </div>
                  <Settings className="h-4 w-4 flex-none text-ink-3" />
                </Link>
                <button
                  onClick={() => {
                    logout();
                    setMenuOpen(false);
                  }}
                  className="flex items-center justify-center gap-2 w-full h-[46px] rounded-xl bg-danger-soft text-danger text-[0.9375rem] font-medium hover:bg-[#FDE7E5] transition-colors cursor-pointer"
                >
                  <LogOut className="h-4 w-4" strokeWidth={1.7} />
                  Sign Out
                </button>
              </>
            ) : (
              <Link
                href={ROUTES.login}
                onClick={() => setMenuOpen(false)}
                className="btn-pill btn-pill-glass-dark w-full"
              >
                <LogIn className="h-4 w-4" strokeWidth={1.7} />
                Sign In
              </Link>
            )}
          </div>
        </aside>
      </div>
    </>
  );
};
