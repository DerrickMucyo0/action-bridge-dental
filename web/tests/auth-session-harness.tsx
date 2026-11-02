import { useState } from 'react';
import ReactDOM from 'react-dom/client';
import { AuthProvider, useAuth } from '../src/state/auth';

/** Test-only entry point; never included in the production application routes. */
function Harness() {
  const auth = useAuth();
  const [outcome, setOutcome] = useState('idle');
  return (
    <main>
      <h1>Synthetic authentication concurrency test</h1>
      <p data-testid="status">{auth.status}</p>
      <p data-testid="email">{auth.session?.email ?? 'none'}</p>
      <p data-testid="outcome">{outcome}</p>
      <button
        onClick={() =>
          void auth
            .signIn('first@example.com', 'Fictional-test-1')
            .catch(() => setOutcome('rejected'))
        }
      >
        First sign-in
      </button>
      <button
        onClick={() =>
          void auth
            .signIn('second@example.com', 'Fictional-test-1')
            .catch(() => setOutcome('rejected'))
        }
      >
        Second sign-in
      </button>
      <button
        onClick={() =>
          void auth
            .signIn('third@example.com', 'Fictional-test-1')
            .catch(() => setOutcome('rejected'))
        }
      >
        Third sign-in
      </button>
      <button
        onClick={() => {
          setOutcome('pending');
          void auth.api!.getCase('synthetic-case').then(
            () => setOutcome('completed'),
            () => setOutcome('rejected'),
          );
        }}
      >
        Read synthetic case
      </button>
      <button onClick={() => void auth.signOut().catch(() => undefined)}>
        Sign out
      </button>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <AuthProvider>
    <Harness />
  </AuthProvider>,
);
