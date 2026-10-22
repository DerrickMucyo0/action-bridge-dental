import { z } from 'zod';
import {
  DentalCaseInputSchema,
  PlanYearSchema,
  PolicySchema,
  ProcedureSchema,
  RevisionScopedRequestSchema,
  SourceFactSchema,
} from './case.js';
import { EstimatedResultSchema, EstimateResultSchema, ScheduleEntrySchema } from './estimate.js';
import { CurrencySchema, IdSchema, MAX_CENTS } from './primitives.js';

/** Shared treatment facts; benefit category, network and negotiated prices belong to each plan. */
export const PlanComparisonProcedureSchema = ProcedureSchema.omit({
  category: true,
  network: true,
  allowedCents: true,
  contractualWriteoffCents: true,
  proposedDate: true,
  selfPayQuote: true,
});

/** One confirmed treatment and one fixed schedule, used unchanged for both estimates. */
export const PlanComparisonTreatmentSchema = z.strictObject({
  procedures: z.array(PlanComparisonProcedureSchema).min(1).max(20),
  schedule: z.array(ScheduleEntrySchema).min(1).max(20),
  sourceFacts: z.array(SourceFactSchema).max(200),
}).superRefine((treatment, ctx) => {
  const ids = treatment.procedures.map((procedure) => procedure.id);
  if (new Set(ids).size !== ids.length) {
    ctx.addIssue({ code: 'custom', path: ['procedures'], message: 'Treatment procedure IDs must be unique.' });
  }
  if (!sameProcedureIds(ids, treatment.schedule.map((entry) => entry.procedureId))) {
    ctx.addIssue({ code: 'custom', path: ['schedule'], message: 'Schedule every treatment procedure exactly once.' });
  }
});

/** Unknown rules remain null. The existing single-plan policy contract stays unchanged. */
export const PlanComparisonPolicySchema = PolicySchema.extend({
  deductibleBeforeCoinsurance: PolicySchema.shape.deductibleBeforeCoinsurance.nullable(),
  deductibleAppliesByCategory: z.record(IdSchema, z.boolean().nullable()).nullable(),
  insurerRateBpsByCategory: z.record(IdSchema, PolicySchema.shape.insurerRateBpsByCategory.valueType.nullable()).nullable(),
  annualMaximumAppliesByCategory: z.record(IdSchema, z.boolean().nullable()).nullable(),
  rounding: PolicySchema.shape.rounding.nullable(),
  allServicesCovered: PolicySchema.shape.allServicesCovered.nullable(),
  waitingPeriods: PolicySchema.shape.waitingPeriods.nullable(),
  exclusions: PolicySchema.shape.exclusions.nullable(),
  frequencyRestrictions: PolicySchema.shape.frequencyRestrictions.nullable(),
});

/** Keyed by the shared treatment's procedure ID. Unknown network retains the existing 'unknown' value. */
export const PlanComparisonProcedureFactsSchema = ProcedureSchema.pick({
  category: true,
  network: true,
  allowedCents: true,
  contractualWriteoffCents: true,
}).extend({ category: ProcedureSchema.shape.category.nullable() });

export const ComparisonPlanSchema = z.strictObject({
  /** Identity of this plan configuration, independent of the policy's calculation-model ID. */
  planId: IdSchema,
  label: z.string().trim().min(1).max(120),
  policy: PlanComparisonPolicySchema.nullable(),
  /** An empty map means no benefit periods have been supplied; dates are never invented. */
  planYears: z.record(IdSchema, PlanYearSchema),
  procedureFacts: z.record(IdSchema, PlanComparisonProcedureFactsSchema),
  /** Field paths are relative to this plan, e.g. procedureFacts.crown-1.allowedCents. */
  sourceFacts: z.array(SourceFactSchema).max(200),
});

/**
 * Treatment-cost comparison only; no premiums, enrollment or client-supplied results.
 * The application must verify the confirmed treatment/schedule against this case revision.
 */
export const PlanComparisonRequestSchema = RevisionScopedRequestSchema.extend({
  caseId: IdSchema,
  currency: CurrencySchema,
  treatment: PlanComparisonTreatmentSchema,
  planA: ComparisonPlanSchema,
  planB: ComparisonPlanSchema,
}).superRefine((request, ctx) => {
  if (request.planA.planId === request.planB.planId) {
    ctx.addIssue({ code: 'custom', path: ['planB', 'planId'], message: 'Choose two distinct plans.' });
  }
  const ids = request.treatment.procedures.map((procedure) => procedure.id);
  for (const side of ['planA', 'planB'] as const) {
    if (!sameProcedureIds(ids, Object.keys(request[side].procedureFacts))) {
      ctx.addIssue({ code: 'custom', path: [side, 'procedureFacts'], message: 'Supply independent plan facts for every treatment procedure.' });
    }
  }
});

export const ComparedPlanSchema = ComparisonPlanSchema.pick({ planId: true, label: true }).extend({
  estimate: EstimateResultSchema,
});

/**
 * Only authoritative engine outputs belong here. A null difference makes no cost ranking.
 * Positive planBMinusPlanACents means Plan B costs the patient more; zero means equal.
 * Eligibility is validated here; computing amounts/differences belongs to the engine.
 * Conditional estimates retain their assumptions and may be compared on that stated basis.
 */
export const PlanComparisonResultSchema = z.strictObject({
  caseId: IdSchema,
  caseRevision: DentalCaseInputSchema.shape.caseRevision,
  currency: CurrencySchema,
  engineVersion: EstimatedResultSchema.shape.engineVersion,
  treatment: PlanComparisonTreatmentSchema,
  planA: ComparedPlanSchema,
  planB: ComparedPlanSchema,
  planBMinusPlanACents: z.number().int().min(-MAX_CENTS).max(MAX_CENTS).nullable(),
}).superRefine((result, ctx) => {
  if (result.planA.planId === result.planB.planId) {
    ctx.addIssue({ code: 'custom', path: ['planB', 'planId'], message: 'Choose two distinct plans.' });
  }
  const ids = result.treatment.procedures.map((procedure) => procedure.id);
  const dates = new Map(result.treatment.schedule.map((entry) => [entry.procedureId, entry.date]));
  const charges = new Map(result.treatment.procedures.map((procedure) => [procedure.id, procedure.providerChargeCents]));
  for (const side of ['planA', 'planB'] as const) {
    const estimate = result[side].estimate;
    if (estimate.caseRevision !== result.caseRevision || estimate.engineVersion !== result.engineVersion) {
      ctx.addIssue({ code: 'custom', path: [side, 'estimate'], message: 'Every result must use the comparison revision and engine version.' });
    }
    if (estimate.status === 'estimated') {
      const matchingSchedule = sameProcedureIds(ids, estimate.schedule.map((entry) => entry.procedureId))
        && estimate.schedule.every((entry) => dates.get(entry.procedureId) === entry.date);
      const matchingLines = sameProcedureIds(ids, estimate.lines.map((line) => line.procedureId))
        && estimate.lines.every((line) => dates.get(line.procedureId) === line.date
          && charges.get(line.procedureId) === line.providerChargeCents);
      if (!matchingSchedule || !matchingLines) {
        ctx.addIssue({ code: 'custom', path: [side, 'estimate'], message: 'Estimate the same treatment, provider charges and schedule for both plans.' });
      }
    }
  }
  if (result.planBMinusPlanACents !== null
    && (result.planA.estimate.status !== 'estimated' || result.planB.estimate.status !== 'estimated')) {
    ctx.addIssue({ code: 'custom', path: ['planBMinusPlanACents'], message: 'A cost difference requires two complete, comparable estimates.' });
  }
});

/** Exact set equality, including duplicate detection; input ordering is immaterial. */
function sameProcedureIds(expected: string[], actual: string[]): boolean {
  const expectedIds = new Set(expected);
  return expectedIds.size === expected.length && actual.length === expected.length
    && new Set(actual).size === actual.length && actual.every((id) => expectedIds.has(id));
}

export type PlanComparisonProcedure = z.infer<typeof PlanComparisonProcedureSchema>;
export type PlanComparisonTreatment = z.infer<typeof PlanComparisonTreatmentSchema>;
export type PlanComparisonPolicy = z.infer<typeof PlanComparisonPolicySchema>;
export type PlanComparisonProcedureFacts = z.infer<typeof PlanComparisonProcedureFactsSchema>;
export type ComparisonPlan = z.infer<typeof ComparisonPlanSchema>;
export type PlanComparisonRequest = z.infer<typeof PlanComparisonRequestSchema>;
export type ComparedPlan = z.infer<typeof ComparedPlanSchema>;
export type PlanComparisonResult = z.infer<typeof PlanComparisonResultSchema>;
