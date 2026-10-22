import type {
  ComparisonPlan,
  DentalCase,
  PlanComparisonRequest,
} from '@actionbridge/contracts';
import { ClipboardList } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Notice,
  PageHeading,
} from '../../components/ui';
import { amountLabel, dateLabel } from '../../domain/model';
import { isSampleCase } from '../../domain/provenance';
import { useCase } from '../../state/case-store';
import { ApiNotice } from '../assistant/assistant-page';
import {
  blankComparisonPlan,
  currentComparisonPlan,
  prepareComparison,
} from './comparison-model';
import {
  ComparisonResults,
  type ComparisonViewState,
} from './comparison-results';
import { PlanEditor } from './plan-editor';
import { usePlanComparison } from './use-plan-comparison';

export function PlanComparisonPage() {
  const { record, loading, error, reload } = useCase();
  const navigate = useNavigate();
  if (loading)
    return (
      <div className="page narrow" role="status">
        Loading your treatment…
      </div>
    );
  if (error)
    return (
      <div className="page narrow">
        <ApiNotice error={error} onRetry={() => void reload()} />
      </div>
    );
  if (!record || record.procedures.length === 0)
    return (
      <div className="page">
        <EmptyState
          icon={ClipboardList}
          title="Open a treatment first"
          description="Add and review your treatment before preparing an insurance plan comparison."
          action={<Button onClick={() => navigate('/')}>Start on Home</Button>}
        />
      </div>
    );
  return (
    <ConnectedComparisonWorkspace
      key={`${record.caseId}@${record.caseRevision}`}
      record={record}
      onReload={() => void reload()}
    />
  );
}

function ConnectedComparisonWorkspace({
  record,
  onReload,
}: {
  record: DentalCase;
  onReload: () => void;
}) {
  const { viewState, reloadRequired, compare, clear, retry } =
    usePlanComparison();
  return (
    <ComparisonWorkspace
      record={record}
      onCompare={compare}
      onDraftChange={clear}
      viewState={viewState}
      onRetry={retry}
      reloadRequired={reloadRequired}
      onReload={onReload}
    />
  );
}

export interface ComparisonWorkspaceProps {
  record: DentalCase;
  /** The caller supplies transport; drafts never write to the source case. */
  onCompare?: (request: PlanComparisonRequest) => void;
  onDraftChange?: () => void;
  viewState?: ComparisonViewState;
  onRetry?: () => void;
  reloadRequired?: boolean;
  onReload?: () => void;
}

/** Drafts last for this screen and source revision; editing never updates the current case. */
export function ComparisonWorkspace({
  record,
  onCompare,
  onDraftChange,
  viewState = { status: 'idle' },
  onRetry,
  reloadRequired = false,
  onReload,
}: ComparisonWorkspaceProps) {
  const [planA, setPlanA] = useState(() =>
    blankComparisonPlan('plan-a', record),
  );
  const [planB, setPlanB] = useState(() =>
    blankComparisonPlan('plan-b', record),
  );
  const [importVersion, setImportVersion] = useState(0);
  const [submitted, setSubmitted] = useState(false);
  const [message, setMessage] = useState('');
  const [prepared, setPrepared] = useState<PlanComparisonRequest | null>(null);
  const navigate = useNavigate();
  const busy = viewState.status === 'loading';
  const change = (side: 'A' | 'B', value: ComparisonPlan) => {
    (side === 'A' ? setPlanA : setPlanB)(value);
    setPrepared(null);
    setMessage('');
    onDraftChange?.();
  };
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || reloadRequired) return;
    setSubmitted(true);
    const prepared = prepareComparison(record, planA, planB);
    if (!prepared.ok) {
      setMessage(prepared.message);
      setPrepared(null);
      onDraftChange?.();
      const invalid =
        event.currentTarget.querySelector<HTMLElement>(':invalid');
      invalid?.focus();
      return;
    }
    // AmountField sets native custom validity for malformed numbers while keeping unknowns null.
    if (!event.currentTarget.checkValidity()) {
      setMessage(
        'Check the highlighted fields. Enter valid amounts and complete any benefit-year dates you added.',
      );
      event.currentTarget.querySelector<HTMLElement>(':invalid')?.focus();
      return;
    }
    setMessage('');
    setPrepared(prepared.request);
    onCompare?.(prepared.request);
  };
  return (
    <div className="page plan-comparison-page">
      <PageHeading
        eyebrow={
          isSampleCase(record)
            ? 'Synthetic sample · Treatment comparison'
            : 'Treatment comparison'
        }
        title="Compare insurance plans"
        description="The same dental treatment and dates, with each plan's own coverage and prices."
        actions={
          <Button variant="secondary" onClick={() => navigate('/facts')}>
            Review treatment
          </Button>
        }
      />
      <CommonTreatment record={record} />
      <Notice>
        Enter two plan configurations. Blank insurance amounts mean unknown,
        never zero. Compare to request estimates from the service. Changing a
        candidate plan does not edit your current case.
      </Notice>
      <form
        noValidate
        onSubmit={submit}
        className="stack"
        aria-label="Insurance plan comparison"
      >
        <div className="plan-comparison-grid">
          <PlanEditor
            key={importVersion}
            side="Plan A"
            record={record}
            plan={planA}
            submitted={submitted}
            onChange={(plan) => change('A', plan)}
            onUseCurrent={() => {
              change('A', currentComparisonPlan(record));
              setImportVersion((version) => version + 1);
            }}
          />
          <PlanEditor
            side="Plan B"
            record={record}
            plan={planB}
            submitted={submitted}
            onChange={(plan) => change('B', plan)}
          />
        </div>
        {message && <Notice tone="danger">{message}</Notice>}
        <div className="footer-actions">
          <p className="small muted">
            Treatment costs only. This does not enroll you in insurance or
            guarantee insurer payment.
          </p>
          <Button type="submit" busy={busy} disabled={reloadRequired}>
            Compare plans
          </Button>
        </div>
      </form>
      <ComparisonResults
        state={viewState}
        request={prepared}
        onRetry={onRetry}
        onReload={reloadRequired ? onReload : undefined}
      />
    </div>
  );
}

function CommonTreatment({ record }: { record: DentalCase }) {
  return (
    <Card className="comparison-treatment">
      <div className="section-title">
        <h3>Common treatment and schedule</h3>
        <Badge>Case version {record.caseRevision}</Badge>
      </div>
      <p className="small muted">
        These details apply to both plans. Confirm changes in your treatment
        review first.
      </p>
      <div
        className="table-scroll"
        tabIndex={0}
        aria-label="Common treatment and schedule"
      >
        <table>
          <caption className="visually-hidden">
            The treatment and planned dates used for both insurance plans
          </caption>
          <thead>
            <tr>
              <th scope="col">Treatment</th>
              <th scope="col">Planned date</th>
              <th scope="col">Dentist's charge</th>
            </tr>
          </thead>
          <tbody>
            {record.procedures.map((procedure) => {
              const date =
                procedure.proposedDate ?? procedure.dentistEarliestDate;
              return (
                <tr key={procedure.id}>
                  <th scope="row">{procedure.label}</th>
                  <td>{date ? dateLabel(date) : 'Date not answered'}</td>
                  <td>{amountLabel(procedure.providerChargeCents)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
