import {
  PlanComparisonRequestSchema,
  PlanComparisonResultSchema,
  type ComparisonPlan,
  type ErrorIssue,
  type PlanComparisonRequest,
  type PlanComparisonResult,
} from '@actionbridge/contracts';
import type { CaseCheckInput } from './case-check.js';
import { estimateSchedule, type EngineEstimateResult, type InvalidResult } from './estimate.js';
import { ENGINE_VERSION } from './version.js';

/** Contradictions follow the existing engine convention; the API maps invalid results to 422. */
export type EnginePlanComparisonResult = PlanComparisonResult | InvalidResult;

/**
 * Estimate two insurance plans independently on one confirmed treatment and fixed schedule.
 * The caller verifies the source case revision/confirmation; this pure function has no saved state.
 * No schedule optimization, premiums or enrollment economics are involved.
 */
export function comparePlans(input: PlanComparisonRequest): EnginePlanComparisonResult {
  const meta = { engineVersion: ENGINE_VERSION, caseRevision: input.expectedRevision };
  const parsed = PlanComparisonRequestSchema.safeParse(input);
  if (!parsed.success) {
    return { status: 'invalid', ...meta, issues: contractIssues(parsed.error.issues, 'INVALID_COMPARISON_INPUT') };
  }
  const request = parsed.data;
  const estimateA = estimatePlan(request, request.planA);
  const estimateB = estimatePlan(request, request.planB);
  if (estimateA.status === 'invalid' || estimateB.status === 'invalid') {
    const issues: ErrorIssue[] = [];
    for (const [side, estimate] of [['planA', estimateA], ['planB', estimateB]] as const) {
      if (estimate.status === 'invalid') {
        issues.push(...estimate.issues.map((issue) => ({
          ...issue,
          fieldPath: issue.fieldPath === null || issue.fieldPath.startsWith('treatment.')
            ? issue.fieldPath : `${side}.${issue.fieldPath}`,
        })));
      }
    }
    return { status: 'invalid', ...meta, issues };
  }

  // Validate shared scope, revision, version and output bounds before permitting a difference.
  const checked = PlanComparisonResultSchema.safeParse({
    ...meta,
    caseId: request.caseId,
    currency: request.currency,
    treatment: request.treatment,
    planA: { planId: request.planA.planId, label: request.planA.label, estimate: estimateA },
    planB: { planId: request.planB.planId, label: request.planB.label, estimate: estimateB },
    planBMinusPlanACents: null,
  });
  if (!checked.success) {
    return { status: 'invalid', ...meta, issues: contractIssues(checked.error.issues, 'INVALID_COMPARISON_RESULT') };
  }
  const result = checked.data;
  if (result.planA.estimate.status === 'estimated' && result.planB.estimate.status === 'estimated') {
    result.planBMinusPlanACents = result.planB.estimate.totals.patientPaysCents
      - result.planA.estimate.totals.patientPaysCents;
  }
  return result;
}

function estimatePlan(request: PlanComparisonRequest, plan: ComparisonPlan): EngineEstimateResult {
  const dates = new Map(request.treatment.schedule.map((entry) => [entry.procedureId, entry.date]));
  const input: CaseCheckInput = {
    caseRevision: request.expectedRevision,
    currency: request.currency,
    coverageMode: 'insured',
    policy: plan.policy,
    planYears: plan.planYears,
    procedures: request.treatment.procedures.map((procedure) => ({
      ...procedure,
      ...plan.procedureFacts[procedure.id]!,
      proposedDate: dates.get(procedure.id)!,
    })),
  };
  const result = estimateSchedule(input, request.treatment.schedule);
  switch (result.status) {
    case 'needs_information':
      return { ...result, missing: result.missing.map((fact) => ({ ...fact, fieldPath: comparisonPath(fact.fieldPath) })) };
    case 'unsupported':
      return { ...result, limitations: result.limitations.map((limitation) => ({
        ...limitation,
        ...(limitation.fieldPath === undefined ? {} : { fieldPath: comparisonPath(limitation.fieldPath) }),
      })) };
    case 'invalid':
      return { ...result, issues: result.issues.map((issue) => ({
        ...issue, fieldPath: issue.fieldPath === null ? null : comparisonPath(issue.fieldPath),
      })) };
    case 'estimated':
      return result;
  }
}

/** Per-plan paths are relative to that plan; shared treatment paths refer to the comparison root. */
function comparisonPath(path: string): string {
  if (path === 'procedures') return 'treatment.procedures';
  const match = /^procedures\.([^.]+)(?:\.(.+))?$/.exec(path);
  if (!match) return path;
  const [, id, field] = match;
  if (field === 'category' || field === 'network' || field === 'allowedCents' || field === 'contractualWriteoffCents') {
    return `procedureFacts.${id}.${field}`;
  }
  if (field === 'proposedDate') return `treatment.schedule.${id}.date`;
  return `treatment.procedures.${id}${field === undefined ? '' : `.${field}`}`;
}

function contractIssues(
  issues: readonly { path: readonly PropertyKey[]; message: string }[],
  code: string,
): ErrorIssue[] {
  return issues.map((issue) => ({
    fieldPath: issue.path.length === 0 ? null : issue.path.join('.'),
    code,
    message: issue.message.slice(0, 300),
  }));
}
