import type {
  ComparisonPlan,
  DentalCase,
  PlanComparisonPolicy,
  PlanComparisonProcedureFacts,
  PlanYear,
  SourceFact,
} from '@actionbridge/contracts';
import { Badge, Button, Disclosure, Field, Notice } from '../../components/ui';
import { AmountField } from '../intake/case-forms';
import { editComparisonPlan, unknownPolicy } from './comparison-model';

type Props = {
  side: 'Plan A' | 'Plan B';
  plan: ComparisonPlan;
  record: DentalCase;
  onChange: (plan: ComparisonPlan) => void;
  submitted: boolean;
  onUseCurrent?: () => void;
};

type CategoryMap =
  | 'insurerRateBpsByCategory'
  | 'deductibleAppliesByCategory'
  | 'annualMaximumAppliesByCategory';

const categoryRules = [
  ['deductibleAppliesByCategory', 'Deductible applies'],
  ['annualMaximumAppliesByCategory', 'Annual maximum applies'],
] as const;

const restrictions = [
  ['waitingPeriods', 'Waiting periods'],
  ['exclusions', 'Exclusions'],
  ['frequencyRestrictions', 'Frequency restrictions'],
] as const;

function UnknownBooleanOptions() {
  return (
    <>
      <option value="unknown">Unknown</option>
      <option value="true">Yes</option>
      <option value="false">No</option>
    </>
  );
}

function booleanValue(value: string): boolean | null {
  return value === 'unknown' ? null : value === 'true';
}

/** Each editor updates only its supplied plan. Common treatment stays read-only. */
export function PlanEditor({
  side,
  plan,
  record,
  onChange,
  submitted,
  onUseCurrent,
}: Props) {
  const policy = plan.policy ?? unknownPolicy(plan.planId);
  const categoryIds = [
    ...new Set([
      'basic',
      'major',
      'preventive',
      ...Object.keys(policy.insurerRateBpsByCategory ?? {}),
      ...Object.keys(policy.deductibleAppliesByCategory ?? {}),
      ...Object.keys(policy.annualMaximumAppliesByCategory ?? {}),
      ...Object.values(plan.procedureFacts).flatMap((facts) =>
        facts.category ? [facts.category] : [],
      ),
    ]),
  ];
  const usedCategories = [
    ...new Set(
      Object.values(plan.procedureFacts).flatMap((facts) =>
        facts.category ? [facts.category] : [],
      ),
    ),
  ];
  const years = Object.entries(plan.planYears);
  const edit = (
    patch: Partial<ComparisonPlan>,
    path: string,
    value: SourceFact['value'],
  ) => onChange(editComparisonPlan(plan, patch, path, value));
  const patchPolicy = (
    patch: Partial<PlanComparisonPolicy>,
    field: string,
    value: SourceFact['value'],
  ) => edit({ policy: { ...policy, ...patch } }, `policy.${field}`, value);
  const patchCategory = (
    map: CategoryMap,
    category: string,
    value: number | boolean | null,
  ) => {
    patchPolicy(
      { [map]: { ...policy[map], [category]: value } },
      `${map}.${category}`,
      value,
    );
  };
  const patchProcedure = (
    id: string,
    facts: PlanComparisonProcedureFacts,
    field: keyof PlanComparisonProcedureFacts,
    value: SourceFact['value'],
  ) => {
    const patch: Partial<ComparisonPlan> = {
      procedureFacts: {
        ...plan.procedureFacts,
        [id]: { ...facts, [field]: value },
      },
    };
    if (field === 'category' && typeof value === 'string') {
      patch.policy = {
        ...policy,
        insurerRateBpsByCategory: {
          ...policy.insurerRateBpsByCategory,
          [value]: policy.insurerRateBpsByCategory?.[value] ?? null,
        },
        deductibleAppliesByCategory: {
          ...policy.deductibleAppliesByCategory,
          [value]: policy.deductibleAppliesByCategory?.[value] ?? null,
        },
        annualMaximumAppliesByCategory: {
          ...policy.annualMaximumAppliesByCategory,
          [value]: policy.annualMaximumAppliesByCategory?.[value] ?? null,
        },
      };
    }
    edit(patch, `procedureFacts.${id}.${field}`, value);
  };
  const patchYear = (
    id: string,
    year: PlanYear,
    field: keyof PlanYear,
    value: string | number | null,
  ) =>
    edit(
      {
        planYears: {
          ...plan.planYears,
          [id]: { ...year, [field]: value, sourceStatus: 'user_entered' },
        },
      },
      `planYears.${id}.${field}`,
      value,
    );

  return (
    <fieldset className="comparison-plan-editor card stack">
      <legend>{side}</legend>
      <div className="section-title">
        <Badge>
          {plan.sourceFacts.length
            ? 'Source history available'
            : 'Enter plan details'}
        </Badge>
        {onUseCurrent && (
          <Button variant="secondary" onClick={onUseCurrent}>
            Use current plan
          </Button>
        )}
      </div>
      <Field
        label="Plan name"
        hint="Name this insurance plan configuration so you can identify it."
        error={
          submitted && !plan.label.trim()
            ? 'Enter a name for this plan.'
            : undefined
        }
      >
        <input
          required
          maxLength={120}
          value={plan.label}
          onChange={(event) =>
            edit({ label: event.target.value }, 'label', event.target.value)
          }
        />
      </Field>
      <p className="small muted">
        Leave unknown amounts blank and select Unknown for rules you cannot
        confirm. Entering a value does not verify it with an insurer.
      </p>

      <Disclosure title="Procedure insurance facts" open>
        <p className="small muted">
          Allowed amount is the price this plan recognizes. A write-off is the
          amount the dentist agrees not to collect. Both can differ between
          plans.
        </p>
        <div className="stack">
          {record.procedures.map((procedure, index) => {
            const facts = plan.procedureFacts[procedure.id] ?? {
              category: null,
              network: 'unknown',
              allowedCents: null,
              contractualWriteoffCents: null,
            };
            return (
              <Disclosure
                key={procedure.id}
                title={procedure.label}
                open={index === 0}
              >
                <div className="form-grid">
                  <Field label={`${procedure.label} · Benefit category`}>
                    <select
                      value={facts.category ?? 'unknown'}
                      onChange={(event) =>
                        patchProcedure(
                          procedure.id,
                          facts,
                          'category',
                          event.target.value === 'unknown'
                            ? null
                            : event.target.value,
                        )
                      }
                    >
                      <option value="unknown">Unknown</option>
                      {categoryIds.map((category) => (
                        <option key={category} value={category}>
                          {category}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label={`${procedure.label} · Provider network`}>
                    <select
                      value={facts.network}
                      onChange={(event) =>
                        patchProcedure(
                          procedure.id,
                          facts,
                          'network',
                          event.target.value,
                        )
                      }
                    >
                      <option value="unknown">Unknown</option>
                      <option value="in">In network</option>
                      <option value="out">Out of network</option>
                    </select>
                  </Field>
                  <AmountField
                    label={`${procedure.label} · Allowed amount`}
                    value={facts.allowedCents}
                    onChange={(value) =>
                      patchProcedure(procedure.id, facts, 'allowedCents', value)
                    }
                  />
                  <AmountField
                    label={`${procedure.label} · Dentist write-off`}
                    value={facts.contractualWriteoffCents}
                    onChange={(value) =>
                      patchProcedure(
                        procedure.id,
                        facts,
                        'contractualWriteoffCents',
                        value,
                      )
                    }
                  />
                </div>
              </Disclosure>
            );
          })}
        </div>
      </Disclosure>

      <Disclosure title="Coverage rules" open>
        <div className="stack">
          <p className="small muted">
            A deductible is what you pay before the plan shares eligible costs.
            The annual maximum limits what the insurer pays during a benefit
            year.
          </p>
          <div className="form-grid">
            {(
              [
                [
                  'deductibleBeforeCoinsurance',
                  'Deductible before coinsurance',
                ],
                ['allServicesCovered', 'All listed services covered'],
              ] as const
            ).map(([field, label]) => (
              <Field key={field} label={label}>
                <select
                  value={
                    policy[field] == null ? 'unknown' : String(policy[field])
                  }
                  onChange={(event) => {
                    const value = booleanValue(event.target.value);
                    patchPolicy({ [field]: value }, field, value);
                  }}
                >
                  <UnknownBooleanOptions />
                </select>
              </Field>
            ))}
            <Field label="Insurer payment rounding">
              <select
                value={policy.rounding ?? 'unknown'}
                onChange={(event) => {
                  const value =
                    event.target.value === 'unknown' ? null : 'half_up_to_cent';
                  patchPolicy({ rounding: value }, 'rounding', value);
                }}
              >
                <option value="unknown">Unknown</option>
                <option value="half_up_to_cent">
                  Nearest cent, half cents round up
                </option>
              </select>
            </Field>
          </div>
          {!usedCategories.length && (
            <p className="small muted">
              Choose a procedure benefit category to enter its coverage rules.
            </p>
          )}
          {usedCategories.map((category) => (
            <fieldset className="rule-group stack" key={category}>
              <legend>{category} services</legend>
              <div className="form-grid">
                <AmountField
                  percent
                  label={`${category} services · Plan pays`}
                  value={policy.insurerRateBpsByCategory?.[category]}
                  onChange={(value) =>
                    patchCategory('insurerRateBpsByCategory', category, value)
                  }
                />
                {categoryRules.map(([map, label]) => (
                  <Field key={map} label={`${category} services · ${label}`}>
                    <select
                      value={
                        policy[map]?.[category] == null
                          ? 'unknown'
                          : String(policy[map]?.[category])
                      }
                      onChange={(event) =>
                        patchCategory(
                          map,
                          category,
                          booleanValue(event.target.value),
                        )
                      }
                    >
                      <UnknownBooleanOptions />
                    </select>
                  </Field>
                ))}
              </div>
            </fieldset>
          ))}
          <div className="form-grid">
            {restrictions.map(([field, label]) => (
              <Field key={field} label={label}>
                <select
                  value={
                    policy[field] === null
                      ? 'unknown'
                      : policy[field].length
                        ? 'present'
                        : 'none'
                  }
                  onChange={(event) => {
                    const value = event.target.value;
                    patchPolicy(
                      {
                        [field]:
                          value === 'unknown'
                            ? null
                            : value === 'none'
                              ? []
                              : [
                                  {
                                    id: `reported-${field}`,
                                    description: `User reports a ${label.toLowerCase()} rule; details require review.`,
                                    categoryIds: [],
                                  },
                                ],
                      },
                      field,
                      value,
                    );
                  }}
                >
                  <option value="unknown">Unknown</option>
                  <option value="none">None</option>
                  <option value="present">Present</option>
                </select>
              </Field>
            ))}
          </div>
          <Notice>
            Waiting periods, exclusions and frequency restrictions need a
            separate review. Reporting one preserves an unsupported result
            instead of assuming coverage.
          </Notice>
        </div>
      </Disclosure>

      <div className="stack">
        <h3>Benefit years</h3>
        <p className="small muted">
          Enter the exact period from this plan's benefits summary. Dates and
          balances are independent for each plan; nothing is filled in
          automatically.
        </p>
        {!years.length && <Badge tone="warning">Benefit year unknown</Badge>}
        {years.map(([id, year], index) => (
          <fieldset className="rule-group stack" key={id}>
            <legend>Benefit year {index + 1}</legend>
            <div className="form-grid">
              <Field
                label="Benefit year starts"
                error={
                  submitted && !year.startDate
                    ? 'Enter the benefit year start date.'
                    : undefined
                }
              >
                <input
                  type="date"
                  required
                  value={year.startDate}
                  onChange={(event) =>
                    patchYear(id, year, 'startDate', event.target.value)
                  }
                />
              </Field>
              <Field
                label="Benefit year ends"
                error={
                  submitted && !year.endDate
                    ? 'Enter the benefit year end date.'
                    : submitted && year.endDate < year.startDate
                      ? 'End date must not be before start date.'
                      : undefined
                }
              >
                <input
                  type="date"
                  required
                  min={year.startDate || undefined}
                  value={year.endDate}
                  onChange={(event) =>
                    patchYear(id, year, 'endDate', event.target.value)
                  }
                />
              </Field>
              {(
                [
                  ['annualMaximumCents', 'Annual insurer maximum'],
                  ['annualDeductibleCents', 'Annual deductible'],
                  ['insurerAlreadyPaidCents', 'Insurer already paid'],
                  ['deductibleAlreadyMetCents', 'Deductible already met'],
                ] as const
              ).map(([field, label]) => (
                <AmountField
                  key={field}
                  label={label}
                  value={year[field]}
                  onChange={(value) => patchYear(id, year, field, value)}
                />
              ))}
            </div>
            <Button
              variant="ghost"
              aria-label={`Remove benefit year ${index + 1}`}
              onClick={() => {
                const planYears = { ...plan.planYears };
                delete planYears[id];
                edit({ planYears }, `planYears.${id}`, null);
              }}
            >
              Remove benefit year
            </Button>
          </fieldset>
        ))}
        <div>
          <Button
            variant="secondary"
            disabled={years.length >= 6}
            onClick={() => {
              let number = 1;
              while (plan.planYears[`benefit-year-${number}`]) number += 1;
              const id = `benefit-year-${number}`;
              edit(
                {
                  planYears: {
                    ...plan.planYears,
                    [id]: {
                      startDate: '',
                      endDate: '',
                      annualMaximumCents: null,
                      annualDeductibleCents: null,
                      insurerAlreadyPaidCents: null,
                      deductibleAlreadyMetCents: null,
                      sourceStatus: 'user_entered',
                    },
                  },
                },
                `planYears.${id}`,
                null,
              );
            }}
          >
            Add benefit year
          </Button>
        </div>
      </div>
    </fieldset>
  );
}
