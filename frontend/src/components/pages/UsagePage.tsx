'use client';

import React, { useState } from 'react';
import { useApp } from '../../context/AppContext';
import { motion, AnimatePresence } from 'motion/react';
import { BETA } from '../docs/facts';

// usage_logs records the model each request ran on (its public slug). Map the
// slug to the display name used elsewhere (Playground, Docs) rather than showing
// the raw key.
const PRODUCT_LABELS: Record<string, string> = {
  'kael-beta': 'Kael Beta',
  'kael-pro-beta': 'Kael Pro Beta',
};

// Kael Beta's input price, USD per 1M tokens: the rate the top-up estimate below
// uses. Read from components/docs/facts.ts, which mirrors
// backend/app/models/kael/config.py.
const KAEL_INPUT_PRICE_PER_MILLION_USD = BETA.price.input;

export const UsagePage: React.FC = () => {
  const { user, usageHistory, usageByProduct, isStatsLoading } = useApp();
  const [showTopUpModal, setShowTopUpModal] = useState(false);
  const [showDailyTokenInfo, setShowDailyTokenInfo] = useState(false);
  const [selectedTopUpAmount, setSelectedTopUpAmount] = useState<number>(50);

  const totalInputTokens = usageHistory.reduce((acc, d) => acc + d.inputTokens, 0);
  const totalCachedTokens = usageHistory.reduce((acc, d) => acc + d.cachedTokens, 0);
  const totalOutputTokens = usageHistory.reduce((acc, d) => acc + d.outputTokens, 0);
  const totalSpend = usageHistory.reduce((acc, d) => acc + d.costDollars, 0);

  // Overall cache hit percentage
  const cacheHitRate = Math.round((totalCachedTokens / (totalInputTokens || 1)) * 100);

  // Total saved vs standard $5.00/$15.00 frontier pricing
  const frontierSpend = (totalInputTokens * 5.0) / 1000000 + (totalOutputTokens * 15.0) / 1000000;
  const totalSavedDollars = Math.max(0, frontierSpend - totalSpend);

  // No payment processor is wired up yet,
  // so there is no real invoice or saved-card data to show. Rather than
  // fabricate placeholder rows, both panels below show an honest
  // "not connected yet" state until a processor exists to source this from.

  return (
    <div className="max-w-[1160px] mx-auto px-[clamp(20px,5vw,48px)] py-[clamp(40px,7vh,64px)] space-y-8">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-5">
        <div>
          <span className="page-eyebrow mb-3">Billing</span>
          <h1 className="page-title mt-3 mb-2">Usage, Cost &amp; Billing</h1>
          <p className="page-lead">
            Track token consumption, cache hit savings, and manage prepaid credit balances.
          </p>
        </div>

        <button
          onClick={() => setShowTopUpModal(true)}
          className="btn-pill btn-pill-blue !h-[46px] !px-5 !text-[0.8125rem]"
        >
          <span>Add Prepaid Credits</span>
        </button>
      </div>

      {/* Available balance */}
      <div className="stat-card">
        <div>
          <span className="stat-label">Available Balance</span>
          <div className="stat-value font-mono">
            {user?.creditBalance != null ? `$${user.creditBalance.toFixed(2)}` : '—'}
          </div>
        </div>
        <button
          onClick={() => setShowTopUpModal(true)}
          className="btn-pill btn-pill-dark !h-10 !px-4 !text-xs"
        >
          + Top up
        </button>
      </div>

      {/* Daily usage breakdown */}
      <div className="card-panel p-6 sm:p-7 space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-line-soft pb-4">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-medium text-ink tracking-[-0.01em]">Daily Token &amp; Cost Telemetry</h3>
            <button
              onClick={() => setShowDailyTokenInfo(!showDailyTokenInfo)}
              className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-line text-ink-2 hover:bg-line-soft font-semibold text-[10px] cursor-pointer transition-colors"
              title="Click for rate details"
            >
              !
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-4 text-xs">
            <div className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-accent-blue" />
              <span className="text-ink-2 font-medium">Cached In (up to 80% off)</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-accent-blue/45" />
              <span className="text-ink-2 font-medium">Uncached In</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-ink/70" />
              <span className="text-ink-2 font-medium">Output Tokens</span>
            </div>
          </div>
        </div>

        <AnimatePresence>
          {showDailyTokenInfo && (
            <motion.div
              initial={{ opacity: 0, height: 0, y: -4 }}
              animate={{ opacity: 1, height: 'auto', y: 0 }}
              exit={{ opacity: 0, height: 0, y: -4 }}
              transition={{ duration: 0.18, ease: 'easeOut' }}
              className="bg-ink text-white p-4 rounded-2xl text-xs flex items-center justify-between overflow-hidden"
            >
              <div className="flex items-center gap-2.5">
                <span className="flex h-4 w-4 items-center justify-center rounded-full bg-accent-blue text-white font-semibold text-[10px] shrink-0">
                  !
                </span>
                <p className="text-white/70 text-xs">
                  Aggregated daily token volumes across every product on this account.
                  Cached input tokens are billed at up to 80% off the standard input
                  rate. Exact per-token rates differ by model; see the
                  &quot;Usage by Product&quot; breakdown below or the pricing table
                  in Docs for exact numbers.
                </p>
              </div>
              <button
                onClick={() => setShowDailyTokenInfo(false)}
                className="text-white/50 hover:text-white p-1 rounded-xl cursor-pointer shrink-0 ml-2 text-sm leading-none"
                title="Close explanation"
              >
                &times;
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        <div className="space-y-4">
          {usageHistory.length === 0 && (
            <div className="py-6 text-center text-xs text-ink-3">
              {isStatsLoading ? 'Loading…' : 'No usage yet — make your first API call to see daily breakdowns here.'}
            </div>
          )}
          {usageHistory.map((day, idx) => {
            // Guard against an all-zero day (e.g. only /v1/models calls
            // logged, which carry no token counts) — without the `|| 1`,
            // 0/0 produces NaN and the bar widths silently disappear.
            const totalTokens = day.inputTokens + day.outputTokens || 1;
            const cachedPct = Math.round((day.cachedTokens / totalTokens) * 100);
            const uncachedInPct = Math.round(((day.inputTokens - day.cachedTokens) / totalTokens) * 100);
            const outPct = Math.max(5, 100 - cachedPct - uncachedInPct);

            return (
              <div key={idx} className="space-y-1.5 text-xs">
                <div className="flex justify-between items-center">
                  <span className="font-medium text-ink font-mono">{day.date}</span>
                  <div className="flex items-center gap-4 text-[11px] font-mono">
                    <span className="text-ink-3">{day.totalRequests} reqs</span>
                    <span className="text-ink-3">{(totalTokens / 1000).toLocaleString()}k tokens</span>
                    <span className="text-accent-blue font-medium">${day.costDollars.toFixed(2)}</span>
                  </div>
                </div>

                <div className="h-3 w-full bg-line-soft rounded-full flex overflow-hidden">
                  <div
                    className="bg-accent-blue hover:opacity-90 transition-all"
                    style={{ width: `${cachedPct}%` }}
                    title={`Cached Input: ${(day.cachedTokens / 1000).toLocaleString()}k tokens`}
                  />
                  <div
                    className="bg-accent-blue/45 hover:opacity-90 transition-all"
                    style={{ width: `${uncachedInPct}%` }}
                    title={`Uncached Input: ${((day.inputTokens - day.cachedTokens) / 1000).toLocaleString()}k tokens`}
                  />
                  <div
                    className="bg-ink/70 hover:opacity-90 transition-all"
                    style={{ width: `${outPct}%` }}
                    title={`Output: ${(day.outputTokens / 1000).toLocaleString()}k tokens`}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Usage by product */}
      {Object.keys(usageByProduct).length > 0 && (
        <div className="card-panel p-6 sm:p-7 space-y-4">
          <h3 className="text-base font-medium text-ink tracking-[-0.01em]">Usage by Product</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {Object.entries(usageByProduct).map(([product, stats]) => (
              <div key={product} className="rounded-2xl border border-line bg-surface p-4 text-xs space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-ink">{PRODUCT_LABELS[product] || product}</span>
                  <span className="text-ink-3 font-mono">{stats.requests} reqs</span>
                </div>
                <div className="flex items-center justify-between text-[11px] text-ink-3 font-mono">
                  <span>{(stats.total_tokens / 1000).toLocaleString()}k tokens</span>
                  <span>{(stats.cached_tokens / 1000).toLocaleString()}k cached</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Invoices & payment preferences */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        <div className="lg:col-span-7 space-y-4">
          <h3 className="text-sm font-medium text-ink tracking-[-0.01em]">Billing History &amp; Invoices</h3>

          <div className="table-card">
            <div className="overflow-x-auto">
              <table className="data-table !text-xs">
                <thead>
                  <tr>
                    <th>Invoice #</th>
                    <th>Date</th>
                    <th>Amount</th>
                    <th>Status</th>
                    <th className="text-right" style={{ textAlign: 'right' }}>Receipt</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td colSpan={5} className="text-center text-ink-3">
                      No invoices yet — this account runs on prepaid credits, and
                      itemized invoices will appear here once a payment processor
                      is connected.
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="lg:col-span-5 space-y-4">
          <h3 className="text-sm font-medium text-ink tracking-[-0.01em]">Payment Preferences</h3>

          <div className="card-panel p-5 space-y-3 text-xs">
            <div className="flex items-center gap-3 rounded-2xl border border-dashed border-line bg-surface p-3.5">
              <div className="rounded-lg bg-line px-2 py-1 font-medium text-ink-3 text-[11px]">
                CARD
              </div>
              <div>
                <div className="font-medium text-ink-2">No payment method on file</div>
                <div className="text-[10px] text-ink-3">
                  Add prepaid credits manually above — saved cards and
                  auto-recharge are coming soon.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Top up modal */}
      {showTopUpModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-[28px] border border-line bg-white p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-line-soft pb-3">
              <h3 className="text-base font-medium text-ink tracking-[-0.01em]">Add Prepaid AI Credits</h3>
              <button
                onClick={() => setShowTopUpModal(false)}
                className="text-ink-3 hover:text-ink text-lg leading-none cursor-pointer"
              >
                &times;
              </button>
            </div>

            <div className="space-y-4 text-xs">
              <p className="text-ink-2">
                Credits are a prepaid allowance for using Quancis, shown in dollars for convenience. They are not
                money: they have no cash value, can&rsquo;t be withdrawn, transferred, or exchanged, and can only be
                used on Quancis. Credits expire 12 months after they are added to your account, oldest first. See the{' '}
                <a href="/terms-of-service" className="text-accent-blue hover:underline">Terms of Service</a>.
              </p>

              <div className="grid grid-cols-3 gap-2">
                {[25, 50, 100].map((amt) => (
                  <button
                    key={amt}
                    onClick={() => setSelectedTopUpAmount(amt)}
                    className={`rounded-2xl border p-3 font-mono text-center font-medium text-sm transition-all cursor-pointer ${
                      selectedTopUpAmount === amt
                        ? 'border-accent-blue bg-accent-blue-soft text-accent-blue'
                        : 'border-line bg-surface text-ink-2 hover:border-ink-3'
                    }`}
                  >
                    ${amt}
                  </button>
                ))}
              </div>

              <div className="rounded-2xl border border-line bg-surface p-3.5 font-mono text-[11px] space-y-1 text-ink-2">
                <div className="flex justify-between">
                  <span>Charge Amount:</span>
                  <span className="text-ink font-medium">${selectedTopUpAmount}.00 USD</span>
                </div>
                <div className="flex justify-between">
                  <span>Estimated Tokens (Kael Beta input rate):</span>
                  <span className="text-accent-blue font-medium">~{Math.round((selectedTopUpAmount / KAEL_INPUT_PRICE_PER_MILLION_USD) * 1000000).toLocaleString()} in tokens</span>
                </div>
              </div>

              <div className="space-y-2">
                <button
                  disabled
                  className="w-full rounded-full bg-line py-3 font-medium text-ink-3 cursor-not-allowed text-xs"
                >
                  Credit Top-Up (Coming Soon)
                </button>
                <p className="text-[10px] text-center text-ink-3">
                  Payment processor integration is currently in progress.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
