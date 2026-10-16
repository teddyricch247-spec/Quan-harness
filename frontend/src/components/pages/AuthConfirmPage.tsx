'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AlertCircle, CheckCircle2, Lock } from 'lucide-react';
import { getSupabase } from '../../lib/supabase';

// Landing page for the links in the confirm-signup and reset-password
// emails when the backend runs with AUTH_LINK_MODE=confirm_page (see
// backend app/config.py and auth_email._auth_link). The email links to
//   /auth/confirm?token_hash=...&type=magiclink|recovery
// and the one-time token is only spent when the person presses the button
// below (supabase.auth.verifyOtp). That is the point of the page: email
// security scanners that pre-fetch every link in a message only load this
// harmless page, so they cannot burn the token before the real person
// clicks, and the link in the email sits on our own domain.
//
// Success needs no routing code here: verifyOtp establishes the session,
// and AppContext's onAuthStateChange listener sends a confirmed signup to
// /dashboard (SIGNED_IN) and a recovery to /reset-password
// (PASSWORD_RECOVERY). The timer below is only a fallback.

type LinkType = 'magiclink' | 'recovery';
type LinkParams = { tokenHash: string; type: LinkType };

export const AuthConfirmPage: React.FC = () => {
  const router = useRouter();
  // undefined = not read yet (first render, so server and client markup
  // match); null = the URL has no usable token.
  const [params, setParams] = useState<LinkParams | null | undefined>(undefined);
  const [isWorking, setIsWorking] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isDone, setIsDone] = useState(false);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const tokenHash = q.get('token_hash');
    const type = q.get('type');
    if (tokenHash && (type === 'magiclink' || type === 'recovery')) {
      setParams({ tokenHash, type });
    } else {
      setParams(null);
    }
  }, []);

  useEffect(() => {
    if (!isDone || !params) return;
    const timer = setTimeout(() => {
      router.push(params.type === 'recovery' ? '/reset-password' : '/dashboard');
    }, 2500);
    return () => clearTimeout(timer);
  }, [isDone, params, router]);

  const handleConfirm = async () => {
    if (!params) return;
    const supabase = getSupabase();
    if (!supabase) {
      setErrorMessage('Sign-in is not available right now. Please try again in a moment.');
      return;
    }
    setErrorMessage(null);
    setIsWorking(true);
    try {
      const { error } = await supabase.auth.verifyOtp({ token_hash: params.tokenHash, type: params.type });
      if (error) {
        setErrorMessage('This link has expired or was already used.');
      } else {
        setIsDone(true);
      }
    } finally {
      setIsWorking(false);
    }
  };

  const isRecovery = params?.type === 'recovery';
  const title = isRecovery ? 'Reset your password' : 'Confirm your email';
  const lead = isRecovery
    ? 'Press the button to continue and choose a new password.'
    : 'Press the button to finish creating your Quancis account.';

  return (
    <div className="min-h-[calc(100vh-8rem)] flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-md space-y-6">
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center h-12 w-12 rounded-2xl bg-ink text-white shadow-md mb-2">
            {isRecovery ? <Lock className="h-5 w-5" /> : <CheckCircle2 className="h-5 w-5" />}
          </div>
          <h1 className="text-2xl font-medium text-ink tracking-tight">{params === null ? 'Link not valid' : title}</h1>
          {params !== null && <p className="text-xs text-ink-3 max-w-xs mx-auto">{lead}</p>}
        </div>

        {errorMessage && (
          <div className="rounded-2xl border border-danger-border bg-danger-soft/90 p-4 text-xs text-danger flex items-start gap-3 shadow-none">
            <AlertCircle className="h-4 w-4 shrink-0 text-danger mt-0.5" />
            <div className="space-y-1">
              <p className="text-[11px] leading-relaxed text-danger">{errorMessage}</p>
              <p className="text-[11px] leading-relaxed text-danger">
                {isRecovery
                  ? 'Go to sign in and choose "Forgot password" to get a new link.'
                  : 'Go to sign in and use "Resend confirmation email" to get a new link.'}
              </p>
            </div>
          </div>
        )}

        <div className="rounded-3xl border border-line bg-white p-6 sm:p-8 shadow-none space-y-6">
          {params === undefined ? (
            <p className="text-xs text-ink-3 text-center">Loading...</p>
          ) : params === null ? (
            <div className="flex flex-col items-center text-center gap-3 py-2">
              <p className="text-xs text-ink-3">This link is incomplete or has been altered. Please use the link from your most recent email, or request a new one.</p>
              <button
                type="button"
                onClick={() => router.push('/login')}
                className="mt-2 w-full rounded-2xl bg-ink px-4 py-3 text-xs sm:text-sm font-bold text-white shadow-md hover:bg-ink active:scale-[0.99] transition-all cursor-pointer"
              >
                Go to sign in
              </button>
            </div>
          ) : isDone ? (
            <div className="flex flex-col items-center text-center gap-3 py-4">
              <CheckCircle2 className="h-8 w-8 text-accent-blue" />
              <p className="text-sm font-bold text-ink">{isRecovery ? 'Verified' : 'Email confirmed'}</p>
              <p className="text-xs text-ink-3">{isRecovery ? 'Taking you to choose a new password...' : 'Taking you to your dashboard...'}</p>
            </div>
          ) : errorMessage ? (
            <button
              type="button"
              onClick={() => router.push('/login')}
              className="w-full rounded-2xl bg-ink px-4 py-3.5 text-xs sm:text-sm font-bold text-white shadow-md hover:bg-ink active:scale-[0.99] transition-all cursor-pointer"
            >
              Go to sign in
            </button>
          ) : (
            <button
              type="button"
              onClick={handleConfirm}
              disabled={isWorking}
              className="w-full rounded-2xl bg-ink px-4 py-3.5 text-xs sm:text-sm font-bold text-white shadow-md hover:bg-ink active:scale-[0.99] transition-all cursor-pointer disabled:opacity-60"
            >
              {isWorking ? 'Working...' : isRecovery ? 'Continue' : 'Confirm email'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
