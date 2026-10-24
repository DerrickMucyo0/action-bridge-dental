import { afterEach, describe, expect, it, vi } from 'vitest';
import { BedrockAgentModel } from '../src/features/agent-jobs/infrastructure/aws.js';
import { ModelError, type AgentModel, type UploadStore } from '../src/features/agent-jobs/ports.js';
import { createRouter } from '../src/shared/http.js';
import { safeErrorName } from '../src/shared/logger.js';
import { createAgentHarness, ScriptedModel } from './agent-harness.js';

// Fictional sentinels only: any occurrence in diagnostics demonstrates unsafe exception logging.
const PRIVATE = 'synthetic-password-token-request-body-never-log';
const request = { system: 'Synthetic request', messages: [], tools: [], maxTokens: 10 };

afterEach(() => vi.restoreAllMocks());

describe('upstream exception diagnostics omit sensitive values', () => {
  it.each([
    ['ThrottlingException', true], ['ServiceUnavailableException', true],
    ['ModelTimeoutException', true], ['AccessDeniedException', false],
    [`BadDocumentException-${PRIVATE}`, false], [PRIVATE, false],
  ])('retains only an exact safe SDK classification for %s', async (name, retryable) => {
    const sdkError = Object.assign(new Error(PRIVATE), { name });
    const model = new BedrockAgentModel({ send: vi.fn().mockRejectedValue(sdkError) } as never, 'synthetic-model');
    const error = await model.converse(request).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ModelError);
    expect(error).toMatchObject({ retryable, detail: null });
    expect((error as Error).message).not.toContain(PRIVATE);
    expect((error as Error).message).toBe(`Model call failed: ${safeErrorName(sdkError)}`);
  });

  it('never serializes thrown non-Error objects', async () => {
    const sdkError = { name: PRIVATE, message: PRIVATE, request: { password: PRIVATE } };
    const model = new BedrockAgentModel({ send: vi.fn().mockRejectedValue(sdkError) } as never, 'synthetic-model');
    await expect(model.converse(request)).rejects.toMatchObject({ message: 'Model call failed: UnknownError', retryable: false, detail: null });
  });

  it.each([
    new ModelError(PRIVATE, true, PRIVATE),
    Object.assign(new ModelError(PRIVATE, false, PRIVATE), { name: PRIVATE }),
    Object.assign(new Error(PRIVATE), { name: PRIVATE }),
    { name: PRIVATE, message: PRIVATE, body: PRIVATE },
  ])('logs only classifications and keeps failed job responses generic', async (failure) => {
    const logs = vi.spyOn(console, 'log').mockImplementation(() => {});
    const model: AgentModel = { converse: async () => { throw failure; } };
    const h = createAgentHarness(model);
    const created = await h.call('POST /v1/cases', {}, { currency: 'USD', coverageMode: 'unknown', policy: null, planYears: {}, procedures: [] });
    const started = await h.call('POST /v1/cases/{caseId}/jobs', { caseId: created.body.caseId }, { expectedRevision: 1, operation: 'interpret', input: { text: PRIVATE } });
    await h.drain();
    const viewed = await h.call('GET /v1/jobs/{jobId}', { jobId: started.body.jobId });
    expect(viewed.body.status).toBe('failed');
    expect(JSON.stringify(viewed.body)).not.toContain(PRIVATE);
    expect(JSON.stringify(logs.mock.calls)).not.toContain(PRIVATE);
    const failureLog = logs.mock.calls.map(([line]) => JSON.parse(line as string)).find((entry) => entry.message === 'job_failed');
    expect(failureLog).toMatchObject({ errorName: safeErrorName(failure) });
    expect(failureLog).not.toHaveProperty('errorDetail');
    expect(Object.keys(failureLog).sort()).toEqual(['errorName', 'jobId', 'level', 'message', 'retryable']);
  });

  it('a manipulated document error name cannot enter unreadable-document diagnostics', async () => {
    const logs = vi.spyOn(console, 'log').mockImplementation(() => {});
    const uploads: UploadStore = {
      bucket: 'synthetic-bucket', presignPost: async (key) => ({ url: 'https://uploads.invalid/', fields: { key } }),
      head: async () => ({ sizeBytes: 10, contentType: 'application/pdf' }),
      firstBytes: async () => new Uint8Array(Buffer.from('%PDF-1.7')), remove: async () => {},
    };
    const failure = Object.assign(new Error(PRIVATE), { name: `BadDocumentException-${PRIVATE}` });
    const h = createAgentHarness(new ScriptedModel([]), { uploads, reader: { readLines: async () => { throw failure; } } });
    const created = await h.call('POST /v1/cases', {}, { currency: 'USD', coverageMode: 'unknown', policy: null, planYears: {}, procedures: [] });
    const started = await h.call('POST /v1/cases/{caseId}/jobs', { caseId: created.body.caseId }, {
      expectedRevision: 1, operation: 'analyze_document', input: { documentId: 'synthetic-upload' },
    });
    await h.drain();
    const viewed = await h.call('GET /v1/jobs/{jobId}', { jobId: started.body.jobId });
    expect(viewed.body.error.code).toBe('UPSTREAM_UNAVAILABLE');
    expect(JSON.stringify(viewed.body)).not.toContain(PRIVATE);
    expect(JSON.stringify(logs.mock.calls)).not.toContain(PRIVATE);
  });

  it('redacts attacker-controlled HTTP exception names as well as messages', async () => {
    const logs = vi.spyOn(console, 'log').mockImplementation(() => {});
    const router = createRouter({ 'GET /synthetic': async () => { throw Object.assign(new Error(PRIVATE), { name: PRIVATE }); } });
    const response = await router({ routeKey: 'GET /synthetic', requestContext: { requestId: 'synthetic-request' } });
    expect(response.statusCode).toBe(500);
    expect(response.body).not.toContain(PRIVATE);
    expect(JSON.stringify(logs.mock.calls)).not.toContain(PRIVATE);
    expect(JSON.parse(logs.mock.calls[0]![0] as string).errorCode).toBe('UnknownError');
  });
});
