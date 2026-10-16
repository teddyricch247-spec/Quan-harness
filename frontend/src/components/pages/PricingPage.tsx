'use client';

import React from 'react';
import Link from 'next/link';
import { ROUTES, docsPath } from '../../lib/routes';
import { BETA, PRO_BETA, usd } from '../docs/facts';

// Both Kael models' prices come from components/docs/facts.ts, which mirrors
// backend/app/models/kael/config.py (customer_price_per_million). Change that
// first, then facts.ts; this page reads facts.ts, so it needs no edit of its own.
const KAEL_INPUT = BETA.price.input;
const KAEL_CACHED_INPUT = BETA.price.cachedInput;
const KAEL_OUTPUT = BETA.price.output;
const PRO_INPUT = PRO_BETA.price.input;
const PRO_CACHED_INPUT = PRO_BETA.price.cachedInput;
const PRO_OUTPUT = PRO_BETA.price.output;

type ComparisonRow = {
  name: string;
  id: string;
  isUs?: boolean;
  input: number;
  cachedInput: number;
  output: number;
};

// First-party list prices as of 2026-09-28: standard (short-context) rates,
// not reseller/router prices and not promotional ones. How each was checked:
//   - Claude Opus 5.5 / Fable 5.1: Anthropic's own pricing docs.
//   - GPT-6 Sol / Astra: OpenAI's own pricing page (developers.openai.com/
//     api/docs/pricing). OpenAI charges MORE for long prompts (Astra $20/$75,
//     Sol $4/$15 in its "long context" columns); the table shows the standard
//     rates and the caption says so.
//   - Kimi K3: read from several independent trackers that all cite
//     Moonshot's own pricing page and agree ($3 / $0.30 / $15). Moonshot's
//     page itself was NOT opened. Some hosts sell K3 for less (OpenRouter
//     listed ~$1/$9), which is why the copy says first-party rates.
// Sorted by output price, since that is usually the larger share of a bill.
//
// The hero line near the top of the page ("ties for the lowest output
// price") is written by hand from THIS table, not computed from it. At Kael
// Beta's 2026-10-08 price of $3.00 / $10.00, GPT-6 Sol is lower on input
// ($2.00) and level on output ($10.00), which is why the line says "ties",
// not "lowest". Re-read that line every time a price here changes, or the
// page can claim something the table no longer shows.
const COMPARISON: ComparisonRow[] = [
  { name: 'Quancis (Kael Beta)', id: 'quancis', isUs: true, input: KAEL_INPUT, cachedInput: KAEL_CACHED_INPUT, output: KAEL_OUTPUT },
  { name: 'Quancis (Kael Pro Beta)', id: 'quancis-pro', isUs: true, input: PRO_INPUT, cachedInput: PRO_CACHED_INPUT, output: PRO_OUTPUT },
  { name: 'GPT-6 Sol', id: 'gpt-6-sol', input: 2.0, cachedInput: 0.2, output: 10.0 },
  { name: 'Kimi K3', id: 'kimi-k3', input: 3.0, cachedInput: 0.3, output: 15.0 },
  { name: 'Claude Opus 5.5', id: 'opus-5-5', input: 4.0, cachedInput: 0.2, output: 20.0 },
  { name: 'Claude Fable 5.1', id: 'fable-5-1', input: 10.0, cachedInput: 0.25, output: 50.0 },
  { name: 'GPT-6 Astra', id: 'gpt-6-astra', input: 10.0, cachedInput: 1.0, output: 50.0 },
].sort((a, b) => a.output - b.output);

const fmt = (n: number) => `$${n.toFixed(2)}`;
const minOf = (key: 'input' | 'cachedInput' | 'output') => Math.min(...COMPARISON.map((r) => r[key]));

export const PricingPage: React.FC = () => {
  const minInput = minOf('input');
  const minCached = minOf('cachedInput');
  const minOutput = minOf('output');

  return (
    <div className="w-full bg-white">
      {/* ================= HERO ================= */}
      <section className="px-[clamp(20px,5vw,48px)] pt-[clamp(120px,16vh,168px)] pb-[clamp(56px,8vh,88px)]">
        <div className="max-w-[760px] mx-auto text-center">
          <span className="text-xs font-medium tracking-[0.14em] uppercase text-ink-3">Pricing</span>
          <h1
            className="mt-3.5 mb-6 font-medium text-ink leading-[1.1] tracking-[-0.034em]"
            style={{ fontSize: 'clamp(2rem, 4.6vw, 3.2rem)' }}
          >
            Frontier Intelligence. Not Frontier Prices.
          </h1>
          <p className="max-w-[560px] mx-auto text-ink-2 leading-[1.7]" style={{ fontSize: 'clamp(1.0625rem, 1.4vw, 1.1875rem)' }}>
            At low, high and max thinking, Kael Beta ties for the lowest output price on this page.
          </p>
        </div>
      </section>

      {/* ================= PRICE CARD ================= */}
      <section className="px-[clamp(20px,5vw,48px)] py-[clamp(48px,8vh,88px)]">
        <div className="max-w-[1160px] mx-auto grid grid-cols-1 md:grid-cols-2 gap-x-[clamp(40px,7vw,96px)] gap-y-10 items-start">
          <div>
            <span className="text-xs font-medium tracking-[0.14em] uppercase text-ink-3">Two Models</span>
            <h2
              className="mt-3.5 mb-6 font-medium text-ink leading-[1.14] tracking-[-0.032em]"
              style={{ fontSize: 'clamp(1.75rem, 3.3vw, 2.6rem)' }}
            >
              Pick How Hard It Thinks.
            </h2>
            <p className="max-w-[640px] text-ink-2 leading-[1.72]" style={{ fontSize: 'clamp(1rem, 1.05vw, 1.0625rem)' }}>
              Kael has two models, and each has one price for all of its levels. Kael Beta is the general model: low,
              high and max cost the same per token. Kael Pro Beta is for the most demanding work and costs more per token. Your
              rate depends only on the model you call, whether you send ten requests a day or ten million. Cached input — the parts of your
              prompt that repeat, like a system prompt or tool definitions — costs a fraction of the standard rate.
            </p>
            <p className="mt-5 max-w-[640px] text-ink-2 leading-[1.72]" style={{ fontSize: 'clamp(1rem, 1.05vw, 1.0625rem)' }}>
              There&apos;s no &quot;contact sales&quot; tier hiding a better rate. A weekend project and a
              production workload pay the exact same {fmt(KAEL_INPUT)} in and {fmt(KAEL_OUTPUT)} out for Kael Beta, at
              any of its levels, and {fmt(PRO_INPUT)} in and {fmt(PRO_OUTPUT)} out for Kael Pro Beta, at either of its
              levels.
            </p>
          </div>

          <div className="border border-line rounded-[20px] p-[clamp(28px,3.4vw,44px)]">
            <span className="text-xs font-medium tracking-[0.14em] uppercase text-ink-3">Beta Access</span>
            <div className="mt-3.5 mb-3 text-2xl font-medium tracking-[-0.025em] text-ink">Kael Beta and Kael Pro Beta</div>
            <p className="mb-8 text-[0.9375rem] leading-[1.7] text-ink-2">
              The world&apos;s most advanced intelligence, behind an API surface you already know.
            </p>

            <div className="mb-[26px] border-t border-b border-line-soft text-[0.9375rem]">
              <div className="grid grid-cols-[1fr_auto_auto] items-end gap-x-6 py-[14px] text-xs font-medium uppercase tracking-[0.08em] text-ink-3">
                <span>Per 1M tokens</span>
                <span className="text-right normal-case tracking-normal text-ink">
                  {BETA.name}
                  <span className="block text-[11px] uppercase tracking-[0.08em] text-ink-3">Low · High · Max</span>
                </span>
                <span className="text-right normal-case tracking-normal text-ink">
                  {PRO_BETA.name}
                  <span className="block text-[11px] uppercase tracking-[0.08em] text-ink-3">z-low · z-high</span>
                </span>
              </div>
              {[
                { label: 'Input', beta: KAEL_INPUT, pro: PRO_INPUT },
                { label: 'Cached input', beta: KAEL_CACHED_INPUT, pro: PRO_CACHED_INPUT },
                { label: 'Output', beta: KAEL_OUTPUT, pro: PRO_OUTPUT },
              ].map((row) => (
                <div
                  key={row.label}
                  className="grid grid-cols-[1fr_auto_auto] items-baseline gap-x-6 py-[15px] border-t border-line-soft"
                >
                  <span className="text-ink-2">{row.label}</span>
                  <span className="text-right font-medium text-ink whitespace-nowrap">{fmt(row.beta)}</span>
                  <span className="text-right font-medium text-ink whitespace-nowrap">{fmt(row.pro)}</span>
                </div>
              ))}
              <p className="m-0 border-t border-line-soft py-3 text-xs leading-[1.6] text-ink-3">
                Cached input is up to 80% off the input rate.
              </p>
            </div>

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

            <Link href={ROUTES.login} className="btn-pill btn-pill-glass-dark w-full">
              Create An Account
            </Link>
          </div>
        </div>
      </section>

      {/* ================= COMPARISON ================= */}
      <section className="px-[clamp(20px,5vw,48px)] py-[clamp(48px,8vh,88px)]">
        <div className="max-w-[1000px] mx-auto">
          <span className="text-xs font-medium tracking-[0.14em] uppercase text-ink-3">Compared</span>
          <h2
            className="mt-3.5 mb-5 font-medium text-ink leading-[1.14] tracking-[-0.032em]"
            style={{ fontSize: 'clamp(1.6rem, 2.9vw, 2.25rem)' }}
          >
            How The Pricing Compares.
          </h2>
          <p className="max-w-[680px] mb-8 text-ink-2 leading-[1.7]" style={{ fontSize: '0.9375rem' }}>
            Standard first-party API rates as of September 28, 2026, compiled from provider pricing pages and
            independent price trackers. These are not reseller or router prices. Model pricing changes often,
            so confirm the current rate with the provider before deciding.
          </p>

          <div className="rounded-2xl border border-line bg-white overflow-hidden">
            <div className="overflow-x-auto w-full">
              <table className="w-full text-left min-w-[560px]">
                <thead className="bg-surface border-b border-line text-ink-3 uppercase font-mono text-[11px] tracking-wider">
                  <tr>
                    <th className="py-3.5 px-5 font-medium">Model</th>
                    <th className="py-3.5 px-5 font-medium text-right">Input / 1M</th>
                    <th className="py-3.5 px-5 font-medium text-right">Cached input / 1M</th>
                    <th className="py-3.5 px-5 font-medium text-right">Output / 1M</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line-soft">
                  {COMPARISON.map((row) => (
                    <tr key={row.id} className={row.isUs ? 'bg-accent-blue-soft/50' : undefined}>
                      <td className="py-4 px-5 text-[0.9375rem] font-medium text-ink whitespace-nowrap">
                        {row.name}
                        {row.isUs && (
                          <span className="ml-2 align-middle rounded-full bg-accent-blue px-2 py-0.5 text-[10px] font-mono font-semibold text-white">
                            THIS IS US
                          </span>
                        )}
                      </td>
                      <td
                        className={`py-4 px-5 text-right font-mono text-[0.9375rem] ${
                          row.input === minInput ? 'font-bold text-ink' : 'text-ink-2'
                        }`}
                      >
                        {fmt(row.input)}
                      </td>
                      <td
                        className={`py-4 px-5 text-right font-mono text-[0.9375rem] ${
                          row.cachedInput === minCached ? 'font-bold text-ink' : 'text-ink-2'
                        }`}
                      >
                        {fmt(row.cachedInput)}
                      </td>
                      <td
                        className={`py-4 px-5 text-right font-mono text-[0.9375rem] ${
                          row.output === minOutput ? 'font-bold text-ink' : 'text-ink-2'
                        }`}
                      >
                        {fmt(row.output)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <p className="mt-4 text-xs text-ink-3 leading-[1.6]">
            Bold marks the lowest price in each column. Cached-input discounts vary by provider — from 80% off
            here to as much as 97.5% off elsewhere — so a workload that reuses a lot of prompt structure can
            shift the real-world ranking. Where a provider charges more for very long prompts (OpenAI does),
            the standard rate is shown; Kael&apos;s prices are the same at any prompt length. Each Kael row is one
            model at its own levels: Kael Beta&apos;s is low, high and max, and Kael Pro Beta&apos;s is z-low and z-high.
          </p>
        </div>
      </section>

      {/* ================= CLOSING ================= */}
      <section className="px-[clamp(20px,5vw,48px)] py-[clamp(72px,12vh,140px)] text-center">
        <div className="max-w-[680px] mx-auto">
          <h2
            className="m-0 mb-4 font-medium leading-[1.16] tracking-[-0.03em] text-ink"
            style={{ fontSize: 'clamp(1.75rem, 3.6vw, 2.6rem)' }}
          >
            Compatible With Code You Already Have.
          </h2>
          <p className="mb-10 text-ink-2 leading-[1.7]" style={{ fontSize: '1.0625rem' }}>
            Kael speaks the OpenAI API. Create an account, generate a key, and change one base URL.
          </p>
          <Link href={ROUTES.login} className="btn-pill btn-pill-glass-dark">
            Create An Account
          </Link>
          <div>
            <Link
              href={docsPath('endpoints')}
              className="inline-block mt-8 text-[0.9375rem] font-medium text-ink border-b border-[#D5D5D1] hover:border-ink transition-colors cursor-pointer pb-0.5"
            >
              Full API Reference →
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
};
