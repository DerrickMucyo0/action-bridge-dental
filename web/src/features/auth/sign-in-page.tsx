import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useSearchParams } from 'react-router-dom';
import { WelcomeVisual } from '../../components/welcome-visual';
import { appConfig as config } from '../../config';
import { CognitoError } from '../../services/cognito';
import { useAuth } from '../../state/auth';
import { PublicAccountForm, type PublicMode } from './public-account-form';
import { passwordValidationMessage } from './password-policy';
import { PasswordRequirements } from './password-requirements';
import '../../landing.css';

type Mode = 'signin' | PublicMode;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function errorMessage(caught: unknown): string {
  return caught instanceof CognitoError
    ? caught.message
    : 'Sign-in failed. Try again.';
}

/**
 * Sign in and self-service accounts use the existing public Cognito client.
 * Admin-created demo accounts keep the first-sign-in password challenge.
 */
export function SignInPage() {
  const auth = useAuth();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const requested = params.get('mode');
  const mode: Mode =
    requested === 'create' ||
    requested === 'forgot' ||
    requested === 'verify' ||
    requested === 'reset'
      ? requested
      : 'signin';
  const [notice, setNotice] = useState<string | null>(null);
  const [unconfirmed, setUnconfirmed] = useState(false);
  const [resendAt, setResendAt] = useState(0);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  /** True while Cognito asks this first-time user to choose a new password. */
  const [session, setSession] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{
    message: string;
    field?: 'email' | 'password' | 'confirmation';
  } | null>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const newPasswordRef = useRef<HTMLInputElement>(null);
  const requestPending = useRef(false);

  useEffect(() => {
    document.title =
      (mode === 'signin'
        ? 'Sign in'
        : mode === 'create'
          ? 'Create account'
          : mode === 'verify'
            ? 'Verify email'
            : 'Reset password') + ' · ActionBridge Dental';
    document.getElementById('si-title')?.focus();
  }, [mode]);

  if (auth.status === 'signed_in') {
    const from = (location.state as { from?: string } | null)?.from;
    return (
      <Navigate
        to={from?.startsWith('/') && !from.startsWith('//') ? from : '/'}
        replace
      />
    );
  }

  const go = (next: Mode, message?: string) => {
    if (requestPending.current) return;
    setError(null);
    setNotice(message ?? null);
    setUnconfirmed(false);
    setSession(false);
    setNewPassword('');
    setConfirmation('');
    setPassword('');
    setParams(next === 'signin' ? {} : { mode: next }, { replace: true });
  };

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || requestPending.current || auth.status === 'restoring') return;
    if (session) {
      const message = passwordValidationMessage(newPassword);
      if (message) {
        setError({ message, field: 'password' });
        newPasswordRef.current?.focus();
        return;
      }
      if (confirmation !== newPassword) {
        setError({ message: 'Passwords must match.', field: 'confirmation' });
        return;
      }
    } else if (!EMAIL.test(email.trim())) {
      setError({ message: 'Enter a valid email address.', field: 'email' });
      return;
    } else if (!password) {
      setError({ message: 'Enter your password.', field: 'password' });
      passwordRef.current?.focus();
      return;
    }
    requestPending.current = true;
    setBusy(true);
    setError(null);
    try {
      if (session) {
        await auth.completeNewPassword(newPassword);
      } else {
        const result = await auth.signIn(email, password);
        if (result.kind === 'new_password_required') {
          setSession(true);
          setPassword('');
        }
      }
    } catch (caught) {
      setError({ message: errorMessage(caught) });
      setUnconfirmed(
        caught instanceof CognitoError &&
          caught.code === 'UserNotConfirmedException',
      );
    } finally {
      requestPending.current = false;
      setBusy(false);
    }
  }

  const note =
    auth.ended === 'expired'
      ? 'Your session expired. Sign in again to continue.'
      : auth.ended === 'signed_out'
        ? 'You’re signed out.'
        : null;

  const copy = session
    ? {
        eyebrow: 'NEW PASSWORD',
        title: 'Choose a new password to finish signing in.',
      }
    : {
        signin: {
          eyebrow: 'WELCOME BACK',
          title: 'Sign in to continue your saved plans.',
        },
        create: {
          eyebrow: 'NEW ACCOUNT',
          title: 'Create your ActionBridge account.',
        },
        verify: {
          eyebrow: 'VERIFY EMAIL',
          title: 'Verify your email address.',
        },
        reset: { eyebrow: 'RESET PASSWORD', title: 'Choose a new password.' },
        forgot: {
          eyebrow: 'RESET PASSWORD',
          title: 'Reset your password.',
        },
      }[mode];

  return (
    <div className="si">
      <aside className="si-aside">
        <WelcomeVisual />
        <div className="si-aside-content">
          <Link
            to="/"
            className="si-brand"
            aria-label="ActionBridge Dental home"
          >
            <span className="lp-brand-name">ActionBridge</span>
            <span className="lp-brand-rule" />
            <span className="lp-brand-sub">Dental</span>
          </Link>
          <p className="si-tagline">
            A clearer way to understand your dental costs.
          </p>
        </div>
      </aside>

      <main className="si-main">
        <div className="si-back">
          <Link to="/">Back to site</Link>
        </div>
        <div className="si-form-wrap">
          <div className="si-panel">
            <div className="si-eyebrow">{copy.eyebrow}</div>
            <h1 className="si-title" id="si-title" tabIndex={-1}>
              {copy.title}
            </h1>

            {!config.ok && (
              <p className="si-notice si-alert" role="alert">
                This site isn’t set up yet: {config.problems.join(' ')} Add the
                VITE_* settings and rebuild.
              </p>
            )}
            {config.ok && (notice || note) && !error && !session && (
              <p className="si-notice" role="status">
                {notice || note}
              </p>
            )}
            {error && (
              <p id="si-error" className="si-notice si-alert" role="alert">
                {error.message}
              </p>
            )}

            {session ? (
              <form className="si-form" noValidate onSubmit={submit}>
                <div className="si-field">
                  <label htmlFor="si-new-password">New password</label>
                  <input
                    id="si-new-password"
                    ref={newPasswordRef}
                    className="si-input"
                    type="password"
                    autoComplete="new-password"
                    minLength={12}
                    maxLength={256}
                    value={newPassword}
                    onChange={(e) => {
                      setNewPassword(e.target.value);
                      setError(null);
                    }}
                    aria-invalid={error?.field === 'password'}
                    aria-describedby={
                      error?.field === 'password'
                        ? 'si-new-password-hint si-error'
                        : 'si-new-password-hint'
                    }
                    autoFocus
                  />
                  <PasswordRequirements
                    id="si-new-password-hint"
                    value={newPassword}
                  />
                </div>
                <div className="si-field">
                  <label htmlFor="si-confirm-password">Confirm password</label>
                  <input
                    id="si-confirm-password"
                    className="si-input"
                    type="password"
                    autoComplete="new-password"
                    value={confirmation}
                    onChange={(e) => {
                      setConfirmation(e.target.value);
                      setError(null);
                    }}
                    aria-invalid={error?.field === 'confirmation'}
                  />
                </div>
                <button className="si-submit" type="submit" disabled={busy}>
                  {busy ? 'Saving…' : 'Set password and continue'}
                </button>
              </form>
            ) : mode === 'signin' ? (
              <form className="si-form" noValidate onSubmit={submit}>
                <div className="si-field">
                  <label htmlFor="si-email">Email</label>
                  <input
                    id="si-email"
                    className="si-input"
                    type="email"
                    autoComplete="username"
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      setError(null);
                    }}
                    aria-invalid={
                      error?.field === 'email' || (!!error && !error.field)
                    }
                  />
                </div>
                <div className="si-field">
                  <div className="si-field-head">
                    <label htmlFor="si-password">Password</label>
                    <button
                      type="button"
                      className="si-link"
                      disabled={busy}
                      onClick={() => go('forgot')}
                    >
                      Forgot password?
                    </button>
                  </div>
                  <input
                    id="si-password"
                    ref={passwordRef}
                    className="si-input"
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => {
                      setPassword(e.target.value);
                      setError(null);
                    }}
                    aria-invalid={
                      error?.field === 'password' || (!!error && !error.field)
                    }
                  />
                </div>
                <button
                  className="si-submit"
                  type="submit"
                  disabled={busy || !config.ok || auth.status === 'restoring'}
                >
                  {busy ? 'Signing in…' : 'Sign in'}
                </button>
              </form>
            ) : (
              <PublicAccountForm
                key={mode}
                mode={mode}
                email={email}
                onEmailChange={setEmail}
                onMode={go}
                configured={config.ok}
                resendAt={resendAt}
                onCooldown={() => setResendAt(Date.now() + 60_000)}
              />
            )}

            {unconfirmed && mode === 'signin' && (
              <div className="si-switch">
                <button
                  type="button"
                  className="si-link"
                  disabled={busy}
                  onClick={() => go('verify')}
                >
                  Verify email
                </button>
              </div>
            )}
            {!session && (mode === 'signin' || mode === 'create') && (
              <div className="si-switch">
                <button
                  type="button"
                  className="si-link"
                  disabled={busy}
                  onClick={() => go('verify')}
                >
                  Already have a verification code?
                </button>
              </div>
            )}
            <div className="si-switch">
              {session ? (
                <>
                  <span>Not you?</span>
                  <button
                    type="button"
                    className="si-link"
                    disabled={busy}
                    onClick={() => {
                      setSession(false);
                      setNewPassword('');
                      setConfirmation('');
                      setError(null);
                    }}
                  >
                    Use a different account
                  </button>
                </>
              ) : mode === 'signin' ? (
                <>
                  <span>New to ActionBridge?</span>
                  <button
                    type="button"
                    className="si-link"
                    disabled={busy}
                    onClick={() => go('create')}
                  >
                    Create an account
                  </button>
                </>
              ) : (
                <>
                  <span>
                    {mode === 'create'
                      ? 'Already have an account?'
                      : 'Remembered it?'}
                  </span>
                  <button
                    type="button"
                    className="si-link"
                    disabled={busy}
                    onClick={() => go('signin')}
                  >
                    {mode === 'create' ? 'Sign in' : 'Back to sign in'}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
        <p className="si-foot">
          Estimates only. Your dentist and insurer determine final treatment and
          costs.
        </p>
      </main>
    </div>
  );
}
