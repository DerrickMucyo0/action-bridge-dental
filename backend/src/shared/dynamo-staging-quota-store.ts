import { createHash } from 'node:crypto';
import { TransactWriteCommand } from '@aws-sdk/lib-dynamodb';
import { isConditionFailure, type DocumentClient } from './dynamo.js';
import { HttpError } from './http.js';
import type { StagingOperation, StagingQuotaStore } from './staging-controls.js';

/** No in-process counters: concurrent Lambda instances share atomic DynamoDB transactions. */
export class DynamoStagingQuotaStore implements StagingQuotaStore {
  constructor(
    private readonly client: DocumentClient,
    private readonly tableName: string,
  ) {}

  async consume(ownerId: string, operation: StagingOperation, limits: { user: number; global: number }, now: Date): Promise<void> {
    const day = now.toISOString().slice(0, 10);
    const ownerHash = createHash('sha256').update(ownerId).digest('hex');
    // Keys, not eventual TTL removal, determine the daily reset. Keep counters two days beyond it.
    const expiresAt = Math.floor(Date.parse(`${day}T00:00:00.000Z`) / 1000) + 3 * 86_400;
    try {
      await this.client.send(
        new TransactWriteCommand({
          TransactItems: [
            { scope: `USER#${ownerHash}`, limit: limits.user },
            { scope: 'GLOBAL', limit: limits.global },
          ].map(({ scope, limit }) => ({
            Update: {
              TableName: this.tableName,
              Key: { pk: `STAGING_QUOTA#${day}#${operation}#${scope}`, sk: 'COUNTER' },
              UpdateExpression: 'SET #count = if_not_exists(#count, :zero) + :one, expiresAt = :ttl',
              ConditionExpression: 'attribute_not_exists(#count) OR #count < :limit',
              ExpressionAttributeNames: { '#count': 'count' },
              ExpressionAttributeValues: { ':zero': 0, ':one': 1, ':limit': limit, ':ttl': expiresAt },
            },
          })),
        }),
      );
    } catch (error) {
      if (isConditionFailure(error, 0) || isConditionFailure(error, 1)) {
        throw new HttpError('RATE_LIMITED', 'The staging daily limit for this operation has been reached. Try again after midnight UTC.');
      }
      // An unavailable/unauthorized quota store never permits the expensive operation or logs its exception.
      throw new HttpError('UPSTREAM_UNAVAILABLE', 'Staging usage limits could not be checked. Please try again later.');
    }
  }
}
