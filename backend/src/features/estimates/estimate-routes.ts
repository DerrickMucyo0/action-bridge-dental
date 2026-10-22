import { PlanComparisonRequestSchema, RevisionScopedRequestSchema } from '@actionbridge/contracts';
import { compareCoverage, estimateCase } from '@actionbridge/benefits-engine';
import { resolveOwnerId, type AuthMode } from '../../shared/auth.js';
import { HttpError, jsonResult, parseBody, type RouteHandler } from '../../shared/http.js';
import { caseIdFrom } from '../cases/api/case-routes.js';
import { toEngineInput, type CaseService } from '../cases/application/case-service.js';
import { PlanComparisonService } from './application/plan-comparison-service.js';

export interface CalculationRouteDeps {
  cases: CaseService;
  authMode: AuthMode;
}

/**
 * `POST /v1/cases/{caseId}/estimates` → 200 with `estimated | needs_information | unsupported`,
 * 409 on a stale revision, 422 on contradictory inputs (decision D-02).
 */
export function estimateRoutes({ cases, authMode }: CalculationRouteDeps): Record<string, RouteHandler> {
  const planComparisons = new PlanComparisonService({ cases });
  return {
    /** Two candidate insurance plans on the owner's current stored treatment; no writes. */
    'POST /v1/cases/{caseId}/plan-comparison': async (event) => {
      const ownerId = resolveOwnerId(event, authMode);
      const request = parseBody(event, PlanComparisonRequestSchema);
      const result = await planComparisons.compare(ownerId, caseIdFrom(event), request);
      return jsonResult(200, result, event.requestContext.requestId);
    },

    'POST /v1/cases/{caseId}/estimates': async (event) => {
      const ownerId = resolveOwnerId(event, authMode);
      const { expectedRevision } = parseBody(event, RevisionScopedRequestSchema);
      const record = await cases.getAtRevision(ownerId, caseIdFrom(event), expectedRevision);

      const result = estimateCase(toEngineInput(record));
      if (result.status === 'invalid') {
        throw new HttpError('INCONSISTENT_INPUT', 'Some values contradict each other. Review them and try again.', result.issues);
      }
      return jsonResult(200, result, event.requestContext.requestId);
    },

    /** Insured estimate versus explicit cash quotes for the same procedures (U-02). */
    'POST /v1/cases/{caseId}/coverage-comparison': async (event) => {
      const ownerId = resolveOwnerId(event, authMode);
      const { expectedRevision } = parseBody(event, RevisionScopedRequestSchema);
      const record = await cases.getAtRevision(ownerId, caseIdFrom(event), expectedRevision);

      const result = compareCoverage(toEngineInput(record));
      if ('status' in result) {
        throw new HttpError('INCONSISTENT_INPUT', 'Some values contradict each other. Review them and try again.', result.issues);
      }
      return jsonResult(200, result, event.requestContext.requestId);
    },
  };
}
