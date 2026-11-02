import { PutCommand } from '@aws-sdk/lib-dynamodb';
import { describe, expect, it } from 'vitest';
import { DynamoJobRepository } from '../src/features/agent-jobs/infrastructure/aws.js';
import { InMemoryJobRepository } from '../src/features/agent-jobs/infrastructure/in-memory.js';
import type { JobRecord } from '../src/features/agent-jobs/ports.js';
import type { DocumentClient } from '../src/shared/dynamo.js';

function job(attempt = 0): JobRecord {
  return {
    jobId: 'synthetic-job', ownerId: 'demo:synthetic-owner', caseId: 'synthetic-case', caseRevision: 1,
    operation: 'interpret', status: 'queued', attempt, maxAttempts: 3, inputText: null,
    events: [], questions: null, resultBlocks: null, error: null, proposals: [],
    leaseToken: null, leaseUntil: null, createdAt: '2026-10-30T22:00:00.000Z', updatedAt: '2026-10-30T22:00:00.000Z',
  };
}

describe('job attempt write conditions', () => {
  it('checks the existing nested attempt, including zero, alongside status and lease in DynamoDB', async () => {
    const sent: PutCommand[] = [];
    const client: DocumentClient = { send: (async (command: PutCommand) => { sent.push(command); return {}; }) as DocumentClient['send'] };
    const next = { ...job(), status: 'failed' as const };
    await expect(new DynamoJobRepository(client, 'synthetic-table').put(next, { status: ['queued'], leaseToken: 'current-lease', attempt: 0 }, null)).resolves.toBe(true);

    expect(sent).toHaveLength(1);
    expect(sent[0]).toBeInstanceOf(PutCommand);
    expect(sent[0]!.input).toMatchObject({
      ConditionExpression: 'attribute_exists(pk) AND #status IN (:s0) AND leaseToken = :lease AND #job.#attempt = :attempt',
      ExpressionAttributeNames: { '#status': 'status', '#job': 'job', '#attempt': 'attempt' },
      ExpressionAttributeValues: { ':s0': 'queued', ':lease': 'current-lease', ':attempt': 0 },
      Item: { pk: 'USER#demo%3Asynthetic-owner#JOB#synthetic-job', sk: 'JOB', job: next },
    });
    expect(sent[0]!.input.Item).not.toHaveProperty('attempt');
  });

  it('returns false on a failed DynamoDB attempt condition without retrying the write', async () => {
    let writes = 0;
    const error = Object.assign(new Error('condition no longer holds'), { name: 'ConditionalCheckFailedException' });
    const client: DocumentClient = { send: (async () => { writes++; throw error; }) as DocumentClient['send'] };
    await expect(new DynamoJobRepository(client, 'synthetic-table').put(job(), { status: ['queued'], attempt: 0 }, null)).resolves.toBe(false);
    expect(writes).toBe(1);
  });

  it('preserves the newer in-memory attempt when the same queued status recurs', async () => {
    const repo = new InMemoryJobRepository();
    await repo.create(job(1));
    expect(await repo.put(job(2), { status: ['queued'], attempt: 1 })).toBe(true);
    expect(await repo.put({ ...job(1), status: 'failed' }, { status: ['queued'], attempt: 1 })).toBe(false);
    expect(await repo.get(job().ownerId, job().jobId)).toEqual(job(2));
  });
});
