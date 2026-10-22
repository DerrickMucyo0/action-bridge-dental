import {
  MAX_CENTS,
  PlanComparisonPolicySchema,
  PlanComparisonRequestSchema,
  PlanComparisonResultSchema,
  PolicySchema,
  type EstimateResult,
  type PlanComparisonRequest,
  type PlanComparisonResult,
} from '@actionbridge/contracts';
import { describe, expect, it } from 'vitest';

// Synthetic contract examples only. No calculator or API is invoked by these tests.
function request(): PlanComparisonRequest {
  const planA: PlanComparisonRequest['planA'] = {
    planId: 'plan-a',
    label: 'Fictional Plan A',
    policy: {
      id: 'fictional-individual-ppo-v1',
      deductibleBeforeCoinsurance: true,
      deductibleAppliesByCategory: { basic: true, major: true },
      insurerRateBpsByCategory: { basic: 8000, major: 5000 },
      annualMaximumAppliesByCategory: { basic: true, major: true },
      rounding: 'half_up_to_cent',
      allServicesCovered: true,
      waitingPeriods: [],
      exclusions: [],
      frequencyRestrictions: [],
    },
    planYears: {
      'py-2026': {
        startDate: '2026-01-01', endDate: '2026-12-31', annualMaximumCents: 200000,
        insurerAlreadyPaidCents: 0, annualDeductibleCents: 5000, deductibleAlreadyMetCents: 5000,
        sourceStatus: 'synthetic_confirmed_input',
      },
    },
    procedureFacts: {
      'filling-1': { category: 'basic', network: 'in', allowedCents: 25000, contractualWriteoffCents: 0 },
      'crown-1': { category: 'major', network: 'in', allowedCents: 80000, contractualWriteoffCents: 20000 },
    },
    sourceFacts: [{
      id: 'source-a', fieldPath: 'procedureFacts.crown-1.allowedCents', value: 80000,
      sourceId: null, location: null, origin: 'synthetic', extractionStatus: 'not_applicable',
      userConfirmed: true, insurerVerification: { status: 'not_verified' }, conflict: false,
      recordedAt: '2026-10-22T12:00:00.000Z',
    }],
  };
  const planB = structuredClone(planA);
  planB.planId = 'plan-b';
  planB.label = 'Fictional Plan B';
  planB.policy!.insurerRateBpsByCategory!.major = 7000;
  planB.procedureFacts['crown-1'] = { category: 'major', network: 'out', allowedCents: 90000, contractualWriteoffCents: 10000 };
  planB.sourceFacts[0]!.id = 'source-b';
  planB.sourceFacts[0]!.value = 90000;
  return {
    caseId: 'synthetic-case', expectedRevision: 3, currency: 'USD',
    treatment: {
      procedures: [
        { id: 'filling-1', label: 'Filling', cdtCode: null, providerChargeCents: 25000,
          dentistEarliestDate: null, dentistLatestDate: null, timingSource: 'unknown', prerequisiteIds: [] },
        { id: 'crown-1', label: 'Crown', cdtCode: 'D2740', providerChargeCents: 100000,
          dentistEarliestDate: null, dentistLatestDate: null, timingSource: 'unknown', prerequisiteIds: [] },
      ],
      schedule: [{ procedureId: 'filling-1', date: '2026-11-10' }, { procedureId: 'crown-1', date: '2026-11-12' }],
      sourceFacts: [],
    },
    planA, planB,
  };
}

function estimate(side: 'A' | 'B'): Extract<EstimateResult, { status: 'estimated' }> {
  return {
    status: 'estimated', caseRevision: 3, engineVersion: 'synthetic-contract-v1',
    schedule: request().treatment.schedule,
    lines: [
      { procedureId: 'filling-1', planYearId: 'py-2026', date: '2026-11-10',
        providerChargeCents: 25000, allowedCents: 25000, contractualWriteoffCents: 0,
        insurerRateBps: 8000, deductibleAppliedCents: 0, coinsuranceCents: 5000,
        capShortfallCents: 0, balanceBillCents: 0, insurerPaysCents: 20000, patientPaysCents: 5000 },
      { procedureId: 'crown-1', planYearId: 'py-2026', date: '2026-11-12',
        providerChargeCents: 100000, allowedCents: side === 'A' ? 80000 : 90000,
        contractualWriteoffCents: side === 'A' ? 20000 : 10000,
        insurerRateBps: side === 'A' ? 5000 : 7000, deductibleAppliedCents: 0,
        coinsuranceCents: side === 'A' ? 40000 : 27000, capShortfallCents: 0, balanceBillCents: 0,
        insurerPaysCents: side === 'A' ? 40000 : 63000, patientPaysCents: side === 'A' ? 40000 : 27000 },
    ],
    totals: { providerChargeCents: 125000, contractualWriteoffCents: side === 'A' ? 20000 : 10000,
      insurerPaysCents: side === 'A' ? 60000 : 83000, patientPaysCents: side === 'A' ? 45000 : 32000 },
    yearProjections: {
      'py-2026': { planYearId: 'py-2026', annualMaximumCents: 200000, reportedInsurerPaidCents: 0,
        scenarioInsurerPaysCents: side === 'A' ? 60000 : 83000,
        projectedTotalInsurerPaidCents: side === 'A' ? 60000 : 83000,
        remainingMaximumCents: side === 'A' ? 140000 : 117000, annualDeductibleCents: 5000,
        projectedDeductibleMetCents: 5000, assumedPlanTerms: false },
    },
    assumptions: [{ code: 'SYNTHETIC_INPUT', message: 'Fictional contract example.' }], conditional: false,
  };
}

function result(): PlanComparisonResult {
  const input = request();
  return {
    caseId: input.caseId, caseRevision: 3, currency: 'USD', engineVersion: 'synthetic-contract-v1',
    treatment: input.treatment,
    planA: { planId: input.planA.planId, label: input.planA.label, estimate: estimate('A') },
    planB: { planId: input.planB.planId, label: input.planB.label, estimate: estimate('B') },
    planBMinusPlanACents: -13000,
  };
}

describe('two-plan request contracts', () => {
  it('shares one treatment/schedule while preserving independent plan prices, rules, network and sources', () => {
    const input = request();
    expect(PlanComparisonRequestSchema.parse(input)).toEqual(input);
    expect(input.planA.policy!.id).toBe(input.planB.policy!.id);
    input.planB.procedureFacts['crown-1']!.category = 'restorative';
    expect(PlanComparisonRequestSchema.parse(input).planA.procedureFacts['crown-1']!.category).toBe('major');
  });

  it('preserves unknown balances, prices, category and policy rules without defaults', () => {
    const input = request();
    input.planA.policy!.insurerRateBpsByCategory!.major = null;
    input.planA.policy!.deductibleAppliesByCategory!.major = null;
    input.planA.policy!.annualMaximumAppliesByCategory = null;
    input.planA.policy!.deductibleBeforeCoinsurance = null;
    input.planA.policy!.allServicesCovered = null;
    input.planA.policy!.rounding = null;
    input.planA.policy!.waitingPeriods = null;
    input.planA.policy!.exclusions = null;
    input.planA.policy!.frequencyRestrictions = null;
    input.planA.planYears['py-2026']!.insurerAlreadyPaidCents = null;
    input.planA.procedureFacts['crown-1'] = { category: null, network: 'unknown', allowedCents: null, contractualWriteoffCents: null };
    input.planB.policy = null;
    input.planB.planYears = {};
    expect(PlanComparisonRequestSchema.parse(input)).toEqual(input);
    const facts = input.planA.procedureFacts['crown-1'];
    expect(PlanComparisonRequestSchema.safeParse({ ...input, planA: { ...input.planA,
      procedureFacts: { ...input.planA.procedureFacts, 'crown-1': { ...facts, allowedCents: undefined } } } }).success).toBe(false);
  });

  it('keeps existing single-plan policy validation unchanged', () => {
    const policy = request().planA.policy;
    expect(PolicySchema.safeParse(policy).success).toBe(true);
    expect(PlanComparisonPolicySchema.safeParse({ ...policy, allServicesCovered: null }).success).toBe(true);
    expect(PolicySchema.safeParse({ ...policy, allServicesCovered: null }).success).toBe(false);
  });

  it.each<[string, (input: PlanComparisonRequest) => void]>([
    ['duplicate plan identity', (i) => { i.planB.planId = i.planA.planId; }],
    ['duplicate shared procedure', (i) => { i.treatment.procedures[1] = i.treatment.procedures[0]!; }],
    ['duplicate schedule entry', (i) => { i.treatment.schedule[1] = i.treatment.schedule[0]!; }],
    ['missing schedule entry', (i) => { i.treatment.schedule.pop(); }],
    ['unknown schedule procedure', (i) => { i.treatment.schedule[0]!.procedureId = 'other'; }],
    ['missing side facts', (i) => { delete i.planA.procedureFacts['crown-1']; }],
    ['extra side facts', (i) => { i.planB.procedureFacts.other = i.planB.procedureFacts['crown-1']!; }],
    ['malformed date', (i) => { i.treatment.schedule[0]!.date = '2026-02-30'; }],
    ['missing revision value', (i) => { i.expectedRevision = 0; }],
    ['invalid rate', (i) => { i.planB.policy!.insurerRateBpsByCategory!.major = 10001; }],
  ])('rejects %s', (_name, mutate) => {
    const input = request(); mutate(input);
    expect(PlanComparisonRequestSchema.safeParse(input).success).toBe(false);
  });

  it.each([-1, 0.5, Number.NaN, Number.POSITIVE_INFINITY, MAX_CENTS + 1])('rejects invalid cents %s', (value) => {
    const input = request(); input.planA.procedureFacts['crown-1']!.allowedCents = value;
    expect(PlanComparisonRequestSchema.safeParse(input).success).toBe(false);
  });

  it('accepts an explicit zero separately from unknown', () => {
    const input = request(); input.planA.procedureFacts['crown-1']!.allowedCents = 0;
    expect(PlanComparisonRequestSchema.parse(input).planA.procedureFacts['crown-1']!.allowedCents).toBe(0);
  });

  it('rejects premiums, enrollment, result amounts and per-plan treatment/schedule overrides', () => {
    const input = request();
    for (const extras of [{ monthlyPremiumCents: 10000 }, { enroll: true }, { patientPaysCents: 0 },
      { schedule: input.treatment.schedule }, { procedures: input.treatment.procedures }]) {
      expect(PlanComparisonRequestSchema.safeParse({ ...input, planA: { ...input.planA, ...extras } }).success).toBe(false);
    }
    expect(PlanComparisonRequestSchema.safeParse({ ...input, planBMinusPlanACents: 0 }).success).toBe(false);
    expect(PlanComparisonRequestSchema.safeParse({ ...input, treatment: { ...input.treatment,
      procedures: input.treatment.procedures.map((p) => ({ ...p, allowedCents: 0 })) } }).success).toBe(false);
  });

  it('retains unsupported rules for engine review rather than treating them as covered', () => {
    const input = request(); input.planB.policy!.waitingPeriods = [{ id: 'waiting', description: 'Fictional waiting period.', categoryIds: ['major'] }];
    expect(PlanComparisonRequestSchema.parse(input)).toEqual(input);
  });
});

describe('two-plan result contracts', () => {
  it('accepts complete results with a signed patient-cost difference', () => {
    expect(PlanComparisonResultSchema.parse(result())).toEqual(result());
    const swapped = result();
    [swapped.planA, swapped.planB] = [swapped.planB, swapped.planA];
    swapped.planBMinusPlanACents = 13000;
    expect(PlanComparisonResultSchema.safeParse(swapped).success).toBe(true);
  });

  it('accepts equal costs and an explicitly unavailable difference', () => {
    const output = result(); output.planB.estimate = estimate('A'); output.planBMinusPlanACents = 0;
    expect(PlanComparisonResultSchema.safeParse(output).success).toBe(true);
    output.planBMinusPlanACents = null;
    expect(PlanComparisonResultSchema.safeParse(output).success).toBe(true);
  });

  const incomplete: EstimateResult[] = [
    { status: 'needs_information', caseRevision: 3, engineVersion: 'synthetic-contract-v1',
      missing: [{ fieldPath: 'procedureFacts.crown-1.allowedCents', code: 'VALUE_UNKNOWN', message: 'Allowed amount is unknown.' }] },
    { status: 'unsupported', caseRevision: 3, engineVersion: 'synthetic-contract-v1',
      limitations: [{ code: 'WAITING_PERIOD_UNSUPPORTED', message: 'Waiting periods are not supported.' }] },
  ];
  it.each(['planA', 'planB'] as const)('keeps %s missing/unsupported results and forbids any difference, including zero', (side) => {
    for (const estimate of incomplete) {
      const output = result(); output[side].estimate = estimate; output.planBMinusPlanACents = null;
      expect(PlanComparisonResultSchema.parse(output)).toEqual(output);
      for (const value of [-1, 0, 1]) {
        output.planBMinusPlanACents = value;
        expect(PlanComparisonResultSchema.safeParse(output).success).toBe(false);
      }
    }
  });

  it('accepts both plans incomplete without a ranking', () => {
    const output = result(); output.planA.estimate = incomplete[0]!; output.planB.estimate = incomplete[1]!; output.planBMinusPlanACents = null;
    expect(PlanComparisonResultSchema.safeParse(output).success).toBe(true);
  });

  it.each<[string, (output: PlanComparisonResult, completeEstimate: ReturnType<typeof estimate>) => void]>([
    ['stale revision', (_o, e) => { e.caseRevision = 2; }],
    ['different engine', (_o, e) => { e.engineVersion = 'other-version'; }],
    ['different schedule', (_o, e) => { e.schedule[0]!.date = '2026-11-11'; }],
    ['duplicate schedule entry', (_o, e) => { e.schedule[1] = e.schedule[0]!; }],
    ['missing schedule entry', (_o, e) => { e.schedule.pop(); }],
    ['missing cost line', (_o, e) => { e.lines.pop(); }],
    ['duplicate cost line', (_o, e) => { e.lines[1] = e.lines[0]!; }],
    ['different line date', (_o, e) => { e.lines[0]!.date = '2026-11-11'; }],
    ['different provider charge', (_o, e) => { e.lines[0]!.providerChargeCents = 99999; }],
    ['unknown shared provider charge', (o) => { o.treatment.procedures[0]!.providerChargeCents = null; }],
    ['duplicate plan identity', (o) => { o.planB.planId = o.planA.planId; }],
  ])('rejects noncomparable %s even when the difference is null', (_name, mutate) => {
    const output = result(); const complete = estimate('B'); output.planB.estimate = complete;
    mutate(output, complete);
    expect(PlanComparisonResultSchema.safeParse(output).success).toBe(false);
    output.planBMinusPlanACents = null;
    expect(PlanComparisonResultSchema.safeParse(output).success).toBe(false);
  });

  it('validates metadata on incomplete results too', () => {
    const output = result(); output.planA.estimate = { ...incomplete[0]!, caseRevision: 2 }; output.planBMinusPlanACents = null;
    expect(PlanComparisonResultSchema.safeParse(output).success).toBe(false);
  });

  it('compares procedure scope independent of ordering', () => {
    const output = result(); const complete = estimate('B'); output.planB.estimate = complete;
    complete.schedule.reverse(); complete.lines.reverse();
    expect(PlanComparisonResultSchema.safeParse(output).success).toBe(true);
  });

  it('preserves conditional assumptions with complete estimates', () => {
    const output = result(); const complete = estimate('B'); output.planB.estimate = complete;
    complete.conditional = true;
    complete.assumptions.push({ code: 'UNCHANGED_PLAN_ASSUMED', planYearId: 'py-2026', message: 'Fictional explicitly confirmed assumption.' });
    expect(PlanComparisonResultSchema.parse(output).planB.estimate).toEqual(complete);
  });

  it.each([0.5, Number.NaN, Number.POSITIVE_INFINITY, MAX_CENTS + 1, -MAX_CENTS - 1])('rejects invalid difference %s', (value) => {
    expect(PlanComparisonResultSchema.safeParse({ ...result(), planBMinusPlanACents: value }).success).toBe(false);
  });
});
