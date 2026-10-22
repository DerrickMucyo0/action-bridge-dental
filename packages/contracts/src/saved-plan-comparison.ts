import { z } from 'zod';
import { RevisionScopedRequestSchema } from './case.js';
import {
  ComparisonPlanSchema,
  PlanComparisonRequestSchema,
  PlanComparisonResultSchema,
  type PlanComparisonTreatment,
} from './plan-comparison.js';
import { IdSchema, IsoDateTimeSchema } from './primitives.js';

/** Save candidate inputs only. The server verifies the case and calculates both results. */
export const SavePlanComparisonRequestSchema = z.strictObject({
  comparison: PlanComparisonRequestSchema,
  consent: z.literal(true),
});

/** Immutable inputs and authoritative engine outputs, not a claim, payment or enrollment. */
export const SavedPlanComparisonSchema = z.strictObject({
  comparisonId: IdSchema,
  caseId: IdSchema,
  caseRevision: RevisionScopedRequestSchema.shape.expectedRevision,
  request: PlanComparisonRequestSchema,
  result: PlanComparisonResultSchema,
  savedAt: IsoDateTimeSchema,
}).superRefine((snapshot, ctx) => {
  if (snapshot.caseId !== snapshot.request.caseId || snapshot.caseId !== snapshot.result.caseId) {
    ctx.addIssue({ code: 'custom', path: ['caseId'], message: 'Snapshot inputs and results must belong to this case.' });
  }
  if (snapshot.caseRevision !== snapshot.request.expectedRevision || snapshot.caseRevision !== snapshot.result.caseRevision) {
    ctx.addIssue({ code: 'custom', path: ['caseRevision'], message: 'Snapshot inputs and results must use the same case revision.' });
  }
  if (snapshot.request.currency !== snapshot.result.currency || !sameTreatment(snapshot.request.treatment, snapshot.result.treatment)) {
    ctx.addIssue({ code: 'custom', path: ['result', 'treatment'], message: 'Snapshot results must use the requested treatment, schedule and sources.' });
  }
  for (const side of ['planA', 'planB'] as const) {
    if (snapshot.request[side].planId !== snapshot.result[side].planId || snapshot.request[side].label !== snapshot.result[side].label) {
      ctx.addIssue({ code: 'custom', path: ['result', side], message: 'Snapshot results must match each independently supplied plan.' });
    }
  }
});

/** POST requires an Idempotency-Key header; 201 for a new snapshot, 200 for replay. */
export const SavePlanComparisonResponseSchema = z.strictObject({
  comparison: SavedPlanComparisonSchema,
  replayed: z.boolean(),
});

/** List responses omit treatment, source evidence, insurance facts and cost amounts. */
export const SavedPlanComparisonMetadataSchema = z.strictObject({
  comparisonId: IdSchema,
  caseId: IdSchema,
  caseRevision: RevisionScopedRequestSchema.shape.expectedRevision,
  savedAt: IsoDateTimeSchema,
  planALabel: ComparisonPlanSchema.shape.label,
  planBLabel: ComparisonPlanSchema.shape.label,
  planAStatus: z.enum(['estimated', 'needs_information', 'unsupported']),
  planBStatus: z.enum(['estimated', 'needs_information', 'unsupported']),
});

/** Only snapshots for the checked current case revision are exposed by the list endpoint. */
export const PlanComparisonListSchema = z.strictObject({
  caseId: IdSchema,
  caseRevision: RevisionScopedRequestSchema.shape.expectedRevision,
  comparisons: z.array(SavedPlanComparisonMetadataSchema).max(20),
}).superRefine((list, ctx) => {
  for (const [index, comparison] of list.comparisons.entries()) {
    if (comparison.caseId !== list.caseId) {
      ctx.addIssue({ code: 'custom', path: ['comparisons', index, 'caseId'], message: 'List only snapshots belonging to this case.' });
    }
    if (comparison.caseRevision !== list.caseRevision) {
      ctx.addIssue({ code: 'custom', path: ['comparisons', index, 'caseRevision'], message: 'List only snapshots for the current case revision.' });
    }
  }
});

/** Zod normalizes object keys; procedure and schedule ordering may be canonicalized by the server. */
function sameTreatment(left: PlanComparisonTreatment, right: PlanComparisonTreatment): boolean {
  const normalize = (treatment: PlanComparisonTreatment) => ({
    procedures: [...treatment.procedures].sort((a, b) => a.id.localeCompare(b.id)),
    schedule: [...treatment.schedule].sort((a, b) => a.procedureId.localeCompare(b.procedureId)),
    sourceFacts: treatment.sourceFacts,
  });
  return JSON.stringify(normalize(left)) === JSON.stringify(normalize(right));
}

export type SavePlanComparisonRequest = z.infer<typeof SavePlanComparisonRequestSchema>;
export type SavedPlanComparison = z.infer<typeof SavedPlanComparisonSchema>;
export type SavePlanComparisonResponse = z.infer<typeof SavePlanComparisonResponseSchema>;
export type SavedPlanComparisonMetadata = z.infer<typeof SavedPlanComparisonMetadataSchema>;
export type PlanComparisonList = z.infer<typeof PlanComparisonListSchema>;
