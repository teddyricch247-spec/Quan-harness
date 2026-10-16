'use client';

import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'motion/react';
import { EXTERNAL, ROUTES } from '../../lib/routes';
import { Sparkles, Globe2, ArrowUp, MessageCircle, Braces, Check, Copy } from 'lucide-react';
import { HeroCanvas } from '../three/HeroCanvas';
import { BETA, PRO_BETA, usd } from '../docs/facts';

// "Create An Account" CTAs open the login page directly in sign-up mode
// (LoginPage reads ?mode=signup). Plain ROUTES.login opens in sign-in mode.
const SIGNUP_HREF = `${ROUTES.login}?mode=signup`;

type Lang = 'python' | 'typescript' | 'curl' | 'langchain';

const CODE_SNIPPETS: Record<Lang, string> = {
  python: `import openai

# Quancis is 100% drop-in compatible with the OpenAI SDK.
client = openai.OpenAI(
    api_key="sk-quan-...",
    base_url="https://api.quancis.space/v1",
)

response = client.chat.completions.create(
    model="kael-beta",
    messages=[
        {"role": "system", "content": "You are a helpful coding assistant."},
        {"role": "user", "content": "Refactor our distributed cache..."},
    ],
)

print(response.choices[0].message.content)`,
  typescript: `import OpenAI from "openai";

const client = new OpenAI({
  apiKey: process.env.QUANCIS_API_KEY,
  baseURL: "https://api.quancis.space/v1",
});

const response = await client.chat.completions.create({
  model: "kael-beta",
  messages: [
    { role: "system", content: "You are a helpful coding assistant." },
    { role: "user", content: "Refactor our distributed cache..." },
  ],
});

console.log(response.choices[0].message.content);`,
  curl: `curl https://api.quancis.space/v1/chat/completions \\
  -H "Authorization: Bearer $QUANCIS_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "kael-beta",
    "messages": [
      {"role": "user", "content": "Refactor our distributed cache..."}
    ]
  }'`,
  langchain: `from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="kael-beta",
    api_key="sk-quan-...",
    base_url="https://api.quancis.space/v1",
)

llm.invoke("Refactor our distributed cache...")`,
};

const TABS: { id: Lang; label: string }[] = [
  { id: 'python', label: 'Python' },
  { id: 'typescript', label: 'TypeScript' },
  { id: 'curl', label: 'cURL' },
  { id: 'langchain', label: 'LangChain' },
];

export const HomePage: React.FC = () => {
  const [tab, setTab] = useState<Lang>('python');
  const [copied, setCopied] = useState(false);
  const [reasoningOn, setReasoningOn] = useState(false);
  const [webOn, setWebOn] = useState(false);

  // +1 when the newly-selected tab is to the right of the previous one in
  // TABS, -1 when it's to the left. Drives which way the code panel slides
  // (see codeVariants below) so "Python -> TypeScript" visibly moves right,
  // matching the direction the glass indicator (below) slides too.
  const [direction, setDirection] = useState(1);
  const handleTabChange = (next: Lang) => {
    if (next === tab) return;
    const from = TABS.findIndex((t) => t.id === tab);
    const to = TABS.findIndex((t) => t.id === next);
    setDirection(to > from ? 1 : -1);
    setTab(next);
  };

  // Sliding glass indicator behind the active tab (tabbar-glass /
  // tab-indicator-glass in globals.css). Measured from the real DOM rather
  // than computed from index/width guesses, so it lines up exactly under
  // each label regardless of font metrics or viewport width.
  const trayRef = useRef<HTMLDivElement>(null);
  const tabRefs = useRef<Record<Lang, HTMLButtonElement | null>>({
    python: null,
    typescript: null,
    curl: null,
    langchain: null,
  });
  const [indicator, setIndicator] = useState<{ left: number; width: number } | null>(null);

  const positionIndicator = useCallback((id: Lang) => {
    const tray = trayRef.current;
    const btn = tabRefs.current[id];
    if (!tray || !btn) return;
    const trayRect = tray.getBoundingClientRect();
    const btnRect = btn.getBoundingClientRect();
    // The indicator is an absolutely-positioned child of the tray, so its
    // `left` is relative to the tray's PADDING edge — but getBoundingClientRect
    // measures the tray's BORDER edge. tabbar-glass has a 1px border, so
    // without this the indicator lands 1px off from the button it's meant
    // to sit under. Subtracting the tray's own border-left-width corrects it
    // regardless of what that border width happens to be.
    const trayBorderLeft = parseFloat(getComputedStyle(tray).borderLeftWidth) || 0;
    setIndicator({ left: btnRect.left - trayRect.left - trayBorderLeft, width: btnRect.width });
  }, []);

  // useLayoutEffect (not useEffect): measures and sets the indicator's
  // position before the browser paints, so it never flashes at a stale spot
  // on tab change, and on first mount it renders already in place instead of
  // growing in from a 0-width guess.
  useLayoutEffect(() => {
    positionIndicator(tab);
  }, [tab, positionIndicator]);

  useEffect(() => {
    const onResize = () => positionIndicator(tab);
    window.addEventListener('resize', onResize);
    window.addEventListener('orientationchange', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('orientationchange', onResize);
    };
  }, [tab, positionIndicator]);

  // Respect reduced-motion for the code panel's slide distance (see
  // HeroCanvas.tsx for the same matchMedia check). The tray indicator's own
  // motion is handled in CSS (tab-indicator-glass's reduced-motion rule).
  const [reduceMotion, setReduceMotion] = useState(false);
  useEffect(() => {
    setReduceMotion(window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }, []);
  const codeSlide = reduceMotion ? 0 : 14;
  const codeVariants = {
    enter: (dir: number) => ({ opacity: 0, x: dir * codeSlide }),
    center: { opacity: 1, x: 0 },
    exit: (dir: number) => ({ opacity: 0, x: dir * -codeSlide }),
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(CODE_SNIPPETS[tab]);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="w-full bg-white">
      {/* ================= HERO ================= */}
      <section id="hero" className="relative min-h-[100svh] flex items-start px-[clamp(20px,5vw,48px)] pt-[152px] pb-[14vh] overflow-hidden isolate bg-hero">
        <HeroCanvas />
        <div
          className="absolute inset-0 -z-10 pointer-events-none"
          style={{
            background:
              'linear-gradient(to bottom, rgba(8,9,11,0.30) 0%, rgba(8,9,11,0.12) 42%, rgba(8,9,11,0.16) 70%, rgba(8,9,11,0.10) 100%)',
          }}
        />
        <div
          className="absolute left-0 right-0 bottom-0 -z-10 pointer-events-none h-[min(42vh,420px)]"
          style={{
            background:
              'linear-gradient(to bottom, rgba(255,255,255,0) 0%, rgba(255,255,255,0) 46%, rgba(255,255,255,0.34) 70%, rgba(255,255,255,0.84) 88%, #ffffff 100%)',
          }}
        />

        <div className="relative w-full max-w-[1160px] mx-auto">
          <div className="max-w-[820px]">
            <div className="flex items-center gap-3 mb-[30px] text-xs font-medium tracking-[0.13em] uppercase text-white/60">
              <span>Developer API</span>
              <span className="inline-flex items-center h-6 px-[11px] rounded-full border border-white/28 text-white text-[0.6875rem] tracking-[0.1em]">
                Beta
              </span>
            </div>

            <h1 className="m-0 mb-[30px] font-medium text-white leading-[1.03] tracking-[-0.038em]" style={{ fontSize: 'clamp(2.5rem, 5.4vw, 4.4rem)' }}>
              The World&apos;s First Composite Intelligence.
            </h1>

            <p className="m-0 mb-[42px] max-w-[680px] text-white leading-[1.62]" style={{ fontSize: 'clamp(1.0625rem, 1.3vw, 1.1875rem)' }}>
              Our intelligence system outperforms every AI model that has{' '}
              <span className="highlight-ever text-white">EVER</span> existed at coding, mathematics, and agentic work.
            </p>

            <div className="flex flex-wrap gap-3.5">
              <Link href={SIGNUP_HREF} className="btn-pill btn-pill-glass">
                Create An Account
              </Link>
              <a
                href={EXTERNAL.wwwDemos}
                className="inline-flex h-12 items-center gap-1.5 self-center border-b border-white/40 text-[0.9375rem] font-medium text-white/90 transition-colors hover:border-white hover:text-white cursor-pointer"
              >
                See what Kael can build &rarr;
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* ================= ASK / PLAYGROUND ================= */}
      <section id="playground" className="px-[clamp(20px,5vw,48px)] py-[clamp(96px,14vh,156px)] scroll-mt-[100px]">
        <div className="max-w-[720px] mx-auto text-center">
          <h2 className="m-0 mb-[clamp(34px,5vh,52px)] font-medium text-ink leading-[1.08] tracking-[-0.036em]" style={{ fontSize: 'clamp(2rem, 4.4vw, 3.1rem)' }}>
            Ask Anything.<span className="typed-cursor" />
          </h2>

          <form
            onSubmit={(e) => e.preventDefault()}
            className="glow-box relative flex flex-col gap-3.5 p-[22px_22px_14px] bg-white border border-[#E5E5E1] rounded-[28px] text-left"
          >
            <label htmlFor="home-prompt" className="sr-only">Your prompt</label>
            <textarea
              id="home-prompt"
              rows={1}
              placeholder="Ask Quancis Anything…"
              className="relative z-[3] w-full border-0 outline-none resize-none bg-transparent text-[1.0625rem] leading-[1.55] text-ink p-[4px_2px] min-h-8 placeholder:text-[#9AA0A6]"
            />
            <div className="relative z-[3] flex items-center justify-between gap-3">
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setReasoningOn((v) => !v)}
                  aria-pressed={reasoningOn}
                  aria-label="Deep reasoning"
                  className={`w-[38px] h-[38px] rounded-full border grid place-items-center transition-colors cursor-pointer ${
                    reasoningOn
                      ? 'text-accent-blue border-accent-blue-border bg-accent-blue-soft'
                      : 'text-ink-2 border-[#E8E8E4] hover:text-ink hover:border-[#D6D6D1] hover:bg-surface'
                  }`}
                >
                  <Sparkles className="h-[17px] w-[17px]" strokeWidth={1.7} />
                </button>
                <button
                  type="button"
                  onClick={() => setWebOn((v) => !v)}
                  aria-pressed={webOn}
                  aria-label="Web access"
                  className={`w-[38px] h-[38px] rounded-full border grid place-items-center transition-colors cursor-pointer ${
                    webOn
                      ? 'text-accent-blue border-accent-blue-border bg-accent-blue-soft'
                      : 'text-ink-2 border-[#E8E8E4] hover:text-ink hover:border-[#D6D6D1] hover:bg-surface'
                  }`}
                >
                  <Globe2 className="h-[17px] w-[17px]" strokeWidth={1.7} />
                </button>
              </div>
              <Link
                href={ROUTES.login}
                aria-label="Send"
                className="flex-none w-11 h-11 rounded-full bg-ink text-white grid place-items-center hover:bg-[#2B2E32] transition-colors cursor-pointer"
              >
                <ArrowUp className="h-[18px] w-[18px]" strokeWidth={2} />
              </Link>
            </div>
          </form>

          <div className="grid grid-cols-2 gap-3.5 mt-[clamp(30px,4.5vh,44px)]">
            <Link href={ROUTES.login} className="btn-pill btn-pill-outline">
              <MessageCircle className="h-[17px] w-[17px] flex-none" strokeWidth={1.7} />
              Chat With Quancis
            </Link>
            <a href="#integration" className="btn-pill btn-pill-outline">
              <Braces className="h-[17px] w-[17px] flex-none" strokeWidth={1.7} />
              Use API Platform
            </a>
          </div>
        </div>
      </section>

      {/* ================= WHY ================= */}
      <section id="why" className="px-[clamp(20px,5vw,48px)] py-[clamp(88px,15vh,176px)] scroll-mt-[100px]">
        <div className="max-w-[1160px] mx-auto">
          <h2 className="m-0 mb-6 font-medium text-ink leading-[1.14] tracking-[-0.032em]" style={{ fontSize: 'clamp(1.75rem, 3.3vw, 2.6rem)' }}>
            One Intelligence. A Whole System Inside It.
          </h2>

          <p className="max-w-[720px] text-ink-2 leading-[1.7]" style={{ fontSize: 'clamp(1.0625rem, 1.4vw, 1.1875rem)' }}>
            Quancis comes from <em className="not-italic">quán</em>, the Chinese word for the whole. Not a fragment.
            Not a committee of parts pretending to be one thing. The whole. The entire system, working as a single
            intelligence. It&apos;s how a company works: hundreds of people, hundreds of tools, and the world only
            sees one name on the door. That&apos;s Quancis. You see one. Behind it, everything.
          </p>

          <p className="max-w-[720px] mt-[clamp(24px,3.5vh,34px)] text-ink-2 leading-[1.7]" style={{ fontSize: 'clamp(1.0625rem, 1.4vw, 1.1875rem)' }}>
            That principle is why Kael, the model inside Quancis, is the best in the world. A great company isn&apos;t
            one genius doing everything alone. It&apos;s many specialists pointed at the same goal. Kael works the
            same way. Not a bigger model, but a smarter system: many intelligences working as one. Using Kael, we
            built <a href={EXTERNAL.wwwNotAvailable} className="border-b border-[#D5D5D1] hover:border-ink transition-colors"><strong className="text-ink font-medium">Quan Harness</strong></a>, a full coding agent, and{' '}
            <a href={EXTERNAL.wwwNotAvailable} className="border-b border-[#D5D5D1] hover:border-ink transition-colors"><strong className="text-ink font-medium">Quan Chat</strong></a>, an agentic assistant, in a single month.
            Both rival, and in places surpass, what the top AI companies spent years building.{' '}
            <strong className="text-ink font-medium">Quancis is the system. Kael is the model. Together, they are the best intelligence in the world.</strong>
          </p>
        </div>
      </section>

      {/* ================= PRICING ================= */}
      <section id="pricing" className="px-[clamp(20px,5vw,48px)] py-[clamp(88px,15vh,176px)] scroll-mt-[100px]">
        <div className="max-w-[1160px] mx-auto grid grid-cols-1 md:grid-cols-2 gap-x-[clamp(40px,7vw,96px)] gap-y-10 items-start">
          <div>
            <span className="text-xs font-medium tracking-[0.14em] uppercase text-ink-3">Developer Access</span>
            <h2 className="mt-3.5 mb-6 font-medium text-ink leading-[1.14] tracking-[-0.032em]" style={{ fontSize: 'clamp(1.75rem, 3.3vw, 2.6rem)' }}>
              One System. The Best The World Has Ever Built.
            </h2>
            <p className="max-w-[640px] text-ink-2 leading-[1.72]" style={{ fontSize: 'clamp(1rem, 1.05vw, 1.0625rem)' }}>
              No contact-sales tier. No compromises. Just the most capable intelligence system in the world, at a price
              that makes the decision obvious.
            </p>
          </div>

          <div className="border border-line rounded-[20px] p-[clamp(28px,3.4vw,44px)]">
            <span className="text-xs font-medium tracking-[0.14em] uppercase text-ink-3">Beta Access</span>
            <div className="mt-3.5 mb-3 text-2xl font-medium tracking-[-0.025em] text-ink">Kael Beta</div>
            <p className="mb-8 text-[0.9375rem] leading-[1.7] text-ink-2">
              The world&apos;s most advanced intelligence, behind an API surface you already know.
            </p>

            <dl className="flex flex-col mb-[26px]">
              <div className="flex items-baseline justify-between gap-5 py-[15px] border-t border-line-soft text-[0.9375rem]">
                <dt className="text-ink-2">Input</dt>
                <dd className="m-0 font-medium text-ink text-right whitespace-nowrap">
                  {usd(BETA.price.input)} <small className="block text-xs font-normal text-ink-3">per 1M tokens</small>
                </dd>
              </div>
              <div className="flex items-baseline justify-between gap-5 py-[15px] border-t border-line-soft text-[0.9375rem]">
                <dt className="text-ink-2">Cached input</dt>
                <dd className="m-0 font-medium text-ink text-right whitespace-nowrap">
                  {usd(BETA.price.cachedInput)} <small className="block text-xs font-normal text-ink-3">per 1M tokens · up to 80% off</small>
                </dd>
              </div>
              <div className="flex items-baseline justify-between gap-5 py-[15px] border-t border-b border-line-soft text-[0.9375rem]">
                <dt className="text-ink-2">Output</dt>
                <dd className="m-0 font-medium text-ink text-right whitespace-nowrap">
                  {usd(BETA.price.output)} <small className="block text-xs font-normal text-ink-3">per 1M tokens</small>
                </dd>
              </div>
            </dl>
            <p className="mb-[26px] text-[0.875rem] leading-[1.6] text-ink-2">
              For the hardest problems, <span className="font-medium text-ink">{PRO_BETA.name}</span> goes further. It
              costs {usd(PRO_BETA.price.input)} in and {usd(PRO_BETA.price.output)} out per 1M tokens.
            </p>

            <dl className="mb-[26px] p-[18px_20px] bg-surface rounded-2xl flex flex-col gap-3 text-[0.8125rem]">
              <div className="flex items-baseline justify-between gap-4">
                <dt className="text-ink-3 text-xs tracking-[0.10em] uppercase font-medium">Input</dt>
                <dd className="m-0 text-ink font-medium">Text + images</dd>
              </div>
              <div className="flex items-baseline justify-between gap-4">
                <dt className="text-ink-3 text-xs tracking-[0.10em] uppercase font-medium">Output</dt>
                <dd className="m-0 text-ink font-medium">Text</dd>
              </div>
              <div className="flex items-baseline justify-between gap-4">
                <dt className="text-ink-3 text-xs tracking-[0.10em] uppercase font-medium">Context</dt>
                <dd className="m-0 text-ink font-medium">1M tokens</dd>
              </div>
              <div className="flex items-baseline justify-between gap-4">
                <dt className="text-ink-3 text-xs tracking-[0.10em] uppercase font-medium">Max response</dt>
                <dd className="m-0 text-ink font-medium">128k tokens</dd>
              </div>
            </dl>

            <Link href={SIGNUP_HREF} className="btn-pill btn-pill-glass-dark w-full">
              Create An Account
            </Link>
            <Link
              href={ROUTES.pricing}
              className="block mt-5 text-center text-[0.875rem] font-medium text-ink-2 hover:text-ink transition-colors cursor-pointer"
            >
              Full pricing &amp; model comparison →

            </Link>
            <Link
              href={ROUTES.pricing}
              className="block mt-5 text-center text-[0.875rem] font-medium text-ink-2 hover:text-ink transition-colors cursor-pointer"
            >
              Full pricing &amp; model comparison →
            </Link>
          </div>
        </div>
      </section>

      {/* ================= INTEGRATION ================= */}
      <section id="integration" className="px-[clamp(20px,5vw,48px)] py-[clamp(88px,15vh,176px)] scroll-mt-[100px]">
        <div className="max-w-[1160px] mx-auto">
          <div className="bg-surface rounded-[24px] p-[clamp(28px,4vw,48px)]">
            <span className="text-xs font-medium tracking-[0.14em] uppercase text-ink-3">Integration</span>
            <h2 className="mt-3 mb-3 font-medium leading-[1.14] tracking-[-0.03em] text-ink" style={{ fontSize: 'clamp(1.6rem, 2.9vw, 2.25rem)' }}>
              Swap The Base URL.
            </h2>
            <p className="mb-1.5 text-ink-2 leading-[1.6]" style={{ fontSize: 'clamp(0.9375rem, 1.05vw, 1.0625rem)' }}>
              No custom SDK. No migration. If you already speak OpenAI, you already speak Quancis.
            </p>
            <code className="block mb-[clamp(26px,3.4vw,36px)] font-mono text-sm text-ink-3 break-all">
              https://api.quancis.space/v1
            </code>

            <div className="flex items-center justify-between gap-3.5 mb-4">
              <div className="overflow-x-auto [scrollbar-width:none]">
                <div
                  ref={trayRef}
                  role="tablist"
                  aria-label="Code examples"
                  className="tabbar-glass relative inline-flex gap-0.5 p-1 rounded-full whitespace-nowrap"
                >
                  {indicator && (
                    <div
                      aria-hidden="true"
                      className="tab-indicator-glass"
                      style={{ left: indicator.left, width: indicator.width }}
                    />
                  )}
                  {TABS.map((t) => (
                    <button
                      key={t.id}
                      ref={(el) => {
                        tabRefs.current[t.id] = el;
                      }}
                      role="tab"
                      aria-selected={tab === t.id}
                      onClick={() => handleTabChange(t.id)}
                      className={`relative z-10 h-[38px] px-[18px] rounded-full text-[0.8125rem] font-medium cursor-pointer transition-colors ${
                        tab === t.id && indicator ? 'text-white' : 'text-[#6E747A] hover:text-ink'
                      }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>
              <button
                onClick={handleCopy}
                className="btn-glass-outline flex-none h-9 px-4 rounded-full text-ink-2 text-[0.8125rem] font-medium hover:text-ink transition-colors cursor-pointer flex items-center gap-1.5"
              >
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>

            <div className="bg-code-bg rounded-2xl overflow-hidden">
              <AnimatePresence mode="wait" initial={false} custom={direction}>
                <motion.pre
                  key={tab}
                  custom={direction}
                  variants={codeVariants}
                  initial="enter"
                  animate="center"
                  exit="exit"
                  transition={{ duration: 0.22, ease: [0.22, 0.61, 0.36, 1] }}
                  className="m-0 p-[26px_24px_28px] overflow-x-auto font-mono text-[12.75px] leading-[1.78] text-code-ink"
                >
                  <code>{CODE_SNIPPETS[tab]}</code>
                </motion.pre>
              </AnimatePresence>
            </div>
          </div>
          <Link href={ROUTES.docs} className="inline-block mt-8 text-[0.9375rem] font-medium text-ink border-b border-[#D5D5D1] hover:border-ink transition-colors cursor-pointer pb-0.5">
            API Reference →
          </Link>
        </div>
      </section>

      {/* ================= CLOSING ================= */}
      <section className="px-[clamp(20px,5vw,48px)] py-[clamp(88px,15vh,180px)] text-center scroll-mt-[100px]">
        <div className="max-w-[760px] mx-auto">
          <h2 className="m-0 mb-10 font-medium leading-[1.12] tracking-[-0.034em] text-ink" style={{ fontSize: 'clamp(1.875rem, 4.4vw, 3.1rem)' }}>
            Built For The Engineers Who Can&apos;t Afford Shortcuts.
          </h2>
          <Link href={SIGNUP_HREF} className="btn-pill btn-pill-glass-dark">
            Create An Account

          </Link>
        </div>
      </section>
    </div>
  );
};
