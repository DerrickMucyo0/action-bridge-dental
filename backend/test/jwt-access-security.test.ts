import { afterEach, describe, expect, it, vi } from 'vitest';
import { resolveOwnerId } from '../src/shared/auth.js';
import { createRouter, type HttpEvent } from '../src/shared/http.js';
import { speechRoutes } from '../src/features/speech/speech.js';
import { uploadKey, type UploadStore } from '../src/features/agent-jobs/ports.js';
import { createAgentHarness, ScriptedModel } from './agent-harness.js';
import { createTestApi, fixtureCreateRequest, MAYA } from './helpers.js';

const ALICE = { sub: 'synthetic-alice-sub', token_use: 'access' };
const BOB = { sub: 'synthetic-bob-sub', token_use: 'access' };
const INVALID_CLAIMS: (Record<string, unknown> | undefined)[] = [
  undefined, {}, { sub: ALICE.sub }, { sub: ALICE.sub, token_use: 'id' },
  { sub: ALICE.sub, token_use: 'refresh' }, { sub: ALICE.sub, token_use: 'ACCESS' },
  { sub: ALICE.sub, token_use: ['access'] }, { sub: ALICE.sub, token_use: true },
  { token_use: 'access' }, { sub: '', token_use: 'access' },
  { sub: '  ', token_use: 'access' }, { sub: ' alice ', token_use: 'access' },
  { sub: 123, token_use: 'access' }, { sub: { value: 'alice' }, token_use: 'access' },
];
const CORE_ROUTES = [
  'POST /v1/cases', 'GET /v1/cases/{caseId}', 'PATCH /v1/cases/{caseId}',
  'POST /v1/cases/{caseId}/estimates', 'POST /v1/cases/{caseId}/scenarios',
  'POST /v1/cases/{caseId}/coverage-comparison', 'POST /v1/cases/{caseId}/plan-comparison',
  'POST /v1/cases/{caseId}/strategies', 'GET /v1/cases/{caseId}/strategies',
  'GET /v1/cases/{caseId}/ledger', 'POST /v1/cases/{caseId}/plan-comparisons',
  'GET /v1/cases/{caseId}/plan-comparisons', 'GET /v1/cases/{caseId}/plan-comparisons/{comparisonId}',
];
const JOB_ROUTES = [
  'POST /v1/cases/{caseId}/uploads', 'POST /v1/cases/{caseId}/jobs',
  'GET /v1/jobs/{jobId}', 'POST /v1/jobs/{jobId}/answers',
  'POST /v1/jobs/{jobId}/retry', 'POST /v1/jobs/{jobId}/cancel',
];

function event(claims?: Record<string, unknown>): HttpEvent {
  return {
    routeKey: 'POST /v1/speech', headers: {
      authorization: 'Bearer synthetic-unvalidated-header', 'x-demo-user-id': MAYA,
      'x-owner-id': `user:${ALICE.sub}`,
    }, body: JSON.stringify({ text: 'Synthetic accessibility text' }),
    requestContext: { requestId: 'synthetic-request', ...(claims ? { authorizer: { jwt: { claims } } } : {}) },
  };
}

class TestUploads implements UploadStore {
  readonly bucket = 'synthetic-private-bucket';
  readonly signedKeys: string[] = [];
  readonly readKeys: string[] = [];
  async presignPost(key: string) {
    this.signedKeys.push(key);
    return { url: 'https://uploads.invalid/', fields: { key } };
  }
  async head(key: string) { this.readKeys.push(key); return null; }
  async firstBytes(key: string) { this.readKeys.push(key); return new Uint8Array(); }
  async remove(key: string) { this.readKeys.push(key); }
}

afterEach(() => vi.restoreAllMocks());

describe('only Gateway-validated Cognito access claims authenticate private routes', () => {
  it('rejects missing, ID and malformed token claims even with plausible bearer/owner headers', () => {
    for (const claims of INVALID_CLAIMS) {
      expect(() => resolveOwnerId(event(claims), 'jwt')).toThrowError(expect.objectContaining({ code: 'UNAUTHENTICATED' }));
    }
    expect(resolveOwnerId(event(ALICE), 'jwt')).toBe(`user:${ALICE.sub}`);
    expect(resolveOwnerId(event({ ...ALICE, ownerId: BOB.sub }), 'jwt')).toBe(`user:${ALICE.sub}`);
  });

  it.each(CORE_ROUTES)('rejects ID/missing/invalid claims before handling %s', async (route) => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const api = createTestApi({ authMode: 'jwt' });
    for (const claims of INVALID_CLAIMS) {
      const response = await api.call(route, {
        caseId: 'synthetic-case', comparisonId: 'synthetic-comparison', body: {},
        headers: { authorization: 'Bearer synthetic-unvalidated-header', 'x-owner-id': ALICE.sub },
        ...(claims ? { claims } : {}),
      });
      expect(response.status).toBe(401);
      expect(response.body.error.code).toBe('UNAUTHENTICATED');
    }
  });

  it.each(JOB_ROUTES)('rejects ID/missing/invalid claims before handling %s', async (route) => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const uploads = new TestUploads();
    const h = createAgentHarness(new ScriptedModel([]), { authMode: 'jwt', uploads });
    for (const claims of INVALID_CLAIMS) {
      const response = await h.call(route, { caseId: 'synthetic-case', jobId: 'synthetic-job' }, {}, MAYA, claims);
      expect(response.status).toBe(401);
      expect(response.body.error.code).toBe('UNAUTHENTICATED');
    }
    expect(uploads.signedKeys).toEqual([]);
    expect(h.queue.messages).toEqual([]);
  });

  it('rejects ID/missing/invalid claims before calling speech synthesis, then accepts access claims', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const synthesize = vi.fn(async () => ({ audio: new Uint8Array([1]), voice: 'Joanna' }));
    const router = createRouter(speechRoutes({ authMode: 'jwt', synthesizer: { synthesize } }));
    for (const claims of INVALID_CLAIMS) expect((await router(event(claims))).statusCode).toBe(401);
    expect(synthesize).not.toHaveBeenCalled();
    expect((await router(event(ALICE))).statusCode).toBe(200);
    expect(synthesize).toHaveBeenCalledOnce();
  });

  it('keeps explicit synthetic-only local demo ownership unchanged', () => {
    expect(resolveOwnerId(event({ ...ALICE, token_use: 'id' }), 'demo')).toBe(`demo:${MAYA}`);
  });
});

describe('private data is scoped by the validated access-token subject', () => {
  it('rejects cross-user case, estimate, saved-strategy and ledger operations despite owner headers', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const api = createTestApi({ authMode: 'jwt' });
    const created = await api.call('POST /v1/cases', { body: fixtureCreateRequest(), claims: ALICE });
    expect(created.status).toBe(201);
    const caseId = created.body.caseId as string;
    const save = { expectedRevision: 1, scenarioId: 'alt-1', consent: true };
    const headers = { 'idempotency-key': 'synthetic-save-key', 'x-owner-id': `user:${ALICE.sub}` };
    expect((await api.call('POST /v1/cases/{caseId}/strategies', { caseId, claims: ALICE, headers, body: save })).status).toBe(201);
    const attempts: [string, unknown][] = [
      ['GET /v1/cases/{caseId}', undefined],
      ['PATCH /v1/cases/{caseId}', { expectedRevision: 1, changes: { policy: null } }],
      ['POST /v1/cases/{caseId}/estimates', { expectedRevision: 1 }],
      ['POST /v1/cases/{caseId}/scenarios', { expectedRevision: 1 }],
      ['POST /v1/cases/{caseId}/coverage-comparison', { expectedRevision: 1 }],
      ['POST /v1/cases/{caseId}/strategies', save],
      ['GET /v1/cases/{caseId}/strategies', undefined],
      ['GET /v1/cases/{caseId}/ledger', undefined],
    ];
    for (const [route, body] of attempts) {
      const response = await api.call(route, { caseId, body, headers, claims: BOB });
      expect(response.status).toBe(404);
      expect(response.body.error.code).toBe('NOT_FOUND');
      expect(JSON.stringify(response.body)).not.toContain(ALICE.sub);
    }
    const mine = await api.call('GET /v1/cases/{caseId}/strategies', { caseId, claims: ALICE });
    expect(mine.status).toBe(200);
    expect(mine.body.strategies).toHaveLength(1);
    expect((await api.call('GET /v1/cases/{caseId}', { caseId, claims: ALICE })).body.caseRevision).toBe(1);
  });

  it('rejects cross-user job operations and signs/reads uploads only within the current owner and case', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const uploads = new TestUploads();
    const h = createAgentHarness(new ScriptedModel([]), { authMode: 'jwt', uploads });
    const created = await h.call('POST /v1/cases', {}, fixtureCreateRequest(), MAYA, ALICE);
    const caseId = created.body.caseId as string;
    const jobBody = { expectedRevision: 1, operation: 'interpret', input: { text: 'Fictional crown' } };
    const uploadBody = { kind: 'document', mimeType: 'application/pdf', sizeBytes: 100 };
    const slot = await h.call('POST /v1/cases/{caseId}/uploads', { caseId }, uploadBody, MAYA, ALICE);
    expect(slot.status).toBe(201);
    expect(uploads.signedKeys).toEqual([uploadKey(`user:${ALICE.sub}`, caseId, slot.body.uploadId)]);
    const started = await h.call('POST /v1/cases/{caseId}/jobs', { caseId }, jobBody, MAYA, ALICE);
    expect(started.status).toBe(202);
    const jobId = started.body.jobId as string;
    const attempts: [string, unknown][] = [
      ['POST /v1/cases/{caseId}/uploads', uploadBody],
      ['POST /v1/cases/{caseId}/jobs', jobBody],
      ['GET /v1/jobs/{jobId}', undefined],
      ['POST /v1/jobs/{jobId}/answers', { expectedRevision: 1, answers: [{ questionId: 'synthetic-question', value: null, unknown: true, responseMode: 'tap', attachmentId: null }] }],
      ['POST /v1/jobs/{jobId}/retry', {}], ['POST /v1/jobs/{jobId}/cancel', {}],
    ];
    for (const [route, body] of attempts) {
      const response = await h.call(route, { caseId, jobId }, body, MAYA, BOB);
      expect(response.status).toBe(404);
      expect(response.body.error.code).toBe('NOT_FOUND');
    }
    expect(uploads.signedKeys).toHaveLength(1);
    expect(h.queue.messages).toHaveLength(1);
    expect((await h.call('GET /v1/jobs/{jobId}', { jobId }, undefined, MAYA, ALICE)).body.status).toBe('queued');

    // Knowing another owner's upload ID cannot make the worker read that owner's key.
    const otherCase = await h.call('POST /v1/cases', {}, fixtureCreateRequest(), MAYA, BOB);
    const foreignUpload = await h.call('POST /v1/cases/{caseId}/jobs', { caseId: otherCase.body.caseId }, {
      expectedRevision: 1, operation: 'analyze_document', input: { documentId: slot.body.uploadId },
    }, MAYA, BOB);
    expect(foreignUpload.status).toBe(202);
    h.runner.reader = { readLines: vi.fn(async () => []) };
    await h.drain();
    expect(uploads.readKeys).toContain(uploadKey(`user:${BOB.sub}`, otherCase.body.caseId, slot.body.uploadId));
    expect(uploads.readKeys).not.toContain(uploadKey(`user:${ALICE.sub}`, caseId, slot.body.uploadId));
  });
});
