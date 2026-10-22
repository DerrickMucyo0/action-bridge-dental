import {
  SavedPlanComparisonMetadataSchema,
  SavedPlanComparisonSchema,
  type SavedPlanComparison,
  type SavedPlanComparisonMetadata,
} from '@actionbridge/contracts';
import { GetCommand, QueryCommand, TransactWriteCommand } from '@aws-sdk/lib-dynamodb';
import { z } from 'zod';
import { caseKey, casePartition, isConditionFailure, ttl, type DocumentClient } from '../../../shared/dynamo.js';
import type {
  ComparisonIdempotencyRecord,
  ComparisonSaveOutcome,
  PlanComparisonRepository,
  PlanComparisonSave,
} from '../ports/plan-comparison-repository.js';

const IdempotencyRecordSchema = z.object({
  comparisonId: SavedPlanComparisonSchema.shape.comparisonId,
  caseRevision: SavedPlanComparisonSchema.shape.caseRevision,
  requestFingerprint: z.string().min(1),
});

/** Uses the existing table and case partition; no separate personal-data or result index. */
export class DynamoPlanComparisonRepository implements PlanComparisonRepository {
  constructor(
    private readonly client: DocumentClient,
    private readonly tableName: string,
  ) {}

  async findComparisonByIdempotencyKey(ownerId: string, caseId: string, key: string): Promise<ComparisonIdempotencyRecord | null> {
    const output = await this.client.send(new GetCommand({
      TableName: this.tableName,
      Key: idempotencyKey(ownerId, caseId, key),
      ConsistentRead: true,
    }));
    return output.Item === undefined ? null : IdempotencyRecordSchema.parse(output.Item);
  }

  async saveComparison(input: PlanComparisonSave): Promise<ComparisonSaveOutcome> {
    const { ownerId, comparison, expiresAtEpochSeconds } = input;
    if (comparison.caseRevision !== input.expectedRevision) return 'revision_conflict';
    const metadata = metadataOf(comparison);
    try {
      await this.client.send(new TransactWriteCommand({
        TransactItems: [
          {
            ConditionCheck: {
              TableName: this.tableName,
              Key: caseKey(ownerId, comparison.caseId),
              ConditionExpression: 'caseRevision = :expected',
              ExpressionAttributeValues: { ':expected': input.expectedRevision },
            },
          },
          {
            Put: {
              TableName: this.tableName,
              Item: {
                ...idempotencyKey(ownerId, comparison.caseId, input.idempotencyKey),
                comparisonId: comparison.comparisonId,
                caseRevision: comparison.caseRevision,
                requestFingerprint: input.requestFingerprint,
                ...ttl(expiresAtEpochSeconds),
              },
              ConditionExpression: 'attribute_not_exists(pk)',
            },
          },
          {
            Put: {
              TableName: this.tableName,
              Item: {
                ...snapshotKey(ownerId, comparison.caseId, comparison.caseRevision, comparison.comparisonId),
                comparison,
                metadata,
                ...ttl(expiresAtEpochSeconds),
              },
              ConditionExpression: 'attribute_not_exists(pk)',
            },
          },
        ],
      }));
      return 'saved';
    } catch (error) {
      if (isConditionFailure(error, 0)) return 'revision_conflict';
      if (isConditionFailure(error, 1)) return 'idempotency_key_taken';
      throw error;
    }
  }

  async getComparison(ownerId: string, caseId: string, caseRevision: number, comparisonId: string): Promise<SavedPlanComparison | null> {
    const output = await this.client.send(new GetCommand({
      TableName: this.tableName,
      Key: snapshotKey(ownerId, caseId, caseRevision, comparisonId),
      ConsistentRead: true,
    }));
    if (output.Item === undefined) return null;
    const comparison = SavedPlanComparisonSchema.parse(output.Item.comparison);
    return comparison.caseId === caseId && comparison.caseRevision === caseRevision && comparison.comparisonId === comparisonId
      ? comparison
      : null;
  }

  async listComparisonsForCase(ownerId: string, caseId: string, caseRevision: number): Promise<SavedPlanComparisonMetadata[]> {
    const output = await this.client.send(new QueryCommand({
      TableName: this.tableName,
      KeyConditionExpression: 'pk = :pk AND begins_with(sk, :prefix)',
      ExpressionAttributeValues: {
        ':pk': casePartition(ownerId, caseId),
        ':prefix': `PLAN_COMPARISON#${caseRevision}#`,
      },
      ProjectionExpression: '#metadata',
      ExpressionAttributeNames: { '#metadata': 'metadata' },
      ScanIndexForward: false,
      Limit: 20,
      ConsistentRead: true,
    }));
    return (output.Items ?? [])
      .map((item) => SavedPlanComparisonMetadataSchema.parse(item.metadata))
      .filter((metadata) => metadata.caseId === caseId && metadata.caseRevision === caseRevision);
  }
}

function snapshotKey(ownerId: string, caseId: string, caseRevision: number, comparisonId: string): { pk: string; sk: string } {
  return { pk: casePartition(ownerId, caseId), sk: `PLAN_COMPARISON#${caseRevision}#${comparisonId}` };
}

function idempotencyKey(ownerId: string, caseId: string, key: string): { pk: string; sk: string } {
  return { pk: casePartition(ownerId, caseId), sk: `PLAN_COMPARISON_IDEMPOTENCY#${key}` };
}

function metadataOf(comparison: SavedPlanComparison): SavedPlanComparisonMetadata {
  return SavedPlanComparisonMetadataSchema.parse({
    comparisonId: comparison.comparisonId,
    caseId: comparison.caseId,
    caseRevision: comparison.caseRevision,
    savedAt: comparison.savedAt,
    planALabel: comparison.request.planA.label,
    planBLabel: comparison.request.planB.label,
    planAStatus: comparison.result.planA.estimate.status,
    planBStatus: comparison.result.planB.estimate.status,
  });
}
