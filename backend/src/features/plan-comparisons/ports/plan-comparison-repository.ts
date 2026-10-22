import type { SavedPlanComparison, SavedPlanComparisonMetadata } from '@actionbridge/contracts';

export interface ComparisonIdempotencyRecord {
  comparisonId: string;
  caseRevision: number;
  /** Hash of the candidate inputs, without duplicating their treatment or insurance facts. */
  requestFingerprint: string;
}

export type ComparisonSaveOutcome = 'saved' | 'revision_conflict' | 'idempotency_key_taken';

export interface PlanComparisonSave {
  ownerId: string;
  idempotencyKey: string;
  requestFingerprint: string;
  expectedRevision: number;
  comparison: SavedPlanComparison;
  expiresAtEpochSeconds: number | null;
}

/** Immutable snapshots in the existing owner's case partition; writes check the revision atomically. */
export interface PlanComparisonRepository {
  findComparisonByIdempotencyKey(ownerId: string, caseId: string, key: string): Promise<ComparisonIdempotencyRecord | null>;
  saveComparison(input: PlanComparisonSave): Promise<ComparisonSaveOutcome>;
  getComparison(ownerId: string, caseId: string, caseRevision: number, comparisonId: string): Promise<SavedPlanComparison | null>;
  /** At most 20 snapshots from this revision, newest first; no treatment, source evidence or costs. */
  listComparisonsForCase(ownerId: string, caseId: string, caseRevision: number): Promise<SavedPlanComparisonMetadata[]>;
}
