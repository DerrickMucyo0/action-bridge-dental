import { isDeepStrictEqual } from 'node:util';
import {
  PlanComparisonProcedureSchema,
  PlanComparisonResultSchema,
  type DentalCase,
  type ErrorIssue,
  type PlanComparisonRequest,
  type PlanComparisonResult,
  type PlanComparisonTreatment,
} from '@actionbridge/contracts';
import { comparePlans } from '@actionbridge/benefits-engine';
import { HttpError } from '../../../shared/http.js';
import type { CaseService } from '../../cases/application/case-service.js';

export interface PlanComparisonServiceDeps {
  cases: Pick<CaseService, 'getAtRevision'>;
}

/** Read-only comparison of candidate insurance plans against the owner's stored treatment. */
export class PlanComparisonService {
  constructor(private readonly deps: PlanComparisonServiceDeps) {}

  async compare(ownerId: string, caseId: string, request: PlanComparisonRequest): Promise<PlanComparisonResult> {
    const record = await this.deps.cases.getAtRevision(ownerId, caseId, request.expectedRevision);
    if (request.caseId !== caseId) {
      throw new HttpError('BAD_REQUEST', 'The request caseId must match the case in the URL.', [
        { fieldPath: 'caseId', code: 'CASE_ID_MISMATCH', message: 'Use the same case ID in the URL and request.' },
      ]);
    }

    const treatment = storedTreatment(record);
    const issues: ErrorIssue[] = [];
    if (request.currency !== record.currency) {
      issues.push({ fieldPath: 'currency', code: 'TREATMENT_MISMATCH', message: 'Use the stored case currency.' });
    }
    const submitted = new Map(request.treatment.procedures.map((procedure) => [procedure.id, procedure]));
    if (submitted.size !== treatment.procedures.length) {
      issues.push({ fieldPath: 'treatment.procedures', code: 'TREATMENT_MISMATCH', message: 'Compare every stored treatment procedure exactly once.' });
    }
    for (const procedure of treatment.procedures) {
      if (!isDeepStrictEqual(submitted.get(procedure.id), procedure)) {
        issues.push({ fieldPath: `treatment.procedures.${procedure.id}`, code: 'TREATMENT_MISMATCH',
          message: 'Treatment details must match this case revision. Update the case before changing them.' });
      }
    }
    const dates = new Map(request.treatment.schedule.map((entry) => [entry.procedureId, entry.date]));
    for (const entry of treatment.schedule) {
      if (dates.get(entry.procedureId) !== entry.date) {
        issues.push({ fieldPath: `treatment.schedule.${entry.procedureId}.date`, code: 'TREATMENT_MISMATCH',
          message: 'Confirm the new treatment date by updating the case before comparing plans.' });
      }
    }
    if (!isDeepStrictEqual(request.treatment.sourceFacts, treatment.sourceFacts)) {
      issues.push({ fieldPath: 'treatment.sourceFacts', code: 'TREATMENT_MISMATCH',
        message: 'Use the stored treatment sources without changing their confirmation or verification.' });
    }
    if (issues.length > 0) {
      throw new HttpError('INCONSISTENT_INPUT', 'The treatment does not match the current case. Reload it and try again.', issues);
    }

    // Canonical order preserves the estimator's stable same-day ordering. Candidate facts remain independent.
    const result = comparePlans({
      ...request,
      caseId: record.caseId,
      expectedRevision: record.caseRevision,
      currency: record.currency,
      treatment,
    });
    if ('status' in result) {
      throw new HttpError('INCONSISTENT_INPUT', 'Some values contradict each other. Review them and try again.', result.issues);
    }
    return PlanComparisonResultSchema.parse(result);
  }
}

/** Manual case writes and confirmed extraction answers already establish the stored input revision. */
function storedTreatment(record: DentalCase): PlanComparisonTreatment {
  const schedule = record.procedures.map((procedure) => {
    const date = procedure.proposedDate ?? procedure.dentistEarliestDate;
    if (date === null) {
      throw new HttpError('INCONSISTENT_INPUT', 'Confirm the planned treatment dates in the case before comparing plans.', [
        { fieldPath: `treatment.schedule.${procedure.id}.date`, code: 'TREATMENT_DATE_REQUIRED', message: 'A stored planned treatment date is needed.' },
      ]);
    }
    return { procedureId: procedure.id, date };
  });
  const procedures = record.procedures.map((procedure) => {
    const { category, network, allowedCents, contractualWriteoffCents, proposedDate, selfPayQuote, ...shared } = procedure;
    return shared;
  });
  const ids = new Set(procedures.map((procedure) => procedure.id));
  const sharedFields = new Set([...Object.keys(PlanComparisonProcedureSchema.shape), 'proposedDate']);
  const sourceFacts = record.sourceFacts.filter((fact) => {
    if (fact.fieldPath === 'currency' || fact.fieldPath === 'procedures') return true;
    const [section, id, field] = fact.fieldPath.split('.');
    return section === 'procedures' && id !== undefined && ids.has(id)
      && (field === undefined || sharedFields.has(field));
  });
  return { procedures, schedule, sourceFacts };
}
