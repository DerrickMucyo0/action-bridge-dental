import { useState } from 'react';
import ReactDOM from 'react-dom/client';
import { AuthProvider, useAuth } from '../src/state/auth';

/** Offline browser harness only; absent from the production router/build entry. */
function Harness() {
  const auth = useAuth();
  const [result, setResult] = useState('idle');
  const actions: [string, () => Promise<unknown>][] = [
    [
      'SignUp',
      () => auth.signUp('fictional@example.com', 'Fictional-Password-42'),
    ],
    [
      'ConfirmSignUp',
      () => auth.confirmSignUp('fictional@example.com', '123456'),
    ],
    [
      'ResendConfirmationCode',
      () => auth.resendConfirmationCode('fictional@example.com'),
    ],
    ['ForgotPassword', () => auth.forgotPassword('fictional@example.com')],
    [
      'ConfirmForgotPassword',
      () =>
        auth.confirmForgotPassword(
          'fictional@example.com',
          '123456',
          'Fictional-Password-42',
        ),
    ],
  ];
  return (
    <main>
      <h1>Synthetic public account policy</h1>
      <p data-testid="result">{result}</p>
      {actions.map(([name, action]) => (
        <button
          key={name}
          onClick={() => {
            setResult('pending');
            void action().then(
              () => setResult('unexpected-success'),
              (error: unknown) =>
                setResult(
                  error && typeof error === 'object' && 'code' in error
                    ? String(error.code)
                    : 'unknown-error',
                ),
            );
          }}
        >
          {name}
        </button>
      ))}
    </main>
  );
}
ReactDOM.createRoot(document.getElementById('root')!).render(
  <AuthProvider>
    <Harness />
  </AuthProvider>,
);
