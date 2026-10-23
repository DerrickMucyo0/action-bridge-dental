import { useEffect, useRef, useState, type FormEvent } from 'react';
import { CognitoError } from '../../services/cognito';
import { useAuth } from '../../state/auth';
import { passwordValidationMessage } from './password-policy';
import { PasswordRequirements } from './password-requirements';

export type PublicMode = 'create' | 'verify' | 'forgot' | 'reset';
type Field = 'email' | 'password' | 'confirmation' | 'code';
const actions = {
  create: 'Create account',
  verify: 'Verify email',
  forgot: 'Send reset code',
  reset: 'Reset password',
};

export function PublicAccountForm({
  mode,
  email,
  onEmailChange,
  onMode,
  resendAt,
  onCooldown,
  configured,
}: {
  mode: PublicMode;
  email: string;
  onEmailChange: (email: string) => void;
  onMode: (mode: PublicMode | 'signin', notice?: string) => void;
  resendAt: number;
  onCooldown: () => void;
  configured: boolean;
}) {
  const auth = useAuth();
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; field?: Field } | null>(
    null,
  );
  const [notice, setNotice] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now);
  const live = useRef(true);
  const pending = useRef(false);
  const remaining = Math.max(0, Math.ceil((resendAt - now) / 1000));

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  useEffect(() => {
    if (!resendAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [resendAt]);
  useEffect(() => {
    if (error?.field) document.getElementById('public-' + error.field)?.focus();
  }, [error]);

  function validateEmail() {
    if (
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()) ||
      email.trim().length > 254
    ) {
      setError({ message: 'Enter a valid email address.', field: 'email' });
      return false;
    }
    return true;
  }
  function startCooldown() {
    setNow(Date.now());
    onCooldown();
  }
  async function run(action: () => Promise<void>) {
    if (pending.current || !configured || auth.status === 'restoring') return;
    pending.current = true;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (caught) {
      if (!live.current) return;
      const reason = caught instanceof CognitoError ? caught.code : '';
      const message =
        caught instanceof CognitoError
          ? caught.message
          : 'Unable to complete this request. Try again.';
      if (
        [
          'TooManyRequestsException',
          'TooManyFailedAttemptsException',
          'LimitExceededException',
        ].includes(reason)
      )
        startCooldown();
      if (
        mode === 'create' &&
        ['LimitExceededException', 'CodeDeliveryFailureException'].includes(
          reason,
        )
      ) {
        onMode('verify', message);
      } else {
        const field: Field | undefined = [
          'CodeMismatchException',
          'ExpiredCodeException',
        ].includes(reason)
          ? 'code'
          : reason === 'InvalidPasswordException'
            ? 'password'
            : undefined;
        setError({ message, ...(field ? { field } : {}) });
      }
    } finally {
      pending.current = false;
      if (live.current) setBusy(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending.current || !validateEmail()) return;
    if (mode === 'create' || mode === 'reset') {
      const message = passwordValidationMessage(password);
      if (message) {
        setError({ message, field: 'password' });
        return;
      }
    }
    if ((mode === 'create' || mode === 'reset') && password !== confirmation) {
      setError({ message: 'Passwords must match.', field: 'confirmation' });
      return;
    }
    if (
      (mode === 'verify' || mode === 'reset') &&
      !/^\S{1,2048}$/.test(code.trim())
    ) {
      setError({ message: 'Enter the code from your email.', field: 'code' });
      return;
    }
    if (mode === 'forgot' && remaining) return;
    const address = email.trim().toLowerCase();
    await run(async () => {
      if (mode === 'create') {
        await auth.signUp(address, password);
        if (!live.current) return;
        startCooldown();
        onMode(
          'verify',
          'Check your email for a verification code. Your account is not signed in yet.',
        );
      } else if (mode === 'verify') {
        await auth.confirmSignUp(address, code.trim());
        if (live.current)
          onMode('signin', 'Email verified. Sign in to continue.');
      } else if (mode === 'forgot') {
        await auth.forgotPassword(address);
        if (!live.current) return;
        startCooldown();
        onMode(
          'reset',
          'If this account can reset its password, a code has been sent to its verified email.',
        );
      } else {
        await auth.confirmForgotPassword(address, code.trim(), password);
        if (live.current)
          onMode('signin', 'Password reset. Sign in with your new password.');
      }
    });
  }
  async function resend() {
    if (pending.current || remaining || !validateEmail()) return;
    startCooldown();
    await run(async () => {
      if (mode === 'verify')
        await auth.resendConfirmationCode(email.trim().toLowerCase());
      else await auth.forgotPassword(email.trim().toLowerCase());
      if (live.current)
        setNotice(
          mode === 'verify'
            ? 'A new verification code has been requested. Check your email.'
            : 'If this account can reset its password, a new code has been sent to its verified email.',
        );
    });
  }

  const disabled = busy || auth.status === 'restoring';
  function field(
    name: Field,
    label: string,
    type: string,
    autocomplete: string,
  ) {
    const value = { email, password, confirmation, code }[name];
    const setters = {
      email: onEmailChange,
      password: setPassword,
      confirmation: setConfirmation,
      code: setCode,
    };
    const hint = name === 'password';
    return (
      <div className="si-field" key={name}>
        <label htmlFor={'public-' + name}>{label}</label>
        <input
          id={'public-' + name}
          className="si-input"
          type={type}
          autoComplete={autocomplete}
          required
          spellCheck={false}
          autoCapitalize="none"
          inputMode={
            name === 'email' ? 'email' : name === 'code' ? 'numeric' : undefined
          }
          minLength={hint ? 12 : undefined}
          maxLength={name === 'email' ? 254 : name === 'code' ? 2048 : 256}
          value={value}
          disabled={disabled}
          onChange={(event) => {
            setters[name](event.target.value);
            if (name === 'email') setCode('');
            setError(null);
          }}
          aria-invalid={error?.field === name}
          aria-describedby={
            [
              hint ? 'public-password-hint' : '',
              error?.field === name ? 'public-error' : '',
            ]
              .filter(Boolean)
              .join(' ') || undefined
          }
        />
        {hint && (
          <PasswordRequirements id="public-password-hint" value={password} />
        )}
      </div>
    );
  }
  return (
    <>
      {mode === 'verify' && (
        <p className="si-message">
          Enter the code sent to your email. You can return here if you already
          requested a code.
        </p>
      )}
      {mode === 'reset' && (
        <p className="si-message">
          Enter the password reset code from your email and choose a new
          password.
        </p>
      )}
      {error && (
        <p id="public-error" className="si-notice si-alert" role="alert">
          {error.message}
        </p>
      )}
      {notice && !error && (
        <p className="si-notice" role="status">
          {notice}
        </p>
      )}
      <form className="si-form" noValidate onSubmit={submit} aria-busy={busy}>
        {field('email', 'Email', 'email', 'username')}
        {(mode === 'create' || mode === 'reset') &&
          field(
            'password',
            mode === 'reset' ? 'New password' : 'Password',
            'password',
            'new-password',
          )}
        {(mode === 'create' || mode === 'reset') &&
          field('confirmation', 'Confirm password', 'password', 'new-password')}
        {(mode === 'verify' || mode === 'reset') &&
          field(
            'code',
            mode === 'verify' ? 'Verification code' : 'Reset code',
            'text',
            'one-time-code',
          )}
        <button
          className="si-submit"
          type="submit"
          disabled={
            disabled || !configured || (mode === 'forgot' && remaining > 0)
          }
        >
          {busy ? 'Please wait…' : actions[mode]}
        </button>
      </form>
      {(mode === 'verify' || mode === 'reset') && (
        <div className="si-switch">
          <button
            className="si-link"
            type="button"
            disabled={disabled || !configured || remaining > 0}
            onClick={() => void resend()}
          >
            {mode === 'verify'
              ? 'Resend verification code'
              : 'Resend reset code'}
          </button>
          {remaining > 0 && (
            <span className="si-hint">Try again in {remaining} seconds.</span>
          )}
        </div>
      )}
      <p className="si-hint">
        This demo is for fictional data only. Do not upload real patient
        information.
      </p>
    </>
  );
}
