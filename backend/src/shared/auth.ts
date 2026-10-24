import { HttpError, type HttpEvent } from './http.js';

/**
 * - `jwt`: owner is the `sub` of an access token validated by the API Gateway JWT authorizer.
 * - `demo`: synthetic-data-only environment without login. Each device sends a random
 *   `x-demo-user-id`; this isolates demo sessions from each other but is NOT authentication.
 *   Never use demo mode with real dental documents or patient data.
 */
export type AuthMode = 'jwt' | 'demo';

const DEMO_USER_PATTERN = /^[A-Za-z0-9-]{16,64}$/;

export function resolveOwnerId(event: HttpEvent, mode: AuthMode): string {
  if (mode === 'jwt') {
    // Only Gateway-validated claims are authoritative. Never decode an Authorization header
    // here or use request bodies/demo headers to infer ownership or token validity.
    const claims = event.requestContext.authorizer?.jwt?.claims;
    const sub = claims?.sub;
    if (claims?.token_use !== 'access' || typeof sub !== 'string' || sub.trim().length === 0 || sub !== sub.trim()) {
      throw new HttpError('UNAUTHENTICATED', 'Sign in to continue.');
    }
    return `user:${sub}`;
  }
  const demoUser = event.headers?.['x-demo-user-id'];
  if (demoUser === undefined || !DEMO_USER_PATTERN.test(demoUser)) {
    throw new HttpError('UNAUTHENTICATED', 'Demo mode requires an x-demo-user-id device identifier.');
  }
  return `demo:${demoUser}`;
}
