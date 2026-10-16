'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useApp } from '../../context/AppContext';
import { ROUTES } from '../../lib/routes';
import { X, Wallet, KeySquare } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

export const DashboardPage: React.FC = () => {
  const { user, apiKeys, requestLogs, isStatsLoading } = useApp();
  const [showTelemetryInfo, setShowTelemetryInfo] = useState(false);

  return (
    <div className="max-w-[1160px] mx-auto px-[clamp(20px,5vw,48px)] py-[clamp(40px,7vh,64px)] space-y-10">

      {/* Page header */}
      <div>
        <span className="page-eyebrow mb-3">Account</span>
        <h1 className="page-title mt-3 mb-2">Overview</h1>
        <p className="page-lead">
          All dates and times are GMT+2, and data may be delayed up to 5 minutes.
        </p>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="stat-card">
          <div>
            <span className="stat-label">Prepaid Balance</span>
            <div className="stat-value font-mono">
              {user?.creditBalance != null ? `$${user.creditBalance.toFixed(2)}` : '—'}
            </div>
          </div>
          <div className="flex flex-col items-end gap-3">
            <div className="stat-icon"><Wallet className="h-[18px] w-[18px]" strokeWidth={1.7} /></div>
            <Link href={ROUTES.usage} className="btn-pill btn-pill-dark !h-9 !px-4 !text-xs">
              + Top up
            </Link>
          </div>
        </div>

        <div className="stat-card">
          <div>
            <span className="stat-label">Active Secret Keys</span>
            <div className="stat-value font-mono">{apiKeys.length} {apiKeys.length === 1 ? 'Key' : 'Keys'}</div>
          </div>
          <div className="flex flex-col items-end gap-3">
            <div className="stat-icon"><KeySquare className="h-[18px] w-[18px]" strokeWidth={1.7} /></div>
            <Link href={ROUTES.keys} className="btn-pill btn-pill-dark !h-9 !px-4 !text-xs">
              Manage
            </Link>
          </div>
        </div>
      </div>

      {/* Live request telemetry */}
      <div className="table-card relative">
        <div className="p-5 sm:px-7 border-b border-line-soft flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-medium text-ink tracking-[-0.01em]">Live API Request Telemetry</h3>
            <button
              onClick={() => setShowTelemetryInfo(!showTelemetryInfo)}
              className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-line text-ink-2 hover:bg-line-soft font-semibold text-[10px] cursor-pointer transition-colors"
              title="Click for details"
            >
              !
            </button>
          </div>
          <Link
            href={ROUTES.usage}
            className="text-xs text-accent-blue font-medium hover:text-accent-blue-hover flex items-center gap-1 cursor-pointer"
          >
            View Full Cost Analytics &rarr;
          </Link>
        </div>

        <AnimatePresence>
          {showTelemetryInfo && (
            <motion.div
              initial={{ opacity: 0, height: 0, y: -4 }}
              animate={{ opacity: 1, height: 'auto', y: 0 }}
              exit={{ opacity: 0, height: 0, y: -4 }}
              transition={{ duration: 0.18, ease: 'easeOut' }}
              className="bg-ink text-white px-5 sm:px-7 py-4 text-xs flex items-center justify-between overflow-hidden"
            >
              <div className="flex items-center gap-2.5">
                <span className="flex h-4 w-4 items-center justify-center rounded-full bg-accent-blue text-white font-semibold text-[10px] shrink-0">
                  !
                </span>
                <p className="text-white/70 text-xs">
                  Real-time log of every request, with its tokens, cache hits and cost.
                </p>
              </div>
              <button
                onClick={() => setShowTelemetryInfo(false)}
                className="text-white/50 hover:text-white p-1 rounded-xl cursor-pointer shrink-0 ml-2"
                title="Close explanation"
              >
                <X className="h-4 w-4" />
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Model</th>
                <th>Endpoint</th>
                <th>Status</th>
                <th>Tokens</th>
                <th>Cache</th>
                <th>Latency</th>
                <th className="text-right" style={{ textAlign: 'right' }}>Cost</th>
              </tr>
            </thead>
            <tbody>
              {requestLogs.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-center text-ink-3">
                    {isStatsLoading ? 'Loading…' : 'No requests yet — make your first API call to see it here.'}
                  </td>
                </tr>
              )}
              {requestLogs.map((log) => {
                const isSuccess = log.status < 400;
                return (
                  <tr key={log.id} className="hover:bg-surface transition-colors">
                    <td className="font-mono whitespace-nowrap text-ink-3">{log.timestamp.split('T')[1]?.replace('Z', '') || log.timestamp}</td>
                    <td className="font-medium text-ink whitespace-nowrap">{log.model}</td>
                    <td className="font-mono text-ink-3 whitespace-nowrap">{log.endpoint}</td>
                    <td className="whitespace-nowrap">
                      <span className="inline-flex items-center gap-1.5">
                        {log.status} {isSuccess ? 'OK' : 'Error'}
                        <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${isSuccess ? 'bg-accent-blue' : 'bg-danger'}`} />
                      </span>
                    </td>
                    <td className="font-mono whitespace-nowrap">{log.tokens.toLocaleString()}</td>
                    <td className="whitespace-nowrap">
                      {log.cacheHit ? (
                        <span className="text-accent-blue font-medium">Cached</span>
                      ) : (
                        <span className="text-ink-3">&mdash;</span>
                      )}
                    </td>
                    <td className="font-mono whitespace-nowrap">{log.latency}ms</td>
                    <td className="font-mono whitespace-nowrap text-right text-ink font-medium">
                      ${log.cost.toFixed(5)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
