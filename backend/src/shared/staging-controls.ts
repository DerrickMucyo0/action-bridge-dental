import type { AppConfig, StagingConfig } from './config.js';
import { resolveOwnerId } from './auth.js';
import { HttpError, type RouteHandler } from './http.js';

export type StagingOperation = 'jobs' | 'uploads' | 'speech';

/** A transaction must reserve both the account's and the whole stage's UTC-day allowance. */
export interface StagingQuotaStore {
  consume(ownerId: string, operation: StagingOperation, limits: { user: number; global: number }, now: Date): Promise<void>;
}

/** Restrictions apply to staging only. Owners always come from validated authorizer claims. */
export class StagingControls {
  constructor(
    private readonly config: StagingConfig,
    private readonly store: StagingQuotaStore,
    private readonly now: () => Date = () => new Date(),
  ) {
    if (config.allowedUserSubs.length === 0 || config.allowedUserSubs.some((sub) => sub.length === 0)) {
      throw new Error('Staging requires approved Cognito subjects');
    }
  }

  assertAllowed(ownerId: string): void {
    assertApprovedStagingOwner(this.config, ownerId);
  }

  async consume(ownerId: string, operation: StagingOperation): Promise<void> {
    this.assertAllowed(ownerId);
    const limits =
      operation === 'jobs'
        ? { user: this.config.jobDailyLimit, global: this.config.globalJobDailyLimit }
        : operation === 'uploads'
          ? { user: this.config.uploadDailyLimit, global: this.config.globalUploadDailyLimit }
          : { user: this.config.speechDailyLimit, global: this.config.globalSpeechDailyLimit };
    await this.store.consume(ownerId, operation, limits, this.now());
  }
}

export function assertApprovedStagingOwner(config: StagingConfig, ownerId: string): void {
  if (!config.allowedUserSubs.some((sub) => ownerId === `user:${sub}`)) {
    throw new HttpError('FORBIDDEN', 'This staging environment is available to approved test accounts only.');
  }
}

/** The health endpoint stays public; every other known HTTP route is guarded before any I/O. */
export function restrictStagingRoutes(config: AppConfig, routes: Record<string, RouteHandler>): Record<string, RouteHandler> {
  if (config.appEnv !== 'staging') return routes;
  if (!config.staging || config.authMode !== 'jwt' || config.staging.allowedUserSubs.length === 0) {
    throw new Error('Staging restrictions are not configured');
  }
  const owners = new Set(config.staging.allowedUserSubs.map((sub) => `user:${sub}`));
  return Object.fromEntries(
    Object.entries(routes).map(([key, route]) => [
      key,
      key === 'GET /health'
        ? route
        : async (event) => {
            const ownerId = resolveOwnerId(event, config.authMode);
            if (!owners.has(ownerId)) throw new HttpError('FORBIDDEN', 'This staging environment is available to approved test accounts only.');
            return route(event);
          },
    ]),
  );
}
