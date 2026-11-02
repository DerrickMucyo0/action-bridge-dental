import { Socket } from 'node:net';
import { ConverseCommand, type BedrockRuntimeClientConfig } from '@aws-sdk/client-bedrock-runtime';
import { SynthesizeSpeechCommand, type PollyClientConfig } from '@aws-sdk/client-polly';
import { StartDocumentTextDetectionCommand, type TextractClientConfig } from '@aws-sdk/client-textract';
import { StartTranscriptionJobCommand, type TranscribeClientConfig } from '@aws-sdk/client-transcribe';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({
  clients: new Map<string, unknown>(),
  created: [] as unknown[],
  configs: new Map<string, { maxAttempts?: unknown; region?: unknown }>(),
  calls: new Map<string, number>(),
  // Deliberately fictional signing input used only with the in-memory transport.
  credentials: { accessKeyId: 'synthetic-key', secretAccessKey: 'synthetic-not-a-secret' },
}));

function transport(service: string) {
  return {
    async handle() {
      state.calls.set(service, (state.calls.get(service) ?? 0) + 1);
      return {
        response: {
          statusCode: 503,
          headers: { 'content-type': 'application/json', 'x-amzn-errortype': 'ThrottlingException' },
          body: new TextEncoder().encode(JSON.stringify({ __type: 'ThrottlingException', message: 'Synthetic throttling' })),
        },
      };
    },
    destroy() {},
  };
}

function remember(service: string, client: unknown, config: { maxAttempts?: unknown; region?: unknown }) {
  state.clients.set(service, client);
  state.created.push(client);
  state.configs.set(service, config);
}

vi.mock('@aws-sdk/client-bedrock-runtime', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@aws-sdk/client-bedrock-runtime')>();
  return { ...actual, BedrockRuntimeClient: class extends actual.BedrockRuntimeClient {
    constructor(config: BedrockRuntimeClientConfig = {}) {
      super({ ...config, region: config.region ?? 'us-east-2', credentials: state.credentials, requestHandler: transport('bedrock') });
      remember('bedrock', this, config);
    }
  } };
});

vi.mock('@aws-sdk/client-polly', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@aws-sdk/client-polly')>();
  return { ...actual, PollyClient: class extends actual.PollyClient {
    constructor(config: PollyClientConfig = {}) {
      super({ ...config, region: config.region ?? 'us-east-2', credentials: state.credentials, requestHandler: transport('polly') });
      remember('polly', this, config);
    }
  } };
});

vi.mock('@aws-sdk/client-textract', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@aws-sdk/client-textract')>();
  return { ...actual, TextractClient: class extends actual.TextractClient {
    constructor(config: TextractClientConfig = {}) {
      super({ ...config, region: config.region ?? 'us-east-2', credentials: state.credentials, requestHandler: transport('textract') });
      remember('textract', this, config);
    }
  } };
});

vi.mock('@aws-sdk/client-transcribe', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@aws-sdk/client-transcribe')>();
  return { ...actual, TranscribeClient: class extends actual.TranscribeClient {
    constructor(config: TranscribeClientConfig = {}) {
      super({ ...config, region: config.region ?? 'us-east-2', credentials: state.credentials, requestHandler: transport('transcribe') });
      remember('transcribe', this, config);
    }
  } };
});

type CapturedClient = {
  config: { maxAttempts: () => Promise<number> };
  send(command: unknown): Promise<unknown>;
  destroy(): void;
};

describe('deferred paid-service command attempts', () => {
  beforeAll(async () => {
    vi.spyOn(Socket.prototype, 'connect').mockImplementation(() => { throw new Error('Live network is forbidden in this test'); });
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => { throw new Error('Live fetch is forbidden in this test'); });
    for (const [name, value] of Object.entries({
      APP_ENV: 'staging', AUTH_MODE: 'jwt', TABLE_NAME: 'synthetic-only-table', RETENTION_DAYS: '7',
      JOB_QUEUE_URL: 'https://queues.test.invalid/staging-jobs', BEDROCK_MODEL_ID: 'synthetic-model',
      UPLOAD_BUCKET: 'synthetic-only-uploads', STAGING_ALLOWED_USER_SUBS: '00000000-0000-4000-8000-000000000001',
      TRANSCRIPTION_JOB_PREFIX: 'actionbridge-synthetic-staging_', AWS_MAX_ATTEMPTS: '9',
      AWS_RETRY_MODE: 'standard', AWS_EC2_METADATA_DISABLED: 'true',
    })) vi.stubEnv(name, value);
    vi.stubEnv('POLLY_REGION', undefined);
    vi.resetModules();
    // Jobs eagerly builds its actual clients. The empty local worker batch builds
    // its actual clients without running a job or sending any service command.
    await import('../src/functions/jobs.js');
    const worker = await import('../src/functions/job-worker.js');
    expect(await worker.handler({ Records: [] })).toEqual({ batchItemFailures: [] });
  });

  afterAll(() => {
    for (const client of state.created) (client as CapturedClient).destroy();
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  it.each([
    ['bedrock', () => new ConverseCommand({ modelId: 'synthetic-model', messages: [{ role: 'user', content: [{ text: 'Fictional offline test' }] }] })],
    ['polly', () => new SynthesizeSpeechCommand({ Text: 'Fictional offline test', OutputFormat: 'mp3', VoiceId: 'Joanna', Engine: 'neural' })],
    ['textract', () => new StartDocumentTextDetectionCommand({ DocumentLocation: { S3Object: { Bucket: 'synthetic-only-uploads', Name: 'fictional.pdf' } } })],
    ['transcribe', () => new StartTranscriptionJobCommand({ TranscriptionJobName: 'synthetic-only', LanguageCode: 'en-US', MediaFormat: 'm4a', Media: { MediaFileUri: 's3://synthetic-only-uploads/fictional.m4a' } })],
  ] as const)('%s sends exactly once even when the real SDK receives a retryable HTTP 503', async (service, command) => {
    const client = state.clients.get(service) as CapturedClient;
    expect(client).toBeDefined();
    expect(state.configs.get(service)?.maxAttempts).toBe(1);
    expect(await client.config.maxAttempts()).toBe(1); // Overrides AWS_MAX_ATTEMPTS=9.
    await expect(client.send(command())).rejects.toMatchObject({ $metadata: { httpStatusCode: 503, attempts: 1, totalRetryDelay: 0 } });
    expect(state.calls.get(service)).toBe(1);
  });

  it('preserves the existing default Polly region', () => {
    expect(state.configs.get('polly')?.region).toBe('us-east-1');
  });

  it('preserves an explicit Polly region override without increasing attempts', async () => {
    vi.stubEnv('POLLY_REGION', 'us-east-2');
    vi.resetModules();
    await import('../src/functions/jobs.js');
    expect(state.configs.get('polly')).toMatchObject({ region: 'us-east-2', maxAttempts: 1 });
    const client = state.clients.get('polly') as CapturedClient;
    expect(await client.config.maxAttempts()).toBe(1);
  });
});
