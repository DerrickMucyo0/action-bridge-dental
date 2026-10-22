import type {
  DentalCase,
  PlanComparisonList,
  PlanComparisonRequest,
  SavedPlanComparison,
} from '@actionbridge/contracts';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Card, Notice } from '../../components/ui';
import { ApiError, asApiError } from '../../services/api';
import { useApi } from '../../state/auth';
import { ApiNotice } from '../assistant/assistant-page';
import { prepareComparison } from './comparison-model';
import { matchesRequest, sameComparisonInputs } from './comparison-results';

/** Saved snapshots never update the source case or accept client-computed results. */
export function useSavedComparisons(
  record: DentalCase,
  onOpen: (comparison: SavedPlanComparison) => void,
) {
  const api = useApi();
  const [list, setList] = useState<PlanComparisonList | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<ApiError | null>(null);
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [consent, setConsent] = useState(false);
  const [saving, setSaving] = useState(false);
  const [opening, setOpening] = useState<string | null>(null);
  const [saved, setSaved] = useState<SavedPlanComparison | null>(null);
  const [reloadRequired, setReloadRequired] = useState(false);
  const generation = useRef(0);
  const listGeneration = useRef(0);
  const pending = useRef(false);
  const blocked = useRef(false);
  const key = useRef<string | null>(null);

  const noteFailure = useCallback((error: ApiError) => {
    if (error.code === 'REVISION_CONFLICT' || error.code === 'NOT_FOUND') {
      blocked.current = true;
      setReloadRequired(true);
    }
  }, []);

  const refresh = useCallback(async () => {
    const mine = ++listGeneration.current;
    setListLoading(true);
    setListError(null);
    try {
      const value = await api.listPlanComparisons(
        record.caseId,
        record.caseRevision,
      );
      if (mine !== listGeneration.current) return;
      if (
        value.caseId !== record.caseId ||
        value.caseRevision !== record.caseRevision
      )
        throw new ApiError(
          'BAD_RESPONSE',
          'The saved comparisons do not match this treatment version.',
        );
      setList(value);
    } catch (caught) {
      if (mine !== listGeneration.current) return;
      const error = asApiError(caught);
      noteFailure(error);
      setListError(error);
    } finally {
      if (mine === listGeneration.current) setListLoading(false);
    }
  }, [api, record.caseId, record.caseRevision, noteFailure]);

  useEffect(() => {
    void refresh();
    return () => {
      generation.current++;
      listGeneration.current++;
    };
  }, [refresh]);

  const clear = useCallback(() => {
    generation.current++;
    pending.current = false;
    key.current = null;
    setConsent(false);
    setSaving(false);
    setOpening(null);
    setSaved(null);
    setFailure(null);
  }, []);

  const save = async (request: PlanComparisonRequest) => {
    if (!consent || pending.current || blocked.current || saved) return;
    pending.current = true;
    const mine = ++generation.current;
    key.current ??= crypto.randomUUID();
    setSaving(true);
    setFailure(null);
    try {
      const value = await api.savePlanComparison(
        record.caseId,
        { comparison: request, consent: true },
        key.current,
      );
      if (mine !== generation.current) return;
      if (
        !sameComparisonInputs(value.comparison.request, request) ||
        !matchesRequest(value.comparison.result, request)
      )
        throw new ApiError(
          'BAD_RESPONSE',
          'The saved comparison does not match your submitted plans.',
        );
      setSaved(value.comparison);
      onOpen(value.comparison);
      void refresh();
    } catch (caught) {
      if (mine !== generation.current) return;
      const error = asApiError(caught);
      noteFailure(error);
      setFailure(error);
    } finally {
      if (mine === generation.current) {
        pending.current = false;
        setSaving(false);
      }
    }
  };

  const open = async (comparisonId: string) => {
    if (pending.current || blocked.current) return;
    clear();
    pending.current = true;
    const mine = ++generation.current;
    setOpening(comparisonId);
    try {
      const value = await api.getPlanComparison(
        record.caseId,
        comparisonId,
        record.caseRevision,
      );
      if (mine !== generation.current) return;
      const current = prepareComparison(
        record,
        value.request.planA,
        value.request.planB,
      );
      if (
        value.comparisonId !== comparisonId ||
        !current.ok ||
        !matchesRequest(value.result, current.request)
      )
        throw new ApiError(
          'BAD_RESPONSE',
          'The saved comparison does not match this treatment version.',
        );
      onOpen(value);
      setSaved(value);
    } catch (caught) {
      if (mine !== generation.current) return;
      const error = asApiError(caught);
      noteFailure(error);
      setFailure(error);
    } finally {
      if (mine === generation.current) {
        pending.current = false;
        setOpening(null);
      }
    }
  };

  return {
    list,
    listLoading,
    listError,
    failure,
    consent,
    setConsent,
    saving,
    opening,
    saved,
    reloadRequired,
    refresh,
    clear,
    save,
    open,
  };
}

export function SavedComparisons({
  state,
  request,
  canSave,
  reloadRequired = false,
  onReload,
}: {
  state: ReturnType<typeof useSavedComparisons>;
  request: PlanComparisonRequest | null;
  canSave: boolean;
  reloadRequired?: boolean;
  onReload: () => void;
}) {
  const busy = state.saving || state.opening !== null;
  const blocked = state.reloadRequired || reloadRequired;
  return (
    <Card>
      <div
        className="stack"
        role="region"
        aria-label="Saved insurance comparisons"
      >
        <h2>Save and reopen comparisons</h2>
        <p className="small muted">
          Saving keeps these inputs and the server's results in your account. It
          does not enroll you, submit a claim or use benefits. Incomplete
          comparisons keep their missing or unsupported status.
        </p>
        {state.failure && <ApiNotice error={state.failure} />}
        {state.reloadRequired && (
          <Notice tone="warning">
            The treatment version or access changed. Reload and review the
            treatment before saving or reopening a comparison.
            <Button variant="secondary" onClick={onReload}>
              Reload treatment
            </Button>
          </Notice>
        )}
        {state.saved ? (
          <Notice>
            Comparison saved in your account. Saved{' '}
            {new Date(state.saved.savedAt).toLocaleString()}.
          </Notice>
        ) : (
          canSave &&
          request && (
            <>
              <label
                className={`consent-box ${state.consent ? 'checked' : ''}`}
              >
                <input
                  type="checkbox"
                  checked={state.consent}
                  disabled={busy || blocked}
                  onChange={(event) => state.setConsent(event.target.checked)}
                />
                <span>
                  Save this insurance comparison and my answers in my account.
                </span>
              </label>
              <Button
                busy={state.saving}
                disabled={
                  !state.consent ||
                  busy ||
                  blocked ||
                  (state.failure !== null && !state.failure.options.retryable)
                }
                onClick={() => void state.save(request)}
              >
                {state.failure?.options.retryable
                  ? 'Retry saving comparison'
                  : 'Save comparison'}
              </Button>
            </>
          )
        )}
        <h3>Saved for this treatment version</h3>
        {state.listLoading && <p role="status">Loading saved comparisons…</p>}
        {state.listError && (
          <ApiNotice
            error={state.listError}
            onRetry={blocked ? undefined : () => void state.refresh()}
          />
        )}
        {!state.listLoading &&
          !state.listError &&
          state.list?.comparisons.length === 0 && (
            <p>No saved comparisons for this treatment version.</p>
          )}
        {state.list?.comparisons.map((comparison) => (
          <div key={comparison.comparisonId} className="stack">
            <p>
              {comparison.planALabel} / {comparison.planBLabel} ·{' '}
              {new Date(comparison.savedAt).toLocaleString()}
            </p>
            <Button
              variant="secondary"
              disabled={busy || blocked}
              busy={state.opening === comparison.comparisonId}
              onClick={() => void state.open(comparison.comparisonId)}
            >
              Open saved comparison: {comparison.planALabel} /{' '}
              {comparison.planBLabel}
            </Button>
          </div>
        ))}
      </div>
    </Card>
  );
}
