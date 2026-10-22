import {
  MAX_CENTS,
  PlanComparisonRequestSchema,
  PlanComparisonResultSchema,
  type ComparisonPlan,
  type DentalCaseInput,
  type PlanComparisonRequest,
} from '@actionbridge/contracts';
import { comparePlans, ENGINE_VERSION, estimateSchedule } from '@actionbridge/benefits-engine';
import { describe, expect, it } from 'vitest';
import { caseWith, expectEstimated, expectReconciles, fixtureCase, planYear, procedure } from './helpers.js';

/** All test inputs are fictional. Reuse existing single-plan fixtures without changing them. */
function comparison(input = fixtureCase(), other = input): PlanComparisonRequest {
  const plan = (source: DentalCaseInput, planId: string): ComparisonPlan => ({
    planId, label: `Fictional ${planId}`, policy: structuredClone(source.policy),
    planYears: structuredClone(source.planYears), sourceFacts: [],
    procedureFacts: Object.fromEntries(source.procedures.map((p) => [p.id, {
      category: p.category, network: p.network, allowedCents: p.allowedCents,
      contractualWriteoffCents: p.contractualWriteoffCents,
    }])),
  });
  return PlanComparisonRequestSchema.parse({
    caseId: 'synthetic-case', expectedRevision: input.caseRevision, currency: input.currency,
    treatment: {
      procedures: input.procedures.map((p) => {
        const { category, network, allowedCents, contractualWriteoffCents, proposedDate, selfPayQuote, ...shared } = p;
        return shared;
      }),
      schedule: input.procedures.map((p) => ({ procedureId: p.id, date: p.proposedDate ?? p.dentistEarliestDate })),
      sourceFacts: [],
    },
    planA: plan(input, 'plan-a'), planB: plan(other, 'plan-b'),
  });
}

function compared(input: PlanComparisonRequest) {
  const result = comparePlans(input);
  if ('status' in result) throw new Error(`Unexpected ${result.status}: ${JSON.stringify(result.issues)}`);
  expect(PlanComparisonResultSchema.parse(result)).toEqual(result);
  for (const plan of [result.planA, result.planB]) {
    if (plan.estimate.status === 'estimated') expectReconciles(plan.estimate);
  }
  return result;
}

function simpleCase(): DentalCaseInput {
  return caseWith([procedure({ id: 'p1' })], {
    'py-2026': planYear({ startDate: '2026-01-01', endDate: '2026-12-31', deductibleAlreadyMetCents: 5000 }),
  });
}

describe('two-plan calculation using the existing estimator', () => {
  it('matches the original regression baseline independently for both plans', () => {
    const source = fixtureCase();
    const input = comparison(source);
    const result = compared(input);
    expect(result.planA.estimate).toEqual(estimateSchedule(source, input.treatment.schedule));
    expect(result.planB.estimate).toEqual(result.planA.estimate);
    expect(result.planA.estimate).toMatchObject({ totals: { patientPaysCents: 120000, insurerPaysCents: 30000 } });
    expect(result.planBMinusPlanACents).toBe(0);
    expect(result).toMatchObject({ caseId: input.caseId, caseRevision: input.expectedRevision, engineVersion: ENGINE_VERSION });
  });

  it('uses independent balances and reverses the signed patient-pay difference when plans swap', () => {
    const input = comparison();
    input.planB.planYears['py-2026']!.insurerAlreadyPaidCents = 0;
    const result = compared(input);
    expect(result.planA.estimate).toMatchObject({ totals: { patientPaysCents: 120000 } });
    expect(result.planB.estimate).toMatchObject({ totals: { patientPaysCents: 70000 } });
    expect(result.planBMinusPlanACents).toBe(-50000);
    [input.planA, input.planB] = [input.planB, input.planA];
    expect(compared(input).planBMinusPlanACents).toBe(50000);
  });

  it('uses each plan’s category, rates, network, allowed amount and write-off without borrowing facts', () => {
    const source = simpleCase();
    Object.assign(source.procedures[0]!, { providerChargeCents: 150000, allowedCents: 100000,
      contractualWriteoffCents: 50000, category: 'major' });
    source.planYears['py-2026']!.deductibleAlreadyMetCents = 0;
    const other = structuredClone(source);
    Object.assign(other.procedures[0]!, { category: 'basic', network: 'out', allowedCents: 80000, contractualWriteoffCents: 10000 });
    const input = comparison(source, other);
    const result = compared(input);
    expect(result.planA.estimate).toEqual(estimateSchedule(source, input.treatment.schedule));
    expect(result.planB.estimate).toEqual(estimateSchedule(other, input.treatment.schedule));
    expect(result.planA.estimate).toMatchObject({ totals: { patientPaysCents: 52500, insurerPaysCents: 47500 } });
    expect(result.planB.estimate).toMatchObject({ totals: { patientPaysCents: 80000, insurerPaysCents: 60000 },
      lines: [{ balanceBillCents: 60000, allowedCents: 80000, contractualWriteoffCents: 10000, insurerRateBps: 8000 }] });
    expect(result.planBMinusPlanACents).toBe(27500);
  });

  it('applies deductibles separately', () => {
    const input = comparison(simpleCase());
    input.planA.planYears['py-2026']!.deductibleAlreadyMetCents = 0;
    const result = compared(input);
    expect(result.planA.estimate).toMatchObject({ lines: [{ deductibleAppliedCents: 5000, patientPaysCents: 6000 }] });
    expect(result.planB.estimate).toMatchObject({ lines: [{ deductibleAppliedCents: 0, patientPaysCents: 2000 }] });
    expect(result.planBMinusPlanACents).toBe(-4000);
  });

  it('keeps an exhausted maximum separate from the other plan’s remaining benefits', () => {
    const input = comparison(simpleCase());
    input.planA.planYears['py-2026']!.insurerAlreadyPaidCents = 150000;
    const result = compared(input);
    expect(result.planA.estimate).toMatchObject({ totals: { patientPaysCents: 10000, insurerPaysCents: 0 } });
    expect(result.planB.estimate).toMatchObject({ totals: { patientPaysCents: 2000, insurerPaysCents: 8000 } });
    expect(result.planBMinusPlanACents).toBe(-8000);
  });

  it('keeps the fixed schedule across independently keyed, noncalendar benefit years', () => {
    const input = comparison(simpleCase());
    input.planB.planYears = { 'benefit-july': planYear({ startDate: '2025-07-01', endDate: '2026-06-30', deductibleAlreadyMetCents: 5000 }) };
    const result = compared(input);
    expect(result.planA.estimate).toMatchObject({ lines: [{ planYearId: 'py-2026' }] });
    expect(result.planB.estimate).toMatchObject({ lines: [{ planYearId: 'benefit-july' }] });
    expect(result.planBMinusPlanACents).toBe(0);
    for (const side of [result.planA, result.planB]) {
      expectEstimated(side.estimate);
      expect(side.estimate.schedule).toEqual(input.treatment.schedule);
    }
  });

  it('retains conditional assumptions for an explicitly selected permitted schedule', () => {
    const input = comparison();
    input.treatment.schedule.find((entry) => entry.procedureId === 'crown-1')!.date = '2027-01-01';
    input.planB.planYears['py-2027']!.sourceStatus = 'user_confirmed';
    const result = compared(input);
    expect(result.planA.estimate).toMatchObject({ conditional: true, totals: { patientPaysCents: 72500 },
      assumptions: expect.arrayContaining([expect.objectContaining({ code: 'UNCHANGED_PLAN_ASSUMED' })]) });
    expect(result.planB.estimate).toMatchObject({ conditional: false, totals: { patientPaysCents: 72500 } });
    expect(result.planBMinusPlanACents).toBe(0);
  });
});

describe('missing information remains local to each plan', () => {
  it.each(['planA', 'planB'] as const)('preserves a missing %s policy and the other estimate', (side) => {
    const input = comparison(); input[side].policy = null;
    const result = compared(input);
    expect(result[side].estimate).toMatchObject({ status: 'needs_information', missing: [{ fieldPath: 'policy', code: 'POLICY_NOT_SUPPLIED' }] });
    expect(result[side === 'planA' ? 'planB' : 'planA'].estimate.status).toBe('estimated');
    expect(result.planBMinusPlanACents).toBeNull();
  });

  it.each([
    'deductibleBeforeCoinsurance', 'allServicesCovered', 'rounding',
    'waitingPeriods', 'exclusions', 'frequencyRestrictions',
    'deductibleAppliesByCategory', 'insurerRateBpsByCategory', 'annualMaximumAppliesByCategory',
  ] as const)('asks for unknown policy.%s instead of assuming a supported rule', (field) => {
    const input = comparison(); input.planB.policy![field] = null;
    const result = compared(input);
    expect(result.planB.estimate).toMatchObject({ status: 'needs_information',
      missing: expect.arrayContaining([expect.objectContaining({ fieldPath: `policy.${field}`, code: 'VALUE_UNKNOWN' })]) });
    expect(result.planA.estimate.status).toBe('estimated');
    expect(result.planBMinusPlanACents).toBeNull();
  });

  it.each(['deductibleAppliesByCategory', 'insurerRateBpsByCategory', 'annualMaximumAppliesByCategory'] as const)('asks once for a nullable used category rule in %s', (field) => {
    const input = comparison(); input.planB.policy![field]!.basic = null;
    const result = compared(input);
    expect(result.planB.estimate).toMatchObject({ status: 'needs_information',
      missing: [{ fieldPath: `policy.${field}.basic`, code: 'POLICY_CATEGORY_RULE_MISSING' }] });
    expect(result.planBMinusPlanACents).toBeNull();
  });

  it.each(['category', 'allowedCents', 'contractualWriteoffCents'] as const)('does not reuse Plan A’s %s when Plan B is unknown', (field) => {
    const input = comparison(); input.planB.procedureFacts['crown-1']![field] = null;
    const result = compared(input);
    expect(result.planB.estimate).toMatchObject({ status: 'needs_information',
      missing: [{ fieldPath: `procedureFacts.crown-1.${field}`, code: 'VALUE_UNKNOWN' }] });
    expect(result.planBMinusPlanACents).toBeNull();
  });

  it('does not reuse Plan A’s network status for Plan B', () => {
    const input = comparison(); input.planB.procedureFacts['crown-1']!.network = 'unknown';
    const result = compared(input);
    expect(result.planB.estimate).toMatchObject({ status: 'needs_information',
      missing: [{ fieldPath: 'procedureFacts.crown-1.network', code: 'NETWORK_UNKNOWN' }] });
    expect(result.planBMinusPlanACents).toBeNull();
  });

  it.each(['annualMaximumCents', 'insurerAlreadyPaidCents', 'annualDeductibleCents', 'deductibleAlreadyMetCents'] as const)('does not default an unknown %s balance to zero', (field) => {
    const input = comparison(); input.planB.planYears['py-2026']![field] = null;
    const result = compared(input);
    expect(result.planB.estimate).toMatchObject({ status: 'needs_information',
      missing: [{ fieldPath: `planYears.py-2026.${field}`, code: 'VALUE_UNKNOWN' }] });
    expect(result.planBMinusPlanACents).toBeNull();
  });

  it('requires supplied benefit periods rather than guessing calendar years', () => {
    const input = comparison(); input.planB.planYears = {};
    expect(compared(input).planB.estimate).toMatchObject({ status: 'needs_information', missing: [{ code: 'PLAN_YEAR_NOT_SUPPLIED' }] });
  });

  it('returns both plans incomplete for an unknown shared charge', () => {
    const input = comparison(); input.treatment.procedures[0]!.providerChargeCents = null;
    const result = compared(input);
    for (const plan of [result.planA, result.planB]) {
      expect(plan.estimate).toMatchObject({ status: 'needs_information',
        missing: [{ fieldPath: 'treatment.procedures.filling-1.providerChargeCents', code: 'VALUE_UNKNOWN' }] });
    }
    expect(result.planBMinusPlanACents).toBeNull();
  });

  it('does not require unused category rules or unused year balances', () => {
    const input = comparison();
    input.planB.policy!.insurerRateBpsByCategory!.unused = null;
    input.planB.policy!.deductibleAppliesByCategory!.unused = null;
    input.planB.policy!.annualMaximumAppliesByCategory!.unused = null;
    input.planB.planYears['py-2027']!.annualMaximumCents = null;
    expect(compared(input).planBMinusPlanACents).toBe(0);
  });
});

describe('unsupported and contradictory comparison inputs', () => {
  it.each([
    ['waitingPeriods', 'WAITING_PERIOD_UNSUPPORTED'],
    ['exclusions', 'EXCLUSION_UNSUPPORTED'],
    ['frequencyRestrictions', 'FREQUENCY_RESTRICTION_UNSUPPORTED'],
  ] as const)('preserves unsupported %s and the complete other plan', (field, code) => {
    const input = comparison();
    input.planB.policy![field] = [{ id: 'restriction', description: 'Fictional rule.', categoryIds: ['major'] }];
    input.planB.policy!.rounding = null;
    const result = compared(input);
    expect(result.planA.estimate.status).toBe('estimated');
    expect(result.planB.estimate).toMatchObject({ status: 'unsupported', limitations: [{ code, fieldPath: `policy.${field}` }] });
    expect(result.planBMinusPlanACents).toBeNull();
  });

  it.each([
    ['deductibleBeforeCoinsurance', 'DEDUCTIBLE_AFTER_COINSURANCE_UNSUPPORTED'],
    ['allServicesCovered', 'PARTIAL_COVERAGE_UNSUPPORTED'],
  ] as const)('preserves a known unsupported %s rule', (field, code) => {
    const input = comparison(); input.planB.policy![field] = false;
    expect(compared(input).planB.estimate).toMatchObject({ status: 'unsupported', limitations: [{ code }] });
  });

  it('preserves the absent-category unsupported rule rather than copying a category from Plan A', () => {
    const input = comparison(); input.planB.procedureFacts['crown-1']!.category = 'unlisted';
    const result = compared(input);
    expect(result.planB.estimate).toMatchObject({ status: 'unsupported', limitations: [{
      code: 'CATEGORY_NOT_IN_POLICY', fieldPath: 'procedureFacts.crown-1.category', procedureId: 'crown-1',
    }] });
    expect(result.planBMinusPlanACents).toBeNull();
  });

  it('reports the existing six-procedure limit without comparing incomplete totals', () => {
    const input = comparison(caseWith(Array.from({ length: 7 }, (_, n) => procedure({ id: `p${n}`, proposedDate: '2026-11-10' }))));
    const result = compared(input);
    for (const plan of [result.planA, result.planB]) {
      expect(plan.estimate).toMatchObject({ status: 'unsupported', limitations: [{ code: 'TOO_MANY_PROCEDURES', fieldPath: 'treatment.procedures' }] });
    }
    expect(result.planBMinusPlanACents).toBeNull();
  });

  it.each<[string, (input: PlanComparisonRequest) => void, string, string]>([
    ['allowed above charge', (i) => { i.planB.procedureFacts['crown-1']!.allowedCents = 120000; }, 'ALLOWED_EXCEEDS_CHARGE', 'planB.procedureFacts.crown-1.allowedCents'],
    ['excess write-off', (i) => { i.planB.procedureFacts['crown-1']!.contractualWriteoffCents = 1; }, 'WRITEOFF_EXCEEDS_CHARGE_MINUS_ALLOWED', 'planB.procedureFacts.crown-1.contractualWriteoffCents'],
    ['excess met deductible', (i) => { i.planB.planYears['py-2026']!.deductibleAlreadyMetCents = 5001; }, 'DEDUCTIBLE_MET_EXCEEDS_DEDUCTIBLE', 'planB.planYears.py-2026.deductibleAlreadyMetCents'],
    ['overlapping years', (i) => { i.planB.planYears['py-2027']!.startDate = '2026-12-01'; }, 'PLAN_YEARS_OVERLAP', 'planB.planYears.py-2027.startDate'],
    ['shared date outside dentist window', (i) => { i.treatment.schedule[2]!.date = '2027-02-01'; }, 'PROPOSED_DATE_OUTSIDE_WINDOW', 'treatment.schedule.crown-1.date'],
    ['shared dependency cycle', (i) => { i.treatment.procedures[0]!.prerequisiteIds = ['filling-2']; i.treatment.procedures[1]!.prerequisiteIds = ['filling-1']; }, 'DEPENDENCY_CYCLE', 'treatment.procedures'],
  ])('rejects %s using the existing invalid-result convention', (_name, mutate, code, fieldPath) => {
    const input = comparison(); mutate(input);
    input.planB.policy!.rounding = null;
    const result = comparePlans(input);
    expect(result).toMatchObject({ status: 'invalid', issues: expect.arrayContaining([expect.objectContaining({ code, fieldPath })]) });
    expect(result).not.toHaveProperty('planBMinusPlanACents');
  });

  it('rejects duplicate plan IDs and missing facts before constructing an engine input', () => {
    const input = comparison(); input.planB.planId = input.planA.planId;
    expect(comparePlans(input)).toMatchObject({ status: 'invalid', issues: [{ fieldPath: 'planB.planId', code: 'INVALID_COMPARISON_INPUT' }] });
    input.planB.planId = 'plan-b'; delete input.planB.procedureFacts['crown-1'];
    expect(comparePlans(input)).toMatchObject({ status: 'invalid', issues: [{ fieldPath: 'planB.procedureFacts', code: 'INVALID_COMPARISON_INPUT' }] });
  });
});

describe('integer boundaries and purity', () => {
  it('reuses half-up rounding at a one-cent boundary', () => {
    const source = simpleCase();
    Object.assign(source.procedures[0]!, { providerChargeCents: 1, allowedCents: 1 });
    const input = comparison(source);
    input.planA.policy!.insurerRateBpsByCategory!.basic = 5000;
    input.planB.policy!.insurerRateBpsByCategory!.basic = 4999;
    const result = compared(input);
    expect(result.planA.estimate).toMatchObject({ totals: { patientPaysCents: 0, insurerPaysCents: 1 } });
    expect(result.planB.estimate).toMatchObject({ totals: { patientPaysCents: 1, insurerPaysCents: 0 } });
    expect(result.planBMinusPlanACents).toBe(1);
  });

  it('distinguishes explicit zero prices, deductible and maximum from unknown values', () => {
    const source = simpleCase();
    Object.assign(source.procedures[0]!, { providerChargeCents: 0, allowedCents: 0 });
    Object.assign(source.planYears['py-2026']!, { annualMaximumCents: 0, annualDeductibleCents: 0, deductibleAlreadyMetCents: 0 });
    const result = compared(comparison(source));
    expect(result.planBMinusPlanACents).toBe(0);
    expect(result.planA.estimate).toMatchObject({ totals: { patientPaysCents: 0, insurerPaysCents: 0 } });
  });

  it('supports the maximum contract amount without fractional arithmetic', () => {
    const source = simpleCase();
    Object.assign(source.procedures[0]!, { providerChargeCents: MAX_CENTS, allowedCents: MAX_CENTS });
    Object.assign(source.planYears['py-2026']!, { annualMaximumCents: MAX_CENTS, annualDeductibleCents: 0, deductibleAlreadyMetCents: 0 });
    const input = comparison(source);
    input.planA.policy!.insurerRateBpsByCategory!.basic = 0;
    input.planB.policy!.insurerRateBpsByCategory!.basic = 10000;
    expect(compared(input).planBMinusPlanACents).toBe(-MAX_CENTS);
  });

  it('rejects aggregate amounts beyond the response contract without clamping or a cost ranking', () => {
    const source = simpleCase();
    Object.assign(source.procedures[0]!, { providerChargeCents: MAX_CENTS, allowedCents: MAX_CENTS });
    source.procedures.push(procedure({ id: 'p2', providerChargeCents: 1, allowedCents: 1 }));
    const result = comparePlans(comparison(source));
    expect(result).toMatchObject({ status: 'invalid', issues: expect.arrayContaining([expect.objectContaining({
      fieldPath: 'planA.estimate.totals.providerChargeCents', code: 'INVALID_COMPARISON_RESULT',
    })]) });
    expect(result).not.toHaveProperty('planBMinusPlanACents');
  });

  it('is deterministic and does not mutate frozen inputs or reported benefit usage', () => {
    const input = comparison(); const snapshot = structuredClone(input);
    const freeze = (value: unknown): void => {
      if (value !== null && typeof value === 'object') {
        Object.values(value).forEach(freeze); Object.freeze(value);
      }
    };
    freeze(input);
    expect(compared(input)).toEqual(compared(input));
    expect(input).toEqual(snapshot);
  });
});
