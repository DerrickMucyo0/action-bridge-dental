import { expect, test } from '@playwright/test';
import { readConfig } from '../src/config';
import { createApiClient, type ApiClient } from '../src/services/api';

const configured = {
  apiBaseUrl: 'https://api.test.invalid/staging',
  cognitoClientId: 'testclientid0123456789abcd',
  cognitoRegion: 'us-east-2',
};

for (const setting of [undefined, 'true', 'false']) {
  test(`background setting ${String(setting)} is explicit core opt-out with existing-mode compatibility`, () => {
    const result = readConfig({
      ...configured,
      backgroundJobsEnabled: setting,
    });
    expect(result.ok).toBe(true);
    if (result.ok)
      expect(result.config.backgroundJobsEnabled).toBe(setting !== 'false');
  });
}

for (const setting of ['no', '', '0']) {
  test(`malformed background setting ${JSON.stringify(setting)} fails configuration`, () => {
    const result = readConfig({
      ...configured,
      backgroundJobsEnabled: setting,
    });
    expect(result.ok).toBe(false);
    if (!result.ok)
      expect(result.problems).toContain(
        'VITE_BACKGROUND_JOBS_ENABLED must be true or false when set.',
      );
  });
}

const operations: [string, (api: ApiClient) => Promise<unknown>][] = [
  [
    'upload',
    (api) =>
      api.createUpload('case-synthetic', {
        kind: 'document',
        mimeType: 'application/pdf',
        sizeBytes: 100,
      }),
  ],
  [
    'interpret',
    (api) =>
      api.createJob('case-synthetic', {
        expectedRevision: 1,
        operation: 'interpret',
        input: {},
      }),
  ],
  [
    'transcribe',
    (api) =>
      api.createJob('case-synthetic', {
        expectedRevision: 1,
        operation: 'transcribe_audio',
        input: { documentId: 'upload-synthetic' },
      }),
  ],
  ['read job', (api) => api.getJob('job-synthetic')],
  [
    'answer job',
    (api) =>
      api.answerJob('job-synthetic', { expectedRevision: 1, answers: [] }),
  ],
  ['retry job', (api) => api.retryJob('job-synthetic')],
  ['cancel job', (api) => api.cancelJob('job-synthetic')],
  ['speech', (api) => api.speech('Synthetic test words')],
];

for (const [name, invoke] of operations) {
  test(`core mode blocks ${name} before credentials or network`, async () => {
    let tokens = 0;
    let requests = 0;
    const api = createApiClient({
      baseUrl: configured.apiBaseUrl,
      backgroundJobsEnabled: false,
      getAccessToken: async () => {
        tokens++;
        return 'synthetic';
      },
      fetchImpl: async () => {
        requests++;
        throw new Error('Network must not be called');
      },
    });
    await expect(invoke(api)).rejects.toMatchObject({
      code: 'FEATURE_UNAVAILABLE',
      options: { retryable: false },
    });
    expect(tokens).toBe(0);
    expect(requests).toBe(0);
  });
}

for (const enabled of [undefined, true]) {
  test(`enabled background mode ${String(enabled)} retains typed job transport`, async () => {
    const requests: { url: string; body: unknown }[] = [];
    const api = createApiClient({
      baseUrl: configured.apiBaseUrl,
      ...(enabled === undefined ? {} : { backgroundJobsEnabled: enabled }),
      getAccessToken: async () => 'synthetic',
      fetchImpl: async (input, init) => {
        requests.push({
          url: String(input),
          body: JSON.parse(String(init?.body)),
        });
        return new Response(JSON.stringify({ jobId: 'job-synthetic' }), {
          status: 202,
          headers: { 'content-type': 'application/json' },
        });
      },
    });
    const request = {
      expectedRevision: 1,
      operation: 'interpret' as const,
      input: {},
    };
    await expect(api.createJob('case-synthetic', request)).resolves.toEqual({
      jobId: 'job-synthetic',
    });
    expect(requests).toEqual([
      {
        url: configured.apiBaseUrl + '/v1/cases/case-synthetic/jobs',
        body: request,
      },
    ]);
  });
}
