'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useApp } from '../../context/AppContext';
import { AlertCircle, CheckCircle2, Lock } from 'lucide-react';

export const ResetPasswordPage: React.FC = () => {
  const { updatePassword } = useApp();
  const router = useRouter();
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isDone, setIsDone] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    if (password.length < 8) {
      setErrorMessage('Password must be at least 8 characters.');
      return;
    }
    if (password !== confirmPassword) {
      setErrorMessage('Passwords do not match.');
      return;
    }

    setIsSubmitting(true);
    try {
      const { error } = await updatePassword(password);
      if (error) {
        setErrorMessage(error);
      } else {
        setIsDone(true);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-[calc(100vh-8rem)] flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-md space-y-6">
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center h-12 w-12 rounded-2xl bg-ink text-white shadow-md mb-2">
            <Lock className="h-5 w-5" />
          </div>
          <h1 className="text-2xl font-medium text-ink tracking-tight">
            Set a new password
          </h1>
          <p className="text-xs text-ink-3 max-w-xs mx-auto">
            Choose a new password for your Quancis account.
          </p>
        </div>

        {errorMessage && (
          <div className="rounded-2xl border border-danger-border bg-danger-soft/90 p-4 text-xs text-danger flex items-start gap-3 shadow-none">
            <AlertCircle className="h-4 w-4 shrink-0 text-danger mt-0.5" />
            <p className="text-[11px] leading-relaxed text-danger">{errorMessage}</p>
          </div>
        )}

        <div className="rounded-3xl border border-line bg-white p-6 sm:p-8 shadow-none space-y-6">
          {isDone ? (
            <div className="flex flex-col items-center text-center gap-3 py-4">
              <CheckCircle2 className="h-8 w-8 text-accent-blue" />
              <p className="text-sm font-bold text-ink">Password updated</p>
              <p className="text-xs text-ink-3">You can now sign in with your new password.</p>
              <button
                type="button"
                onClick={() => router.push('/login')}
                className="mt-2 w-full rounded-2xl bg-ink px-4 py-3 text-xs sm:text-sm font-bold text-white shadow-md hover:bg-ink active:scale-[0.99] transition-all cursor-pointer"
              >
                Go to sign in
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label htmlFor="new-password" className="text-xs font-bold text-ink-2">New password</label>
                <input
                  id="new-password"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-xl border border-line px-3.5 py-2.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ink/10 focus:border-ink-3"
                  placeholder="At least 8 characters"
                  required
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="confirm-password" className="text-xs font-bold text-ink-2">Confirm new password</label>
                <input
                  id="confirm-password"
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="w-full rounded-xl border border-line px-3.5 py-2.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ink/10 focus:border-ink-3"
                  required
                />
              </div>
              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full rounded-2xl bg-ink px-4 py-3.5 text-xs sm:text-sm font-bold text-white shadow-md hover:bg-ink active:scale-[0.99] transition-all cursor-pointer disabled:opacity-60"
              >
                {isSubmitting ? 'Updating...' : 'Update password'}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};
