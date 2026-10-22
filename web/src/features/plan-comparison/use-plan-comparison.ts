import type {
  PlanComparisonRequest,
  PlanComparisonResult,
} from '@actionbridge/contracts';
import { useCallback, useEffect, useRef, useState } from 'react';
import { asApiError } from '../../services/api';
import { useApi } from '../../state/auth';
import type { ComparisonViewState } from './comparison-results';

/** A comparison belongs to one submitted draft and one mounted case revision. */
export function usePlanComparison() {
  const api = useApi();
  const [viewState, setViewState] = useState<ComparisonViewState>({
    status: 'idle',
  });
  const [reloadRequired, setReloadRequired] = useState(false);
  const generation = useRef(0);
  const pending = useRef(false);
  const blocked = useRef(false);
  const lastRequest = useRef<PlanComparisonRequest | null>(null);

  useEffect(
    () => () => {
      // Navigation, case switches and source revision changes discard outstanding responses.
      generation.current++;
    },
    [],
  );

  const clear = useCallback(() => {
    generation.current++;
    pending.current = false;
    lastRequest.current = null;
    if (!blocked.current) setViewState({ status: 'idle' });
  }, []);

  const compare = useCallback(
    async (request: PlanComparisonRequest) => {
      // A ref also guards submissions before React has rendered the loading state.
      if (pending.current || blocked.current) return;
      pending.current = true;
      lastRequest.current = request;
      const mine = ++generation.current;
      setViewState({ status: 'loading' });
      try {
        const result = await api.planComparison(request);
        if (mine !== generation.current) return;
        setViewState({ status: 'ready', result });
      } catch (caught) {
        if (mine !== generation.current) return;
        const error = asApiError(caught);
        const needsReload =
          error.code === 'REVISION_CONFLICT' || error.code === 'NOT_FOUND';
        if (needsReload) {
          blocked.current = true;
          setReloadRequired(true);
        }
        const message =
          error.code === 'REVISION_CONFLICT'
            ? 'This treatment changed since you opened it. Reload the treatment and review both plans before comparing again. Reloading clears the plan drafts.'
            : error.code === 'NOT_FOUND'
              ? 'This case is no longer available or you do not have access to it. Reload your treatment or open another case.'
              : error.code === 'FORBIDDEN'
                ? 'You do not have permission to compare this case. Open a case you own.'
                : error.message;
        setViewState({
          status: 'error',
          message,
          requestId: error.options.requestId,
          issues: error.options.issues,
          retryable: !needsReload && error.options.retryable === true,
        });
      } finally {
        if (mine === generation.current) pending.current = false;
      }
    },
    [api],
  );

  const retry = useCallback(() => {
    if (lastRequest.current) void compare(lastRequest.current);
  }, [compare]);

  const restore = useCallback(
    (request: PlanComparisonRequest, result: PlanComparisonResult) => {
      if (blocked.current) return;
      generation.current++;
      pending.current = false;
      lastRequest.current = request;
      setViewState({ status: 'ready', result });
    },
    [],
  );

  return { viewState, reloadRequired, compare, clear, retry, restore };
}
