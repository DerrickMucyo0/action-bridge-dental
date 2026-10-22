import { comparePlans } from '@actionbridge/benefits-engine';
import {
  SavedPlanComparisonSchema,
  type ComparisonPlan,
  type PlanComparisonRequest,
  type SavedPlanComparison,
  type SavedPlanComparisonMetadata,
} from '@actionbridge/contracts';
import { GetCommand, QueryCommand, TransactWriteCommand } from '@aws-sdk/lib-dynamodb';
import { describe, expect, it } from 'vitest';
import { DynamoPlanComparisonRepository } from '../src/features/plan-comparisons/infrastructure/dynamo-plan-comparison-repository.js';
import type { PlanComparisonSave } from '../src/features/plan-comparisons/ports/plan-comparison-repository.js';
import type { DocumentClient } from '../src/shared/dynamo.js';
import { fixtureCreateRequest } from './helpers.js';

const OWNER = 'jwt:fictional-user-1';
const PK = 'USER#jwt%3Afictional-user-1#CASE#case-1';
const COMPARISON_ID = '20261003150000000-snapshot-1';

function snapshot(state: 'estimated' | 'needs_information' | 'unsupported' = 'estimated'): SavedPlanComparison {
  const input = fixtureCreateRequest();
  const plan = (planId: string): ComparisonPlan => ({
    planId,
    label: `Fictional ${planId}`,
    policy: structuredClone(input.policy),
    planYears: structuredClone(input.planYears),
    procedureFacts: Object.fromEntries(input.procedures.map((procedure) => [procedure.id, {
      category: procedure.category,
      network: procedure.network,
      allowedCents: procedure.allowedCents,
      contractualWriteoffCents: procedure.contractualWriteoffCents,
    }])),
    sourceFacts: [],
  });
  const request: PlanComparisonRequest = {
    caseId: 'case-1',
    expectedRevision: 1,
    currency: input.currency,
    treatment: {
      procedures: input.procedures.map((procedure) => {
        const { category, network, allowedCents, contractualWriteoffCents, proposedDate, selfPayQuote, ...shared } = procedure;
        return shared;
      }),
      schedule: input.procedures.map((procedure) => ({ procedureId: procedure.id, date: (procedure.proposedDate ?? procedure.dentistEarliestDate)! })),
      sourceFacts: [],
    },
    planA: plan('plan-a'),
    planB: plan('plan-b'),
  };
  request.planB.planYears['py-2026']!.insurerAlreadyPaidCents = 0;
  if (state === 'needs_information') request.planB.procedureFacts['crown-1']!.allowedCents = null;
  if (state === 'unsupported') request.planB.policy!.exclusions!.push({ id: 'fictional-exclusion', description: 'Fictional restriction', categoryIds: ['major'] });
  return SavedPlanComparisonSchema.parse({
    comparisonId: COMPARISON_ID,
    caseId: request.caseId,
    caseRevision: request.expectedRevision,
    request,
    result: comparePlans(request),
    savedAt: '2026-10-03T15:00:00.000Z',
  });
}

function metadataOf(comparison: SavedPlanComparison): SavedPlanComparisonMetadata {
  return {
    comparisonId: comparison.comparisonId,
    caseId: comparison.caseId,
    caseRevision: comparison.caseRevision,
    savedAt: comparison.savedAt,
    planALabel: comparison.request.planA.label,
    planBLabel: comparison.request.planB.label,
    planAStatus: comparison.result.planA.estimate.status,
    planBStatus: comparison.result.planB.estimate.status,
  };
}

function saveInput(comparison = snapshot()): PlanComparisonSave {
  return { ownerId: OWNER, idempotencyKey: 'fictional-save-key', requestFingerprint: 'fictional-input-hash', expectedRevision: 1, comparison, expiresAtEpochSeconds: 1_760_000_000 };
}

function stubClient(respond: (command: unknown) => unknown): DocumentClient & { sent: unknown[] } {
  const sent: unknown[] = [];
  return {
    sent,
    send: (async (command: unknown) => {
      sent.push(command);
      return respond(command);
    }) as DocumentClient['send'],
  };
}

function cancelled(...codes: string[]): Error {
  return Object.assign(new Error('Transaction cancelled'), {
    name: 'TransactionCanceledException', CancellationReasons: codes.map((Code) => ({ Code })),
  });
}

describe('DynamoPlanComparisonRepository', () => {
  it('atomically checks the case revision and reserves a separate idempotency key before writing one immutable snapshot', async () => {
    const client = stubClient(() => ({}));
    const input = saveInput();
    await expect(new DynamoPlanComparisonRepository(client, 'existing-table').saveComparison(input)).resolves.toBe('saved');
    expect(client.sent).toHaveLength(1);
    const command = client.sent[0] as TransactWriteCommand;
    expect(command).toBeInstanceOf(TransactWriteCommand);
    const items = command.input.TransactItems!;
    expect(items).toHaveLength(3);
    expect(items[0]?.ConditionCheck).toEqual({
      TableName: 'existing-table', Key: { pk: PK, sk: 'CASE' },
      ConditionExpression: 'caseRevision = :expected', ExpressionAttributeValues: { ':expected': 1 },
    });
    expect(items[1]?.Put).toEqual({
      TableName: 'existing-table',
      ConditionExpression: 'attribute_not_exists(pk)',
      Item: {
        pk: PK, sk: 'PLAN_COMPARISON_IDEMPOTENCY#fictional-save-key', comparisonId: COMPARISON_ID,
        caseRevision: 1, requestFingerprint: 'fictional-input-hash', expiresAt: 1_760_000_000,
      },
    });
    expect(items[2]?.Put).toEqual({
      TableName: 'existing-table', ConditionExpression: 'attribute_not_exists(pk)',
      Item: {
        pk: PK, sk: `PLAN_COMPARISON#1#${COMPARISON_ID}`, comparison: input.comparison,
        metadata: metadataOf(input.comparison), expiresAt: 1_760_000_000,
      },
    });
    expect(input.comparison.request.planB.procedureFacts).not.toBe(input.comparison.request.planA.procedureFacts);
    expect(input.comparison.request.planA.planYears['py-2026']!.insurerAlreadyPaidCents)
      .not.toBe(input.comparison.request.planB.planYears['py-2026']!.insurerAlreadyPaidCents);
  });

  it('omits TTL on both rows when retention is disabled', async () => {
    const client = stubClient(() => ({}));
    await new DynamoPlanComparisonRepository(client, 't').saveComparison({ ...saveInput(), expiresAtEpochSeconds: null });
    const items = (client.sent[0] as TransactWriteCommand).input.TransactItems!;
    expect(items[1]?.Put?.Item).not.toHaveProperty('expiresAt');
    expect(items[2]?.Put?.Item).not.toHaveProperty('expiresAt');
  });

  it.each([
    ['revision_conflict', ['ConditionalCheckFailed', 'None', 'None']],
    ['idempotency_key_taken', ['None', 'ConditionalCheckFailed', 'None']],
  ] as const)('maps only the expected transaction condition to %s', async (outcome, codes) => {
    const client = stubClient(() => Promise.reject(cancelled(...codes)));
    await expect(new DynamoPlanComparisonRepository(client, 't').saveComparison(saveInput())).resolves.toBe(outcome);
  });

  it('rejects a snapshot whose revision differs from the atomic case condition before writing', async () => {
    const client = stubClient(() => ({}));
    await expect(new DynamoPlanComparisonRepository(client, 't').saveComparison({ ...saveInput(), expectedRevision: 2 })).resolves.toBe('revision_conflict');
    expect(client.sent).toHaveLength(0);
  });

  it('propagates collisions on the immutable snapshot and operational storage failures', async () => {
    for (const error of [cancelled('None', 'None', 'ConditionalCheckFailed'), new Error('Storage unavailable')]) {
      const client = stubClient(() => Promise.reject(error));
      await expect(new DynamoPlanComparisonRepository(client, 't').saveComparison(saveInput())).rejects.toBe(error);
    }
  });

  it('reads only the owner, case, revision and comparison ID using a strongly consistent direct get', async () => {
    const stored = snapshot();
    const client = stubClient(() => ({ Item: { comparison: stored } }));
    await expect(new DynamoPlanComparisonRepository(client, 't').getComparison(OWNER, 'case-1', 1, COMPARISON_ID)).resolves.toEqual(stored);
    const command = client.sent[0] as GetCommand;
    expect(command).toBeInstanceOf(GetCommand);
    expect(command.input).toEqual({ TableName: 't', Key: { pk: PK, sk: `PLAN_COMPARISON#1#${COMPARISON_ID}` }, ConsistentRead: true });

    await new DynamoPlanComparisonRepository(client, 't').getComparison('jwt:other#CASE#case-1', 'case-1', 2, COMPARISON_ID);
    expect((client.sent[1] as GetCommand).input.Key).toEqual({
      pk: 'USER#jwt%3Aother%23CASE%23case-1#CASE#case-1', sk: `PLAN_COMPARISON#2#${COMPARISON_ID}`,
    });
  });

  it('returns null for missing or identity-mismatched snapshots and rejects malformed storage data', async () => {
    const missing = new DynamoPlanComparisonRepository(stubClient(() => ({})), 't');
    await expect(missing.getComparison(OWNER, 'case-1', 1, COMPARISON_ID)).resolves.toBeNull();

    const stored = snapshot();
    const repo = new DynamoPlanComparisonRepository(stubClient(() => ({ Item: { comparison: stored } })), 't');
    await expect(repo.getComparison(OWNER, 'another-case', 1, COMPARISON_ID)).resolves.toBeNull();
    await expect(repo.getComparison(OWNER, 'case-1', 2, COMPARISON_ID)).resolves.toBeNull();
    await expect(repo.getComparison(OWNER, 'case-1', 1, 'another-comparison')).resolves.toBeNull();

    const corrupt = new DynamoPlanComparisonRepository(stubClient(() => ({ Item: { comparison: { ...stored, caseRevision: 2 } } })), 't');
    await expect(corrupt.getComparison(OWNER, 'case-1', 1, COMPARISON_ID)).rejects.toThrow();
  });

  it.each(['needs_information', 'unsupported'] as const)('reopens %s without losing unknown facts or inventing a difference', async (status) => {
    const stored = snapshot(status);
    const client = stubClient(() => ({ Item: { comparison: stored } }));
    const reopened = await new DynamoPlanComparisonRepository(client, 't').getComparison(OWNER, 'case-1', 1, COMPARISON_ID);
    expect(reopened).toEqual(stored);
    expect(reopened?.result.planA.estimate.status).toBe('estimated');
    expect(reopened?.result.planB.estimate.status).toBe(status);
    expect(reopened?.result.planBMinusPlanACents).toBeNull();
    if (status === 'needs_information') expect(reopened?.request.planB.procedureFacts['crown-1']!.allowedCents).toBeNull();
  });

  it('lists at most 20 of the current revision, newest first, projecting metadata without case facts or costs', async () => {
    const older = metadataOf(snapshot());
    const newer = { ...older, comparisonId: '20261003150001000-snapshot-2', savedAt: '2026-10-03T15:00:01.000Z' };
    const client = stubClient(() => ({ Items: [{ metadata: newer }, { metadata: older }] }));
    await expect(new DynamoPlanComparisonRepository(client, 't').listComparisonsForCase(OWNER, 'case-1', 1)).resolves.toEqual([newer, older]);
    const command = client.sent[0] as QueryCommand;
    expect(command).toBeInstanceOf(QueryCommand);
    expect(command.input).toEqual({
      TableName: 't', KeyConditionExpression: 'pk = :pk AND begins_with(sk, :prefix)',
      ExpressionAttributeValues: { ':pk': PK, ':prefix': 'PLAN_COMPARISON#1#' },
      ProjectionExpression: '#metadata', ExpressionAttributeNames: { '#metadata': 'metadata' },
      ScanIndexForward: false, Limit: 20, ConsistentRead: true,
    });
    expect(newer).not.toHaveProperty('request');
    expect(newer).not.toHaveProperty('result');
  });

  it('validates metadata and filters unexpected case or revision identities', async () => {
    const metadata = metadataOf(snapshot());
    const client = stubClient(() => ({ Items: [
      { metadata }, { metadata: { ...metadata, caseId: 'foreign-case' } }, { metadata: { ...metadata, caseRevision: 2 } },
    ] }));
    await expect(new DynamoPlanComparisonRepository(client, 't').listComparisonsForCase(OWNER, 'case-1', 1)).resolves.toEqual([metadata]);
    const missing = new DynamoPlanComparisonRepository(stubClient(() => ({})), 't');
    await expect(missing.listComparisonsForCase(OWNER, 'case-1', 1)).resolves.toEqual([]);
    const corrupt = new DynamoPlanComparisonRepository(stubClient(() => ({ Items: [{ metadata: { ...metadata, planBStatus: 'winner' } }] })), 't');
    await expect(corrupt.listComparisonsForCase(OWNER, 'case-1', 1)).rejects.toThrow();
  });

  it('reads and validates only the idempotency reference, scoped separately to the owner’s case', async () => {
    const reference = { comparisonId: COMPARISON_ID, caseRevision: 1, requestFingerprint: 'fictional-input-hash' };
    const client = stubClient(() => ({ Item: { pk: PK, ...reference, expiresAt: 1_760_000_000 } }));
    await expect(new DynamoPlanComparisonRepository(client, 't').findComparisonByIdempotencyKey(OWNER, 'case-1', 'save-key')).resolves.toEqual(reference);
    expect((client.sent[0] as GetCommand).input).toEqual({
      TableName: 't', Key: { pk: PK, sk: 'PLAN_COMPARISON_IDEMPOTENCY#save-key' }, ConsistentRead: true,
    });
    const missing = new DynamoPlanComparisonRepository(stubClient(() => ({})), 't');
    await expect(missing.findComparisonByIdempotencyKey(OWNER, 'case-1', 'save-key')).resolves.toBeNull();
    const corrupt = new DynamoPlanComparisonRepository(stubClient(() => ({ Item: { ...reference, requestFingerprint: null } })), 't');
    await expect(corrupt.findComparisonByIdempotencyKey(OWNER, 'case-1', 'save-key')).rejects.toThrow();
  });

  it('propagates failures from retrieval, metadata queries and idempotency lookups', async () => {
    const error = new Error('Storage unavailable');
    const repo = new DynamoPlanComparisonRepository(stubClient(() => Promise.reject(error)), 't');
    await expect(repo.getComparison(OWNER, 'case-1', 1, COMPARISON_ID)).rejects.toBe(error);
    await expect(repo.listComparisonsForCase(OWNER, 'case-1', 1)).rejects.toBe(error);
    await expect(repo.findComparisonByIdempotencyKey(OWNER, 'case-1', 'save-key')).rejects.toBe(error);
  });
});
