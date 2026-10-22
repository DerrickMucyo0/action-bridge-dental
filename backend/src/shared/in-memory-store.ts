import type { DentalCase, LedgerEvent, LedgerPage, SavedPlanComparison, SavedPlanComparisonMetadata, SavedStrategy } from '@actionbridge/contracts';
import type { CaseRepository, ReplaceOutcome } from '../features/cases/ports/case-repository.js';
import type { LedgerReader } from '../features/ledger/ports/ledger-reader.js';
import type { IdempotencyRecord, SaveOutcome, StrategyRepository, StrategySave } from '../features/strategies/ports/strategy-repository.js';
import type { ComparisonIdempotencyRecord, ComparisonSaveOutcome, PlanComparisonRepository, PlanComparisonSave } from '../features/plan-comparisons/ports/plan-comparison-repository.js';

/**
 * Test and local-development adapter mirroring the single DynamoDB table: the same owner
 * scoping, conditional writes and atomic event recording. Lost on restart.
 */
export class InMemoryStore implements CaseRepository, StrategyRepository, LedgerReader, PlanComparisonRepository {
  private readonly cases = new Map<string, DentalCase>();
  private readonly ledger = new Map<string, LedgerEvent[]>();
  private readonly idempotency = new Map<string, IdempotencyRecord>();
  private readonly strategies = new Map<string, SavedStrategy[]>();
  private readonly comparisons = new Map<string, SavedPlanComparison[]>();
  private readonly comparisonIdempotency = new Map<string, ComparisonIdempotencyRecord>();

  // ---- cases ----

  async create(record: DentalCase, event: LedgerEvent): Promise<void> {
    const key = this.key(record.ownerId, record.caseId);
    if (this.cases.has(key)) throw new Error('Case ID collision');
    this.cases.set(key, structuredClone(record));
    this.append(key, event);
  }

  async get(ownerId: string, caseId: string): Promise<DentalCase | null> {
    const item = this.cases.get(this.key(ownerId, caseId));
    return item === undefined ? null : structuredClone(item);
  }

  async replace(record: DentalCase, event: LedgerEvent, expectedRevision: number): Promise<ReplaceOutcome> {
    const key = this.key(record.ownerId, record.caseId);
    const current = this.cases.get(key);
    if (current === undefined || current.caseRevision !== expectedRevision) return 'revision_conflict';
    this.cases.set(key, structuredClone(record));
    this.append(key, event);
    return 'replaced';
  }

  // ---- strategies ----

  async findByIdempotencyKey(ownerId: string, caseId: string, idempotencyKey: string): Promise<IdempotencyRecord | null> {
    const record = this.idempotency.get(`${this.key(ownerId, caseId)}|${idempotencyKey}`);
    return record === undefined ? null : structuredClone(record);
  }

  async save(input: StrategySave): Promise<SaveOutcome> {
    const key = this.key(input.ownerId, input.strategy.caseId);
    const idempotencyKey = `${key}|${input.idempotencyKey}`;
    if (this.cases.get(key)?.caseRevision !== input.expectedRevision) return 'revision_conflict';
    if (this.idempotency.has(idempotencyKey)) return 'idempotency_key_taken';
    this.idempotency.set(idempotencyKey, structuredClone({ strategy: input.strategy, requestFingerprint: input.requestFingerprint }));
    this.strategies.set(key, [...(this.strategies.get(key) ?? []), structuredClone(input.strategy)]);
    this.append(key, input.event);
    return 'saved';
  }

  async listForCase(ownerId: string, caseId: string): Promise<SavedStrategy[]> {
    return structuredClone(this.strategies.get(this.key(ownerId, caseId)) ?? []);
  }

  // ---- two-plan comparison snapshots ----

  async findComparisonByIdempotencyKey(ownerId: string, caseId: string, idempotencyKey: string): Promise<ComparisonIdempotencyRecord | null> {
    const record = this.comparisonIdempotency.get(`${this.key(ownerId, caseId)}|${idempotencyKey}`);
    return record === undefined ? null : structuredClone(record);
  }

  async saveComparison(input: PlanComparisonSave): Promise<ComparisonSaveOutcome> {
    const { comparison } = input;
    const key = this.key(input.ownerId, comparison.caseId);
    if (this.cases.get(key)?.caseRevision !== input.expectedRevision || comparison.caseRevision !== input.expectedRevision) return 'revision_conflict';
    const idempotencyKey = `${key}|${input.idempotencyKey}`;
    if (this.comparisonIdempotency.has(idempotencyKey)) return 'idempotency_key_taken';
    if ((this.comparisons.get(key) ?? []).some((saved) => saved.caseRevision === comparison.caseRevision && saved.comparisonId === comparison.comparisonId)) {
      throw new Error('Comparison ID collision');
    }
    this.comparisons.set(key, [...(this.comparisons.get(key) ?? []), structuredClone(comparison)]);
    this.comparisonIdempotency.set(idempotencyKey, {
      comparisonId: comparison.comparisonId,
      caseRevision: comparison.caseRevision,
      requestFingerprint: input.requestFingerprint,
    });
    return 'saved';
  }

  async getComparison(ownerId: string, caseId: string, caseRevision: number, comparisonId: string): Promise<SavedPlanComparison | null> {
    const comparison = this.comparisons.get(this.key(ownerId, caseId))?.find((saved) => saved.caseRevision === caseRevision && saved.comparisonId === comparisonId);
    return comparison ? structuredClone(comparison) : null;
  }

  async listComparisonsForCase(ownerId: string, caseId: string, caseRevision: number): Promise<SavedPlanComparisonMetadata[]> {
    return (this.comparisons.get(this.key(ownerId, caseId)) ?? [])
      .filter((saved) => saved.caseRevision === caseRevision)
      .sort((a, b) => b.comparisonId.localeCompare(a.comparisonId))
      .slice(0, 20)
      .map((saved) => ({
        comparisonId: saved.comparisonId, caseId, caseRevision, savedAt: saved.savedAt,
        planALabel: saved.request.planA.label, planBLabel: saved.request.planB.label,
        planAStatus: saved.result.planA.estimate.status, planBStatus: saved.result.planB.estimate.status,
      }));
  }

  // ---- ledger ----

  async list(ownerId: string, caseId: string, cursor: string | null, limit: number): Promise<LedgerPage> {
    const events = [...(this.ledger.get(this.key(ownerId, caseId)) ?? [])].reverse();
    const start = cursor === null ? 0 : Number(cursor);
    const page = events.slice(start, start + limit);
    return { events: structuredClone(page), nextCursor: start + limit < events.length ? String(start + limit) : null };
  }

  private append(key: string, event: LedgerEvent): void {
    this.ledger.set(key, [...(this.ledger.get(key) ?? []), structuredClone(event)]);
  }

  private key(ownerId: string, caseId: string): string {
    return `${ownerId}|${caseId}`;
  }
}
