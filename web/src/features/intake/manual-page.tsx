import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type { DentalCase, DentalCaseInput } from '@actionbridge/contracts';
import {
  Button,
  Card,
  Dialog,
  FooterActions,
  Notice,
  PageHeading,
} from '../../components/ui';
import { emptyPolicy, emptyProcedure } from '../../domain/case-fields';
import { ApiError, asApiError } from '../../services/api';
import { backgroundJobsEnabled } from '../../config';
import { useCase } from '../../state/case-store';
import { ApiNotice } from '../assistant/assistant-page';
import {
  CoverageFields,
  CoverageStatus,
  TreatmentFields,
  validateCase,
} from './case-forms';

export function ManualPage() {
  const [search] = useSearchParams();
  const requestedCaseId = search.get('caseId');
  const { caseId, record, error, open, reload } = useCase();
  const navigate = useNavigate();

  useEffect(() => {
    if (requestedCaseId && caseId !== requestedCaseId) open(requestedCaseId);
  }, [requestedCaseId, caseId, open]);

  if (requestedCaseId && record?.caseId !== requestedCaseId)
    return (
      <div className="page narrow centered">
        {error && caseId === requestedCaseId ? (
          <>
            <PageHeading title="Couldn’t open your saved case" />
            <ApiNotice error={error} onRetry={() => void reload()} />
            <Button variant="secondary" onClick={() => navigate('/')}>
              Back to Home
            </Button>
          </>
        ) : (
          <p className="muted" role="status">
            Opening your saved details…
          </p>
        )}
      </div>
    );

  return (
    <ManualForm
      key={requestedCaseId ?? 'new'}
      existing={requestedCaseId && record ? record : undefined}
    />
  );
}

function manualDraft(record?: DentalCase): DentalCaseInput {
  if (record) {
    const draft = structuredClone(record);
    // An empty case from the composer needs an editable row, with every amount
    // and timing fact still unknown until the user supplies it.
    if (draft.procedures.length === 0) draft.procedures = [emptyProcedure()];
    return draft;
  }
  return {
    caseRevision: 1,
    currency: 'USD',
    coverageMode: 'unknown',
    policy: emptyPolicy(),
    planYears: {},
    procedures: [emptyProcedure()],
  };
}

function ManualForm({ existing }: { existing?: DentalCase }) {
  const { create, update, reload } = useCase();
  const navigate = useNavigate();
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [input, setInput] = useState<DentalCaseInput>(() =>
    manualDraft(existing),
  );
  const [error, setError] = useState('');
  const [draftReset, setDraftReset] = useState(0);

  const loadLatest = async () => {
    const latest = await reload();
    if (latest && latest.caseId === existing?.caseId) {
      setInput(manualDraft(latest));
      setDraftReset((value) => value + 1);
      setFailure(null);
      setError('');
    }
  };

  return (
    <div className="page medium">
      <PageHeading
        eyebrow="Manual entry"
        title="Enter your details"
        description={
          existing
            ? 'Continue with your saved details. Leave unknown values empty and review your entries before calculating. Use made-up details in this demo.'
            : backgroundJobsEnabled
              ? 'Add what you know. Leave anything else empty and I’ll ask for it next. Use made-up details in this demo.'
              : 'Add what you know. Leave unknown values empty and add missing details before calculating. Use made-up details in this demo.'
        }
      />
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          if (saving) return;
          const error = validateCase(input);
          if (error) {
            setError(error);
            return;
          }
          setError('');
          setSaving(true);
          setFailure(null);
          try {
            if (existing) {
              if (input.caseRevision !== existing.caseRevision)
                throw new ApiError(
                  'REVISION_CONFLICT',
                  'This case changed. Load the latest details before saving your changes.',
                );
              await update(input);
            } else {
              const { caseRevision: _revision, ...request } = input;
              await create({
                ...request,
                policy: input.coverageMode === 'insured' ? input.policy : null,
              });
            }
            navigate('/facts');
          } catch (caught) {
            setFailure(asApiError(caught));
          } finally {
            setSaving(false);
          }
        }}
      >
        <Card>
          <CoverageStatus input={input} onChange={setInput} />
        </Card>
        <TreatmentFields
          key={`treatment-${draftReset}`}
          input={input}
          onChange={setInput}
        />
        {input.coverageMode === 'insured' && (
          <CoverageFields
            key={`coverage-${draftReset}`}
            input={input}
            onChange={setInput}
          />
        )}
        {error && <Notice tone="danger">{error}</Notice>}
        {failure && (
          <>
            <ApiNotice error={failure} />
            {existing && failure.code === 'REVISION_CONFLICT' && (
              <div>
                <Button variant="secondary" onClick={() => void loadLatest()}>
                  Load latest details
                </Button>
              </div>
            )}
          </>
        )}
        <FooterActions note="Prices and rules you enter are saved to your account and are not verified with your insurer.">
          <Button variant="secondary" onClick={() => navigate('/')}>
            Cancel
          </Button>
          <Button type="submit" busy={saving}>
            Continue to review
          </Button>
        </FooterActions>
      </form>
    </div>
  );
}
export function CaseEditor({
  section,
  onClose,
}: {
  section: 'treatment' | 'coverage';
  onClose: () => void;
}) {
  const { record, update } = useCase();
  const [input, setInput] = useState<DentalCaseInput>(() =>
    structuredClone(record!),
  );
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<ApiError | null>(null);
  return (
    <Dialog
      title={
        section === 'treatment' ? 'Edit your treatment' : 'Your plan’s coverage'
      }
      onClose={onClose}
      drawer
    >
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          if (saving) return;
          const error = validateCase(input);
          if (error) {
            setError(error);
            return;
          }
          setError('');
          setSaving(true);
          setFailure(null);
          try {
            await update(input);
            onClose();
          } catch (caught) {
            setFailure(asApiError(caught));
          } finally {
            setSaving(false);
          }
        }}
      >
        <p className="muted small">
          Saving updates your case and recalculates. Unknown values stay
          unknown.
        </p>
        {section === 'treatment' ? (
          <TreatmentFields input={input} onChange={setInput} />
        ) : (
          <>
            <CoverageStatus input={input} onChange={setInput} />
            {input.coverageMode !== 'self_pay' && (
              <CoverageFields input={input} onChange={setInput} />
            )}
          </>
        )}
        {error && <Notice tone="danger">{error}</Notice>}
        {failure && <ApiNotice error={failure} />}
        <div className="actions">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" busy={saving}>
            Save changes
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
