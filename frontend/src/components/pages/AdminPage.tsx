'use client';

import React, { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { useApp } from '../../context/AppContext';
import { ROUTES } from '../../lib/routes';
import {
  Users,
  DollarSign,
  Activity,
  Lock,
  Search,
  CheckCircle2,
  AlertCircle,
  Key,
  RefreshCw,
  Zap,
  PlusCircle,
  X
} from 'lucide-react';
import { ApiError, ReconcileAdminResponse } from '../../lib/api';

// Reconcile amounts arrive as decimal strings with 5 places (the balance
// column's precision). Keep all 5: a one-hundred-thousandth of a dollar
// is still a real mismatch. Sign goes before the $ ("-$0.20000").
const formatReconcileUsd = (value: string): string => {
  const n = parseFloat(value);
  if (isNaN(n)) return value;
  return `${n < 0 ? '-' : ''}$${Math.abs(n).toFixed(5)}`;
};

export const AdminPage: React.FC = () => {
  const {
    user,
    adminStats,
    adminUsers,
    isAdminDataLoading,
    loadAdminStats,
    loadAdminUsers,
    creditAdminUser,
    suspendAdminUser,
    activateAdminUser,
    runAdminReconcile,
    refreshBilling
  } = useApp();

  const [activeTab, setActiveTab] = useState<'overview' | 'developers'>('overview');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'suspended'>('all');
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

  // Per-row processing state for buttons
  const [processingUserId, setProcessingUserId] = useState<string | null>(null);

  // Custom Credit Modal State
  const [creditModalUser, setCreditModalUser] = useState<{ id: string; email: string } | null>(null);
  // "Add to my balance" card on the Overview tab.
  const [selfAmount, setSelfAmount] = useState<string>('100');
  const [selfSubmitting, setSelfSubmitting] = useState(false);
  const [customCreditAmount, setCustomCreditAmount] = useState<string>('25');
  const [creditSubmitting, setCreditSubmitting] = useState(false);
  const [creditModalError, setCreditModalError] = useState<string | null>(null);

  // Billing integrity check (Overview tab). Kept separate from the notice/
  // error toasts above: the result has to stay on screen until the next run.
  const [reconcileRunning, setReconcileRunning] = useState(false);
  const [reconcileResult, setReconcileResult] = useState<ReconcileAdminResponse | null>(null);
  const [reconcileError, setReconcileError] = useState<string | null>(null);

  const isAdmin = user?.role === 'admin';

  const showNotification = (msg: string) => {
    setActionNotice(msg);
    setActionError(null);
    setTimeout(() => setActionNotice(null), 4500);
  };

  const showFailureNotification = (msg: string) => {
    setActionError(msg);
    setActionNotice(null);
    setTimeout(() => setActionError(null), 5000);
  };

  const loadData = useCallback(async () => {
    if (!isAdmin) return;
    setFetchError(null);
    try {
      await Promise.all([loadAdminStats(), loadAdminUsers()]);
    } catch (err: any) {
      if (err instanceof ApiError && (err.status === 403 || err.code === 'admin_required')) {
        setFetchError('Admin privileges required. Your account is not authorized to access server telemetry.');
      } else {
        setFetchError(err?.message || 'Failed to load admin analytics from the server.');
      }
    }
  }, [isAdmin, loadAdminStats, loadAdminUsers]);

  useEffect(() => {
    if (isAdmin) {
      loadData();
    }
  }, [isAdmin, loadData]);

  const handleRunReconcile = async () => {
    if (reconcileRunning) return;
    setReconcileRunning(true);
    setReconcileError(null);
    try {
      setReconcileResult(await runAdminReconcile());
    } catch (err: any) {
      // Drop any earlier result: a stale "all clear" must not sit next to a
      // check that just failed to run.
      setReconcileResult(null);
      setReconcileError(err?.message || 'The check could not run.');
    } finally {
      setReconcileRunning(false);
    }
  };

  // The admin's own balance is shown from the billing data (header, Usage,
  // Account), not from the admin user list, so re-read it after crediting self.
  const refreshIfSelf = (userId: string) => {
    if (user && userId === user.id) refreshBilling().catch(() => {});
  };

  const handleQuickCredit = async (userId: string, userEmail: string, amount: number) => {
    if (processingUserId) return;
    setProcessingUserId(userId);
    try {
      const res = await creditAdminUser(userId, amount);
      refreshIfSelf(userId);
      const newBal = parseFloat(res.new_balance_usd);
      showNotification(`Credited $${amount}.00 to ${userEmail}. New balance: $${isNaN(newBal) ? res.new_balance_usd : newBal.toFixed(2)}`);
    } catch (err: any) {
      showFailureNotification(err?.message || 'Failed to credit user balance.');
    } finally {
      setProcessingUserId(null);
    }
  };

  const handleCustomCreditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!creditModalUser) return;
    const parsedAmount = parseFloat(customCreditAmount);
    if (isNaN(parsedAmount) || parsedAmount <= 0) {
      setCreditModalError('Please enter a valid positive dollar amount.');
      return;
    }

    setCreditSubmitting(true);
    setCreditModalError(null);
    try {
      const res = await creditAdminUser(creditModalUser.id, parsedAmount);
      refreshIfSelf(creditModalUser.id);
      const newBal = parseFloat(res.new_balance_usd);
      showNotification(`Credited $${parsedAmount.toFixed(2)} to ${creditModalUser.email}. New balance: $${isNaN(newBal) ? res.new_balance_usd : newBal.toFixed(2)}`);
      setCreditModalUser(null);
      setCustomCreditAmount('25');
    } catch (err: any) {
      setCreditModalError(err?.message || 'Failed to apply credit adjustment.');
    } finally {
      setCreditSubmitting(false);
    }
  };

  const handleSelfCredit = async (amount: number) => {
    if (!user || selfSubmitting) return;
    if (!isFinite(amount) || amount <= 0) {
      showFailureNotification('Enter an amount greater than $0.');
      return;
    }
    setSelfSubmitting(true);
    try {
      const res = await creditAdminUser(user.id, amount);
      refreshIfSelf(user.id);
      const newBal = parseFloat(res.new_balance_usd);
      showNotification(`Added $${amount.toFixed(2)} to your balance. New balance: $${isNaN(newBal) ? res.new_balance_usd : newBal.toFixed(2)}`);
    } catch (err: any) {
      showFailureNotification(err?.message || 'Failed to add to your balance.');
    } finally {
      setSelfSubmitting(false);
    }
  };

  const handleToggleSuspend = async (userId: string, userEmail: string, currentStatus: 'active' | 'suspended') => {
    if (processingUserId) return;
    setProcessingUserId(userId);

    try {
      if (currentStatus === 'active') {
        const res = await suspendAdminUser(userId);
        const revokedCount = res.api_keys_revoked ?? 0;
        showNotification(`Suspended ${userEmail} — ${revokedCount} active API key${revokedCount === 1 ? '' : 's'} revoked.`);
      } else {
        await activateAdminUser(userId);
        showNotification(`Reactivated ${userEmail} — they'll need to generate a new API key.`);
      }
    } catch (err: any) {
      showFailureNotification(err?.message || 'Failed to update user account status.');
    } finally {
      setProcessingUserId(null);
    }
  };

  const filteredUsers = adminUsers.filter((u) => {
    const q = searchQuery.toLowerCase().trim();
    const matchesSearch =
      !q ||
      u.email.toLowerCase().includes(q) ||
      (u.github_username || '').toLowerCase().includes(q) ||
      u.id.toLowerCase().includes(q);
    const matchesStatus = statusFilter === 'all' || u.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  // isLoggedIn flips true as soon as a session exists (fast, local),
  // but `user` — and its `role` — only populates once loadUserData's
  // backend calls resolve. RequireAuth already lets this page mount
  // during that gap, so without this check a real admin would
  // momentarily see the "Admin Access Required" card below before
  // their role loads in. Distinguish "don't know yet" from "loaded,
  // and definitely not an admin" rather than treating both as denied.
  if (!user) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center text-sm text-ink-3">
        Checking your session…
      </div>
    );
  }

  // Restricted Access View
  if (!isAdmin) {
    return (
      <div className="max-w-xl mx-auto px-4 py-20">
        <div className="card-panel p-8 text-center space-y-6">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-warning-soft text-warning border border-warning-border">
            <Lock className="h-6 w-6" />
          </div>

          <div className="space-y-2">
            <h1 className="text-xl font-medium text-ink tracking-[-0.01em]">
              Admin Access Required
            </h1>
            <p className="text-xs text-ink-3">
              Signed in as <span className="font-mono font-medium text-ink-2">{user?.email || 'developer'}</span>
            </p>
            <p className="text-xs text-ink-2 max-w-sm mx-auto leading-relaxed">
              This administrative dashboard is restricted to authorized server administrators. Admin roles are enforced on the backend.
            </p>
          </div>

          <div className="flex items-center justify-center pt-2">
            <Link
              id="admin-gate-back-btn"
              href={ROUTES.dashboard}
              className="btn-outline-pill !h-10 !px-5 !text-xs"
            >
              Back to Overview
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const revenueNum = adminStats?.revenue_in_window_usd != null ? parseFloat(adminStats.revenue_in_window_usd) : null;
  const cacheHitFormatted = adminStats?.cache_hit_rate_in_window != null
    ? `${(adminStats.cache_hit_rate_in_window * 100).toFixed(1)}%`
    : '—';

  return (
    <div className="max-w-[1160px] mx-auto px-[clamp(20px,5vw,48px)] py-[clamp(40px,7vh,64px)] space-y-8">

      {/* Toast notifications */}
      <div className={`app-toast ${actionNotice ? 'show' : ''}`} style={{ background: actionNotice ? undefined : 'transparent' }}>
        {actionNotice && (
          <span className="flex items-center gap-2.5">
            <CheckCircle2 className="h-4 w-4 text-accent-blue shrink-0" />
            <span className="leading-snug">{actionNotice}</span>
          </span>
        )}
      </div>
      <div className={`app-toast ${actionError ? 'show' : ''}`} style={{ background: actionError ? 'var(--color-danger)' : 'transparent' }}>
        {actionError && (
          <span className="flex items-center gap-2.5">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span className="leading-snug">{actionError}</span>
          </span>
        )}
      </div>

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-5">
        <div>
          <span className="page-eyebrow mb-3">Server</span>
          <div className="flex items-center gap-3 mt-3 mb-2">
            <h1 className="page-title">Admin Analytics</h1>
            <span className="badge-pill">Admin</span>
          </div>
          <p className="page-lead">
            Real-time server telemetry and developer account controls enforced by backend APIs.
          </p>
        </div>

        <button
          id="admin-refresh-data-btn"
          onClick={loadData}
          disabled={isAdminDataLoading}
          className="btn-outline-pill !h-[46px] !px-4 !text-[0.8125rem] disabled:opacity-60"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isAdminDataLoading ? 'animate-spin text-accent-blue' : ''}`} />
          <span>{isAdminDataLoading ? 'Refreshing...' : 'Refresh'}</span>
        </button>
      </div>

      {/* Fetch error banner */}
      {fetchError && (
        <div className="rounded-2xl border border-danger-border bg-danger-soft p-4 flex items-center justify-between gap-3 text-xs text-danger">
          <div className="flex items-center gap-2.5">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{fetchError}</span>
          </div>
          <button
            onClick={loadData}
            className="rounded-full bg-white hover:bg-white/60 px-3 py-1 font-medium text-danger cursor-pointer border border-danger-border"
          >
            Retry
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="tab-group">
        {[
          { id: 'overview', label: 'Overview', icon: Activity },
          { id: 'developers', label: 'Developers', icon: Users, count: adminUsers.length },
        ].map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              id={`admin-tab-${tab.id}`}
              onClick={() => setActiveTab(tab.id as 'overview' | 'developers')}
              className={`tab-pill flex items-center gap-2 ${isActive ? 'active' : ''}`}
            >
              <tab.icon className="h-3.5 w-3.5" />
              <span>{tab.label}</span>
              {tab.count !== undefined && (
                <span className={`rounded-full px-1.5 text-[10px] font-mono ${isActive ? 'bg-white/20' : 'bg-line'}`}>
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* TAB 1: OVERVIEW */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            <div className="stat-card !flex-col !items-start !justify-start">
              <div className="flex items-center justify-between w-full">
                <span className="stat-label">Total Users</span>
                <Users className="h-4 w-4 text-ink-3" />
              </div>
              <span className="stat-value font-mono">
                {adminStats ? adminStats.total_users.toLocaleString() : '—'}
              </span>
            </div>

            <div className="stat-card !flex-col !items-start !justify-start">
              <div className="flex items-center justify-between w-full">
                <span className="stat-label">Revenue ({adminStats?.window_days ?? 30}D)</span>
                <DollarSign className="h-4 w-4 text-accent-blue" />
              </div>
              <span className="stat-value font-mono">
                {revenueNum != null && !isNaN(revenueNum)
                  ? `$${revenueNum.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                  : '—'}
              </span>
            </div>

            <div className="stat-card !flex-col !items-start !justify-start">
              <div className="flex items-center justify-between w-full">
                <span className="stat-label">Requests ({adminStats?.window_days ?? 30}D)</span>
                <Activity className="h-4 w-4 text-accent-blue" />
              </div>
              <span className="stat-value font-mono">
                {adminStats ? adminStats.requests_in_window.toLocaleString() : '—'}
              </span>
            </div>

            <div className="stat-card !flex-col !items-start !justify-start">
              <div className="flex items-center justify-between w-full">
                <span className="stat-label">Cache Hit ({adminStats?.window_days ?? 30}D)</span>
                <Zap className="h-4 w-4 text-accent-blue" />
              </div>
              <span className="stat-value font-mono">{cacheHitFormatted}</span>
            </div>

            <div className="stat-card !flex-col !items-start !justify-start">
              <div className="flex items-center justify-between w-full">
                <span className="stat-label">Active Keys</span>
                <Key className="h-4 w-4 text-warning" />
              </div>
              <span className="stat-value font-mono">
                {adminStats ? adminStats.active_api_keys.toLocaleString() : '—'}
              </span>
            </div>
          </div>

          <div className="card-panel p-6 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2">
              <div className="space-y-1.5">
                <h3 className="text-sm font-medium text-ink tracking-[-0.01em]">Add to my balance</h3>
                <p className="text-xs text-ink-2 leading-relaxed max-w-2xl">
                  Top up your own account by any amount, with no payment. It is recorded in your ledger as an admin self-credit. Like every credit, it expires 12 months after it is added.
                </p>
              </div>
              <div className="text-left sm:text-right shrink-0">
                <div className="stat-label">Your balance</div>
                <div className="font-mono text-lg font-medium text-ink">
                  {user.creditBalance != null ? `$${user.creditBalance.toFixed(2)}` : '—'}
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {[10, 100, 1000, 10000].map((amt) => (
                <button
                  key={amt}
                  type="button"
                  onClick={() => handleSelfCredit(amt)}
                  disabled={selfSubmitting}
                  className="rounded-full border border-line bg-white px-3 py-1.5 text-xs font-medium text-ink-2 hover:bg-surface transition-colors cursor-pointer disabled:opacity-50"
                >
                  +${amt.toLocaleString()}
                </button>
              ))}
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleSelfCredit(parseFloat(selfAmount));
                }}
                className="flex items-center gap-2"
              >
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs font-medium text-ink-3">$</span>
                  <input
                    type="number"
                    min="0.01"
                    step="any"
                    value={selfAmount}
                    onChange={(e) => setSelfAmount(e.target.value)}
                    aria-label="Custom amount to add to your balance (USD)"
                    className="w-32 rounded-xl border border-line bg-white pl-6 pr-3 py-1.5 text-xs text-ink font-mono focus:border-accent-blue focus:outline-none"
                  />
                </div>
                <button
                  type="submit"
                  disabled={selfSubmitting}
                  className="btn-pill btn-pill-dark !h-8 !px-3.5 !text-xs disabled:opacity-60"
                >
                  {selfSubmitting ? 'Adding...' : 'Add'}
                </button>
              </form>
            </div>
          </div>

          <div className="card-panel p-6 space-y-3">
            <h3 className="text-sm font-medium text-ink tracking-[-0.01em]">
              System Architecture &amp; Billing Model
            </h3>
            <p className="text-xs text-ink-2 leading-relaxed max-w-4xl">
              Quancis operates on a prepaid credit balance with usage-based billing per million input, cached input, and output tokens.
              The revenue metric above reflects actual settled token consumption across the active {adminStats?.window_days ?? 30}-day trailing window.
            </p>
          </div>

          <div className="card-panel p-6 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
              <div className="space-y-1.5">
                <h3 className="text-sm font-medium text-ink tracking-[-0.01em]">
                  Billing integrity check
                </h3>
                <p className="text-xs text-ink-2 leading-relaxed max-w-2xl">
                  Compares every account&apos;s balance with its ledger history. Read-only: it never changes a balance.
                  The server also runs it automatically about once a day while it is awake.
                </p>
              </div>
              <button
                id="admin-run-reconcile-btn"
                onClick={handleRunReconcile}
                disabled={reconcileRunning}
                className="btn-outline-pill !h-10 !px-4 !text-xs shrink-0 disabled:opacity-60"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${reconcileRunning ? 'animate-spin text-accent-blue' : ''}`} />
                <span>{reconcileRunning ? 'Checking...' : 'Run check'}</span>
              </button>
            </div>

            <div aria-live="polite" className="space-y-3">
              {reconcileError && (
                <div className="rounded-2xl border border-danger-border bg-danger-soft p-4 flex items-start gap-2.5 text-xs text-danger">
                  <AlertCircle className="h-4 w-4 shrink-0 mt-px" />
                  <div className="min-w-0">
                    <div className="break-words">{reconcileError}</div>
                    <div className="mt-1 font-medium">Balances were not verified.</div>
                  </div>
                </div>
              )}

              {reconcileResult && reconcileResult.status === 'ok' && (
                <div className="rounded-2xl border border-success-border bg-success-soft p-4 flex items-start gap-2.5 text-xs text-success">
                  <CheckCircle2 className="h-4 w-4 shrink-0 mt-px" />
                  <span>
                    Every account matches its ledger history.{' '}
                    <span className="opacity-80">Checked {new Date(reconcileResult.checked_at).toLocaleString()}.</span>
                  </span>
                </div>
              )}

              {reconcileResult && reconcileResult.status === 'drift' && (
                <div className="rounded-2xl border border-warning-border bg-warning-soft p-4 space-y-3 text-xs text-warning">
                  <div className="flex items-start gap-2.5">
                    <AlertCircle className="h-4 w-4 shrink-0 mt-px" />
                    <span>
                      Drift found in {reconcileResult.drift_count} account{reconcileResult.drift_count === 1 ? '' : 's'}:
                      balance and ledger history do not match. Nothing was changed; someone needs to work out
                      why before any balance is touched.{' '}
                      <span className="opacity-80">Checked {new Date(reconcileResult.checked_at).toLocaleString()}.</span>
                    </span>
                  </div>
                  <ul className="space-y-2">
                    {reconcileResult.drifts.map((d) => {
                      const email = adminUsers.find((u) => u.id === d.user_id)?.email;
                      return (
                        <li key={d.user_id} className="rounded-xl border border-warning-border bg-white/60 p-3 space-y-1">
                          {email && <div className="font-medium text-ink break-all">{email}</div>}
                          <div className="font-mono text-[0.6875rem] text-ink-3 break-all">{d.user_id}</div>
                          <div className="grid grid-cols-3 gap-2 pt-1 font-mono text-[0.6875rem] text-ink-2">
                            <span>Expected<br />{formatReconcileUsd(d.expected_balance_usd)}</span>
                            <span>Actual<br />{formatReconcileUsd(d.actual_balance_usd)}</span>
                            <span>Drift<br />{formatReconcileUsd(d.drift_usd)}</span>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: DEVELOPERS */}
      {activeTab === 'developers' && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-medium text-ink tracking-[-0.01em]">Developer Directory</h2>
              <p className="text-xs text-ink-3 mt-0.5">
                {filteredUsers.length} account{filteredUsers.length === 1 ? '' : 's'} registered in Supabase
              </p>
            </div>

            <div className="flex items-center gap-2.5">
              <div className="relative">
                <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-ink-3" />
                <input
                  id="admin-search-users-input"
                  type="text"
                  placeholder="Search by email, GitHub, or ID..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="rounded-full border border-line bg-white pl-9 pr-4 py-2 text-xs text-ink focus:border-accent-blue focus:outline-none w-56 sm:w-64"
                />
              </div>

              <select
                id="admin-status-filter-select"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as 'all' | 'active' | 'suspended')}
                className="rounded-full border border-line bg-white px-3.5 py-2 text-xs text-ink-2 focus:outline-none cursor-pointer"
              >
                <option value="all">All Statuses</option>
                <option value="active">Active</option>
                <option value="suspended">Suspended</option>
              </select>
            </div>
          </div>

          <div className="table-card">
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Developer</th>
                    <th>Spend</th>
                    <th>Balance</th>
                    <th>Requests</th>
                    <th>Status</th>
                    <th className="text-right" style={{ textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredUsers.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="text-center text-ink-3">
                        {adminUsers.length === 0 && isAdminDataLoading
                          ? 'Loading developer records from backend...'
                          : 'No developer accounts found matching criteria.'}
                      </td>
                    </tr>
                  ) : (
                    filteredUsers.map((u) => {
                      const spendNum = u.total_spend_usd != null ? parseFloat(u.total_spend_usd) : 0;
                      const balanceNum = u.credit_balance_usd != null ? parseFloat(u.credit_balance_usd) : null;
                      const initialLetter = (u.email || '?')[0].toUpperCase();
                      const isProcessing = processingUserId === u.id;

                      return (
                        <tr key={u.id} className="hover:bg-surface transition-colors">
                          <td>
                            <div className="flex items-center gap-2.5">
                              <div className="h-8 w-8 rounded-full bg-line text-ink-2 font-medium text-xs flex items-center justify-center shrink-0 font-mono">
                                {initialLetter}
                              </div>
                              <div>
                                <div className="font-medium text-ink flex items-center gap-1.5">
                                  <span>{u.email}</span>
                                  {u.is_admin && (
                                    <span className="rounded-md bg-accent-blue-soft text-accent-blue text-[9px] font-mono px-1.5 py-0.5 font-semibold border border-accent-blue-border">
                                      ADMIN
                                    </span>
                                  )}
                                  {u.id === user.id && <span className="text-[11px] text-ink-3">(you)</span>}
                                </div>
                                {u.github_username && (
                                  <div className="text-[11px] text-ink-3 font-mono">
                                    @{u.github_username}
                                  </div>
                                )}
                              </div>
                            </div>
                          </td>

                          <td className="font-mono font-medium text-ink">
                            ${isNaN(spendNum) ? '0.00' : spendNum.toFixed(2)}
                          </td>

                          <td className="font-mono text-accent-blue font-medium">
                            {balanceNum != null && !isNaN(balanceNum) ? `$${balanceNum.toFixed(2)}` : '—'}
                          </td>

                          <td className="font-mono">
                            {u.total_requests.toLocaleString()}
                          </td>

                          <td>
                            <span className={`badge-pill !rounded-full ${u.status === 'active' ? '' : 'badge-pill-danger'}`}>
                              <span className={`h-1.5 w-1.5 rounded-full mr-1 ${u.status === 'active' ? 'bg-accent-blue' : 'bg-danger'}`} />
                              <span className="capitalize">{u.status}</span>
                            </span>
                          </td>

                          <td className="text-right">
                            {u.is_admin && u.id !== user.id ? (
                              <span className="text-[11px] text-ink-3 italic">
                                Managed in Supabase
                              </span>
                            ) : (
                            <div className="inline-flex items-center gap-1.5">
                              <button
                                onClick={() => handleQuickCredit(u.id, u.email, 50)}
                                disabled={isProcessing}
                                className="rounded-full border border-line bg-white px-2.5 py-1 text-[11px] font-medium text-ink-2 hover:bg-surface transition-colors cursor-pointer disabled:opacity-50"
                                title="Add $50 credit"
                              >
                                +$50
                              </button>

                              <button
                                onClick={() => {
                                  setCreditModalUser({ id: u.id, email: u.email });
                                  setCustomCreditAmount('25');
                                  setCreditModalError(null);
                                }}
                                disabled={isProcessing}
                                className="rounded-full border border-line bg-white px-2.5 py-1 text-[11px] font-medium text-ink-2 hover:bg-surface transition-colors cursor-pointer disabled:opacity-50"
                                title="Custom Credit Amount"
                              >
                                <PlusCircle className="h-3 w-3 inline mr-0.5 text-ink-3" />
                                Credit
                              </button>

                              {!u.is_admin && (
                              <button
                                onClick={() => handleToggleSuspend(u.id, u.email, u.status)}
                                disabled={isProcessing}
                                className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors cursor-pointer disabled:opacity-50 ${
                                  u.status === 'active'
                                    ? 'text-warning hover:bg-warning-soft border border-warning-border'
                                    : 'text-accent-blue hover:bg-accent-blue-soft border border-accent-blue-border'
                                }`}
                              >
                                {isProcessing ? 'Saving...' : u.status === 'active' ? 'Suspend' : 'Activate'}
                              </button>
                              )}
                            </div>
                            )}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Custom Credit Adjustment Modal */}
      {creditModalUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-[28px] bg-white p-6 shadow-2xl border border-line space-y-4">
            <div className="flex items-center justify-between border-b border-line-soft pb-3">
              <h3 className="text-sm font-medium text-ink tracking-[-0.01em] flex items-center gap-2">
                <DollarSign className="h-4 w-4 text-accent-blue" />
                <span>{creditModalUser.id === user.id ? 'Add to My Balance' : 'Adjust Account Credit'}</span>
              </h3>
              <button
                onClick={() => setCreditModalUser(null)}
                className="text-ink-3 hover:text-ink p-1 rounded-xl cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <p className="text-xs text-ink-2">
              {creditModalUser.id === user.id ? 'Add prepaid credit to your own account' : 'Grant prepaid credit balance to account'} <span className="font-medium text-ink">{creditModalUser.email}</span>.
            </p>

            <form onSubmit={handleCustomCreditSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-ink-2 mb-1.5">
                  Credit Amount (USD)
                </label>
                <div className="relative">
                  <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-xs font-medium text-ink-3">$</span>
                  <input
                    type="number"
                    min="0.01"
                    step="any"
                    value={customCreditAmount}
                    onChange={(e) => setCustomCreditAmount(e.target.value)}
                    placeholder="50"
                    required
                    className="w-full rounded-xl border border-line bg-white pl-7 pr-3 py-2 text-xs text-ink font-mono focus:border-accent-blue focus:outline-none"
                  />
                </div>
              </div>

              {creditModalError && (
                <div className="text-xs text-danger font-medium">
                  {creditModalError}
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-line-soft">
                <button
                  type="button"
                  onClick={() => setCreditModalUser(null)}
                  disabled={creditSubmitting}
                  className="btn-outline-pill !h-9 !px-3.5 !text-xs"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creditSubmitting}
                  className="btn-pill btn-pill-dark !h-9 !px-4 !text-xs disabled:opacity-60"
                >
                  {creditSubmitting ? 'Applying Credit...' : 'Confirm Credit'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
