import { randomUUID } from 'node:crypto';
import { BedrockRuntimeClient } from '@aws-sdk/client-bedrock-runtime';
import { S3Client } from '@aws-sdk/client-s3';
import { TextractClient } from '@aws-sdk/client-textract';
import { TranscribeClient } from '@aws-sdk/client-transcribe';
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { DynamoDBDocumentClient } from '@aws-sdk/lib-dynamodb';
import { z } from 'zod';
import { runJob, type JobRunnerDeps } from '../features/agent-jobs/application/job-runner.js';
import { BedrockAgentModel, DynamoJobRepository } from '../features/agent-jobs/infrastructure/aws.js';
import { AwsTranscriber, S3UploadStore, TextractReader } from '../features/agent-jobs/infrastructure/aws-inputs.js';
import { DynamoCaseRepository } from '../features/cases/infrastructure/dynamo-case-repository.js';
import { loadConfig, requireBedrockModelId, requireTableName, requireUploadBucket, type AppConfig } from '../shared/config.js';
import { logEvent, safeErrorName } from '../shared/logger.js';
import { assertApprovedStagingOwner } from '../shared/staging-controls.js';

const MessageSchema = z.object({ ownerId: z.string().min(1).max(300), jobId: z.string().min(1).max(64) });

interface SqsEvent {
  Records: { messageId: string; body: string }[];
}

interface WorkerRuntime {
  deps: JobRunnerDeps;
  assertOwnerAllowed: (ownerId: string) => void;
}

/** Staging job names must match the stack-scoped IAM namespace; no broad fallback is allowed. */
export function stagingTranscriptionJobPrefix(config: Pick<AppConfig, 'appEnv'>, env: Record<string, string | undefined>): string | undefined {
  if (config.appEnv !== 'staging') return undefined;
  const prefix = env.TRANSCRIPTION_JOB_PREFIX;
  // Stack names cannot contain underscores, so the final delimiter prevents overlapping stack prefixes.
  // CloudFormation stack names start with a letter and contain at most 128 letters/digits/hyphens.
  if (!prefix || !/^actionbridge-[A-Za-z][A-Za-z0-9-]{0,127}_$/.test(prefix)) {
    throw new Error('Staging transcription job prefix is not configured correctly');
  }
  return prefix;
}

function build(): WorkerRuntime {
  const config = loadConfig(process.env);
  const transcriptionJobPrefix = stagingTranscriptionJobPrefix(config, process.env);
  const documentClient = DynamoDBDocumentClient.from(new DynamoDBClient({}), { marshallOptions: { removeUndefinedValues: true } });
  const table = requireTableName(config);
  return {
    assertOwnerAllowed: (ownerId) => {
      if (config.staging) assertApprovedStagingOwner(config.staging, ownerId);
    },
    deps: {
      jobs: new DynamoJobRepository(documentClient, table),
      cases: new DynamoCaseRepository(documentClient, table),
      model: new BedrockAgentModel(new BedrockRuntimeClient({ maxAttempts: 1 }), requireBedrockModelId(config)),
      now: () => new Date(),
      newId: randomUUID,
      retentionDays: config.retentionDays,
      leaseMs: 300_000, // Longer than the worker timeout (240 s), so a running job is never reclaimed.
      uploads: new S3UploadStore(new S3Client({}), requireUploadBucket(config)),
      transcriber: new AwsTranscriber(new TranscribeClient({ maxAttempts: 1 })),
      ...(transcriptionJobPrefix ? { transcriptionJobPrefix } : {}),
      reader: new TextractReader(new TextractClient({ maxAttempts: 1 })),
    },
  };
}

/**
 * SQS worker (batch size 1). Malformed messages are dropped and logged; unexpected errors are
 * reported as batch item failures so SQS redelivers, then the dead-letter queue keeps them.
 */
export function createJobWorkerHandler(buildRuntime: () => WorkerRuntime) {
  let runtime: WorkerRuntime | null = null;
  return async (event: SqsEvent) => {
    runtime ??= buildRuntime();
    const batchItemFailures: { itemIdentifier: string }[] = [];
    for (const record of event.Records) {
      let message: z.infer<typeof MessageSchema>;
      try {
        message = MessageSchema.parse(JSON.parse(record.body));
      } catch {
        logEvent('warn', 'job_message_malformed', { messageId: record.messageId });
        continue;
      }
      // The queue is trusted infrastructure, but approval can be removed after a job was queued.
      try {
        runtime.assertOwnerAllowed(message.ownerId);
      } catch {
        logEvent('warn', 'job_owner_not_approved', { messageId: record.messageId });
        continue;
      }
      const started = Date.now();
      try {
        const outcome = await runJob(runtime.deps, message);
        logEvent('info', 'job_processed', { jobId: message.jobId, outcome, durationMs: Date.now() - started });
      } catch (error) {
        logEvent('error', 'job_worker_error', { jobId: message.jobId, errorName: safeErrorName(error) });
        batchItemFailures.push({ itemIdentifier: record.messageId });
      }
    }
    return { batchItemFailures };
  };
}

export const handler = createJobWorkerHandler(build);
