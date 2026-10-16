'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useApp } from '../../context/AppContext';
import { ROUTES } from '../../lib/routes';
import {
  User,
  ShieldCheck,
  Bell,
  Check,
  Save,
  Key,
  Loader2,
  AlertCircle,
  Trash2,
} from 'lucide-react';

const PROVIDER_LABELS: Record<string, string> = {
  email: 'Email & Password',
  google: 'Google',
  github: 'GitHub',
};

const providerLabel = (provider: string | undefined): string =>
  (provider && PROVIDER_LABELS[provider]) || provider || 'Email & Password';

// user.createdAt is a real 'YYYY-MM-DD' string sourced from Supabase
// Auth's own created_at — this just makes it readable, it doesn't
// invent anything (the old copy here was a hardcoded "March 2026" shown
// to every account regardless of when they actually signed up).
const formatMemberSince = (createdAt: string | undefined): string => {
  if (!createdAt) return 'Unknown';
  const d = new Date(`${createdAt}T00:00:00Z`);
  if (isNaN(d.getTime())) return 'Unknown';
  return d.toLocaleDateString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' });
};

export const AccountPage: React.FC = () => {
  const { user, saveDisplayName, changeOwnPassword, updateNotificationPrefs, deleteAccount } = useApp();

  const [activeTab, setActiveTab] = useState<'profile' | 'security' | 'notifications'>('profile');

  // --- Profile: name (email is real + read-only, see render below) ---
  const [name, setName] = useState(user?.name || '');
  const [nameSaving, setNameSaving] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  const [nameSuccess, setNameSuccess] = useState(false);
  useEffect(() => {
    setName(user?.name || '');
  }, [user?.name]);

  const handleSaveName = async (e: React.FormEvent) => {
    e.preventDefault();
    setNameError(null);
    setNameSaving(true);
    const { error } = await saveDisplayName(name);
    setNameSaving(false);
    if (error) {
      setNameError(error);
      return;
    }
    setNameSuccess(true);
    setTimeout(() => setNameSuccess(false), 2500);
  };

  // --- Security: password change, only meaningful for email/password accounts ---
  const isEmailAccount = (user?.provider || 'email') === 'email';
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [pwSaving, setPwSaving] = useState(false);
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwSuccess, setPwSuccess] = useState(false);

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPwError(null);
    if (newPassword.length < 8) {
      setPwError('New password must be at least 8 characters.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setPwError('New password and confirmation do not match.');
      return;
    }
    setPwSaving(true);
    const { error } = await changeOwnPassword(currentPassword, newPassword);
    setPwSaving(false);
    if (error) {
      setPwError(error);
      return;
    }
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setPwSuccess(true);
    setTimeout(() => setPwSuccess(false), 2500);
  };

  // --- Delete account (DELETE /api/account, backend app/account.py) ---
  // Two steps on purpose: the button only opens the confirmation panel, and the
  // final button stays disabled until the typed text matches the account email
  // (or the word DELETE for an account with no email, which the backend also
  // accepts). The backend checks the same thing again; this is only so a
  // mistyped confirmation never reaches it. Admin accounts cannot be deleted
  // from here (the backend answers 403), so they get an explanation instead.
  const deleteExpected = (user?.email || '').trim() || 'DELETE';
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deleteMatches = (user?.email || '').trim()
    ? deleteConfirm.trim().toLowerCase() === deleteExpected.toLowerCase()
    : deleteConfirm.trim() === 'DELETE';

  const handleDeleteAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!deleteMatches || deleting) return;
    setDeleteError(null);
    setDeleting(true);
    // On success the context signs you out and returns to the home page, so there
    // is nothing to reset here; on failure the account still exists.
    const { error } = await deleteAccount(deleteConfirm);
    if (error) {
      setDeleting(false);
      setDeleteError(error);
    }
  };

  // --- Notifications: real, persisted low-balance alert preference ---
  const [lowBalanceAlert, setLowBalanceAlert] = useState(user?.lowBalanceAlertEnabled ?? false);
  const [alertThreshold, setAlertThreshold] = useState(
    String(user?.lowBalanceAlertThresholdUsd ?? 10)
  );
  const [notifSaving, setNotifSaving] = useState(false);
  const [notifError, setNotifError] = useState<string | null>(null);
  const [notifSuccess, setNotifSuccess] = useState(false);
  useEffect(() => {
    setLowBalanceAlert(user?.lowBalanceAlertEnabled ?? false);
    setAlertThreshold(String(user?.lowBalanceAlertThresholdUsd ?? 10));
  }, [user?.lowBalanceAlertEnabled, user?.lowBalanceAlertThresholdUsd]);

  const handleSaveNotifications = async (e: React.FormEvent) => {
    e.preventDefault();
    setNotifError(null);
    const thresholdNumber = parseFloat(alertThreshold);
    if (isNaN(thresholdNumber) || thresholdNumber < 0) {
      setNotifError('Enter a valid, non-negative dollar amount.');
      return;
    }
    setNotifSaving(true);
    const { error } = await updateNotificationPrefs(lowBalanceAlert, thresholdNumber);
    setNotifSaving(false);
    if (error) {
      setNotifError(error);
      return;
    }
    setNotifSuccess(true);
    setTimeout(() => setNotifSuccess(false), 2500);
  };

  const tabs = [
    { id: 'profile' as const, label: 'Profile', icon: User },
    { id: 'security' as const, label: 'Security', icon: ShieldCheck },
    { id: 'notifications' as const, label: 'Notifications', icon: Bell },
  ];

  return (
    <div className="max-w-[1160px] mx-auto px-[clamp(20px,5vw,48px)] py-[clamp(40px,7vh,64px)] space-y-8">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-5">
        <div>
          <span className="page-eyebrow mb-3">Settings</span>
          <h1 className="page-title mt-3 mb-2">Account &amp; Settings</h1>
          <p className="page-lead">
            Manage your developer profile, security, and notification preferences.
          </p>
        </div>

        <Link href={ROUTES.dashboard} className="btn-outline-pill !h-[46px] !px-4 !text-[0.8125rem]">
          &larr; Back to Dashboard
        </Link>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-12 gap-8">

        {/* Left Navigation Sidebar */}
        <div className="md:col-span-3 space-y-4">
          <div className="rounded-2xl border border-line bg-white p-4 space-y-1 shadow-none">
            <div className="px-3 py-2 text-[11px] font-mono uppercase text-ink-3 font-bold">
              Settings Menu
            </div>
            {tabs.map((tab) => {
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`w-full flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-medium transition-all cursor-pointer ${
                    isActive
                      ? 'bg-accent-blue-soft text-accent-blue border border-accent-blue-border font-bold'
                      : 'text-ink-2 hover:bg-surface hover:text-ink'
                  }`}
                >
                  <tab.icon className={`h-4 w-4 ${isActive ? 'text-accent-blue-hover' : 'text-ink-3'}`} />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </div>

          {/* Account Summary Card */}
          <div className="rounded-2xl border border-line bg-white p-5 space-y-3 shadow-none">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-mono uppercase text-ink-3 font-semibold">Tier Plan</span>
              <span className="rounded-xl bg-accent-blue-soft px-2 py-0.5 text-[10px] font-bold text-accent-blue border border-accent-blue-border">
                {user?.tier || 'Scale Tier'}
              </span>
            </div>
            <div className="text-sm font-bold text-ink">
              {user?.name || '—'}
            </div>
            <div className="text-xs text-ink-3 font-mono truncate">
              {user?.email || 'No email on file'}
            </div>
            <div className="pt-3 border-t border-line-soft flex items-center justify-between text-xs">
              <span className="text-ink-3">Balance</span>
              <span className="font-mono font-bold text-accent-blue-hover">
                {user?.creditBalance != null ? `$${user.creditBalance.toFixed(2)}` : '—'}
              </span>
            </div>
          </div>

          {user?.role === 'admin' && (
            <div className="rounded-2xl border border-accent-blue-border bg-accent-blue-soft/70 p-4 space-y-2 shadow-none">
              <div className="flex items-center gap-2 text-xs font-bold text-ink">
                <ShieldCheck className="h-4 w-4 text-accent-blue" />
                <span>Superadmin Access</span>
              </div>
              <p className="text-[11px] text-ink-2 leading-relaxed">
                You have authorized administrator access to global telemetry and Supabase database tables.
              </p>
              <Link
                href={ROUTES.admin}
                className="w-full mt-2 rounded-xl bg-ink py-2 text-xs font-bold text-white hover:bg-ink transition-colors text-center cursor-pointer  block"
              >
                Open Admin Portal &rarr;
              </Link>
            </div>
          )}
        </div>

        {/* Right Tab Content */}
        <div className="md:col-span-9 space-y-6">

          {/* TAB 1: PROFILE */}
          {activeTab === 'profile' && (
            <div className="space-y-6">

              <div className="rounded-2xl border border-line bg-white p-6 shadow-none space-y-6">
                <div>
                  <h2 className="text-base font-bold text-ink">Personal Information</h2>
                  <p className="text-xs text-ink-3 mt-0.5">
                    Your display name is used across the dashboard and in billing receipts.
                  </p>
                </div>

                <form onSubmit={handleSaveName} className="space-y-4">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <label className="text-xs font-semibold text-ink-2">Full Name</label>
                      <input
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        className="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-xs text-ink focus:bg-white focus:border-accent-blue focus:outline-none transition-colors"
                      />
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-xs font-semibold text-ink-2">Account Email</label>
                      <input
                        type="email"
                        value={user?.email || ''}
                        disabled
                        placeholder="No email on file"
                        className="w-full rounded-xl border border-line bg-line-soft px-3.5 py-2.5 text-xs font-mono text-ink-3 cursor-not-allowed"
                      />
                      <p className="text-[11px] text-ink-3">
                        Tied to your {providerLabel(user?.provider)} sign-in — can&rsquo;t be changed here.
                      </p>
                    </div>
                  </div>

                  {nameError && (
                    <div className="flex items-center gap-2 text-xs text-danger">
                      <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                      <span>{nameError}</span>
                    </div>
                  )}

                  <div className="pt-4 flex items-center justify-between border-t border-line-soft">
                    <span className="text-xs text-ink-3">
                      Member since {formatMemberSince(user?.createdAt)} &middot; Signed in with {providerLabel(user?.provider)}
                    </span>
                    <button
                      type="submit"
                      disabled={nameSaving}
                      className="flex items-center gap-2 rounded-xl bg-accent-blue px-5 py-2.5 text-xs font-bold text-white shadow-none hover:bg-accent-blue transition-all cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
                    >
                      {nameSaving ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : nameSuccess ? (
                        <Check className="h-4 w-4" />
                      ) : (
                        <Save className="h-4 w-4" />
                      )}
                      <span>{nameSuccess ? 'Changes Saved' : 'Save Changes'}</span>
                    </button>
                  </div>
                </form>
              </div>

            </div>
          )}

          {/* TAB 2: SECURITY */}
          {activeTab === 'security' && (
            <div className="space-y-6">

              {isEmailAccount ? (
                <div className="rounded-2xl border border-line bg-white p-6 shadow-none space-y-4">
                  <div className="flex items-center gap-2">
                    <Key className="h-5 w-5 text-ink-2" />
                    <h2 className="text-base font-bold text-ink">Password &amp; Authentication</h2>
                  </div>
                  <p className="text-xs text-ink-3">
                    Choose a new password of at least 8 characters.
                  </p>

                  <form onSubmit={handleChangePassword} className="space-y-4">
                    <div className="space-y-1.5">
                      <label className="text-xs font-semibold text-ink-2">Current Password</label>
                      <input
                        type="password"
                        value={currentPassword}
                        onChange={(e) => setCurrentPassword(e.target.value)}
                        placeholder="••••••••••••"
                        className="w-full max-w-sm rounded-xl border border-line bg-surface px-3.5 py-2.5 text-xs text-ink focus:bg-white focus:border-accent-blue focus:outline-none"
                      />
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div className="space-y-1.5">
                        <label className="text-xs font-semibold text-ink-2">New Password</label>
                        <input
                          type="password"
                          value={newPassword}
                          onChange={(e) => setNewPassword(e.target.value)}
                          placeholder="••••••••••••"
                          className="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-xs text-ink focus:bg-white focus:border-accent-blue focus:outline-none"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <label className="text-xs font-semibold text-ink-2">Confirm New Password</label>
                        <input
                          type="password"
                          value={confirmPassword}
                          onChange={(e) => setConfirmPassword(e.target.value)}
                          placeholder="••••••••••••"
                          className="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-xs text-ink focus:bg-white focus:border-accent-blue focus:outline-none"
                        />
                      </div>
                    </div>

                    {pwError && (
                      <div className="flex items-center gap-2 text-xs text-danger">
                        <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                        <span>{pwError}</span>
                      </div>
                    )}

                    <div className="pt-2 flex justify-end">
                      <button
                        type="submit"
                        disabled={pwSaving}
                        className="flex items-center gap-2 rounded-xl bg-ink px-4 py-2 text-xs font-semibold text-white hover:bg-ink transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
                      >
                        {pwSaving ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : pwSuccess ? (
                          <Check className="h-4 w-4" />
                        ) : null}
                        <span>{pwSuccess ? 'Password Updated' : 'Update Password'}</span>
                      </button>
                    </div>
                  </form>
                </div>
              ) : (
                <div className="rounded-2xl border border-line bg-white p-6 shadow-none space-y-2">
                  <div className="flex items-center gap-2">
                    <Key className="h-5 w-5 text-ink-2" />
                    <h2 className="text-base font-bold text-ink">Password &amp; Authentication</h2>
                  </div>
                  <p className="text-xs text-ink-3 leading-relaxed">
                    You sign in with {providerLabel(user?.provider)}. Quancis doesn&rsquo;t store a password
                    for this account — manage your credentials directly with {providerLabel(user?.provider)}.
                  </p>
                </div>
              )}

              {/* Delete account */}
              <div className="rounded-2xl border border-danger-border bg-white p-6 shadow-none space-y-4">
                <div className="flex items-center gap-2">
                  <Trash2 className="h-5 w-5 text-danger" />
                  <h2 className="text-base font-bold text-ink">Delete Account</h2>
                </div>

                {user?.role === 'admin' ? (
                  <p className="text-xs text-ink-3 leading-relaxed">
                    Administrator accounts can&rsquo;t be deleted from this page. They are removed directly by the
                    owner.
                  </p>
                ) : (
                  <>
                    <p className="text-xs text-ink-2 leading-relaxed">
                      Permanently delete your Quancis account and everything stored with it. This takes effect straight
                      away and <strong className="text-ink">cannot be undone</strong>.
                    </p>
                    <ul className="list-disc pl-5 space-y-1 text-xs text-ink-2 leading-relaxed">
                      <li>All of your API keys stop working.</li>
                      <li>
                        Your Playground conversations, usage records, billing history, and sign-in are deleted.
                      </li>
                      <li>
                        <strong className="text-ink">Any credits left on your account are lost.</strong> Credits have
                        no cash value and are not refunded when an account is deleted
                        {user?.creditBalance != null && user.creditBalance > 0
                          ? ` (you have $${user.creditBalance.toFixed(2)} left)`
                          : ''}
                        . If you are due a refund of unused credits (within 14 days of buying them), ask for it
                        at{' '}
                        <a href="mailto:support@quancis.space" className="text-accent-blue hover:underline">
                          support@quancis.space
                        </a>{' '}
                        before you delete.
                      </li>
                      <li>
                        Payment records are kept by our payment provider, and accounting records the law requires us to
                        keep stay. See the{' '}
                        <Link href="/privacy-policy" className="text-accent-blue hover:underline">
                          Privacy Policy
                        </Link>
                        .
                      </li>
                    </ul>

                    {!deleteOpen ? (
                      <div className="pt-1">
                        <button
                          type="button"
                          onClick={() => setDeleteOpen(true)}
                          className="flex items-center gap-2 rounded-xl border border-danger-border bg-danger-soft px-4 py-2 text-xs font-semibold text-danger hover:bg-white transition-colors cursor-pointer"
                        >
                          <Trash2 className="h-4 w-4" />
                          <span>Delete my account&hellip;</span>
                        </button>
                      </div>
                    ) : (
                      <form onSubmit={handleDeleteAccount} className="space-y-3 pt-1">
                        <div className="space-y-1.5">
                          <label className="text-xs font-semibold text-ink-2" htmlFor="delete-account-confirm">
                            To confirm, type <span className="font-mono text-ink">{deleteExpected}</span>
                          </label>
                          <input
                            id="delete-account-confirm"
                            type="text"
                            value={deleteConfirm}
                            onChange={(e) => setDeleteConfirm(e.target.value)}
                            autoComplete="off"
                            autoCapitalize="off"
                            spellCheck={false}
                            placeholder={deleteExpected}
                            className="w-full max-w-sm rounded-xl border border-line bg-surface px-3.5 py-2.5 text-xs text-ink focus:bg-white focus:border-danger focus:outline-none"
                          />
                        </div>

                        {deleteError && (
                          <div className="flex items-center gap-2 text-xs text-danger">
                            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                            <span>{deleteError}</span>
                          </div>
                        )}

                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="submit"
                            disabled={!deleteMatches || deleting}
                            className="flex items-center gap-2 rounded-xl bg-danger px-4 py-2 text-xs font-semibold text-white hover:opacity-90 transition-opacity cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                            <span>{deleting ? 'Deleting…' : 'Permanently delete my account'}</span>
                          </button>
                          <button
                            type="button"
                            disabled={deleting}
                            onClick={() => {
                              setDeleteOpen(false);
                              setDeleteConfirm('');
                              setDeleteError(null);
                            }}
                            className="rounded-xl border border-line bg-white px-4 py-2 text-xs font-semibold text-ink-2 hover:bg-surface transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
                          >
                            Cancel
                          </button>
                        </div>
                      </form>
                    )}
                  </>
                )}
              </div>

            </div>
          )}

          {/* TAB 3: NOTIFICATIONS */}
          {activeTab === 'notifications' && (
            <div className="space-y-6">

              <form onSubmit={handleSaveNotifications} className="rounded-2xl border border-line bg-white p-6 shadow-none space-y-6">
                <div>
                  <h2 className="text-base font-bold text-ink">Credit Balance &amp; Spend Alerts</h2>
                  <p className="text-xs text-ink-3 mt-0.5">
                    Get notified before your balance depletes to prevent API request drops. We&rsquo;ll
                    email you roughly once a day for as long as your balance stays under this amount.
                  </p>
                </div>

                <div className="space-y-4">
                  <div className="flex items-center justify-between p-4 rounded-xl border border-line bg-surface">
                    <div className="space-y-0.5">
                      <div className="text-xs font-bold text-ink">Low Balance Email Notification</div>
                      <div className="text-[11px] text-ink-3">
                        Send an email alert when prepaid credits drop below the threshold below.
                      </div>
                    </div>
                    <input
                      type="checkbox"
                      checked={lowBalanceAlert}
                      onChange={(e) => setLowBalanceAlert(e.target.checked)}
                      className="h-4 w-4 rounded border-line text-accent-blue focus:ring-accent-blue cursor-pointer"
                    />
                  </div>

                  {lowBalanceAlert && (
                    <div className="space-y-1.5 pt-2">
                      <label className="text-xs font-semibold text-ink-2">Alert Threshold ($ USD)</label>
                      <div className="relative max-w-xs">
                        <span className="absolute left-3.5 top-2.5 text-xs text-ink-3 font-mono">$</span>
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          value={alertThreshold}
                          onChange={(e) => setAlertThreshold(e.target.value)}
                          className="w-full rounded-xl border border-line bg-surface pl-7 pr-3.5 py-2.5 text-xs text-ink font-mono focus:bg-white focus:border-accent-blue focus:outline-none"
                        />
                      </div>
                    </div>
                  )}

                  {notifError && (
                    <div className="flex items-center gap-2 text-xs text-danger">
                      <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                      <span>{notifError}</span>
                    </div>
                  )}

                  <div className="pt-2 flex justify-end">
                    <button
                      type="submit"
                      disabled={notifSaving}
                      className="flex items-center gap-2 rounded-xl bg-accent-blue px-5 py-2.5 text-xs font-bold text-white shadow-none hover:bg-accent-blue transition-all cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
                    >
                      {notifSaving ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : notifSuccess ? (
                        <Check className="h-4 w-4" />
                      ) : (
                        <Save className="h-4 w-4" />
                      )}
                      <span>{notifSuccess ? 'Preferences Saved' : 'Save Preferences'}</span>
                    </button>
                  </div>
                </div>
              </form>

            </div>
          )}

        </div>

      </div>

    </div>
  );
};
