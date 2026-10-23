import type {
  ComparedPlan,
  ComparisonPlan,
  PlanComparisonRequest,
  PlanComparisonResult,
  PlanComparisonTreatment,
  SourceFact,
} from '@actionbridge/contracts';
import { useId } from 'react';
import { dateLabel, money } from '../../domain/model';
import { kindOf, SOURCE_LABEL } from '../../domain/provenance';

type ComparisonReportProps = {
  request: PlanComparisonRequest;
  result: PlanComparisonResult;
  exportedAt: Date;
};

/** A print-only presentation of a validated, current comparison; no estimates are calculated here. */
export function ComparisonReport({
  request,
  result,
  exportedAt,
}: ComparisonReportProps) {
  const titleId = useId();
  const exportDate = new Intl.DateTimeFormat('en-US', {
    dateStyle: 'long',
    timeStyle: 'long',
    timeZone: 'UTC',
  }).format(exportedAt);
  const synthetic =
    result.treatment.procedures.some(
      (procedure) => procedure.timingSource === 'fictional_dentist_supplied',
    ) ||
    result.treatment.sourceFacts.some((fact) => fact.origin === 'synthetic') ||
    [request.planA, request.planB].some(hasSyntheticSources) ||
    [result.planA, result.planB].some(
      (plan) =>
        plan.estimate.status === 'estimated' &&
        plan.estimate.assumptions.some(
          (assumption) => assumption.code === 'SYNTHETIC_INPUT',
        ),
    );

  return (
    <article className="comparison-report" aria-labelledby={titleId}>
      <header className="comparison-report-header">
        <p className="comparison-report-brand">ActionBridge Dental</p>
        <h1 id={titleId}>Insurance plan comparison report</h1>
        <dl className="comparison-report-meta">
          <div>
            <dt>Export date</dt>
            <dd>
              <time dateTime={exportedAt.toISOString()}>{exportDate}</time>
            </dd>
          </div>
          <div>
            <dt>Case revision</dt>
            <dd>{result.caseRevision}</dd>
          </div>
          <div>
            <dt>Calculation engine</dt>
            <dd>{result.engineVersion}</dd>
          </div>
          <div>
            <dt>Currency</dt>
            <dd>{result.currency} · US dollars</dd>
          </div>
        </dl>
        <p>
          The export date records when this report was prepared, not when
          coverage was confirmed.
        </p>
        {synthetic && (
          <p className="comparison-report-warning">
            <strong>Synthetic sample data.</strong> This comparison includes
            fictional inputs; it is not a real patient estimate.
          </p>
        )}
        <p className="comparison-report-warning">
          <strong>NOT INSURER CONFIRMATION</strong>
          <br />
          These are treatment-cost estimates, not a guarantee of insurer
          approval or payment. Confirm coverage, benefit balances and fees with
          your insurer and dentist.
        </p>
      </header>

      <section
        className="comparison-report-section"
        aria-label="Shared treatment"
      >
        <h2>Shared treatment and schedule</h2>
        <p>
          Both plans use this same treatment and schedule. This report does not
          change treatment dates.
        </p>
        <table className="comparison-report-table">
          <caption>Shared treatment and schedule ({result.currency})</caption>
          <thead>
            <tr>
              <th scope="col">Treatment</th>
              <th scope="col">Scheduled date</th>
              <th scope="col">Dentist fee</th>
            </tr>
          </thead>
          <tbody>
            {result.treatment.procedures.map((procedure) => {
              const scheduled = result.treatment.schedule.find(
                (entry) => entry.procedureId === procedure.id,
              );
              return (
                <tr key={procedure.id}>
                  <th scope="row">
                    {procedure.label}
                    {procedure.cdtCode && <span> · {procedure.cdtCode}</span>}
                  </th>
                  <td>
                    {scheduled ? dateLabel(scheduled.date) : 'Not supplied'}
                  </td>
                  <td className="comparison-report-money">
                    {procedure.providerChargeCents === null
                      ? 'Unknown — not supplied'
                      : `${money(procedure.providerChargeCents)} ${result.currency}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <Sources facts={result.treatment.sourceFacts} />
      </section>

      <ReportPlan
        side="Plan A"
        plan={result.planA}
        input={request.planA}
        result={result}
      />
      <ReportPlan
        side="Plan B"
        plan={result.planB}
        input={request.planB}
        result={result}
      />

      <section
        className="comparison-report-section"
        aria-label="Patient-cost comparison"
      >
        <h2>Estimated patient-cost difference</h2>
        {result.planA.estimate.status === 'estimated' &&
        result.planB.estimate.status === 'estimated' &&
        result.planBMinusPlanACents !== null ? (
          <>
            <p>
              Plan B patient estimate minus Plan A patient estimate:{' '}
              <strong>
                {money(result.planBMinusPlanACents)} {result.currency}
              </strong>
              .
              {result.planBMinusPlanACents === 0 &&
                ' Both plans have the same estimated patient cost.'}
            </p>
            <p>
              A positive difference means Plan B costs more; a negative
              difference means Plan B costs less for this treatment. This is not
              a plan recommendation.
            </p>
            {(result.planA.estimate.conditional ||
              result.planB.estimate.conditional) && (
              <p>
                This difference is conditional on the assumptions shown for each
                plan.
              </p>
            )}
          </>
        ) : (
          <p>
            A patient-cost difference is unavailable until both plans have
            complete, comparable estimates. No cost ranking is made.
          </p>
        )}
      </section>

      <footer className="comparison-report-footer">
        <h2>Important limitations</h2>
        <p>
          <strong>NOT INSURER CONFIRMATION.</strong> Source origin and user
          confirmation do not establish insurer approval. Sources and benefit
          balances are not rechecked when printing; confirm current information
          with your insurer and dentist.
        </p>
        <p>
          Contractual write-offs are reductions in the dentist fee, not payments
          by the patient or insurer. Monthly premiums and enrollment decisions
          are excluded. Your dentist decides treatment timing. Printing or
          saving this report does not submit a claim, make a payment or book
          treatment.
        </p>
        <p>
          Prepared by ActionBridge Dental from the returned deterministic
          benefits-engine results. No financial amounts are recalculated for
          this report.
        </p>
      </footer>
    </article>
  );
}

function ReportPlan({
  side,
  plan,
  input,
  result,
}: {
  side: 'Plan A' | 'Plan B';
  plan: ComparedPlan;
  input: ComparisonPlan;
  result: PlanComparisonResult;
}) {
  const titleId = useId();
  const estimate = plan.estimate;
  const currency = result.currency;
  const amount = (cents: number) => `${money(cents)} ${currency}`;

  return (
    <section
      className="comparison-report-section comparison-report-plan"
      aria-labelledby={titleId}
    >
      <h2 id={titleId}>
        {side} · {plan.label}
      </h2>
      {hasSyntheticSources(input) && (
        <p>
          <strong>Synthetic sample inputs for this plan.</strong>
        </p>
      )}
      {estimate.status === 'estimated' ? (
        <>
          <p>
            <strong>
              Complete estimate
              {estimate.conditional ? ' · Conditional estimate' : ''}
            </strong>
          </p>
          <dl className="comparison-report-totals">
            <div>
              <dt>Estimated patient cost</dt>
              <dd>{amount(estimate.totals.patientPaysCents)}</dd>
            </div>
            <div>
              <dt>Estimated insurer payment</dt>
              <dd>{amount(estimate.totals.insurerPaysCents)}</dd>
            </div>
            <div>
              <dt>Contractual write-off</dt>
              <dd>{amount(estimate.totals.contractualWriteoffCents)}</dd>
            </div>
            <div>
              <dt>Dentist fees</dt>
              <dd>{amount(estimate.totals.providerChargeCents)}</dd>
            </div>
          </dl>
          <p>
            Contractual write-offs reduce dentist fees; they are not patient or
            insurer payments.
          </p>
          <table className="comparison-report-table">
            <caption>
              {side} treatment cost estimates ({currency})
            </caption>
            <thead>
              <tr>
                <th scope="col">Treatment / date</th>
                <th scope="col">Dentist fee</th>
                <th scope="col">Insurer pays</th>
                <th scope="col">Patient pays</th>
                <th scope="col">Contractual write-off</th>
              </tr>
            </thead>
            <tbody>
              {estimate.lines.map((line) => (
                <tr key={line.procedureId}>
                  <th scope="row">
                    {procedureLabel(result.treatment, line.procedureId)}
                    <br />
                    {dateLabel(line.date)}
                  </th>
                  <td className="comparison-report-money">
                    {amount(line.providerChargeCents)}
                  </td>
                  <td className="comparison-report-money">
                    {amount(line.insurerPaysCents)}
                  </td>
                  <td className="comparison-report-money">
                    {amount(line.patientPaysCents)}
                  </td>
                  <td className="comparison-report-money">
                    {amount(line.contractualWriteoffCents)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>Assumptions and conditions</h3>
          {estimate.conditional && (
            <p>
              This estimate depends on assumptions. Confirm the plan terms
              before relying on these figures.
            </p>
          )}
          {estimate.assumptions.length > 0 ? (
            <ul>
              {estimate.assumptions.map((assumption, index) => (
                <li key={`${assumption.code}-${index}`}>
                  {assumption.code === 'SYNTHETIC_INPUT' && (
                    <strong>Synthetic sample: </strong>
                  )}
                  {assumption.message}
                </li>
              ))}
            </ul>
          ) : (
            <p>No additional engine assumptions returned.</p>
          )}
        </>
      ) : estimate.status === 'needs_information' ? (
        <>
          <p>
            <strong>Needs information</strong>
          </p>
          <p>
            No patient or insurer estimate is available for this plan. Unknown
            values have not been treated as zero.
          </p>
          <ul>
            {estimate.missing.map((fact, index) => (
              <li key={`${fact.fieldPath}-${index}`}>
                {contextLabel(result.treatment, fact.fieldPath)}
                {fact.message}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <>
          <p>
            <strong>Unsupported plan rules</strong>
          </p>
          <p>
            The calculator cannot estimate this plan under these rules. No
            patient or insurer amounts are supplied.
          </p>
          <ul>
            {estimate.limitations.map((limitation, index) => (
              <li key={`${limitation.code}-${index}`}>
                {limitation.procedureId
                  ? `${procedureLabel(result.treatment, limitation.procedureId)}: `
                  : contextLabel(result.treatment, limitation.fieldPath)}
                {limitation.message}
              </li>
            ))}
          </ul>
        </>
      )}
      <Sources facts={input.sourceFacts} plan={input} />
    </section>
  );
}

function Sources({
  facts,
  plan,
}: {
  facts: SourceFact[];
  plan?: ComparisonPlan;
}) {
  const origins = [...new Set(facts.map((fact) => SOURCE_LABEL[kindOf(fact)]))];
  return (
    <div className="comparison-report-sources">
      <h3>Sources and provenance</h3>
      <p>
        Source labels describe where inputs came from, not insurer confirmation.
      </p>
      {origins.length ? (
        <p>Recorded sources: {origins.join('; ')}.</p>
      ) : (
        <p>No field-level source records were supplied for this section.</p>
      )}
      <ul>
        {facts.some((fact) => !fact.userConfirmed) && (
          <li>Some source inputs have not been confirmed by you.</li>
        )}
        {facts.some((fact) => fact.conflict) && (
          <li>
            Some source records contain conflicting information. Resolve
            conflicts before relying on estimates.
          </li>
        )}
        {facts.some(
          (fact) =>
            fact.extractionStatus === 'low_confidence' ||
            fact.extractionStatus === 'failed',
        ) && (
          <li>
            Some source extraction requires review because it had low confidence
            or failed.
          </li>
        )}
        {facts.some((fact) => fact.value === null) && (
          <li>
            Some source values are unknown; no replacement amounts have been
            invented.
          </li>
        )}
        {facts.some(
          (fact) => fact.insurerVerification.status === 'not_verified',
        ) && <li>Some source facts have not been verified by an insurer.</li>}
        {facts.some(
          (fact) => fact.insurerVerification.status === 'verified',
        ) && (
          <li>
            Some source facts carry an insurer-verification record. That record
            does not confirm this report, all coverage or any future payment.
          </li>
        )}
      </ul>
      {plan && Object.keys(plan.planYears).length > 0 && (
        <>
          <h4>Benefit-period sources</h4>
          <ul>
            {Object.entries(plan.planYears).map(([id, year]) => (
              <li key={id}>
                {dateLabel(year.startDate)}–{dateLabel(year.endDate)}:{' '}
                {PLAN_YEAR_SOURCE[year.sourceStatus]}.
              </li>
            ))}
          </ul>
        </>
      )}
      <p>
        Document quotes, source identifiers and verification references are
        omitted to limit personal information in this report.
      </p>
    </div>
  );
}

const PLAN_YEAR_SOURCE: Record<
  ComparisonPlan['planYears'][string]['sourceStatus'],
  string
> = {
  user_entered: 'Provided by you',
  user_confirmed: 'Confirmed by you, not insurer confirmation',
  document_extracted: 'From your document',
  insurer_confirmed: 'Recorded as insurer-confirmed input, not report approval',
  synthetic_confirmed_input: 'Synthetic sample data',
  explicit_unchanged_plan_assumption: 'Assumed unchanged plan terms',
};

function hasSyntheticSources(plan: ComparisonPlan): boolean {
  return (
    plan.sourceFacts.some((fact) => fact.origin === 'synthetic') ||
    Object.values(plan.planYears).some(
      (year) => year.sourceStatus === 'synthetic_confirmed_input',
    )
  );
}

function procedureLabel(
  treatment: PlanComparisonTreatment,
  id: string,
): string {
  return (
    treatment.procedures.find((procedure) => procedure.id === id)?.label ??
    'Treatment item'
  );
}

function contextLabel(
  treatment: PlanComparisonTreatment,
  path?: string,
): string {
  const procedure = treatment.procedures.find((item) =>
    path?.split('.').includes(item.id),
  );
  return procedure ? `${procedure.label}: ` : '';
}
