import type {
  EstimatedResult,
  PlanComparisonResult,
} from '@actionbridge/contracts';
import { money } from '../../domain/model';
import { Notice } from '../../components/ui';

type CostBreakdownProps = {
  side: 'Plan A' | 'Plan B';
  planLabel: string;
  currency: PlanComparisonResult['currency'];
  totals: EstimatedResult['totals'];
};

/** Returned cents determine display geometry only; no insurance amounts are derived here. */
export function CostBreakdown({
  side,
  planLabel,
  currency,
  totals,
}: CostBreakdownProps) {
  const parts = [
    {
      key: 'patient',
      label: 'Estimated patient cost',
      cents: totals.patientPaysCents,
    },
    {
      key: 'insurer',
      label: 'Estimated insurer payment',
      cents: totals.insurerPaysCents,
    },
    {
      key: 'writeoff',
      label: 'Contractual write-off',
      cents: totals.contractualWriteoffCents,
    },
  ];
  const empty =
    totals.providerChargeCents === 0 && parts.every((part) => part.cents === 0);
  // Validate the visual decomposition; never use this sum as a calculated payment or fee.
  const consistent =
    parts.reduce((sum, part) => sum + part.cents, 0) ===
    totals.providerChargeCents;

  return (
    <figure
      className="comparison-cost-breakdown"
      aria-label={`${side} cost breakdown · ${planLabel}`}
    >
      <figcaption className="comparison-cost-caption">
        <h4>Cost breakdown</h4>
        <span className="small muted">{currency}</span>
      </figcaption>
      {consistent ? (
        <div className="comparison-cost-track" aria-hidden="true">
          {parts.map((part) => (
            <span
              key={part.key}
              className={`comparison-cost-segment ${part.key}${part.cents === 0 ? ' is-zero' : ''}`}
              style={{ flexGrow: part.cents }}
            />
          ))}
        </div>
      ) : (
        <Notice tone="warning">
          The returned amounts do not form a consistent cost breakdown.
        </Notice>
      )}
      {empty && (
        <p className="small muted">No treatment charges in this estimate.</p>
      )}
      <dl className="comparison-cost-legend">
        {parts.map((part) => (
          <div className={`comparison-cost-item ${part.key}`} key={part.key}>
            <dt>
              <span
                className={`comparison-cost-swatch ${part.key}`}
                aria-hidden="true"
              />
              {part.label}
            </dt>
            <dd>
              {money(part.cents)}{' '}
              <span className="comparison-cost-currency">{currency}</span>
            </dd>
          </div>
        ))}
        <div className="comparison-cost-item comparison-cost-total">
          <dt>Dentist fees</dt>
          <dd>
            {money(totals.providerChargeCents)}{' '}
            <span className="comparison-cost-currency">{currency}</span>
          </dd>
        </div>
      </dl>
      <p className="small muted">
        A contractual write-off is a fee reduction. It is not paid by you or
        your insurer.
      </p>
    </figure>
  );
}
