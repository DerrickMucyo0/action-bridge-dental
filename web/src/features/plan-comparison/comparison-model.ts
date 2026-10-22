import {
  PlanComparisonProcedureSchema,
  PlanComparisonRequestSchema,
  type ComparisonPlan,
  type DentalCase,
  type PlanComparisonPolicy,
  type PlanComparisonRequest,
  type SourceFact,
} from '@actionbridge/contracts';

/** Known identities for two independently entered configurations; insurance facts start unknown. */
export function unknownPolicy(id: string): PlanComparisonPolicy {
  return {
    id,
    deductibleBeforeCoinsurance: null,
    allServicesCovered: null,
    rounding: null,
    deductibleAppliesByCategory: {},
    insurerRateBpsByCategory: {},
    annualMaximumAppliesByCategory: {},
    waitingPeriods: null,
    exclusions: null,
    frequencyRestrictions: null,
  };
}

export function blankComparisonPlan(
  side: 'plan-a' | 'plan-b',
  record: DentalCase,
): ComparisonPlan {
  return {
    planId: side,
    label: '',
    policy: unknownPolicy(side),
    planYears: {},
    sourceFacts: [],
    procedureFacts: Object.fromEntries(
      record.procedures.map((procedure) => [
        procedure.id,
        {
          category: null,
          network: 'unknown',
          allowedCents: null,
          contractualWriteoffCents: null,
        },
      ]),
    ),
  };
}

/** Explicit current-plan import only. Never initialize a different plan from these values. */
export function currentComparisonPlan(record: DentalCase): ComparisonPlan {
  const plan = blankComparisonPlan('plan-a', record);
  return {
    ...plan,
    label: 'Current plan',
    policy: structuredClone(record.policy),
    planYears: structuredClone(record.planYears),
    procedureFacts: Object.fromEntries(
      record.procedures.map((procedure) => [
        procedure.id,
        {
          category: procedure.category,
          network: procedure.network,
          allowedCents: procedure.allowedCents,
          contractualWriteoffCents: procedure.contractualWriteoffCents,
        },
      ]),
    ),
    sourceFacts: structuredClone(
      record.sourceFacts.flatMap((fact) => {
        if (
          fact.fieldPath.startsWith('policy.') ||
          fact.fieldPath.startsWith('planYears.')
        )
          return [fact];
        const [section, id, field] = fact.fieldPath.split('.');
        return section === 'procedures' &&
          [
            'category',
            'network',
            'allowedCents',
            'contractualWriteoffCents',
          ].includes(field)
          ? [{ ...fact, fieldPath: `procedureFacts.${id}.${field}` }]
          : [];
      }),
    ),
  };
}

/** Manual edits replace that field's provenance without claiming insurer verification. */
export function editComparisonPlan(
  plan: ComparisonPlan,
  patch: Partial<ComparisonPlan>,
  fieldPath: string,
  value: SourceFact['value'],
): ComparisonPlan {
  return {
    ...plan,
    ...patch,
    sourceFacts: [
      ...plan.sourceFacts.filter(
        (fact) =>
          fact.fieldPath !== fieldPath &&
          !fact.fieldPath.startsWith(`${fieldPath}.`),
      ),
      {
        id: `manual-${crypto.randomUUID()}`,
        fieldPath,
        value,
        sourceId: null,
        location: null,
        origin: 'user_entered',
        extractionStatus: 'not_applicable',
        userConfirmed: true,
        insurerVerification: { status: 'not_verified' },
        conflict: false,
        recordedAt: new Date().toISOString(),
      },
    ].slice(-200) as SourceFact[],
  };
}

/** Matches Ticket 07's stored shared-treatment projection; it contains no candidate insurance facts. */
export function comparisonTreatment(record: DentalCase) {
  const fields = new Set([
    ...Object.keys(PlanComparisonProcedureSchema.shape),
    'proposedDate',
  ]);
  const ids = new Set(record.procedures.map((procedure) => procedure.id));
  return {
    procedures: record.procedures.map((procedure) => {
      const {
        category,
        network,
        allowedCents,
        contractualWriteoffCents,
        proposedDate,
        selfPayQuote,
        ...shared
      } = procedure;
      return shared;
    }),
    schedule: record.procedures.map((procedure) => ({
      procedureId: procedure.id,
      date: procedure.proposedDate ?? procedure.dentistEarliestDate,
    })),
    sourceFacts: record.sourceFacts.filter((fact) => {
      if (fact.fieldPath === 'currency' || fact.fieldPath === 'procedures')
        return true;
      const [section, id, field] = fact.fieldPath.split('.');
      return (
        section === 'procedures' &&
        ids.has(id) &&
        (field === undefined || fields.has(field))
      );
    }),
  };
}

type Preparation =
  { ok: true; request: PlanComparisonRequest } | { ok: false; message: string };

/** Validates inputs only. No patient/insurer payments or cost differences are computed in the browser. */
export function prepareComparison(
  record: DentalCase,
  planA: ComparisonPlan,
  planB: ComparisonPlan,
): Preparation {
  if (!planA.label.trim() || !planB.label.trim())
    return { ok: false, message: 'Name both plans before continuing.' };
  const treatment = comparisonTreatment(record);
  if (treatment.schedule.some((entry) => entry.date === null)) {
    return {
      ok: false,
      message:
        'Confirm the missing treatment dates in your case before comparing plans.',
    };
  }
  for (const [side, plan] of [
    ['Plan A', planA],
    ['Plan B', planB],
  ] as const) {
    for (const procedure of record.procedures) {
      const facts = plan.procedureFacts[procedure.id];
      if (
        facts?.allowedCents != null &&
        procedure.providerChargeCents != null
      ) {
        if (facts.allowedCents > procedure.providerChargeCents) {
          return {
            ok: false,
            message: `${side}: the allowed amount for ${procedure.label} exceeds the dentist's charge.`,
          };
        }
        if (
          facts.contractualWriteoffCents != null &&
          facts.contractualWriteoffCents >
            procedure.providerChargeCents - facts.allowedCents
        ) {
          return {
            ok: false,
            message: `${side}: the write-off for ${procedure.label} exceeds the charge minus the allowed amount.`,
          };
        }
      }
    }
    const years = Object.values(plan.planYears).sort((a, b) =>
      a.startDate.localeCompare(b.startDate),
    );
    for (let i = 0; i < years.length; i++) {
      const year = years[i];
      if (
        year.startDate > year.endDate ||
        (i > 0 && year.startDate <= years[i - 1].endDate)
      ) {
        return {
          ok: false,
          message: `${side}: check the benefit-year dates. Periods must end after they start and cannot overlap.`,
        };
      }
      if (
        year.annualDeductibleCents !== null &&
        year.deductibleAlreadyMetCents !== null &&
        year.deductibleAlreadyMetCents > year.annualDeductibleCents
      ) {
        return {
          ok: false,
          message: `${side}: the deductible already met exceeds the annual deductible.`,
        };
      }
      if (
        year.annualMaximumCents !== null &&
        year.insurerAlreadyPaidCents !== null &&
        year.insurerAlreadyPaidCents > year.annualMaximumCents
      ) {
        return {
          ok: false,
          message: `${side}: insurer payments already made exceed the annual maximum.`,
        };
      }
    }
  }
  const parsed = PlanComparisonRequestSchema.safeParse({
    caseId: record.caseId,
    expectedRevision: record.caseRevision,
    currency: record.currency,
    treatment,
    planA,
    planB,
  });
  return parsed.success
    ? { ok: true, request: parsed.data }
    : {
        ok: false,
        message:
          'Check the plan names, amounts and benefit-year dates. Leave unknown insurance amounts blank.',
      };
}
