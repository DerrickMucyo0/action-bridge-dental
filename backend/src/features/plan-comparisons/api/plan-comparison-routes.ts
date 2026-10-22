import { IdempotencyKeySchema, IdSchema, RevisionScopedRequestSchema, SavePlanComparisonRequestSchema } from '@actionbridge/contracts';
import { resolveOwnerId, type AuthMode } from '../../../shared/auth.js';
import { HttpError, jsonResult, parseBody, type HttpEvent, type RouteHandler } from '../../../shared/http.js';
import { caseIdFrom } from '../../cases/api/case-routes.js';
import type { SavedPlanComparisonService } from '../application/saved-plan-comparison-service.js';

export function planComparisonRoutes({ comparisons, authMode }: {
  comparisons: SavedPlanComparisonService;
  authMode: AuthMode;
}): Record<string, RouteHandler> {
  return {
    'POST /v1/cases/{caseId}/plan-comparisons': async (event) => {
      const ownerId = resolveOwnerId(event, authMode);
      const key = IdempotencyKeySchema.safeParse(event.headers?.['idempotency-key']);
      if (!key.success) throw new HttpError('BAD_REQUEST', 'Saving requires an Idempotency-Key header (8–100 letters, digits, hyphens or underscores).');
      const saved = await comparisons.save(ownerId, caseIdFrom(event), key.data, parseBody(event, SavePlanComparisonRequestSchema));
      return jsonResult(saved.replayed ? 200 : 201, saved, event.requestContext.requestId);
    },
    'GET /v1/cases/{caseId}/plan-comparisons': async (event) => {
      const ownerId = resolveOwnerId(event, authMode);
      return jsonResult(200, await comparisons.list(ownerId, caseIdFrom(event), revisionFrom(event)), event.requestContext.requestId);
    },
    'GET /v1/cases/{caseId}/plan-comparisons/{comparisonId}': async (event) => {
      const ownerId = resolveOwnerId(event, authMode);
      const caseId = caseIdFrom(event);
      const id = IdSchema.safeParse(event.pathParameters?.comparisonId);
      if (!id.success) throw new HttpError('NOT_FOUND', 'Saved comparison not found.');
      return jsonResult(200, await comparisons.get(ownerId, caseId, revisionFrom(event), id.data), event.requestContext.requestId);
    },
  };
}

function revisionFrom(event: HttpEvent): number {
  const raw = event.queryStringParameters?.expectedRevision;
  const parsed = RevisionScopedRequestSchema.safeParse({ expectedRevision: raw && /^[1-9]\d*$/.test(raw) ? Number(raw) : undefined });
  if (!parsed.success) throw new HttpError('BAD_REQUEST', 'Supply the current expectedRevision as a positive integer query parameter.');
  return parsed.data.expectedRevision;
}
