import { TransactWriteCommand } from '@aws-sdk/lib-dynamodb';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CreateJobRequest, JobAnswersRequest } from '@actionbridge/contracts';
import { createJobWorkerHandler } from '../src/functions/job-worker.js';
import { composeHandler } from '../src/functions/compose.js';
import { JobService } from '../src/features/agent-jobs/application/job-service.js';
import { runJob } from '../src/features/agent-jobs/application/job-runner.js';
import { UploadService } from '../src/features/agent-jobs/application/upload-service.js';
import { InMemoryJobQueue, InMemoryJobRepository } from '../src/features/agent-jobs/infrastructure/in-memory.js';
import type { UploadStore } from '../src/features/agent-jobs/ports.js';
import { CaseService } from '../src/features/cases/application/case-service.js';
import { speechRoutes } from '../src/features/speech/speech.js';
import { loadConfig, type StagingConfig } from '../src/shared/config.js';
import { createRouter, jsonResult, type HttpEvent } from '../src/shared/http.js';
import { InMemoryStore } from '../src/shared/in-memory-store.js';
import { StagingControls, restrictStagingRoutes, type StagingQuotaStore } from '../src/shared/staging-controls.js';
import { DynamoStagingQuotaStore } from '../src/shared/dynamo-staging-quota-store.js';
import { ScriptedModel } from './agent-harness.js';

const SUB_A = '11111111-1111-4111-8111-111111111111';
const SUB_B = '22222222-2222-4222-8222-222222222222';
const OWNER_A = `user:${SUB_A}`;
const OWNER_B = `user:${SUB_B}`;
const config = (overrides: Partial<StagingConfig> = {}): StagingConfig => ({
  allowedUserSubs: [SUB_A, SUB_B],
  jobDailyLimit: 10,
  uploadDailyLimit: 10,
  speechDailyLimit: 30,
  globalJobDailyLimit: 20,
  globalUploadDailyLimit: 20,
  globalSpeechDailyLimit: 60,
  ...overrides,
});
const event = (sub?: string, body?: unknown, tokenUse = 'access'): HttpEvent => ({
  routeKey: 'POST /v1/private',
  requestContext: { requestId: 'synthetic-request', ...(sub ? { authorizer: { jwt: { claims: { sub, token_use: tokenUse } } } } : {}) },
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});
afterEach(() => vi.unstubAllEnvs());

/** A transaction-level fake: either both conditional increments commit, or neither does. */
class AtomicDynamo {
  counts = new Map<string, number>();
  commands: TransactWriteCommand[] = [];
  fail: Error | null = null;
  async send(command: TransactWriteCommand) {
    this.commands.push(command);
    if (this.fail) throw this.fail;
    const updates = command.input.TransactItems!.map((item) => item.Update!);
    const reasons = updates.map((update) => ({
      Code: (this.counts.get(update.Key!.pk as string) ?? 0) >= Number(update.ExpressionAttributeValues![':limit']) ? 'ConditionalCheckFailed' : 'None',
    }));
    if (reasons.some((reason) => reason.Code === 'ConditionalCheckFailed')) {
      throw Object.assign(new Error('synthetic transaction rejection'), { name: 'TransactionCanceledException', CancellationReasons: reasons });
    }
    for (const update of updates) this.counts.set(update.Key!.pk as string, (this.counts.get(update.Key!.pk as string) ?? 0) + 1);
    return {};
  }
}

function quotas(overrides: Partial<StagingConfig> = {}) {
  const db = new AtomicDynamo();
  let now = new Date('2026-10-23T23:59:59.000Z');
  const store = new DynamoStagingQuotaStore(db as never, 'synthetic-staging-table');
  const controls = new StagingControls(config(overrides), store, () => now);
  return {
    db,
    store,
    controls,
    setNow: (date: string) => {
      now = new Date(date);
    },
  };
}

function services(staging: StagingControls) {
  let ids = 0;
  const now = () => new Date('2026-10-23T12:00:00.000Z');
  const newId = () => `id-${++ids}`;
  const store = new InMemoryStore();
  const jobsRepo = new InMemoryJobRepository();
  const queue = new InMemoryJobQueue();
  const cases = new CaseService({ repository: store, now, newId, retentionDays: null });
  const jobs = new JobService({ jobs: jobsRepo, queue, cases, now, newId, retentionDays: null, maxAttempts: 3, staging });
  const presignPost = vi.fn(async () => ({ url: 'https://synthetic.invalid', fields: {} }));
  const uploads = new UploadService({ cases, uploads: { presignPost } as unknown as UploadStore, now, newId, staging });
  const model = new ScriptedModel([]);
  const runner = { jobs: jobsRepo, cases: store, now, newId, retentionDays: null, leaseMs: 300_000, model };
  return { cases, jobs, jobsRepo, queue, uploads, presignPost, runner, model };
}
const newCase = (h: ReturnType<typeof services>) =>
  h.cases.create(OWNER_A, { currency: 'USD', coverageMode: 'unknown', policy: null, planYears: {}, procedures: [] });
const request: CreateJobRequest = { expectedRevision: 1, operation: 'interpret', input: {} };

describe('server-enforced staging account restrictions', () => {
  it('guards every known private route before I/O while health stays public', async () => {
    const privateHandler = vi.fn(async () => jsonResult(200, { ok: true }, 'request'));
    const cfg = loadConfig({ APP_ENV: 'staging', AUTH_MODE: 'jwt', STAGING_ALLOWED_USER_SUBS: SUB_A });
    const router = createRouter(
      restrictStagingRoutes(cfg, {
        'POST /v1/private': privateHandler,
        'GET /v1/other': privateHandler,
        'GET /health': async () => jsonResult(200, { status: 'ok' }, 'request'),
      }),
    );
    expect((await router(event())).statusCode).toBe(401);
    expect((await router(event(SUB_A, undefined, 'id'))).statusCode).toBe(401);
    expect((await router(event(SUB_B))).statusCode).toBe(403);
    expect((await router({ ...event(SUB_B), routeKey: 'GET /v1/other', headers: { 'x-demo-user-id': SUB_A } })).statusCode).toBe(403);
    expect(privateHandler).not.toHaveBeenCalled();
    expect((await router({ ...event(), routeKey: 'GET /health' })).statusCode).toBe(200);
    expect((await router(event(SUB_A))).statusCode).toBe(200);
    expect(privateHandler).toHaveBeenCalledTimes(1);
  });

  it('fails closed for missing approval configuration before building request handlers', async () => {
    vi.stubEnv('APP_ENV', 'staging');
    vi.stubEnv('AUTH_MODE', 'jwt');
    vi.stubEnv('STAGING_ALLOWED_USER_SUBS', '');
    const build = vi.fn(() => ({}));
    expect((await composeHandler(build)(event(SUB_A))).statusCode).toBe(500);
    expect(build).not.toHaveBeenCalled();
    expect(() => restrictStagingRoutes({ ...loadConfig({ APP_ENV: 'dev', AUTH_MODE: 'jwt' }), appEnv: 'staging' }, {})).toThrow();
    expect(() => new StagingControls(config({ allowedUserSubs: [] }), { consume: vi.fn() })).toThrow();
  });

  it('leaves existing non-staging routes and demo behavior unchanged', async () => {
    const routes = { 'POST /v1/private': async () => jsonResult(200, { synthetic: true }, 'request') };
    expect(restrictStagingRoutes(loadConfig({ APP_ENV: 'dev', AUTH_MODE: 'demo' }), routes)).toBe(routes);
    expect((await createRouter(routes)(event())).statusCode).toBe(200);
  });

  it('unapproved direct job/upload calls cause neither data reads nor quota/storage work', async () => {
    const store: StagingQuotaStore = { consume: vi.fn() };
    const controls = new StagingControls(config({ allowedUserSubs: [SUB_A] }), store);
    const h = services(controls);
    const get = vi.spyOn(h.cases, 'get');
    const getAtRevision = vi.spyOn(h.cases, 'getAtRevision');
    await expect(h.jobs.create(OWNER_B, 'foreign', request)).rejects.toMatchObject({ code: 'FORBIDDEN' });
    await expect(h.jobs.retry(OWNER_B, 'foreign')).rejects.toMatchObject({ code: 'FORBIDDEN' });
    await expect(h.uploads.create(OWNER_B, 'foreign', { kind: 'document', mimeType: 'application/pdf', sizeBytes: 100 })).rejects.toMatchObject({
      code: 'FORBIDDEN',
    });
    expect(get).not.toHaveBeenCalled();
    expect(getAtRevision).not.toHaveBeenCalled();
    expect(store.consume).not.toHaveBeenCalled();
    expect(h.presignPost).not.toHaveBeenCalled();
    expect(h.queue.messages).toEqual([]);
  });

  it('rechecks approval in the worker before reading jobs, invoking models or touching files', async () => {
    const { controls } = quotas({ allowedUserSubs: [SUB_A] });
    const h = services(controls);
    const read = vi.spyOn(h.jobsRepo, 'get');
    const handler = createJobWorkerHandler(() => ({ deps: h.runner, assertOwnerAllowed: (owner) => controls.assertAllowed(owner) }));
    expect(await handler({ Records: [{ messageId: 'synthetic-message', body: JSON.stringify({ ownerId: OWNER_B, jobId: 'synthetic-job' }) }] })).toEqual({
      batchItemFailures: [],
    });
    expect(read).not.toHaveBeenCalled();
    expect(h.model.requests).toEqual([]);
  });
});

describe('atomic staging UTC-day limits', () => {
  it('reserves both per-user and global allowance atomically across parallel Lambda requests', async () => {
    const q = quotas({ jobDailyLimit: 3, globalJobDailyLimit: 5 });
    const secondInstance = new StagingControls(config({ jobDailyLimit: 3, globalJobDailyLimit: 5 }), q.store, () => new Date('2026-10-23T23:59:59Z'));
    const calls = await Promise.allSettled([
      ...Array.from({ length: 8 }, () => q.controls.consume(OWNER_A, 'jobs')),
      ...Array.from({ length: 8 }, () => secondInstance.consume(OWNER_B, 'jobs')),
    ]);
    expect(calls.filter((call) => call.status === 'fulfilled')).toHaveLength(5);
    for (const call of calls) if (call.status === 'rejected') expect(call.reason).toMatchObject({ code: 'RATE_LIMITED' });
    expect([...q.db.counts.values()].sort()).toEqual([2, 3, 5]);
    const transaction = q.db.commands[0]!.input.TransactItems!;
    expect(transaction).toHaveLength(2);
    for (const item of transaction) {
      expect(item.Update).toMatchObject({
        TableName: 'synthetic-staging-table',
        Key: { sk: 'COUNTER' },
        ConditionExpression: 'attribute_not_exists(#count) OR #count < :limit',
      });
      expect(item.Update!.Key!.pk).toMatch(/^STAGING_QUOTA#2026-10-23#jobs#/);
      expect(item.Update!.Key!.pk).not.toContain(SUB_A);
      expect(item.Update!.ExpressionAttributeValues![':ttl']).toBe(Date.parse('2026-10-26T00:00:00Z') / 1000);
    }
  });

  it('resets at the next UTC date independently of delayed TTL deletion', async () => {
    const q = quotas({ jobDailyLimit: 1, globalJobDailyLimit: 1 });
    await q.controls.consume(OWNER_A, 'jobs');
    await expect(q.controls.consume(OWNER_A, 'jobs')).rejects.toMatchObject({ code: 'RATE_LIMITED' });
    q.setNow('2026-10-24T00:00:00.000Z');
    await expect(q.controls.consume(OWNER_A, 'jobs')).resolves.toBeUndefined();
    expect(q.db.counts.size).toBe(4);
  });

  it('keeps operation quotas separate and enforces their own configured limits', async () => {
    const q = quotas({ jobDailyLimit: 1, uploadDailyLimit: 1, speechDailyLimit: 1 });
    for (const operation of ['jobs', 'uploads', 'speech'] as const) {
      await q.controls.consume(OWNER_A, operation);
      await expect(q.controls.consume(OWNER_A, operation)).rejects.toMatchObject({ code: 'RATE_LIMITED' });
    }
  });

  it('denies operational failures with fixed text without leaking or bypassing the store', async () => {
    const q = quotas();
    q.db.fail = Object.assign(new Error('sensitive synthetic exception detail'), { name: 'AccessDeniedException' });
    await expect(q.controls.consume(OWNER_A, 'jobs')).rejects.toMatchObject({
      code: 'UPSTREAM_UNAVAILABLE',
      message: 'Staging usage limits could not be checked. Please try again later.',
    });
    expect(q.db.counts.size).toBe(0);
  });
});

describe('all expensive entry points reserve quota before side effects', () => {
  it('does not charge foreign cases, malformed job preconditions or unsupported operations', async () => {
    const store = { consume: vi.fn(async () => {}) };
    const h = services(new StagingControls(config(), store));
    const { caseId } = await newCase(h);
    await expect(h.jobs.create(OWNER_B, caseId, request)).rejects.toMatchObject({ code: 'NOT_FOUND' });
    await expect(h.uploads.create(OWNER_B, caseId, { kind: 'document', mimeType: 'application/pdf', sizeBytes: 100 })).rejects.toMatchObject({
      code: 'NOT_FOUND',
    });
    await expect(h.jobs.create(OWNER_A, caseId, { ...request, operation: 'analyze_document' })).rejects.toMatchObject({ code: 'BAD_REQUEST' });
    await expect(h.jobs.create(OWNER_A, caseId, { ...request, expectedRevision: 999 })).rejects.toMatchObject({ code: 'REVISION_CONFLICT' });
    expect(store.consume).not.toHaveBeenCalled();
    expect(h.queue.messages).toEqual([]);
    expect(h.presignPost).not.toHaveBeenCalled();
  });

  it('blocks new jobs and upload URLs when the atomic store is unavailable', async () => {
    const q = quotas();
    const h = services(q.controls);
    const { caseId } = await newCase(h);
    q.db.fail = new Error('synthetic outage');
    const create = vi.spyOn(h.jobsRepo, 'create');
    await expect(h.jobs.create(OWNER_A, caseId, request)).rejects.toMatchObject({ code: 'UPSTREAM_UNAVAILABLE' });
    await expect(h.uploads.create(OWNER_A, caseId, { kind: 'document', mimeType: 'application/pdf', sizeBytes: 100 })).rejects.toMatchObject({
      code: 'UPSTREAM_UNAVAILABLE',
    });
    expect(create).not.toHaveBeenCalled();
    expect(h.queue.messages).toEqual([]);
    expect(h.presignPost).not.toHaveBeenCalled();
  });

  it('throttles answer follow-ups before modifying case facts, job status or the queue', async () => {
    const q = quotas({ jobDailyLimit: 1 });
    const h = services(q.controls);
    const { caseId } = await newCase(h);
    const { jobId } = await h.jobs.create(OWNER_A, caseId, request);
    await runJob(h.runner, { ownerId: OWNER_A, jobId });
    const job = (await h.jobsRepo.get(OWNER_A, jobId))!;
    const question = job.questions!.blocks.find((block) => block.type === 'missing_field')!;
    if (question.type !== 'missing_field') throw new Error('Expected a synthetic question');
    const answer: JobAnswersRequest = {
      expectedRevision: 1,
      answers: [{ questionId: question.questionId, value: null, unknown: true, responseMode: 'tap', attachmentId: null }],
    };
    const before = await h.cases.get(OWNER_A, caseId);
    const count = h.queue.messages.length;
    await expect(h.jobs.answer(OWNER_A, jobId, answer)).rejects.toMatchObject({ code: 'RATE_LIMITED' });
    expect(await h.cases.get(OWNER_A, caseId)).toEqual(before);
    expect(await h.jobsRepo.get(OWNER_A, jobId)).toEqual(job);
    expect(h.queue.messages).toHaveLength(count);
  });

  it('throttles retries before changing failed jobs or enqueuing another attempt', async () => {
    const q = quotas({ jobDailyLimit: 1 });
    const h = services(q.controls);
    const { caseId } = await newCase(h);
    const { jobId } = await h.jobs.create(OWNER_A, caseId, request);
    const original = (await h.jobsRepo.get(OWNER_A, jobId))!;
    const failed = {
      ...original,
      status: 'failed' as const,
      error: { code: 'UPSTREAM_UNAVAILABLE' as const, message: 'Synthetic retryable failure', retryable: true, requestId: 'test' },
    };
    await h.jobsRepo.put(failed, { status: ['queued'] });
    const count = h.queue.messages.length;
    await expect(h.jobs.retry(OWNER_A, jobId)).rejects.toMatchObject({ code: 'RATE_LIMITED' });
    expect(await h.jobsRepo.get(OWNER_A, jobId)).toEqual(failed);
    expect(h.queue.messages).toHaveLength(count);
  });

  it('counts successful answer follow-ups and retries in the same daily job allowance', async () => {
    const q = quotas();
    const h = services(q.controls);
    const { caseId } = await newCase(h);
    const { jobId } = await h.jobs.create(OWNER_A, caseId, request);
    const handler = createJobWorkerHandler(() => ({ deps: h.runner, assertOwnerAllowed: (owner) => q.controls.assertAllowed(owner) }));
    expect(await handler({ Records: [{ messageId: 'approved-message', body: JSON.stringify({ ownerId: OWNER_A, jobId }) }] })).toEqual({
      batchItemFailures: [],
    });
    const original = (await h.jobsRepo.get(OWNER_A, jobId))!;
    const question = original.questions!.blocks.find((block) => block.type === 'missing_field')!;
    if (question.type !== 'missing_field') throw new Error('Expected synthetic question');
    const followup = await h.jobs.answer(OWNER_A, jobId, {
      expectedRevision: 1,
      answers: [{ questionId: question.questionId, value: null, unknown: true, responseMode: 'tap', attachmentId: null }],
    });
    const queued = (await h.jobsRepo.get(OWNER_A, followup.jobId))!;
    await h.jobsRepo.put(
      { ...queued, status: 'failed', error: { code: 'UPSTREAM_UNAVAILABLE', message: 'Synthetic failure', retryable: true, requestId: 'test' } },
      { status: ['queued'] },
    );
    await h.jobs.retry(OWNER_A, followup.jobId);
    expect([...q.db.counts.values()]).toEqual([3, 3]);
    expect(h.queue.messages).toHaveLength(3);
  });

  it('issues an owner-scoped upload URL only once per available slot', async () => {
    const q = quotas({ uploadDailyLimit: 1 });
    const h = services(q.controls);
    const { caseId } = await newCase(h);
    await h.uploads.create(OWNER_A, caseId, { kind: 'document', mimeType: 'application/pdf', sizeBytes: 100 });
    await expect(h.uploads.create(OWNER_A, caseId, { kind: 'document', mimeType: 'application/pdf', sizeBytes: 100 })).rejects.toMatchObject({
      code: 'RATE_LIMITED',
    });
    expect(h.presignPost).toHaveBeenCalledTimes(1);
  });

  it('checks speech input and quotas before invoking Polly, preserving 429 and fail-closed errors', async () => {
    const q = quotas({ speechDailyLimit: 1 });
    const synthesize = vi.fn(async () => ({ audio: new Uint8Array([1]), voice: 'Joanna' }));
    const route = speechRoutes({ synthesizer: { synthesize }, authMode: 'jwt', staging: q.controls })['POST /v1/speech']!;
    await expect(route(event(SUB_A, { text: '' }))).rejects.toMatchObject({ code: 'BAD_REQUEST' });
    expect(q.db.commands).toHaveLength(0);
    expect((await route(event(SUB_A, { text: 'Synthetic example' }))).statusCode).toBe(200);
    await expect(route(event(SUB_A, { text: 'Synthetic example' }))).rejects.toMatchObject({ code: 'RATE_LIMITED' });
    expect(synthesize).toHaveBeenCalledTimes(1);
    q.db.fail = new Error('synthetic outage');
    await expect(route(event(SUB_B, { text: 'Synthetic example' }))).rejects.toMatchObject({ code: 'UPSTREAM_UNAVAILABLE' });
    expect(synthesize).toHaveBeenCalledTimes(1);
  });

  it('keeps an accepted attempt charged if enqueue fails, rather than allowing free retries', async () => {
    const q = quotas({ jobDailyLimit: 1 });
    const h = services(q.controls);
    const { caseId } = await newCase(h);
    vi.spyOn(h.queue, 'enqueue').mockRejectedValue(new Error('synthetic queue outage'));
    await expect(h.jobs.create(OWNER_A, caseId, request)).rejects.toMatchObject({ code: 'UPSTREAM_UNAVAILABLE' });
    await expect(h.jobs.create(OWNER_A, caseId, request)).rejects.toMatchObject({ code: 'RATE_LIMITED' });
  });
});
