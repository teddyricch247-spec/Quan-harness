'use client';

import React, { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useApp } from '../../context/AppContext';
import { ROUTES } from '../../lib/routes';
import { BrandMark } from '../BrandMark';
import {
  AlertCircle,
  CheckCircle2,
  ArrowRight,
  KeyRound,
  Mail,
} from 'lucide-react';

type Mode = 'signin' | 'signup' | 'forgot';

type EmailFieldError = { text: string; blocking: boolean };

type FieldErrors = {
  name?: string | null;
  email?: EmailFieldError | null;
  password?: string | null;
};

// Very common providers only — used purely to catch likely typos (e.g.
// "gmial.com"), never to assert that a domain is invalid. Keeping this
// list short keeps false positives rare for people on smaller/company
// domains, which this list intentionally doesn't try to cover.
const COMMON_EMAIL_DOMAINS = [
  'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'icloud.com',
  'aol.com', 'protonmail.com', 'live.com', 'msn.com', 'me.com',
];

function levenshteinDistance(a: string, b: string): number {
  const dp: number[][] = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = 0; i <= a.length; i++) dp[i][0] = i;
  for (let j = 0; j <= b.length; j++) dp[0][j] = j;
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      dp[i][j] = a[i - 1] === b[j - 1]
        ? dp[i - 1][j - 1]
        : 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
    }
  }
  return dp[a.length][b.length];
}

// Validates shape (not deliverability — that still only gets confirmed
// by the confirmation-link email itself), rejects the "+" alias pattern
// this app doesn't support, and softly flags likely typos of very
// common providers without blocking submission over a guess.
function validateEmailAddress(raw: string): EmailFieldError | null {
  const value = raw.trim();
  if (!value) return { text: 'Email is required.', blocking: true };

  if ((value.match(/@/g) || []).length !== 1) {
    return { text: "That doesn't look like a valid email address.", blocking: true };
  }
  const [localPart, domain] = value.split('@');
  const shapeOk = /^[A-Za-z0-9._%+-]+$/.test(localPart)
    && /^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$/.test(domain);
  if (!localPart || !domain || !shapeOk || /\.\./.test(value)) {
    return { text: "That doesn't look like a valid email address.", blocking: true };
  }
  if (localPart.includes('+')) {
    return {
      text: 'Email aliases (e.g. name+tag@domain.com) aren\u2019t accepted \u2014 please use your primary email address.',
      blocking: true,
    };
  }

  const lowerDomain = domain.toLowerCase();
  if (!COMMON_EMAIL_DOMAINS.includes(lowerDomain)) {
    let closest: string | null = null;
    let closestDistance = Infinity;
    for (const known of COMMON_EMAIL_DOMAINS) {
      const distance = levenshteinDistance(lowerDomain, known);
      if (distance < closestDistance) {
        closestDistance = distance;
        closest = known;
      }
    }
    if (closest && closestDistance === 1) {
      return { text: `Did you mean ${localPart}@${closest}? Double-check the domain before continuing.`, blocking: false };
    }
  }

  return null;
}

// Mirrors backend auth_email._validate_name (the backend is the real gate):
// required, at most 80 characters, and no < or > (markup characters).
const NAME_MAX_LENGTH = 80;

function validateNameField(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return 'Please enter your name.';
  if (trimmed.length > NAME_MAX_LENGTH) return `Name must be ${NAME_MAX_LENGTH} characters or fewer.`;
  if (/[<>]/.test(trimmed)) return "Name can't contain < or > characters.";
  return null;
}

function validatePasswordField(value: string, mode: Mode): string | null {
  if (!value) return 'Please enter your password.';
  if (mode === 'signup' && value.length < 8) return 'Password must be at least 8 characters.';
  return null;
}

export const LoginPage: React.FC = () => {
  const { signInWithGitHub, signInWithGoogle, signInWithEmail, signUpWithEmail, requestPasswordReset, resendConfirmationEmail, isSupabaseReady, isLoggedIn } = useApp();
  const router = useRouter();

  // Mirrors the old "logged-in users never see /login" behavior: the
  // auth listener in AppContext already pushes to /dashboard on sign-in,
  // but this covers the case where an already-authenticated user
  // navigates to /login directly (e.g. a stale bookmark or back button).
  useEffect(() => {
    if (isLoggedIn) {
      router.replace('/dashboard');
    }
  }, [isLoggedIn, router]);

  const [mode, setMode] = useState<Mode>('signin');

  // Landing CTAs ("Create An Account") link to /login?mode=signup. Read
  // it after mount (not in the useState initializer) so server and
  // client render the same markup and hydration doesn't mismatch.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get('mode') === 'signup') {
      setMode('signup');
    }
  }, []);
  const [isGitHubLoading, setIsGitHubLoading] = useState(false);
  const [isGoogleLoading, setIsGoogleLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  // "Resend confirmation email": offered after signing up and when a sign-in
  // fails because the email isn't confirmed yet.
  const [isResending, setIsResending] = useState(false);
  const [resendNote, setResendNote] = useState<string | null>(null);

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});

  // Drives a brief, very visible flag on the terms checkbox (focus +
  // scroll-into-view + a temporary highlight ring) any time someone
  // tries to submit, or clicks Google/GitHub, without having checked
  // it — see flagTermsRequired below.
  const [termsPulse, setTermsPulse] = useState(false);
  const termsCheckboxRef = useRef<HTMLInputElement | null>(null);
  const termsPulseTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (termsPulseTimeout.current) clearTimeout(termsPulseTimeout.current);
    };
  }, []);

  const resetMessages = () => {
    setErrorMessage(null);
    setInfoMessage(null);
    setResendNote(null);
  };

  const handleResendConfirmation = async () => {
    setResendNote(null);
    const emailIssue = validateEmailAddress(email);
    if (emailIssue && emailIssue.blocking) {
      setResendNote('Enter your email address above first.');
      return;
    }
    setIsResending(true);
    try {
      const { error, message } = await resendConfirmationEmail(email);
      setResendNote(error || message || "If that email is waiting to be confirmed, we've sent a new confirmation link.");
    } finally {
      setIsResending(false);
    }
  };

  const switchMode = (next: Mode) => {
    setMode(next);
    resetMessages();
    setFieldErrors({});
  };

  const flagTermsRequired = () => {
    setTermsPulse(true);
    termsCheckboxRef.current?.focus();
    termsCheckboxRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    if (termsPulseTimeout.current) clearTimeout(termsPulseTimeout.current);
    termsPulseTimeout.current = setTimeout(() => setTermsPulse(false), 1600);
  };

  const handleGitHubAuth = async () => {
    if (!termsAccepted) {
      flagTermsRequired();
      return;
    }
    setIsGitHubLoading(true);
    resetMessages();
    try {
      const { error } = await signInWithGitHub(termsAccepted);
      if (error) setErrorMessage(error);
    } catch (err: any) {
      setErrorMessage(err?.message || 'Failed to initialize GitHub authentication.');
    } finally {
      setIsGitHubLoading(false);
    }
  };

  const handleGoogleAuth = async () => {
    if (!termsAccepted) {
      flagTermsRequired();
      return;
    }
    setIsGoogleLoading(true);
    resetMessages();
    try {
      const { error } = await signInWithGoogle(termsAccepted);
      if (error) setErrorMessage(error);
    } catch (err: any) {
      setErrorMessage(err?.message || 'Failed to initialize Google authentication.');
    } finally {
      setIsGoogleLoading(false);
    }
  };

  const handleEmailSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    resetMessages();

    // Validate every visible field up front — rather than stopping at
    // the first problem — so the person sees everything that needs
    // fixing in one pass instead of one error at a time per submit.
    const nextFieldErrors: FieldErrors = {};
    if (mode === 'signup') {
      nextFieldErrors.name = validateNameField(name);
    }
    nextFieldErrors.email = validateEmailAddress(email);
    if (mode !== 'forgot') {
      nextFieldErrors.password = validatePasswordField(password, mode);
    }
    setFieldErrors(nextFieldErrors);

    const hasBlockingFieldError =
      !!nextFieldErrors.name ||
      !!nextFieldErrors.password ||
      !!(nextFieldErrors.email && nextFieldErrors.email.blocking);

    if (hasBlockingFieldError) {
      return;
    }

    if (mode === 'signup' && !termsAccepted) {
      flagTermsRequired();
      return;
    }

    setIsSubmitting(true);
    try {
      if (mode === 'signin') {
        const { error } = await signInWithEmail(email, password);
        if (error) setErrorMessage(error);
        // On success, onAuthStateChange picks up the new session and
        // routes to the dashboard — nothing more to do here.
      } else if (mode === 'signup') {
        const { error, message } = await signUpWithEmail(email, password, name, termsAccepted);
        if (error) setErrorMessage(error);
        else setInfoMessage(message || "Check your inbox for a confirmation link to finish creating your account.");
      } else if (mode === 'forgot') {
        const { error, message } = await requestPasswordReset(email);
        if (error) setErrorMessage(error);
        else setInfoMessage(message || 'If an account exists for that email, a reset link is on its way.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const submitLabel =
    mode === 'signin' ? (isSubmitting ? 'Signing in...' : 'Sign in')
    : mode === 'signup' ? (isSubmitting ? 'Creating account...' : 'Create account')
    : (isSubmitting ? 'Sending link...' : 'Send reset link');

  return (
    <div className="min-h-[calc(100vh-8rem)] flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-md space-y-6">

        {/* Header */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center mb-2">
            <BrandMark size={48} animated />
          </div>
          <h1 className="text-2xl font-medium text-ink tracking-tight">
            {mode === 'signin' && 'Sign in to Quancis'}
            {mode === 'signup' && 'Create your Quancis account'}
            {mode === 'forgot' && 'Reset your password'}
          </h1>
          <p className="text-xs text-ink-3 max-w-xs mx-auto">
            Composite Intelligence System. Ship more accurate code, cheaper.
          </p>
        </div>

        {/* Error Alert */}
        {errorMessage && (
          <div className="rounded-2xl border border-danger-border bg-danger-soft/90 p-4 text-xs text-danger flex items-start gap-3 shadow-none">
            <AlertCircle className="h-4 w-4 shrink-0 text-danger mt-0.5" />
            <div className="space-y-1">
              <span className="font-bold">Authentication Required:</span>
              <p className="text-[11px] leading-relaxed text-danger">{errorMessage}</p>
              {mode === 'signin' && /not confirmed/i.test(errorMessage) && (
                <div className="pt-1">
                  <button
                    type="button"
                    onClick={handleResendConfirmation}
                    disabled={isResending}
                    className="text-[11px] font-medium underline underline-offset-2 disabled:opacity-60"
                  >
                    {isResending ? 'Sending...' : 'Resend confirmation email'}
                  </button>
                  {resendNote && <p className="mt-1 text-[11px] leading-relaxed text-danger">{resendNote}</p>}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Info alert (signup / forgot password confirmations) */}
        {infoMessage && (
          <div className="rounded-2xl border border-accent-blue-border bg-accent-blue-soft/90 p-4 text-xs text-accent-blue flex items-start gap-3 shadow-none">
            <CheckCircle2 className="h-4 w-4 shrink-0 text-accent-blue mt-0.5" />
            <div className="space-y-1">
              <p className="text-[11px] leading-relaxed text-accent-blue-hover">{infoMessage}</p>
              {mode === 'signup' && (
                <div className="pt-1">
                  <button
                    type="button"
                    onClick={handleResendConfirmation}
                    disabled={isResending}
                    className="text-[11px] font-medium text-accent-blue-hover underline underline-offset-2 disabled:opacity-60"
                  >
                    {isResending ? 'Sending...' : "Didn't get it? Resend confirmation email"}
                  </button>
                  {resendNote && <p className="mt-1 text-[11px] leading-relaxed text-accent-blue-hover">{resendNote}</p>}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Supabase Status Notice if credentials are not detected */}
        {!isSupabaseReady && !errorMessage && (
          <div className="rounded-2xl border border-warning-border bg-warning-soft/80 p-4 text-xs text-warning flex items-start gap-3 shadow-none">
            <KeyRound className="h-4 w-4 shrink-0 text-warning mt-0.5" />
            <div className="space-y-1">
              <div className="font-bold">Supabase Credentials Needed</div>
              <p className="text-[11px] leading-relaxed text-warning">
                To sign in, provide your <code className="font-mono bg-warning-soft px-1 py-0.5 rounded text-warning">NEXT_PUBLIC_SUPABASE_URL</code> and <code className="font-mono bg-warning-soft px-1 py-0.5 rounded text-warning">NEXT_PUBLIC_SUPABASE_ANON_KEY</code> in Settings.
              </p>
            </div>
          </div>
        )}

        <div className="rounded-3xl border border-line bg-white p-6 sm:p-8 shadow-none space-y-6">

          {/* Email + password form */}
          <form onSubmit={handleEmailSubmit} className="space-y-3.5">
            {mode === 'signup' && (
              <div className="space-y-1.5">
                <label htmlFor="name" className="text-xs font-bold text-ink-2">Name</label>
                <input
                  id="name"
                  type="text"
                  autoComplete="name"
                  value={name}
                  onChange={(e) => {
                    setName(e.target.value);
                    if (fieldErrors.name) {
                      setFieldErrors((prev) => ({ ...prev, name: validateNameField(e.target.value) }));
                    }
                  }}
                  onBlur={() => setFieldErrors((prev) => ({ ...prev, name: validateNameField(name) }))}
                  className={`w-full rounded-xl border px-3.5 py-2.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ink/10 ${
                    fieldErrors.name ? 'border-danger-border focus:border-danger' : 'border-line focus:border-ink-3'
                  }`}
                  placeholder="Ada Lovelace"
                  aria-invalid={!!fieldErrors.name}
                  aria-describedby={fieldErrors.name ? 'name-error' : undefined}
                  required
                />
                {fieldErrors.name && (
                  <p id="name-error" className="text-[11px] font-semibold text-danger">{fieldErrors.name}</p>
                )}
              </div>
            )}

            <div className="space-y-1.5">
              <label htmlFor="email" className="text-xs font-bold text-ink-2">Email</label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (fieldErrors.email) {
                    setFieldErrors((prev) => ({ ...prev, email: validateEmailAddress(e.target.value) }));
                  }
                }}
                onBlur={() => setFieldErrors((prev) => ({ ...prev, email: validateEmailAddress(email) }))}
                className={`w-full rounded-xl border px-3.5 py-2.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ink/10 ${
                  fieldErrors.email
                    ? fieldErrors.email.blocking
                      ? 'border-danger-border focus:border-danger'
                      : 'border-warning-border focus:border-warning'
                    : 'border-line focus:border-ink-3'
                }`}
                placeholder="you@example.com"
                aria-invalid={!!fieldErrors.email?.blocking}
                aria-describedby={fieldErrors.email ? 'email-error' : undefined}
                required
              />
              {fieldErrors.email && (
                <p
                  id="email-error"
                  className={`text-[11px] font-semibold ${fieldErrors.email.blocking ? 'text-danger' : 'text-warning'}`}
                >
                  {fieldErrors.email.text}
                </p>
              )}
            </div>

            {mode !== 'forgot' && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label htmlFor="password" className="text-xs font-bold text-ink-2">Password</label>
                  {mode === 'signin' && (
                    <button
                      type="button"
                      onClick={() => switchMode('forgot')}
                      className="text-[11px] font-semibold text-ink-3 hover:text-ink cursor-pointer"
                    >
                      Forgot password?
                    </button>
                  )}
                </div>
                <input
                  id="password"
                  type="password"
                  autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    if (fieldErrors.password) {
                      setFieldErrors((prev) => ({ ...prev, password: validatePasswordField(e.target.value, mode) }));
                    }
                  }}
                  onBlur={() => setFieldErrors((prev) => ({ ...prev, password: validatePasswordField(password, mode) }))}
                  className={`w-full rounded-xl border px-3.5 py-2.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ink/10 ${
                    fieldErrors.password ? 'border-danger-border focus:border-danger' : 'border-line focus:border-ink-3'
                  }`}
                  placeholder={mode === 'signup' ? 'At least 8 characters' : '••••••••'}
                  aria-invalid={!!fieldErrors.password}
                  aria-describedby={fieldErrors.password ? 'password-error' : undefined}
                  required
                  minLength={mode === 'signup' ? 8 : undefined}
                />
                {fieldErrors.password && (
                  <p id="password-error" className="text-[11px] font-semibold text-danger">{fieldErrors.password}</p>
                )}
              </div>
            )}

            {/* Terms/Privacy consent — sits directly above the submit
                button it gates (in signup mode) so the reason a grayed
                button won't respond is visible without having to
                scroll past it. It also gates the Google/GitHub buttons
                further down the page (see the note by those buttons for
                why: OAuth sign-in silently creates a brand-new account
                on first use, so this is the only point that can require
                consent before ANY account gets created through this
                page). Not shown for password reset, which never creates
                an account. */}
            {mode !== 'forgot' && (
              <div className={`space-y-2 rounded-2xl transition-shadow ${termsPulse ? 'ring-2 ring-danger' : ''}`}>
                <label htmlFor="terms-accept" className="flex items-start gap-2.5 cursor-pointer select-none">
                  <input
                    id="terms-accept"
                    ref={termsCheckboxRef}
                    type="checkbox"
                    checked={termsAccepted}
                    onChange={(e) => setTermsAccepted(e.target.checked)}
                    className={`mt-0.5 h-3.5 w-3.5 shrink-0 rounded border-line text-ink focus:ring-2 focus:ring-ink/10 cursor-pointer ${termsPulse ? 'ring-2 ring-danger' : ''}`}
                    aria-describedby={!termsAccepted ? 'terms-hint' : undefined}
                  />
                  <span className="text-[11px] leading-relaxed text-ink-3">
                    I agree to the{' '}
                    <Link href={ROUTES.terms} target="_blank" className="font-semibold text-ink-2 hover:underline">
                      Terms of Service
                    </Link>{' '}
                    and{' '}
                    <Link href={ROUTES.privacy} target="_blank" className="font-semibold text-ink-2 hover:underline">
                      Privacy Policy
                    </Link>
                    .
                  </span>
                </label>

                {!termsAccepted && (
                  <p
                    id="terms-hint"
                    aria-live="polite"
                    className="flex items-start gap-2 rounded-2xl border border-warning-border bg-warning-soft px-3 py-2 text-[11px] leading-relaxed text-warning"
                  >
                    <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-warning" />
                    <span>
                      {mode === 'signup'
                        ? 'Check this box to enable account creation and sign-in with Google or GitHub below.'
                        : 'Check this box to enable sign-in with Google or GitHub below.'}
                    </span>
                  </p>
                )}
              </div>
            )}

            <button
              type="submit"
              disabled={isSubmitting}
              aria-disabled={mode === 'signup' && !termsAccepted}
              className={`w-full flex items-center justify-center gap-2 rounded-2xl bg-ink px-4 py-3.5 text-xs sm:text-sm font-bold text-white shadow-md active:scale-[0.99] transition-all cursor-pointer disabled:opacity-60 ${
                mode === 'signup' && !termsAccepted ? 'opacity-60' : 'hover:bg-ink'
              }`}
            >
              <Mail className="h-4 w-4 shrink-0" />
              <span>{submitLabel}</span>
            </button>
          </form>

          {/* Mode switch links */}
          <div className="text-center text-[11px] text-ink-3">
            {mode === 'signin' && (
              <span>
                New here?{' '}
                <button type="button" onClick={() => switchMode('signup')} className="font-bold text-ink hover:underline cursor-pointer">
                  Create an account
                </button>
              </span>
            )}
            {mode === 'signup' && (
              <span>
                Already have an account?{' '}
                <button type="button" onClick={() => switchMode('signin')} className="font-bold text-ink hover:underline cursor-pointer">
                  Sign in
                </button>
              </span>
            )}
            {mode === 'forgot' && (
              <button type="button" onClick={() => switchMode('signin')} className="font-bold text-ink hover:underline cursor-pointer">
                Back to sign in
              </button>
            )}
          </div>

          <div className="flex items-center gap-3">
            <div className="h-px flex-1 bg-line-soft" />
            <span className="text-[10px] uppercase tracking-wider text-ink-3 font-bold">or</span>
            <div className="h-px flex-1 bg-line-soft" />
          </div>

          {/* Google/GitHub — wrapped in their own space-y-3.5 group
              (matching the Password → Submit spacing inside the form
              above) instead of inheriting the parent's larger space-y-6,
              which used to leave an oversized gap between these two
              buttons. Kept clickable even when terms aren't accepted
              yet (rather than a native `disabled`) so a click always
              does something useful — it flags the checkbox above
              instead of just silently doing nothing. */}
          {mode !== 'forgot' && (
            <div className="space-y-3.5">
              {/* Google Auth */}
              <button
                id="google-auth-btn"
                type="button"
                onClick={handleGoogleAuth}
                disabled={isGoogleLoading}
                aria-disabled={!termsAccepted}
                title={!termsAccepted ? 'Check the Terms & Privacy Policy box above to continue' : undefined}
                className={`w-full flex items-center justify-center gap-3 rounded-2xl border border-line bg-white px-4 py-3.5 text-xs sm:text-sm font-bold text-ink shadow-none active:scale-[0.99] transition-all cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed disabled:hover:bg-white ${
                  !termsAccepted ? 'opacity-60' : 'hover:bg-surface'
                }`}
              >
                <svg className="h-4 w-4 shrink-0" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                  <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
                  <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.9-2.26 5.36-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
                  <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
                  <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
                </svg>
                <span>{isGoogleLoading ? 'Redirecting to Google...' : 'Continue with Google'}</span>
                <ArrowRight className="h-4 w-4 shrink-0 opacity-70" />
              </button>

              {/* GitHub Auth */}
              <button
                id="github-auth-btn"
                type="button"
                onClick={handleGitHubAuth}
                disabled={isGitHubLoading}
                aria-disabled={!termsAccepted}
                title={!termsAccepted ? 'Check the Terms & Privacy Policy box above to continue' : undefined}
                className={`w-full flex items-center justify-center gap-3 rounded-2xl border border-line bg-white px-4 py-3.5 text-xs sm:text-sm font-bold text-ink shadow-none active:scale-[0.99] transition-all cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed disabled:hover:bg-white ${
                  !termsAccepted ? 'opacity-60' : 'hover:bg-surface'
                }`}
              >
                <svg className="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                  <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
                </svg>
                <span>{isGitHubLoading ? 'Redirecting to GitHub...' : 'Continue with GitHub'}</span>
                <ArrowRight className="h-4 w-4 shrink-0 opacity-70" />
              </button>
            </div>
          )}

        </div>
      </div>
    </div>
  );
};
