import { readFileSync } from 'node:fs';
import {
  ErrorEnvelopeSchema,
  PlanComparisonListSchema,
  SavedPlanComparisonSchema,
  SavePlanComparisonResponseSchema,
  type ComparisonPlan,
  type CreateCaseRequest,
  type PlanComparisonRequest,
} from '@actionbridge/contracts';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createTestApi, fixtureCreateRequest, MAYA, OTHER, type TestApi } from './helpers.js';

const SAVE = 'POST /v1/cases/{caseId}/plan-comparisons';
const LIST = 'GET /v1/cases/{caseId}/plan-comparisons';
const GET = 'GET /v1/cases/{caseId}/plan-comparisons/{comparisonId}';
const HEADERS = { 'idempotency-key': 'comparison-save-0001' };
const QUERY = { expectedRevision: '1' };

function comparisonRequest(caseId: string, input: CreateCaseRequest): PlanComparisonRequest {
  const plan = (planId: string): ComparisonPlan => ({
    planId, label: `Fictional ${planId}`, policy: structuredClone(input.policy), planYears: structuredClone(input.planYears),
    procedureFacts: Object.fromEntries(input.procedures.map((procedure) => [procedure.id, {
      category: procedure.category, network: procedure.network, allowedCents: procedure.allowedCents, contractualWriteoffCents: procedure.contractualWriteoffCents,
    }])), sourceFacts: [],
  });
  return {
    caseId, expectedRevision: 1, currency: input.currency,
    treatment: {
      procedures: input.procedures.map((procedure) => {
        const { category, network, allowedCents, contractualWriteoffCents, proposedDate, selfPayQuote, ...shared } = procedure;
        return shared;
      }),
      schedule: input.procedures.map((procedure) => ({ procedureId: procedure.id, date: (procedure.proposedDate ?? procedure.dentistEarliestDate)! })),
      sourceFacts: [],
    },
    planA: plan('plan-a'), planB: plan('plan-b'),
  };
}

async function setup(api: TestApi, claims?: Record<string, unknown>) {
  const input = fixtureCreateRequest();
  const created = await api.call('POST /v1/cases', { body: input, ...(claims ? { claims } : {}) });
  expect(created.status).toBe(201);
  const caseId = created.body.caseId as string;
  return { caseId, request: comparisonRequest(caseId, input) };
}

function error(response: Awaited<ReturnType<TestApi['call']>>, status: number, code: string) {
  expect(response.status).toBe(status);
  const parsed = ErrorEnvelopeSchema.parse(response.body).error;
  expect(parsed.code).toBe(code);
  expect(response.headers['cache-control']).toBe('no-store');
  return parsed;
}

afterEach(() => vi.restoreAllMocks());

describe('secure saved two-plan comparisons', () => {
  it('saves authoritative results, lists metadata only, and reads an immutable snapshot', async () => {
    const api = createTestApi();
    const { caseId, request } = await setup(api);
    request.planB.planYears['py-2026']!.insurerAlreadyPaidCents = 0;
    const first = await api.call(SAVE, { caseId, headers: HEADERS, body: { comparison: request, consent: true } });
    expect(first.status).toBe(201);
    const { comparison, replayed } = SavePlanComparisonResponseSchema.parse(first.body);
    expect(replayed).toBe(false);
    expect(comparison.request).toEqual(request);
    expect(comparison.result).toMatchObject({
      planA: { estimate: { status: 'estimated', totals: { patientPaysCents: 120000 } } },
      planB: { estimate: { status: 'estimated', totals: { patientPaysCents: 70000 } } }, planBMinusPlanACents: -50000,
    });
    const listed = PlanComparisonListSchema.parse((await api.call(LIST, { caseId, query: QUERY })).body);
    expect(listed.comparisons).toEqual([{
      comparisonId: comparison.comparisonId, caseId, caseRevision: 1, savedAt: comparison.savedAt,
      planALabel: request.planA.label, planBLabel: request.planB.label, planAStatus: 'estimated', planBStatus: 'estimated',
    }]);
    expect(JSON.stringify(listed)).not.toMatch(/providerChargeCents|patientPaysCents|sourceFacts|procedureFacts/);
    const reopened = await api.call(GET, { caseId, comparisonId: comparison.comparisonId, query: QUERY });
    expect(reopened.status).toBe(200);
    expect(SavedPlanComparisonSchema.parse(reopened.body)).toEqual(comparison);
    reopened.body.request.planB.label = 'Changed response only';
    expect((await api.call(GET, { caseId, comparisonId: comparison.comparisonId, query: QUERY })).body).toEqual(comparison);
  });

  it('preserves independent plan facts, unknowns and provenance without copying between plans', async () => {
    const api = createTestApi();
    const { caseId, request } = await setup(api);
    const originalA = structuredClone(request.planA);
    request.planB.procedureFacts['crown-1'] = { category: 'basic', network: 'out', allowedCents: 50000, contractualWriteoffCents: 10000 };
    request.planB.procedureFacts['filling-1']!.allowedCents = null;
    request.planB.sourceFacts.push({
      id: 'manual-b', fieldPath: 'procedureFacts.crown-1.allowedCents', value: 50000, sourceId: null, location: null,
      origin: 'user_entered', extractionStatus: 'not_applicable', userConfirmed: true,
      insurerVerification: { status: 'not_verified' }, conflict: false, recordedAt: '2026-10-03T15:00:00.000Z',
    });
    const response = await api.call(SAVE, { caseId, headers: HEADERS, body: { comparison: request, consent: true } });
    expect(response.status).toBe(201);
    const saved = SavePlanComparisonResponseSchema.parse(response.body).comparison;
    expect(saved.request.planA).toEqual(originalA);
    expect(saved.request.planB).toEqual(request.planB);
    expect(saved.result.planB.estimate.status).toBe('needs_information');
    expect(saved.result.planBMinusPlanACents).toBeNull();
  });

  it.each(['missing', 'unsupported', 'both'] as const)('saves and reopens %s results without a winner', async (state) => {
    const api = createTestApi();
    const { caseId, request } = await setup(api);
    if (state !== 'unsupported') request.planA.policy = null;
    if (state !== 'missing') request.planB.policy!.exclusions!.push({ id: 'excluded', description: 'Fictional restriction', categoryIds: ['major'] });
    const response = await api.call(SAVE, { caseId, headers: HEADERS, body: { comparison: request, consent: true } });
    expect(response.status).toBe(201);
    const saved = SavePlanComparisonResponseSchema.parse(response.body).comparison;
    expect(saved.result.planA.estimate.status).toBe(state === 'unsupported' ? 'estimated' : 'needs_information');
    expect(saved.result.planB.estimate.status).toBe(state === 'missing' ? 'estimated' : 'unsupported');
    expect(saved.result.planBMinusPlanACents).toBeNull();
    expect((await api.call(GET, { caseId, comparisonId: saved.comparisonId, query: QUERY })).body).toEqual(saved);
  });

  it('deduplicates simultaneous saves and rejects a key reused for changed insurance inputs', async () => {
    const api = createTestApi();
    const { caseId, request } = await setup(api);
    const body = { comparison: request, consent: true };
    const responses = await Promise.all([api.call(SAVE, { caseId, headers: HEADERS, body }), api.call(SAVE, { caseId, headers: HEADERS, body })]);
    expect(responses.map((response) => response.status).sort()).toEqual([200, 201]);
    expect(responses[0]!.body.comparison).toEqual(responses[1]!.body.comparison);
    expect((await api.call(LIST, { caseId, query: QUERY })).body.comparisons).toHaveLength(1);
    request.planB.procedureFacts['crown-1']!.allowedCents = 90000;
    error(await api.call(SAVE, { caseId, headers: HEADERS, body: { comparison: request, consent: true } }), 409, 'IDEMPOTENCY_CONFLICT');
  });

  it('canonicalizes shared ordering before fingerprinting a retried save', async () => {
    const api = createTestApi();
    const { caseId, request } = await setup(api);
    const first = await api.call(SAVE, { caseId, headers: HEADERS, body: { comparison: request, consent: true } });
    request.treatment.procedures.reverse();
    request.treatment.schedule.reverse();
    const replay = await api.call(SAVE, { caseId, headers: HEADERS, body: { comparison: request, consent: true } });
    expect(replay.status).toBe(200);
    expect(replay.body).toEqual({ comparison: first.body.comparison, replayed: true });
  });

  it('lists at most the newest 20 summaries and omits older snapshots', async () => {
    const api = createTestApi();
    const { caseId, request } = await setup(api);
    const ids: string[] = [];
    for (let index = 0; index < 23; index++) {
      const response = await api.call(SAVE, { caseId, headers: { 'idempotency-key': `comparison-save-${index}` }, body: { comparison: request, consent: true } });
      expect(response.status).toBe(201);
      ids.unshift(response.body.comparison.comparisonId as string);
    }
    const response = await api.call(LIST, { caseId, query: QUERY });
    expect(PlanComparisonListSchema.parse(response.body).comparisons.map((summary) => summary.comparisonId)).toEqual(ids.slice(0, 20));
  });

  it('leaves the case, usage and ledger untouched and preserves single-plan saving with the same key', async () => {
    const api = createTestApi();
    const { caseId, request } = await setup(api);
    const before = await api.call('GET /v1/cases/{caseId}', { caseId });
    const ledger = await api.call('GET /v1/cases/{caseId}/ledger', { caseId });
    expect((await api.call(SAVE, { caseId, headers: HEADERS, body: { comparison: request, consent: true } })).status).toBe(201);
    expect((await api.call('GET /v1/cases/{caseId}', { caseId })).body).toEqual(before.body);
    expect((await api.call('GET /v1/cases/{caseId}/ledger', { caseId })).body).toEqual(ledger.body);
    const single = await api.call('POST /v1/cases/{caseId}/strategies', { caseId, headers: HEADERS, body: { scenarioId: 'alt-1', expectedRevision: 1, consent: true } });
    expect(single.status).toBe(201);
    expect(single.body.strategy.scenario.estimate.totals.patientPaysCents).toBe(72500);
  });

  it('rejects malformed inputs, missing consent/keys and all client-submitted results', async () => {
    const api = createTestApi();
    const { caseId, request } = await setup(api);
    const save = vi.spyOn(api.store, 'saveComparison');
    for (const body of [
      {}, { comparison: request, consent: false }, { comparison: request, consent: true, result: {} },
      { comparison: { ...request, planBMinusPlanACents: 1 }, consent: true },
      { comparison: { ...request, planA: { ...request.planA, estimate: { totals: { patientPaysCents: 1 } } } }, consent: true },
      { comparison: { ...request, monthlyPremiumCents: 10 }, consent: true },
    ]) error(await api.call(SAVE, { caseId, headers: HEADERS, body }), 400, 'BAD_REQUEST');
    for (const headers of [{}, { 'idempotency-key': 'short' }]) {
      error(await api.call(SAVE, { caseId, headers, body: { comparison: request, consent: true } }), 400, 'BAD_REQUEST');
    }
    error(await api.call(SAVE, { caseId, headers: HEADERS, rawBody: '{invalid' }), 400, 'BAD_REQUEST');
    request.planB.procedureFacts['crown-1']!.allowedCents = 1.5;
    error(await api.call(SAVE, { caseId, headers: HEADERS, body: { comparison: request, consent: true } }), 400, 'BAD_REQUEST');
    expect(save).not.toHaveBeenCalled();
  });

  it('rejects source-case, treatment and schedule tampering and contradictory plan facts', async () => {
    const api = createTestApi();
    const { caseId, request } = await setup(api);
    for (const changed of [
      { ...request, caseId: 'another-case' },
      { ...request, treatment: { ...request.treatment, procedures: request.treatment.procedures.map((procedure) => ({ ...procedure, providerChargeCents: 1 })) } },
      { ...request, treatment: { ...request.treatment, schedule: request.treatment.schedule.map((entry) => ({ ...entry, date: '2026-11-01' })) } },
    ]) error(await api.call(SAVE, { caseId, headers: HEADERS, body: { comparison: changed, consent: true } }), changed.caseId !== caseId ? 400 : 422, changed.caseId !== caseId ? 'BAD_REQUEST' : 'INCONSISTENT_INPUT');
    request.planB.procedureFacts['crown-1']!.allowedCents = 999999;
    error(await api.call(SAVE, { caseId, headers: HEADERS, body: { comparison: request, consent: true } }), 422, 'INCONSISTENT_INPUT');
    expect((await api.call(LIST, { caseId, query: QUERY })).body.comparisons).toEqual([]);
  });

  it('rejects stale save, replay, list and reopen requests; current lists exclude older snapshots', async () => {
    const api = createTestApi();
    const { caseId, request } = await setup(api);
    const saved = await api.call(SAVE, { caseId, headers: HEADERS, body: { comparison: request, consent: true } });
    const comparisonId = saved.body.comparison.comparisonId as string;
    await api.call('PATCH /v1/cases/{caseId}', { caseId, body: { expectedRevision: 1, changes: { policy: null } } });
    error(await api.call(SAVE, { caseId, headers: HEADERS, body: { comparison: request, consent: true } }), 409, 'REVISION_CONFLICT');
    error(await api.call(LIST, { caseId, query: QUERY }), 409, 'REVISION_CONFLICT');
    error(await api.call(GET, { caseId, comparisonId, query: QUERY }), 409, 'REVISION_CONFLICT');
    expect((await api.call(LIST, { caseId, query: { expectedRevision: '2' } })).body.comparisons).toEqual([]);
    error(await api.call(GET, { caseId, comparisonId, query: { expectedRevision: '2' } }), 404, 'NOT_FOUND');
  });

  it('atomically rejects a revision change between calculation and storage', async () => {
    const api = createTestApi();
    const { caseId, request } = await setup(api);
    const original = api.store.saveComparison.bind(api.store);
    vi.spyOn(api.store, 'saveComparison').mockImplementationOnce(async (input) => {
      await api.call('PATCH /v1/cases/{caseId}', { caseId, body: { expectedRevision: 1, changes: { policy: null } } });
      return original(input);
    });
    error(await api.call(SAVE, { caseId, headers: HEADERS, body: { comparison: request, consent: true } }), 409, 'REVISION_CONFLICT');
    expect(await api.store.findComparisonByIdempotencyKey(`demo:${MAYA}`, caseId, HEADERS['idempotency-key'])).toBeNull();
    expect((await api.call(LIST, { caseId, query: { expectedRevision: '2' } })).body.comparisons).toEqual([]);
  });

  it('rejects a case revision change while listing and a corrupted stored cost on reopen', async () => {
    const api = createTestApi();
    const { caseId, request } = await setup(api);
    const saved = SavePlanComparisonResponseSchema.parse((await api.call(SAVE, { caseId, headers: HEADERS, body: { comparison: request, consent: true } })).body).comparison;
    const changed = structuredClone(saved);
    if (changed.result.planA.estimate.status !== 'estimated') throw new Error('Expected complete fictional fixture.');
    changed.result.planA.estimate.totals.patientPaysCents = 1;
    vi.spyOn(api.store, 'getComparison').mockResolvedValueOnce(changed);
    error(await api.call(GET, { caseId, comparisonId: saved.comparisonId, query: QUERY }), 409, 'REVISION_CONFLICT');
    const list = api.store.listComparisonsForCase.bind(api.store);
    vi.spyOn(api.store, 'listComparisonsForCase').mockImplementationOnce(async (...args) => {
      const entries = await list(...args);
      await api.call('PATCH /v1/cases/{caseId}', { caseId, body: { expectedRevision: 1, changes: { policy: null } } });
      return entries;
    });
    error(await api.call(LIST, { caseId, query: QUERY }), 409, 'REVISION_CONFLICT');
  });

  it.each([SAVE, LIST, GET])('authenticates and hides cross-user data for %s', async (route) => {
    const api = createTestApi({ authMode: 'jwt' });
    const claims = { sub: 'comparison-owner', token_use: 'access' };
    const { caseId, request } = await setup(api, claims);
    const body = { comparison: request, consent: true };
    const saved = await api.call(SAVE, { caseId, claims, headers: HEADERS, body });
    const comparisonId = saved.body.comparison.comparisonId as string;
    const options = { caseId, comparisonId, headers: HEADERS, body, query: QUERY };
    error(await api.call(route, options), 401, 'UNAUTHENTICATED');
    error(await api.call(route, { ...options, claims: { sub: 'other-owner', token_use: 'access' }, user: MAYA }), 404, 'NOT_FOUND');
    const mine = await api.call(route, { ...options, claims });
    expect(mine.status).toBe(200);
  });

  it('requires valid read revisions and hides unknown case and comparison IDs', async () => {
    const api = createTestApi();
    const { caseId } = await setup(api);
    for (const expectedRevision of ['', '0', '-1', '1.2', '1e0', 'NaN']) error(await api.call(LIST, { caseId, query: { expectedRevision } }), 400, 'BAD_REQUEST');
    error(await api.call(LIST, { caseId }), 400, 'BAD_REQUEST');
    error(await api.call(GET, { caseId, comparisonId: 'not-found', query: QUERY }), 404, 'NOT_FOUND');
    error(await api.call(GET, { caseId, comparisonId: 'bad#id', query: QUERY }), 404, 'NOT_FOUND');
    error(await api.call(LIST, { caseId: 'unknown-case', query: QUERY }), 404, 'NOT_FOUND');
    error(await api.call(LIST, { caseId, user: OTHER, query: QUERY }), 404, 'NOT_FOUND');
  });

  it.each(['saveComparison', 'findComparisonByIdempotencyKey', 'getComparison', 'listComparisonsForCase'] as const)('handles %s storage failures without disclosing error details', async (method) => {
    const api = createTestApi();
    const { caseId, request } = await setup(api);
    vi.spyOn(api.store, method).mockRejectedValueOnce(new Error('Synthetic storage details must stay private'));
    const route = method === 'getComparison' ? GET : method === 'listComparisonsForCase' ? LIST : SAVE;
    const response = await api.call(route, { caseId, comparisonId: 'not-found', query: QUERY, headers: HEADERS, body: { comparison: request, consent: true } });
    error(response, 500, 'INTERNAL');
    expect(JSON.stringify(response.body)).not.toContain('Synthetic storage details');
  });

  it('logs neither tokens, labels nor submitted insurance facts', async () => {
    const api = createTestApi();
    const { caseId, request } = await setup(api);
    const logs = vi.spyOn(console, 'log').mockImplementation(() => {});
    request.planB.label = 'Private fictional plan label';
    await api.call(SAVE, { caseId, headers: { ...HEADERS, authorization: 'Bearer synthetic-test-token' }, body: { comparison: request, consent: true } });
    expect(JSON.stringify(logs.mock.calls)).not.toMatch(/Private fictional|synthetic-test-token|insurerAlreadyPaidCents|procedureFacts/);
  });

  it('registers all three routes on the existing cases Lambda with inherited Cognito authorization', () => {
    const template = readFileSync(new URL('../../infra/template.yaml', import.meta.url), 'utf8');
    expect(template).toContain('DefaultAuthorizer: CognitoJwt');
    const cases = template.split('  CasesFunction:')[1]!.split('  CalculationsFunction:')[0]!;
    expect(cases).toContain('Path: /v1/cases/{caseId}/plan-comparisons');
    expect(cases).toContain('Path: /v1/cases/{caseId}/plan-comparisons/{comparisonId}');
    expect(cases).not.toContain('Authorizer: NONE');
  });
});
