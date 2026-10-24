import { afterEach, describe, expect, it, vi } from 'vitest';
import { handler, stagingTranscriptionJobPrefix } from '../src/functions/job-worker.js';
import type { Transcriber, UploadStore } from '../src/features/agent-jobs/ports.js';
import { createAgentHarness, ScriptedModel } from './agent-harness.js';

const PREFIX = 'actionbridge-actionbridge-dental-staging_';
afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('stack-isolated staging transcription names', () => {
  it('accepts the staging CloudFormation stack namespace', () => {
    expect(stagingTranscriptionJobPrefix({ appEnv: 'staging' }, { TRANSCRIPTION_JOB_PREFIX: PREFIX })).toBe(PREFIX);
    const longest = `actionbridge-${'a'.repeat(128)}_`;
    expect(stagingTranscriptionJobPrefix({ appEnv: 'staging' }, { TRANSCRIPTION_JOB_PREFIX: longest })).toBe(longest);
  });

  it('keeps hyphen-related stack namespaces disjoint', () => {
    const short = stagingTranscriptionJobPrefix({ appEnv: 'staging' }, { TRANSCRIPTION_JOB_PREFIX: 'actionbridge-foo_' })!;
    const longer = stagingTranscriptionJobPrefix({ appEnv: 'staging' }, { TRANSCRIPTION_JOB_PREFIX: 'actionbridge-foo-bar_' })!;
    expect(`${longer}synthetic-job`).not.toMatch(new RegExp(`^${short}`));
    expect(`${short}synthetic-job`).not.toMatch(new RegExp(`^${longer}`));
    expect(() => stagingTranscriptionJobPrefix({ appEnv: 'staging' }, { TRANSCRIPTION_JOB_PREFIX: 'actionbridge-foo-' })).toThrow();
  });

  it.each([
    undefined,
    '',
    'actionbridge-',
    'actionbridge-0invalid_',
    'actionbridge-invalid_stack_',
    'actionbridge-invalid/path_',
    'actionbridge-valid-without-trailing-underscore',
    'actionbridge-valid-stack-',
    `actionbridge-${'a'.repeat(129)}_`,
    `${PREFIX}\n`,
  ])('fails closed for missing or malformed staging prefix %j', async (prefix) => {
    expect(() => stagingTranscriptionJobPrefix({ appEnv: 'staging' }, { TRANSCRIPTION_JOB_PREFIX: prefix })).toThrow('Staging transcription job prefix');
    vi.stubEnv('APP_ENV', 'staging');
    vi.stubEnv('AUTH_MODE', 'jwt');
    vi.stubEnv('STAGING_ALLOWED_USER_SUBS', '11111111-1111-4111-8111-111111111111');
    vi.stubEnv('TRANSCRIPTION_JOB_PREFIX', prefix);
    const fetch = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('No network is permitted'));
    // Build rejects the prefix before creating clients, looking up jobs or making AWS requests.
    await expect(handler({ Records: [] })).rejects.toThrow('Staging transcription job prefix');
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each(['local', 'dev', 'demo'] as const)('preserves the old namespace and ignores staging variables in %s', (appEnv) => {
    expect(stagingTranscriptionJobPrefix({ appEnv }, {})).toBeUndefined();
    expect(stagingTranscriptionJobPrefix({ appEnv }, { TRANSCRIPTION_JOB_PREFIX: 'invalid-or-other-stage' })).toBeUndefined();
  });

  it.each([undefined, PREFIX])('uses one consistent default or staging name for start/get/delete: %j', async (prefix) => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const m4a = new Uint8Array([0, 0, 0, 0x18, ...Buffer.from('ftypM4A '), 0, 0, 0, 0]);
    const uploads: UploadStore = {
      bucket: 'synthetic-isolated-bucket',
      presignPost: async () => ({ url: 'https://uploads.invalid', fields: {} }),
      head: async () => ({ sizeBytes: m4a.length, contentType: 'audio/mp4' }),
      firstBytes: async () => m4a,
      remove: vi.fn(async () => {}),
    };
    const transcriber: Transcriber = {
      start: vi.fn(async () => {}),
      get: vi.fn(async () => ({ status: 'COMPLETED' as const, transcriptUri: 'https://transcript.invalid' })),
      fetchTranscript: async () => 'Synthetic transcription only',
      remove: vi.fn(async () => {}),
    };
    const h = createAgentHarness(new ScriptedModel([]), { uploads, transcriber });
    if (prefix !== undefined) h.runner.transcriptionJobPrefix = prefix;
    const created = await h.call('POST /v1/cases', {}, { currency: 'USD', coverageMode: 'unknown', policy: null, planYears: {}, procedures: [] });
    const job = await h.call(
      'POST /v1/cases/{caseId}/jobs',
      { caseId: created.body.caseId },
      { expectedRevision: 1, operation: 'transcribe_audio', input: { documentId: 'synthetic-upload' } },
    );
    expect(job.status).toBe(202);
    await h.drain();
    const name = `${prefix ?? 'actionbridge-'}${job.body.jobId}`;
    expect(transcriber.start).toHaveBeenCalledWith(name, expect.stringContaining('s3://synthetic-isolated-bucket/'), 'm4a');
    expect(transcriber.get).toHaveBeenCalledWith(name);
    expect(transcriber.remove).toHaveBeenCalledWith(name);
    expect((await h.call('GET /v1/jobs/{jobId}', { jobId: job.body.jobId })).body).toMatchObject({
      status: 'completed',
      transcript: 'Synthetic transcription only',
    });
  });
});
