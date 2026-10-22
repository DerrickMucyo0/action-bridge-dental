import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';
import {
  PlanComparisonListSchema,
  SavedPlanComparisonSchema,
  type PlanComparisonList,
  type PlanComparisonRequest,
  type SavedPlanComparison,
  type SavePlanComparisonRequest,
  type SavePlanComparisonResponse,
} from '@actionbridge/contracts';
import { expiresAtFrom } from '../../../shared/dynamo.js';
import { HttpError } from '../../../shared/http.js';
import { revisionConflict, type CaseService } from '../../cases/application/case-service.js';
import { PlanComparisonService } from '../../estimates/application/plan-comparison-service.js';
import type { ComparisonIdempotencyRecord, PlanComparisonRepository } from '../ports/plan-comparison-repository.js';

export interface SavedPlanComparisonServiceDeps {
  cases: CaseService;
  comparisons: PlanComparisonRepository;
  now: () => Date;
  newId: () => string;
  retentionDays: number | null;
}

/** Server-calculated snapshots, isolated from single-plan strategies and reported benefit usage. */
export class SavedPlanComparisonService {
  private readonly calculator: PlanComparisonService;

  constructor(private readonly deps: SavedPlanComparisonServiceDeps) {
    this.calculator = new PlanComparisonService({ cases: deps.cases });
  }

  async save(ownerId: string, caseId: string, key: string, request: SavePlanComparisonRequest): Promise<SavePlanComparisonResponse> {
    // Ownership, current revision and exact stored treatment are checked even for an idempotent replay.
    const result = await this.calculator.compare(ownerId, caseId, request.comparison);
    const input: PlanComparisonRequest = { ...request.comparison, treatment: result.treatment };
    const fingerprint = createHash('sha256').update(JSON.stringify(canonical(input))).digest('hex');
    const existing = await this.deps.comparisons.findComparisonByIdempotencyKey(ownerId, caseId, key);
    if (existing) return this.replay(ownerId, caseId, input.expectedRevision, existing, fingerprint);

    const now = this.deps.now();
    const savedAt = now.toISOString();
    const comparison = SavedPlanComparisonSchema.parse({
      comparisonId: `${savedAt.replace(/\D/g, '')}-${this.deps.newId()}`,
      caseId,
      caseRevision: input.expectedRevision,
      request: input,
      result,
      savedAt,
    });
    const outcome = await this.deps.comparisons.saveComparison({
      ownerId,
      idempotencyKey: key,
      requestFingerprint: fingerprint,
      expectedRevision: input.expectedRevision,
      comparison,
      expiresAtEpochSeconds: expiresAtFrom(now, this.deps.retentionDays),
    });
    if (outcome === 'revision_conflict') throw revisionConflict();
    if (outcome === 'idempotency_key_taken') {
      const raced = await this.deps.comparisons.findComparisonByIdempotencyKey(ownerId, caseId, key);
      if (raced) return this.replay(ownerId, caseId, input.expectedRevision, raced, fingerprint);
      throw new HttpError('IDEMPOTENCY_CONFLICT', 'This comparison save is being processed. Retry with the same save key.');
    }
    return { comparison, replayed: false };
  }

  async list(ownerId: string, caseId: string, expectedRevision: number): Promise<PlanComparisonList> {
    await this.deps.cases.getAtRevision(ownerId, caseId, expectedRevision);
    const comparisons = await this.deps.comparisons.listComparisonsForCase(ownerId, caseId, expectedRevision);
    // Do not return an older list when the source changes while storage is being read.
    await this.deps.cases.getAtRevision(ownerId, caseId, expectedRevision);
    return PlanComparisonListSchema.parse({ caseId, caseRevision: expectedRevision, comparisons });
  }

  async get(ownerId: string, caseId: string, expectedRevision: number, comparisonId: string): Promise<SavedPlanComparison> {
    await this.deps.cases.getAtRevision(ownerId, caseId, expectedRevision);
    const stored = await this.deps.comparisons.getComparison(ownerId, caseId, expectedRevision, comparisonId);
    if (!stored) throw new HttpError('NOT_FOUND', 'Saved comparison not found for this case revision.');
    const comparison = SavedPlanComparisonSchema.parse(stored);
    if (comparison.caseId !== caseId || comparison.caseRevision !== expectedRevision || comparison.comparisonId !== comparisonId) {
      throw new HttpError('NOT_FOUND', 'Saved comparison not found for this case revision.');
    }
    // Revalidate stored facts and authoritative amounts against the owner's current case before reopening.
    const current = await this.calculator.compare(ownerId, caseId, comparison.request);
    if (!isDeepStrictEqual(current, comparison.result)) {
      throw new HttpError('REVISION_CONFLICT', 'This saved comparison needs recalculation. Compare again and save a new snapshot.');
    }
    return comparison;
  }

  private async replay(ownerId: string, caseId: string, revision: number, existing: ComparisonIdempotencyRecord, fingerprint: string): Promise<SavePlanComparisonResponse> {
    if (existing.requestFingerprint !== fingerprint || existing.caseRevision !== revision) {
      throw new HttpError('IDEMPOTENCY_CONFLICT', 'This save key was already used for different comparison inputs. Start a new save.');
    }
    // get checks ownership/revision again and verifies the snapshot before returning it.
    return { comparison: await this.get(ownerId, caseId, revision, existing.comparisonId), replayed: true };
  }
}

/** Object key ordering must not change the identity of a retried save; no raw facts enter the key. */
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)]));
  }
  return value;
}
