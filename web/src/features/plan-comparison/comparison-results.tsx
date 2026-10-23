import {
  PlanComparisonResultSchema,
  type ComparedPlan,
  type EstimatedResult,
  type ErrorIssue,
  type PlanComparisonRequest,
  type PlanComparisonResult,
  type PlanComparisonTreatment,
} from '@actionbridge/contracts';
import { useId } from 'react';
import {
  Badge,
  Button,
  Card,
  Disclosure,
  Notice,
  Row,
} from '../../components/ui';
import { dateLabel, money } from '../../domain/model';
import { CostBreakdown } from './cost-breakdown';

export type ComparisonViewState =
  | { status: 'idle' }
  | { status: 'loading' }
  | {
      status: 'error';
      message: string;
      requestId?: string;
      retryable?: boolean;
      issues?: ErrorIssue[];
    }
  | { status: 'ready'; result: PlanComparisonResult };

export type ComparisonResultsProps = {
  state: ComparisonViewState;
  request: PlanComparisonRequest | null;
  onRetry?: () => void;
  onReload?: () => void;
};

/** Renders supplied engine results only; API integration belongs to the caller. */
export function ComparisonResults({
  state,
  request,
  onRetry,
  onReload,
}: ComparisonResultsProps) {
  const headingId = useId();
  const checked =
    state.status === 'ready'
      ? PlanComparisonResultSchema.safeParse(state.result)
      : null;
  const result = checked?.success ? checked.data : null;
  const current =
    result !== null && request !== null && matchesRequest(result, request);

  return (
    <section
      className="plan-comparison-results stack"
      aria-labelledby={headingId}
    >
      <h2 id={headingId}>Plan comparison results</h2>
      {state.status === 'idle' && (
        <Notice>
          Prepare both plans to compare the same treatment and schedule.
        </Notice>
      )}
      {state.status === 'loading' && (
        <div role="status" aria-busy="true">
          Comparing the two plans…
        </div>
      )}
      {state.status === 'error' && (
        <Notice tone="danger">
          <strong>The comparison could not be loaded</strong>
          <p>{state.message}</p>
          {state.issues && state.issues.length > 0 && (
            <ul>
              {state.issues.map((issue, index) => (
                <li key={`${issue.fieldPath}-${index}`}>
                  <strong>{issueLabel(issue, request)}</strong>: {issue.message}
                </li>
              ))}
            </ul>
          )}
          {state.requestId && (
            <p className="small">Reference: {state.requestId}</p>
          )}
          {onRetry && state.retryable !== false && (
            <Button variant="secondary" onClick={onRetry}>
              Retry comparison
            </Button>
          )}
          {onReload && (
            <Button variant="secondary" onClick={onReload}>
              Reload treatment
            </Button>
          )}
        </Notice>
      )}
      {state.status === 'ready' && !result && (
        <Notice tone="warning">
          These comparison results could not be validated. Compare again to
          request a current result.
        </Notice>
      )}
      {result && !current && (
        <Notice tone="warning">
          These results do not match the current case, plans, treatment or
          schedule. Compare again to refresh them.
        </Notice>
      )}
      {result && current && (
        <>
          <div className="plan-comparison-grid">
            <PlanResult
              side="Plan A"
              plan={result.planA}
              treatment={result.treatment}
              currency={result.currency}
            />
            <PlanResult
              side="Plan B"
              plan={result.planB}
              treatment={result.treatment}
              currency={result.currency}
            />
          </div>
          <Difference result={result} />
          <p className="muted small">
            Source case revision {result.caseRevision} · Calculation engine{' '}
            {result.engineVersion} · {result.currency}
          </p>
        </>
      )}
      <Notice>
        These are treatment-cost estimates, not a guarantee of insurer approval
        or payment. Confirm coverage, benefit balances and fees with your
        insurer and dentist. Monthly premiums and enrollment decisions are
        excluded. Your dentist decides treatment timing.
      </Notice>
    </section>
  );
}

function PlanResult({
  side,
  plan,
  treatment,
  currency,
}: {
  side: 'Plan A' | 'Plan B';
  plan: ComparedPlan;
  treatment: PlanComparisonTreatment;
  currency: PlanComparisonResult['currency'];
}) {
  const headingId = useId();
  const estimate = plan.estimate;
  return (
    <div role="region" aria-labelledby={headingId}>
      <Card className="stack">
        <h3 id={headingId}>
          {side} · {plan.label}
        </h3>
        {estimate.status === 'estimated' ? (
          <>
            <div className="actions">
              <Badge tone="green">Complete estimate</Badge>
              {estimate.conditional && (
                <Badge tone="assumed">Conditional estimate</Badge>
              )}
              {estimate.assumptions.some(
                (assumption) => assumption.code === 'SYNTHETIC_INPUT',
              ) && <Badge>Synthetic sample</Badge>}
            </div>
            <CostBreakdown
              side={side}
              planLabel={plan.label}
              currency={currency}
              totals={estimate.totals}
            />
            <EstimateLines
              estimate={estimate}
              label={plan.label}
              treatment={treatment}
            />
            <div className="stack">
              <h4>Assumptions and conditions</h4>
              {estimate.conditional && (
                <Notice tone="warning">
                  This estimate depends on assumptions. Confirm the plan terms
                  before relying on these figures.
                </Notice>
              )}
              {estimate.assumptions.length ? (
                <ul className="condition-list">
                  {estimate.assumptions.map((assumption, index) => (
                    <li
                      key={`${assumption.code}-${assumption.planYearId ?? ''}-${index}`}
                    >
                      {assumption.code === 'SYNTHETIC_INPUT' && (
                        <strong>Synthetic sample: </strong>
                      )}
                      {assumption.message}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="small muted">
                  No additional engine assumptions returned.
                </p>
              )}
            </div>
          </>
        ) : estimate.status === 'needs_information' ? (
          <>
            <Badge tone="warning">Needs information</Badge>
            <p>
              Add the following facts for this plan. Unknown values have not
              been treated as zero.
            </p>
            <ul className="condition-list">
              {estimate.missing.map((fact, index) => (
                <li key={`${fact.fieldPath}-${fact.code}-${index}`}>
                  <strong>{factLabel(fact.fieldPath, treatment)}: </strong>
                  {fact.message}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <>
            <Badge tone="warning">Unsupported plan rules</Badge>
            <p>The calculator cannot estimate this plan under these rules.</p>
            <ul className="condition-list">
              {estimate.limitations.map((limitation, index) => (
                <li
                  key={`${limitation.code}-${limitation.fieldPath ?? ''}-${index}`}
                >
                  {limitation.fieldPath && (
                    <strong>
                      {factLabel(limitation.fieldPath, treatment)}:{' '}
                    </strong>
                  )}
                  {limitation.message}
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
    </div>
  );
}

function EstimateLines({
  estimate,
  label,
  treatment,
}: {
  estimate: EstimatedResult;
  label: string;
  treatment: PlanComparisonTreatment;
}) {
  const name = (id: string) =>
    treatment.procedures.find((procedure) => procedure.id === id)?.label ?? id;
  return (
    <>
      <div
        className="table-scroll"
        tabIndex={0}
        aria-label={`${label} procedure cost table`}
      >
        <table>
          <caption>Procedure breakdown · {label}</caption>
          <thead>
            <tr>
              <th scope="col">Procedure</th>
              <th scope="col">Date</th>
              <th scope="col">Dentist fee</th>
              <th scope="col">Insurer pays</th>
              <th scope="col">Patient pays</th>
            </tr>
          </thead>
          <tbody>
            {estimate.lines.map((line) => (
              <tr key={line.procedureId}>
                <th scope="row">{name(line.procedureId)}</th>
                <td>{dateLabel(line.date)}</td>
                <td>{money(line.providerChargeCents)}</td>
                <td>{money(line.insurerPaysCents)}</td>
                <td>{money(line.patientPaysCents)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Disclosure title="How each patient cost is made up">
        {estimate.lines.map((line) => (
          <div className="stack" key={line.procedureId}>
            <h4>{name(line.procedureId)}</h4>
            <Row label="Plan allowed amount" value={money(line.allowedCents)} />
            <Row
              label="Contractual write-off"
              value={money(line.contractualWriteoffCents)}
            />
            <Row
              label="Deductible applied"
              value={money(line.deductibleAppliedCents)}
            />
            <Row
              label="Post-deductible coinsurance"
              value={money(line.coinsuranceCents)}
            />
            <Row
              label="Annual maximum shortfall"
              value={money(line.capShortfallCents)}
            />
            <Row label="Balance billing" value={money(line.balanceBillCents)} />
            <Row
              label="Estimated patient cost"
              value={money(line.patientPaysCents)}
              strong
            />
          </div>
        ))}
      </Disclosure>
    </>
  );
}

function Difference({ result }: { result: PlanComparisonResult }) {
  const difference = result.planBMinusPlanACents;
  const comparable =
    result.planA.estimate.status === 'estimated' &&
    result.planB.estimate.status === 'estimated';
  return (
    <Card className="stack">
      <h3>Estimated patient-cost difference</h3>
      {comparable && difference !== null ? (
        <>
          <p>
            {difference === 0
              ? 'Both plans have the same estimated patient cost.'
              : `${result.planB.label} costs an estimated ${money(Math.abs(difference))} ${difference > 0 ? 'more' : 'less'} than ${result.planA.label} for this treatment.`}
          </p>
          {((result.planA.estimate.status === 'estimated' &&
            result.planA.estimate.conditional) ||
            (result.planB.estimate.status === 'estimated' &&
              result.planB.estimate.conditional)) && (
            <p className="small muted">
              This difference is conditional on the assumptions shown for each
              plan.
            </p>
          )}
        </>
      ) : (
        <p>
          A patient-cost difference is unavailable until both plans have
          complete, comparable estimates.
        </p>
      )}
    </Card>
  );
}

export function matchesRequest(
  result: PlanComparisonResult,
  request: PlanComparisonRequest,
): boolean {
  return (
    result.caseId === request.caseId &&
    result.caseRevision === request.expectedRevision &&
    result.currency === request.currency &&
    result.planA.planId === request.planA.planId &&
    result.planA.label === request.planA.label &&
    result.planB.planId === request.planB.planId &&
    result.planB.label === request.planB.label &&
    treatmentKey(result.treatment) === treatmentKey(request.treatment)
  );
}

/** Saved responses must echo each plan's actual facts, not just the same IDs and names. */
export function sameComparisonInputs(
  left: PlanComparisonRequest,
  right: PlanComparisonRequest,
): boolean {
  const planKey = (plan: PlanComparisonRequest['planA']) =>
    JSON.stringify(
      canonical({
        ...plan,
        sourceFacts: [...plan.sourceFacts].sort((a, b) =>
          a.id.localeCompare(b.id),
        ),
      }),
    );
  return (
    left.caseId === right.caseId &&
    left.expectedRevision === right.expectedRevision &&
    left.currency === right.currency &&
    treatmentKey(left.treatment) === treatmentKey(right.treatment) &&
    planKey(left.planA) === planKey(right.planA) &&
    planKey(left.planB) === planKey(right.planB)
  );
}

/** Compare the shared snapshot without depending on property or procedure ordering. */
function treatmentKey(treatment: PlanComparisonTreatment): string {
  return JSON.stringify(
    canonical({
      procedures: treatment.procedures
        .map((procedure) => ({
          ...procedure,
          prerequisiteIds: [...procedure.prerequisiteIds].sort(),
        }))
        .sort((a, b) => a.id.localeCompare(b.id)),
      schedule: [...treatment.schedule].sort((a, b) =>
        a.procedureId.localeCompare(b.procedureId),
      ),
      sourceFacts: [...treatment.sourceFacts].sort((a, b) =>
        a.id.localeCompare(b.id),
      ),
    }),
  );
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, item]) => [key, canonical(item)]),
    );
  }
  return value;
}

function issueLabel(
  issue: ErrorIssue,
  request: PlanComparisonRequest | null,
): string {
  const path = issue.fieldPath;
  if (!path) return 'Comparison';
  const side = path.startsWith('planA.')
    ? 'Plan A · '
    : path.startsWith('planB.')
      ? 'Plan B · '
      : '';
  return `${side}${request ? factLabel(path, request.treatment) : path}`;
}

function factLabel(path: string, treatment: PlanComparisonTreatment): string {
  const parts = path.split('.');
  const field = parts.at(-1) ?? path;
  const labels: Record<string, string> = {
    policy: 'Plan policy',
    category: 'Benefit category',
    network: 'Dentist network status',
    allowedCents: 'Plan allowed amount',
    contractualWriteoffCents: 'Contractual write-off',
    providerChargeCents: 'Dentist fee',
    annualMaximumCents: 'Annual maximum',
    insurerAlreadyPaidCents: 'Insurer payments already reported',
    annualDeductibleCents: 'Annual deductible',
    deductibleAlreadyMetCents: 'Deductible already met',
    deductibleBeforeCoinsurance: 'Deductible order',
    deductibleAppliesByCategory: 'Deductible rules by category',
    insurerRateBpsByCategory: 'Insurer coverage rate by category',
    annualMaximumAppliesByCategory: 'Annual maximum rules by category',
    rounding: 'Plan rounding rule',
    allServicesCovered: 'Covered treatment scope',
    waitingPeriods: 'Waiting periods',
    exclusions: 'Plan exclusions',
    frequencyRestrictions: 'Frequency restrictions',
    date: 'Treatment date',
  };
  const procedure = treatment.procedures.find((item) =>
    parts.includes(item.id),
  );
  return `${procedure ? `${procedure.label} · ` : ''}${labels[field] ?? field.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/_/g, ' ')}`;
}
