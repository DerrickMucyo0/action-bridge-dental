import { z } from 'zod';
import type { AuthMode } from './auth.js';

const EnvSchema = z.object({
  APP_ENV: z.enum(['local', 'dev', 'demo', 'staging']),
  AUTH_MODE: z.enum(['jwt', 'demo']),
  TABLE_NAME: z.string().min(1).optional(),
  /** Demo data expires via DynamoDB TTL (eventual deletion, not an immediate-delete guarantee). */
  RETENTION_DAYS: z.coerce.number().int().min(1).max(90).optional(),
  JOB_QUEUE_URL: z.string().url().optional(),
  /** Bedrock model or inference profile ID, e.g. us.anthropic.claude-haiku-4-5-20251001-v1:0. */
  BEDROCK_MODEL_ID: z.string().min(1).optional(),
  /** Private bucket for voice notes and documents (short lifecycle). */
  UPLOAD_BUCKET: z.string().min(3).optional(),
});

export interface StagingConfig {
  allowedUserSubs: string[];
  jobDailyLimit: number;
  uploadDailyLimit: number;
  speechDailyLimit: number;
  globalJobDailyLimit: number;
  globalUploadDailyLimit: number;
  globalSpeechDailyLimit: number;
}

// Cognito sub values are UUIDs. Email addresses and arbitrary client-supplied IDs are not approvals.
const CognitoSub = z
  .string()
  .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
const StagingEnvSchema = z.object({
  AUTH_MODE: z.literal('jwt'),
  STAGING_ALLOWED_USER_SUBS: z
    .string()
    .transform((value) => value.split(',').map((sub) => sub.trim()))
    .pipe(
      z
        .array(CognitoSub)
        .min(1)
        .max(10)
        .refine(
          (subs) => new Set(subs).size === subs.length,
          'Duplicate approved user sub',
        ),
    ),
  STAGING_JOB_DAILY_LIMIT: z.coerce.number().int().min(1).max(100).default(10),
  STAGING_UPLOAD_DAILY_LIMIT: z.coerce
    .number()
    .int()
    .min(1)
    .max(100)
    .default(10),
  STAGING_SPEECH_DAILY_LIMIT: z.coerce
    .number()
    .int()
    .min(1)
    .max(100)
    .default(30),
  STAGING_GLOBAL_JOB_DAILY_LIMIT: z.coerce
    .number()
    .int()
    .min(1)
    .max(1000)
    .default(20),
  STAGING_GLOBAL_UPLOAD_DAILY_LIMIT: z.coerce
    .number()
    .int()
    .min(1)
    .max(1000)
    .default(20),
  STAGING_GLOBAL_SPEECH_DAILY_LIMIT: z.coerce
    .number()
    .int()
    .min(1)
    .max(1000)
    .default(60),
});

export interface AppConfig {
  appEnv: 'local' | 'dev' | 'demo' | 'staging';
  authMode: AuthMode;
  tableName: string | null;
  retentionDays: number | null;
  jobQueueUrl: string | null;
  bedrockModelId: string | null;
  uploadBucket: string | null;
  staging: StagingConfig | null;
}

/** Fails closed: a missing or unknown setting is a configuration error, never a silent default. */
export function loadConfig(env: Record<string, string | undefined>): AppConfig {
  const parsed = EnvSchema.parse(env);
  const staging =
    parsed.APP_ENV === 'staging' ? StagingEnvSchema.parse(env) : null;
  return {
    appEnv: parsed.APP_ENV,
    authMode: parsed.AUTH_MODE,
    tableName: parsed.TABLE_NAME ?? null,
    retentionDays: parsed.RETENTION_DAYS ?? null,
    jobQueueUrl: parsed.JOB_QUEUE_URL ?? null,
    bedrockModelId: parsed.BEDROCK_MODEL_ID ?? null,
    uploadBucket: parsed.UPLOAD_BUCKET ?? null,
    staging:
      staging === null
        ? null
        : {
            allowedUserSubs: staging.STAGING_ALLOWED_USER_SUBS,
            jobDailyLimit: staging.STAGING_JOB_DAILY_LIMIT,
            uploadDailyLimit: staging.STAGING_UPLOAD_DAILY_LIMIT,
            speechDailyLimit: staging.STAGING_SPEECH_DAILY_LIMIT,
            globalJobDailyLimit: staging.STAGING_GLOBAL_JOB_DAILY_LIMIT,
            globalUploadDailyLimit: staging.STAGING_GLOBAL_UPLOAD_DAILY_LIMIT,
            globalSpeechDailyLimit: staging.STAGING_GLOBAL_SPEECH_DAILY_LIMIT,
          },
  };
}

function required<T>(value: T | null, name: string): T {
  if (value === null) throw new Error(`${name} is not configured`);
  return value;
}

export const requireTableName = (config: AppConfig) =>
  required(config.tableName, 'TABLE_NAME');
export const requireJobQueueUrl = (config: AppConfig) =>
  required(config.jobQueueUrl, 'JOB_QUEUE_URL');
export const requireBedrockModelId = (config: AppConfig) =>
  required(config.bedrockModelId, 'BEDROCK_MODEL_ID');
export const requireUploadBucket = (config: AppConfig) =>
  required(config.uploadBucket, 'UPLOAD_BUCKET');
