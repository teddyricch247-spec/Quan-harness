'use client';

import React from 'react';
import Link from 'next/link';
import { useApp } from '../../context/AppContext';
import { EXTERNAL, ROUTES, docsPath } from '../../lib/routes';
import { BrandMark } from '../BrandMark';

export const Footer: React.FC = () => {
  const { isLoggedIn } = useApp();

  return (
    <footer className="border-t border-line-soft px-[clamp(20px,5vw,48px)] pt-[clamp(60px,9vh,96px)] pb-[46px]">
      <div className="grid grid-cols-1 md:grid-cols-[1.6fr_1fr_1fr] gap-x-20 gap-y-10 max-w-[1160px] mx-auto">
        <div>
          <span className="flex items-center gap-2 font-semibold text-[1.0625rem] tracking-[-0.015em] text-ink">
            <BrandMark size={24} />
            uancis
          </span>
          <p className="mt-4 max-w-[320px] text-sm leading-relaxed text-ink-2">
            The world&apos;s first composite intelligence. Engineered for high-precision autonomous agents.
          </p>
        </div>

        <div>
          <h4 className="mb-4 text-xs font-medium uppercase tracking-[0.13em] text-ink-3">Platform</h4>
          <ul className="flex flex-col gap-2.5 text-sm">
            <li>
              <Link href={ROUTES.playground} className="text-ink-2 hover:text-ink transition-colors cursor-pointer">
                Playground &amp; Chat
              </Link>
            </li>
            <li>
              <Link href={isLoggedIn ? ROUTES.dashboard : ROUTES.login} className="text-ink-2 hover:text-ink transition-colors cursor-pointer">
                Dashboard
              </Link>
            </li>
            <li>
              <Link href={isLoggedIn ? ROUTES.keys : ROUTES.login} className="text-ink-2 hover:text-ink transition-colors cursor-pointer">
                API Keys
              </Link>
            </li>
            <li>
              <Link href={isLoggedIn ? ROUTES.usage : ROUTES.login} className="text-ink-2 hover:text-ink transition-colors cursor-pointer">
                Cost &amp; Cache
              </Link>
            </li>
          </ul>
        </div>

        <div>
          <h4 className="mb-4 text-xs font-medium uppercase tracking-[0.13em] text-ink-3">Developers</h4>
          <ul className="flex flex-col gap-2.5 text-sm">
            <li>
              <Link href={docsPath('endpoints')} className="text-ink-2 hover:text-ink transition-colors cursor-pointer">
                API Reference
              </Link>
            </li>
            <li>
              <Link href={docsPath('caching')} className="text-ink-2 hover:text-ink transition-colors cursor-pointer">
                Prompt Caching
              </Link>
            </li>
            <li>
              <Link href={ROUTES.docs} className="text-ink-2 hover:text-ink transition-colors cursor-pointer">
                Technical Docs
              </Link>
            </li>
            <li>
              <a href={EXTERNAL.wwwDemos} className="text-ink-2 hover:text-ink transition-colors cursor-pointer">
                Kael Demos
              </a>
            </li>
          </ul>
        </div>
      </div>

      <div className="max-w-[1160px] mx-auto mt-[clamp(56px,8vh,88px)] flex flex-wrap items-center justify-between gap-4 text-[0.8125rem] text-ink-3">
        <span>© {new Date().getFullYear()} Quancis. OpenAI drop-in compatible.</span>
        <div className="flex flex-wrap gap-5">
          <Link href={ROUTES.terms} className="hover:text-ink transition-colors cursor-pointer">
            Terms of Service
          </Link>
          <Link href={ROUTES.privacy} className="hover:text-ink transition-colors cursor-pointer">
            Privacy Policy
          </Link>
        </div>
      </div>
    </footer>
  );
};
