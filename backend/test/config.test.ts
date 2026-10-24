import { describe, expect, it } from 'vitest';
import { loadConfig } from '../src/shared/config.js';

// Synthetic UUIDs: no account, email or token values.
const APPROVED = '11111111-1111-4111-8111-111111111111';
const SECOND = '22222222-2222-4222-8222-222222222222';
const stagingEnv = {
  APP_ENV: 'staging',
  AUTH_MODE: 'jwt',
  STAGING_ALLOWED_USER_SUBS: APPROVED,
};

describe('environment configuration', () => {
  it.each(['local', 'dev', 'demo'])(
    'preserves %s configuration without staging settings',
    (appEnv) => {
      const config = loadConfig({ APP_ENV: appEnv, AUTH_MODE: 'demo' });
      expect(config).toEqual({
        appEnv,
        authMode: 'demo',
        tableName: null,
        retentionDays: null,
        jobQueueUrl: null,
        bedrockModelId: null,
        uploadBucket: null,
        staging: null,
      });
    },
  );

  it('preserves explicitly configured existing JWT resources and retention', () => {
    expect(
      loadConfig({
        APP_ENV: 'dev',
        AUTH_MODE: 'jwt',
        TABLE_NAME: 'isolated-table',
        RETENTION_DAYS: '7',
        JOB_QUEUE_URL:
          'https://sqs.us-east-2.amazonaws.com/000000000000/fictional',
        BEDROCK_MODEL_ID: 'us.amazon.nova-2-lite-v1:0',
        UPLOAD_BUCKET: 'isolated-uploads',
      }),
    ).toMatchObject({
      appEnv: 'dev',
      authMode: 'jwt',
      tableName: 'isolated-table',
      retentionDays: 7,
      jobQueueUrl: 'https://sqs.us-east-2.amazonaws.com/000000000000/fictional',
      bedrockModelId: 'us.amazon.nova-2-lite-v1:0',
      uploadBucket: 'isolated-uploads',
      staging: null,
    });
  });

  it('does not activate staging restrictions outside staging', () => {
    expect(
      loadConfig({
        APP_ENV: 'demo',
        AUTH_MODE: 'jwt',
        STAGING_ALLOWED_USER_SUBS: 'not-a-uuid',
        STAGING_JOB_DAILY_LIMIT: 'invalid',
      }).staging,
    ).toBeNull();
  });

  it('loads restrictive staging defaults and approved identities', () => {
    expect(loadConfig(stagingEnv).staging).toEqual({
      allowedUserSubs: [APPROVED],
      jobDailyLimit: 10,
      uploadDailyLimit: 10,
      speechDailyLimit: 30,
      globalJobDailyLimit: 20,
      globalUploadDailyLimit: 20,
      globalSpeechDailyLimit: 60,
    });
  });

  it('accepts an explicit bounded staging quota and trims the approval list', () => {
    expect(
      loadConfig({
        ...stagingEnv,
        STAGING_ALLOWED_USER_SUBS: ` ${APPROVED}, ${SECOND} `,
        STAGING_JOB_DAILY_LIMIT: '2',
        STAGING_GLOBAL_JOB_DAILY_LIMIT: '3',
      }).staging,
    ).toMatchObject({
      allowedUserSubs: [APPROVED, SECOND],
      jobDailyLimit: 2,
      globalJobDailyLimit: 3,
    });
  });

  it('rejects demo authentication in staging', () => {
    expect(() => loadConfig({ ...stagingEnv, AUTH_MODE: 'demo' })).toThrow();
  });

  it.each([
    undefined,
    '',
    ' ',
    '*',
    'tester@example.invalid',
    `${APPROVED},`,
    `${APPROVED},${APPROVED}`,
  ])('rejects absent, malformed or duplicate approvals: %s', (subs) => {
    expect(() =>
      loadConfig({ ...stagingEnv, STAGING_ALLOWED_USER_SUBS: subs }),
    ).toThrow();
  });

  it('rejects more than ten approved identities', () => {
    const subs = Array.from(
      { length: 11 },
      (_, i) => `${String(i).padStart(8, '0')}-1111-4111-8111-111111111111`,
    );
    expect(() =>
      loadConfig({ ...stagingEnv, STAGING_ALLOWED_USER_SUBS: subs.join(',') }),
    ).toThrow();
  });

  it.each([
    'STAGING_JOB_DAILY_LIMIT',
    'STAGING_UPLOAD_DAILY_LIMIT',
    'STAGING_SPEECH_DAILY_LIMIT',
    'STAGING_GLOBAL_JOB_DAILY_LIMIT',
    'STAGING_GLOBAL_UPLOAD_DAILY_LIMIT',
    'STAGING_GLOBAL_SPEECH_DAILY_LIMIT',
  ])('rejects unsafe %s limits rather than silently disabling them', (name) => {
    for (const value of ['', '0', '-1', '1.5', 'NaN', 'Infinity', '1001']) {
      expect(() => loadConfig({ ...stagingEnv, [name]: value })).toThrow();
    }
    const maximum = name.startsWith('STAGING_GLOBAL_') ? 1000 : 100;
    expect(() =>
      loadConfig({ ...stagingEnv, [name]: String(maximum + 1) }),
    ).toThrow();
    expect(() =>
      loadConfig({ ...stagingEnv, [name]: String(maximum) }),
    ).not.toThrow();
  });

  it.each([
    {},
    { APP_ENV: 'production', AUTH_MODE: 'jwt' },
    { APP_ENV: 'dev', AUTH_MODE: 'unknown' },
  ])(
    'continues failing closed for missing or unsupported base settings',
    (env) => {
      expect(() => loadConfig(env)).toThrow();
    },
  );
});
