import {
  ErrorEnvelopeSchema,
  PlanComparisonResultSchema,
  type ComparisonPlan,
  type CreateCaseRequest,
  type PlanComparisonRequest,
  type SourceFact,
} from '@actionbridge/contracts';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createTestApi, fixtureCreateRequest, MAYA, OTHER, type TestApi } from './helpers.js';

const CREATE = 'POST /v1/cases';
const GET = 'GET /v1/cases/{caseId}';
const COMPARE = 'POST /v1/cases/{caseId}/plan-comparison';

/** All inputs are fictional; each candidate gets its own independent plan facts. */
function comparisonRequest(caseId: string, input: CreateCaseRequest): PlanComparisonRequest {
  const plan = (planId: string): ComparisonPlan => ({
    planId,
    label: `Fictional ${planId}`,
    policy: structuredClone(input.policy),
    planYears: structuredClone(input.planYears),
    procedureFacts: Object.fromEntries(input.procedures.map((procedure) => [procedure.id, {
      category: procedure.category,
      network: procedure.network,
      allowedCents: procedure.allowedCents,
      contractualWriteoffCents: procedure.contractualWriteoffCents,
    }])),
    sourceFacts: [],
  });
  return {
    caseId,
    expectedRevision: 1,
    currency: input.currency,
    treatment: {
      procedures: input.procedures.map((procedure) => {
        const { category, network, allowedCents, contractualWriteoffCents, proposedDate, selfPayQuote, ...shared } = procedure;
        return shared;
      }),
      schedule: input.procedures.map((procedure) => ({
        procedureId: procedure.id,
        date: (procedure.proposedDate ?? procedure.dentistEarliestDate)!,
      })),
      sourceFacts: [],
    },
    planA: plan('plan-a'),
    planB: plan('plan-b'),
  };
}

async function createComparison(api: TestApi, input = fixtureCreateRequest()) {
  const created = await api.call(CREATE, { body: input });
  expect(created.status).toBe(201);
  const caseId = created.body.caseId as string;
  return { caseId, request: comparisonRequest(caseId, input) };
}

function expectError(response: Awaited<ReturnType<TestApi['call']>>, status: number, code: string) {
  expect(response.status).toBe(status);
  const { error } = ErrorEnvelopeSchema.parse(response.body);
  expect(error.code).toBe(code);
  expect(response.headers['x-request-id']).toBe(error.requestId);
  expect(response.headers['cache-control']).toBe('no-store');
  return error;
}

function sharedFact(): SourceFact {
  return {
    id: 'shared-charge',
    fieldPath: 'procedures.filling-1.providerChargeCents',
    value: fixtureCreateRequest().procedures[0]!.providerChargeCents,
    sourceId: null,
    location: null,
    origin: 'synthetic',
    extractionStatus: 'not_applicable',
    userConfirmed: true,
    insurerVerification: { status: 'not_verified' },
    conflict: false,
    recordedAt: '2026-10-03T15:00:00.000Z',
  };
}

afterEach(() => vi.restoreAllMocks());

describe('read-only two-plan comparison API', () => {
  it('returns independent authoritative estimates and a signed patient-pay difference', async () => {
    const api = createTestApi();
    const { caseId, request } = await createComparison(api);
    request.planB.planYears['py-2026']!.insurerAlreadyPaidCents = 0;

    const response = await api.call(COMPARE, { caseId, body: request });
    expect(response.status).toBe(200);
    const result = PlanComparisonResultSchema.parse(response.body);
    expect(result).toMatchObject({
      caseId,
      caseRevision: 1,
      planA: { planId: 'plan-a', estimate: { status: 'estimated', totals: { patientPaysCents: 120000 } } },
      planB: { planId: 'plan-b', estimate: { status: 'estimated', totals: { patientPaysCents: 70000 } } },
      planBMinusPlanACents: -50000,
    });
    expect(result.treatment.schedule).toEqual(request.treatment.schedule);
    expect(response.headers['cache-control']).toBe('no-store');
  });

  it('returns zero for equal costs and accepts equivalent procedure/schedule ordering', async () => {
    const api = createTestApi();
    const { caseId, request } = await createComparison(api);
    const canonicalProcedures = structuredClone(request.treatment.procedures);
    const canonicalSchedule = structuredClone(request.treatment.schedule);
    request.treatment.procedures.reverse();
    request.treatment.schedule.reverse();

    const response = await api.call(COMPARE, { caseId, body: request });
    expect(response.status).toBe(200);
    expect(PlanComparisonResultSchema.parse(response.body)).toMatchObject({
      treatment: { procedures: canonicalProcedures, schedule: canonicalSchedule },
      planBMinusPlanACents: 0,
    });
  });

  it('uses Plan B category, network, allowed amount and write-off independently', async () => {
    const api = createTestApi();
    const { caseId, request } = await createComparison(api);
    const originalFacts = structuredClone(request.planA.procedureFacts['crown-1']!);
    request.planB.procedureFacts['crown-1'] = {
      category: 'basic', network: 'out', allowedCents: 50000, contractualWriteoffCents: 10000,
    };
    // Give both plans ample benefits so the category/rate and negotiated prices remain visible.
    for (const plan of [request.planA, request.planB]) {
      plan.planYears['py-2026']!.insurerAlreadyPaidCents = 0;
    }

    const response = await api.call(COMPARE, { caseId, body: request });
    expect(response.status).toBe(200);
    const result = PlanComparisonResultSchema.parse(response.body);
    expect(result.planA.estimate.status).toBe('estimated');
    expect(result.planB.estimate.status).toBe('estimated');
    if (result.planA.estimate.status !== 'estimated' || result.planB.estimate.status !== 'estimated') return;
    const crownA = result.planA.estimate.lines.find((line) => line.procedureId === 'crown-1');
    const crownB = result.planB.estimate.lines.find((line) => line.procedureId === 'crown-1');
    expect(crownA).toMatchObject({
      allowedCents: originalFacts.allowedCents, contractualWriteoffCents: originalFacts.contractualWriteoffCents,
      insurerRateBps: request.planA.policy!.insurerRateBpsByCategory![originalFacts.category!],
    });
    expect(crownB).toMatchObject({
      allowedCents: 50000, contractualWriteoffCents: 10000,
      insurerRateBps: request.planB.policy!.insurerRateBpsByCategory!.basic,
    });
    expect(crownB!.balanceBillCents).toBeGreaterThan(0);
    expect(result.planBMinusPlanACents).toBe(result.planB.estimate.totals.patientPaysCents - result.planA.estimate.totals.patientPaysCents);
  });

  it.each(['planA', 'planB'] as const)('keeps a missing %s policy local to that plan', async (side) => {
    const api = createTestApi();
    const { caseId, request } = await createComparison(api);
    request[side].policy = null;

    const response = await api.call(COMPARE, { caseId, body: request });
    expect(response.status).toBe(200);
    const result = PlanComparisonResultSchema.parse(response.body);
    expect(result[side].estimate).toMatchObject({ status: 'needs_information', missing: [{ fieldPath: 'policy' }] });
    expect(result[side === 'planA' ? 'planB' : 'planA'].estimate.status).toBe('estimated');
    expect(result.planBMinusPlanACents).toBeNull();
  });

  it.each(['category', 'allowedCents', 'contractualWriteoffCents'] as const)(
    'never borrows Plan A %s when Plan B is unknown',
    async (field) => {
      const api = createTestApi();
      const { caseId, request } = await createComparison(api);
      request.planB.procedureFacts['crown-1']![field] = null;

      const response = await api.call(COMPARE, { caseId, body: request });
      expect(response.status).toBe(200);
      const result = PlanComparisonResultSchema.parse(response.body);
      expect(result.planA.estimate.status).toBe('estimated');
      expect(result.planB.estimate).toMatchObject({
        status: 'needs_information', missing: [{ fieldPath: `procedureFacts.crown-1.${field}` }],
      });
      expect(result.planBMinusPlanACents).toBeNull();
    },
  );

  it('never borrows Plan A network status when Plan B network is unknown', async () => {
    const api = createTestApi();
    const { caseId, request } = await createComparison(api);
    request.planB.procedureFacts['crown-1']!.network = 'unknown';

    const response = await api.call(COMPARE, { caseId, body: request });
    expect(response.status).toBe(200);
    const result = PlanComparisonResultSchema.parse(response.body);
    expect(result.planA.estimate.status).toBe('estimated');
    expect(result.planB.estimate).toMatchObject({
      status: 'needs_information', missing: [{ fieldPath: 'procedureFacts.crown-1.network' }],
    });
    expect(result.planBMinusPlanACents).toBeNull();
  });

  it('retains unsupported rules on one side without suppressing the other estimate', async () => {
    const api = createTestApi();
    const { caseId, request } = await createComparison(api);
    request.planB.policy!.exclusions!.push({ id: 'excluded-major', description: 'Fictional restriction', categoryIds: ['major'] });

    const response = await api.call(COMPARE, { caseId, body: request });
    expect(response.status).toBe(200);
    expect(PlanComparisonResultSchema.parse(response.body)).toMatchObject({
      planA: { estimate: { status: 'estimated' } },
      planB: { estimate: { status: 'unsupported', limitations: [{ code: 'EXCLUSION_UNSUPPORTED' }] } },
      planBMinusPlanACents: null,
    });
  });

  it('returns side-qualified 422 issues for contradictory candidate facts', async () => {
    const api = createTestApi();
    const { caseId, request } = await createComparison(api);
    request.planB.procedureFacts['crown-1']!.allowedCents = 999999;

    const error = expectError(await api.call(COMPARE, { caseId, body: request }), 422, 'INCONSISTENT_INPUT');
    expect(error.issues).toEqual(expect.arrayContaining([
      expect.objectContaining({ fieldPath: 'planB.procedureFacts.crown-1.allowedCents', code: 'ALLOWED_EXCEEDS_CHARGE' }),
    ]));
  });

  it('allows candidate plans when the original case policy is missing', async () => {
    const api = createTestApi();
    const candidates = fixtureCreateRequest();
    const original = structuredClone(candidates);
    original.policy = null;
    const { caseId } = await createComparison(api, original);

    const response = await api.call(COMPARE, { caseId, body: comparisonRequest(caseId, candidates) });
    expect(response.status).toBe(200);
    expect(PlanComparisonResultSchema.parse(response.body)).toMatchObject({
      planA: { estimate: { status: 'estimated' } }, planB: { estimate: { status: 'estimated' } }, planBMinusPlanACents: 0,
    });
  });

  it('preserves a missing shared charge as missing for both plans', async () => {
    const api = createTestApi();
    const input = fixtureCreateRequest();
    input.procedures[0]!.providerChargeCents = null;
    const { caseId, request } = await createComparison(api, input);

    const response = await api.call(COMPARE, { caseId, body: request });
    expect(response.status).toBe(200);
    const result = PlanComparisonResultSchema.parse(response.body);
    for (const side of [result.planA, result.planB]) {
      expect(side.estimate).toMatchObject({ status: 'needs_information' });
    }
    expect(result.planBMinusPlanACents).toBeNull();
  });

  it('does not write a case, strategy, idempotency record or ledger event', async () => {
    const api = createTestApi();
    const { caseId, request } = await createComparison(api);
    const beforeCase = await api.call(GET, { caseId });
    const beforeLedger = await api.call('GET /v1/cases/{caseId}/ledger', { caseId });
    const beforeStrategies = await api.call('GET /v1/cases/{caseId}/strategies', { caseId });
    const create = vi.spyOn(api.store, 'create');
    const replace = vi.spyOn(api.store, 'replace');
    const save = vi.spyOn(api.store, 'save');

    expect((await api.call(COMPARE, { caseId, body: request })).status).toBe(200);
    request.planB.policy = null;
    expect((await api.call(COMPARE, { caseId, body: request })).status).toBe(200);
    request.planA.procedureFacts['crown-1']!.allowedCents = 999999;
    expect((await api.call(COMPARE, { caseId, body: request })).status).toBe(422);

    expect(create).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
    expect(save).not.toHaveBeenCalled();
    expect((await api.call(GET, { caseId })).body).toEqual(beforeCase.body);
    expect((await api.call('GET /v1/cases/{caseId}/ledger', { caseId })).body).toEqual(beforeLedger.body);
    expect((await api.call('GET /v1/cases/{caseId}/strategies', { caseId })).body).toEqual(beforeStrategies.body);
    expect(await api.store.findByIdempotencyKey(`demo:${MAYA}`, caseId, 'unused-comparison-key')).toBeNull();
  });
});

describe('comparison request validation and canonical treatment', () => {
  it.each([undefined, '{not json'])('rejects missing or malformed JSON bodies', async (rawBody) => {
    const api = createTestApi();
    const { caseId } = await createComparison(api);
    const response = await api.call(COMPARE, { caseId, ...(rawBody === undefined ? {} : { rawBody }) });
    expectError(response, 400, 'BAD_REQUEST');
  });

  it('rejects omitted plan facts instead of treating them as explicit unknown values', async () => {
    const api = createTestApi();
    const { caseId, request } = await createComparison(api);
    const body = JSON.parse(JSON.stringify(request));
    delete body.planB.procedureFacts['crown-1'].allowedCents;
    expectError(await api.call(COMPARE, { caseId, body }), 400, 'BAD_REQUEST');
  });

  it.each([
    (request: PlanComparisonRequest) => { request.planB.planId = request.planA.planId; },
    (request: PlanComparisonRequest) => { request.planB.procedureFacts = {}; },
    (request: PlanComparisonRequest) => { request.planB.procedureFacts['crown-1']!.allowedCents = -1; },
    (request: PlanComparisonRequest) => { request.planB.procedureFacts['crown-1']!.allowedCents = 1.5; },
  ])('rejects invalid plan identity, incomplete maps and non-cent amounts (%#)', async (mutate) => {
    const api = createTestApi();
    const { caseId, request } = await createComparison(api);
    mutate(request);
    expectError(await api.call(COMPARE, { caseId, body: request }), 400, 'BAD_REQUEST');
  });

  it('rejects premiums and client-supplied comparison results', async () => {
    const api = createTestApi();
    const { caseId, request } = await createComparison(api);
    expectError(await api.call(COMPARE, { caseId, body: { ...request, monthlyPremiumCents: 5000 } }), 400, 'BAD_REQUEST');
    expectError(await api.call(COMPARE, { caseId, body: { ...request, planBMinusPlanACents: 1 } }), 400, 'BAD_REQUEST');
  });

  it('rejects disagreement between the path and body case IDs', async () => {
    const api = createTestApi();
    const { caseId, request } = await createComparison(api);
    request.caseId = 'another-case';
    expectError(await api.call(COMPARE, { caseId, body: request }), 400, 'BAD_REQUEST');
  });

  it.each([
    (request: PlanComparisonRequest) => { request.treatment.procedures[0]!.label = 'Changed treatment'; },
    (request: PlanComparisonRequest) => { request.treatment.procedures[0]!.providerChargeCents = 1; },
    (request: PlanComparisonRequest) => { request.treatment.procedures[0]!.timingSource = 'unknown'; },
    (request: PlanComparisonRequest) => { request.treatment.procedures[0]!.prerequisiteIds = ['crown-1']; },
    (request: PlanComparisonRequest) => { request.treatment.schedule[0]!.date = '2026-11-01'; },
  ])('rejects submitted treatment or schedule changes absent from the case revision (%#)', async (mutate) => {
    const api = createTestApi();
    const { caseId, request } = await createComparison(api);
    mutate(request);
    expectError(await api.call(COMPARE, { caseId, body: request }), 422, 'INCONSISTENT_INPUT');
  });

  it('rejects an unconfirmed schedule when the stored case has no baseline date', async () => {
    const api = createTestApi();
    const input = fixtureCreateRequest();
    input.procedures[0]!.proposedDate = null;
    input.procedures[0]!.dentistEarliestDate = null;
    const created = await api.call(CREATE, { body: input });
    expect(created.status).toBe(201);
    const caseId = created.body.caseId as string;
    const request = comparisonRequest(caseId, input);
    request.treatment.schedule[0]!.date = '2026-10-20';
    expectError(await api.call(COMPARE, { caseId, body: request }), 422, 'INCONSISTENT_INPUT');
  });

  it('preserves stored shared provenance and rejects fabricated or altered evidence', async () => {
    const api = createTestApi();
    const input = fixtureCreateRequest();
    input.sourceFacts = [sharedFact()];
    const { caseId, request } = await createComparison(api, input);
    request.treatment.sourceFacts = structuredClone(input.sourceFacts);
    const response = await api.call(COMPARE, { caseId, body: request });
    expect(response.status).toBe(200);
    expect(PlanComparisonResultSchema.parse(response.body).treatment.sourceFacts).toEqual(input.sourceFacts);

    request.treatment.sourceFacts[0]!.insurerVerification = {
      status: 'verified', reference: 'invented-reference', verifiedAt: '2026-10-03T15:00:00.000Z',
    };
    expectError(await api.call(COMPARE, { caseId, body: request }), 422, 'INCONSISTENT_INPUT');
    request.treatment.sourceFacts = [];
    expectError(await api.call(COMPARE, { caseId, body: request }), 422, 'INCONSISTENT_INPUT');
  });

  it('does not treat stored plan-specific evidence as shared treatment evidence', async () => {
    const api = createTestApi();
    const input = fixtureCreateRequest();
    input.sourceFacts = [
      sharedFact(),
      { ...sharedFact(), id: 'original-allowed', fieldPath: 'procedures.filling-1.allowedCents', value: 12345 },
      { ...sharedFact(), id: 'original-rate', fieldPath: 'policy.insurerRateBpsByCategory.basic', value: 8000 },
    ];
    const { caseId, request } = await createComparison(api, input);
    request.treatment.sourceFacts = [sharedFact()];
    const response = await api.call(COMPARE, { caseId, body: request });
    expect(response.status).toBe(200);
    expect(PlanComparisonResultSchema.parse(response.body).treatment.sourceFacts).toEqual([sharedFact()]);
  });
});

describe('comparison authentication, ownership and revision checks', () => {
  it('requires authentication before processing comparison inputs', async () => {
    const api = createTestApi();
    const { caseId, request } = await createComparison(api);
    expectError(await api.call(COMPARE, { caseId, body: request, user: null }), 401, 'UNAUTHENTICATED');
  });

  it('does not disclose another owner’s case or a nonexistent case', async () => {
    const api = createTestApi();
    const { caseId, request } = await createComparison(api);
    expectError(await api.call(COMPARE, { caseId, body: request, user: OTHER }), 404, 'NOT_FOUND');
    request.caseId = 'case-not-found';
    expectError(await api.call(COMPARE, { caseId: request.caseId, body: request }), 404, 'NOT_FOUND');
  });

  it('uses JWT ownership and never accepts a demo header as JWT authentication', async () => {
    const api = createTestApi({ authMode: 'jwt' });
    const input = fixtureCreateRequest();
    const created = await api.call(CREATE, { body: input, claims: { sub: 'comparison-owner' } });
    expect(created.status).toBe(201);
    const caseId = created.body.caseId as string;
    const request = comparisonRequest(caseId, input);

    expectError(await api.call(COMPARE, { caseId, body: request }), 401, 'UNAUTHENTICATED');
    expectError(await api.call(COMPARE, {
      caseId, body: request, claims: { sub: 'other-owner' }, headers: { 'x-demo-user-id': MAYA },
    }), 404, 'NOT_FOUND');
    const response = await api.call(COMPARE, { caseId, body: request, claims: { sub: 'comparison-owner' } });
    expect(response.status).toBe(200);
    expect(PlanComparisonResultSchema.parse(response.body).caseId).toBe(caseId);
  });

  it('rejects stale revisions before trusting submitted treatment changes', async () => {
    const api = createTestApi();
    const { caseId, request } = await createComparison(api);
    const updated = await api.call('PATCH /v1/cases/{caseId}', {
      caseId, body: { expectedRevision: 1, changes: { policy: null } },
    });
    expect(updated.status).toBe(200);
    request.treatment.procedures[0]!.label = 'Stale altered treatment';
    expectError(await api.call(COMPARE, { caseId, body: request }), 409, 'REVISION_CONFLICT');
  });
});
