import {
  PlanComparisonListSchema,
  SavedPlanComparisonSchema,
  SavePlanComparisonRequestSchema,
  SavePlanComparisonResponseSchema,
  type EstimateResult,
  type PlanComparisonRequest,
  type SavedPlanComparison,
  type SavedPlanComparisonMetadata,
} from '@actionbridge/contracts';
import { describe, expect, it } from 'vitest';

// Fictional schema examples only. Saving must calculate authoritative results on the server.
function request(): PlanComparisonRequest {
  return {
    caseId: 'synthetic-case', expectedRevision: 3, currency: 'USD',
    treatment: {
      procedures: [
        { id: 'filling-1', label: 'Filling', cdtCode: null, providerChargeCents: 25000,
          dentistEarliestDate: null, dentistLatestDate: null, timingSource: 'unknown', prerequisiteIds: [] },
        { id: 'crown-1', label: 'Crown', cdtCode: null, providerChargeCents: 100000,
          dentistEarliestDate: null, dentistLatestDate: null, timingSource: 'unknown', prerequisiteIds: [] },
      ],
      schedule: [{ procedureId: 'filling-1', date: '2026-11-10' }, { procedureId: 'crown-1', date: '2026-11-12' }],
      sourceFacts: [],
    },
    planA: {
      planId: 'plan-a', label: 'Fictional Plan A', policy: null, planYears: {}, sourceFacts: [],
      procedureFacts: {
        'filling-1': { category: null, network: 'unknown', allowedCents: null, contractualWriteoffCents: null },
        'crown-1': { category: 'major', network: 'in', allowedCents: 80000, contractualWriteoffCents: 20000 },
      },
    },
    planB: {
      planId: 'plan-b', label: 'Fictional Plan B', policy: null, planYears: {}, sourceFacts: [],
      procedureFacts: {
        'filling-1': { category: 'preventive', network: 'out', allowedCents: 20000, contractualWriteoffCents: 0 },
        'crown-1': { category: null, network: 'unknown', allowedCents: null, contractualWriteoffCents: null },
      },
    },
  };
}

function snapshot(): SavedPlanComparison {
  const input = request();
  const missing: EstimateResult = {
    status: 'needs_information', caseRevision: 3, engineVersion: 'synthetic-contract-v1',
    missing: [{ fieldPath: 'policy', code: 'POLICY_NOT_SUPPLIED', message: 'Policy not supplied.' }],
  };
  const unsupported: EstimateResult = {
    status: 'unsupported', caseRevision: 3, engineVersion: 'synthetic-contract-v1',
    limitations: [{ code: 'WAITING_PERIOD_UNSUPPORTED', message: 'Fictional waiting period.' }],
  };
  return {
    comparisonId: 'comparison-1', caseId: input.caseId, caseRevision: input.expectedRevision,
    request: input,
    result: {
      caseId: input.caseId, caseRevision: input.expectedRevision, currency: input.currency,
      engineVersion: 'synthetic-contract-v1', treatment: structuredClone(input.treatment),
      planA: { planId: input.planA.planId, label: input.planA.label, estimate: missing },
      planB: { planId: input.planB.planId, label: input.planB.label, estimate: unsupported },
      planBMinusPlanACents: null,
    },
    savedAt: '2026-10-22T12:00:00.000Z',
  };
}

function metadata(): SavedPlanComparisonMetadata {
  const saved = snapshot();
  return {
    comparisonId: saved.comparisonId, caseId: saved.caseId, caseRevision: saved.caseRevision,
    savedAt: saved.savedAt,
    planALabel: saved.request.planA.label, planBLabel: saved.request.planB.label,
    planAStatus: saved.result.planA.estimate.status, planBStatus: saved.result.planB.estimate.status,
  };
}

describe('saving two-plan comparison contracts', () => {
  it('accepts independently supplied candidate facts and explicit save consent', () => {
    const input = { comparison: request(), consent: true };
    expect(SavePlanComparisonRequestSchema.parse(input)).toEqual(input);
    expect(input.comparison.planA.procedureFacts['crown-1']!.allowedCents).toBe(80000);
    expect(input.comparison.planB.procedureFacts['crown-1']!.allowedCents).toBeNull();
  });

  it('rejects client results, personal owner fields, missing consent and invalid candidate data', () => {
    const input = { comparison: request(), consent: true };
    for (const body of [
      { ...input, result: snapshot().result },
      { ...input, ownerId: 'someone-else' },
      { ...input, consent: false },
      { comparison: input.comparison },
      { ...input, comparison: { ...input.comparison, patientPaysCents: 0 } },
      { ...input, comparison: { ...input.comparison, expectedRevision: 0 } },
    ]) {
      expect(SavePlanComparisonRequestSchema.safeParse(body).success).toBe(false);
    }
  });

  it('preserves missing and unsupported results without a cost ranking', () => {
    const saved = snapshot();
    expect(SavedPlanComparisonSchema.parse(saved)).toEqual(saved);
    expect(SavePlanComparisonResponseSchema.parse({ comparison: saved, replayed: false }).comparison).toEqual(saved);
    expect(SavePlanComparisonResponseSchema.parse({ comparison: saved, replayed: true }).replayed).toBe(true);
    saved.result.planBMinusPlanACents = 0;
    expect(SavedPlanComparisonSchema.safeParse(saved).success).toBe(false);
  });

  it('accepts canonical procedure and schedule ordering while retaining all shared facts', () => {
    const saved = snapshot();
    saved.result.treatment.procedures.reverse();
    saved.result.treatment.schedule.reverse();
    expect(SavedPlanComparisonSchema.safeParse(saved).success).toBe(true);
  });

  it.each<[string, (saved: SavedPlanComparison) => void]>([
    ['snapshot case ID', (s) => { s.caseId = 'other-case'; }],
    ['request case ID', (s) => { s.request.caseId = 'other-case'; }],
    ['result case ID', (s) => { s.result.caseId = 'other-case'; }],
    ['snapshot revision', (s) => { s.caseRevision = 4; }],
    ['request revision', (s) => { s.request.expectedRevision = 4; }],
    ['result revision', (s) => {
      s.result.caseRevision = 4; s.result.planA.estimate.caseRevision = 4; s.result.planB.estimate.caseRevision = 4;
    }],
    ['provider charge', (s) => { s.result.treatment.procedures[0]!.providerChargeCents = 10000; }],
    ['planned date', (s) => { s.result.treatment.schedule[0]!.date = '2026-11-11'; }],
    ['treatment label', (s) => { s.result.treatment.procedures[0]!.label = 'Different treatment'; }],
    ['plan A identity', (s) => { s.result.planA.planId = 'other-plan'; }],
    ['plan B label', (s) => { s.result.planB.label = 'Different plan'; }],
    ['source evidence', (s) => {
      s.result.treatment.sourceFacts.push({
        id: 'extra-source', fieldPath: 'currency', value: 'USD', sourceId: null, location: null,
        origin: 'synthetic', extractionStatus: 'not_applicable', userConfirmed: true,
        insurerVerification: { status: 'not_verified' }, conflict: false, recordedAt: s.savedAt,
      });
    }],
  ])('rejects mismatched %s', (_name, mutate) => {
    const saved = snapshot(); mutate(saved);
    expect(SavedPlanComparisonSchema.safeParse(saved).success).toBe(false);
  });
});

describe('saved comparison list contracts', () => {
  it('lists only metadata for the checked current case revision', () => {
    const list = { caseId: 'synthetic-case', caseRevision: 3, comparisons: [metadata()] };
    expect(PlanComparisonListSchema.parse(list)).toEqual(list);
    expect(PlanComparisonListSchema.parse({ ...list, comparisons: [] }).comparisons).toEqual([]);
    expect(PlanComparisonListSchema.safeParse({ ...list, comparisons: [{ ...metadata(), request: request() }] }).success).toBe(false);
  });

  it('rejects another case, stale snapshots, unknown statuses and oversized lists', () => {
    const list = { caseId: 'synthetic-case', caseRevision: 3, comparisons: [metadata()] };
    for (const changes of [{ caseId: 'other-case' }, { caseRevision: 2 }, { planAStatus: 'winner' }]) {
      expect(PlanComparisonListSchema.safeParse({ ...list, comparisons: [{ ...metadata(), ...changes }] }).success).toBe(false);
    }
    expect(PlanComparisonListSchema.safeParse({ ...list, comparisons: Array.from({ length: 21 }, metadata) }).success).toBe(false);
  });
});
