import {
  AgentJobViewSchema,
  CoverageComparisonSchema,
  CreateCaseResponseSchema,
  CreateJobResponseSchema,
  CreateUploadResponseSchema,
  DentalCaseSchema,
  ErrorEnvelopeSchema,
  EstimateResultSchema,
  LedgerPageSchema,
  PlanComparisonResultSchema,
  PlanComparisonListSchema,
  RETRY_POLICY,
  retryDelayMs,
  SaveStrategyResponseSchema,
  SavePlanComparisonResponseSchema,
  SavedPlanComparisonSchema,
  ScenarioComparisonResultSchema,
  SpeechResponseSchema,
  StrategyListSchema,
  type CreateCaseRequest,
  type CreateJobRequest,
  type CreateUploadRequest,
  type CreateUploadResponse,
  type ErrorIssue,
  type JobAnswersRequest,
  type PatchCaseRequest,
  type PlanComparisonRequest,
  type SaveStrategyRequest,
  type SavePlanComparisonRequest,
} from '@actionbridge/contracts';
import type { z } from 'zod';

/**
 * Typed client for the live ActionBridge API (same contract as the mobile app). Every response is
 * validated against the shared schemas; failures surface as ApiError with a user-facing message
 * and the request ID. The client never substitutes sample data for a failed live call.
 */
export type ApiErrorCode =
  | 'NETWORK'
  | 'TIMEOUT'
  | 'UNAUTHENTICATED'
  | 'BAD_RESPONSE'
  | 'BAD_REQUEST'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'REVISION_CONFLICT'
  | 'IDEMPOTENCY_CONFLICT'
  | 'INCONSISTENT_INPUT'
  | 'RATE_LIMITED'
  | 'UPSTREAM_UNAVAILABLE'
  | 'FEATURE_UNAVAILABLE'
  | 'INTERNAL';

export class ApiError extends Error {
  constructor(
    readonly code: ApiErrorCode,
    message: string,
    readonly options: {
      status?: number;
      requestId?: string;
      retryable?: boolean;
      issues?: ErrorIssue[];
    } = {},
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export interface ApiClientOptions {
  baseUrl: string;
  getAccessToken: () => Promise<string | null>;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  sleep?: (ms: number) => Promise<void>;
  random?: () => number;
  /** Called when a call finds the session ended (no token or HTTP 401), before the error is thrown. */
  onUnauthenticated?: () => void;
  backgroundJobsEnabled?: boolean;
}

export function createApiClient({
  baseUrl,
  getAccessToken,
  fetchImpl = (...args) => fetch(...args),
  timeoutMs = 15_000,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  random = Math.random,
  onUnauthenticated,
  backgroundJobsEnabled = true,
}: ApiClientOptions) {
  const background = <T>(run: () => Promise<T>): Promise<T> =>
    backgroundJobsEnabled
      ? run()
      : Promise.reject(
          new ApiError(
            'FEATURE_UNAVAILABLE',
            'Assistant analysis, uploads and voice are unavailable in this version. Enter details manually instead.',
            { retryable: false },
          ),
        );
  const sessionEnded = (error: ApiError) => {
    onUnauthenticated?.();
    return error;
  };

  async function once<S extends z.ZodType>(
    method: string,
    path: string,
    schema: S,
    body?: unknown,
    extraHeaders: Record<string, string> = {},
  ): Promise<z.infer<S>> {
    const token = await getAccessToken();
    if (!token)
      throw sessionEnded(
        new ApiError('UNAUTHENTICATED', 'Your session ended. Sign in again.'),
      );

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let response: Response;
    let json: unknown;
    try {
      response = await fetchImpl(`${baseUrl}${path}`, {
        method,
        headers: {
          authorization: `Bearer ${token}`,
          'content-type': 'application/json',
          ...extraHeaders,
        },
        signal: controller.signal,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      if (response.status === 401) {
        // The status already establishes an expired/rejected session. Do not
        // wait for an error body before ending it; stop reading that body.
        controller.abort();
      } else {
        // Fetch resolves when headers arrive. Keep the deadline active while
        // reading the body so a stalled response cannot leave the UI pending.
        // Invalid JSON remains a schema/BAD_RESPONSE failure below.
        json = await response.json().catch(() => undefined);
        if (controller.signal.aborted)
          throw new DOMException('Response deadline exceeded', 'AbortError');
      }
    } catch {
      const safeRead = method === 'GET' || method === 'HEAD';
      if (controller.signal.aborted)
        throw new ApiError(
          'TIMEOUT',
          safeRead
            ? 'The server took too long to respond. Your input is safe — try again.'
            : 'The request timed out before its outcome could be confirmed. Check your saved records before submitting again.',
          { retryable: safeRead },
        );
      throw new ApiError(
        'NETWORK',
        safeRead
          ? 'Can’t reach the service. Your input is safe — check your connection and try again.'
          : 'The connection failed before the request outcome could be confirmed. Check your saved records before submitting again.',
        { retryable: safeRead },
      );
    } finally {
      clearTimeout(timer);
    }

    const requestId = response.headers.get('x-request-id') ?? undefined;

    if (response.status === 401)
      throw sessionEnded(
        new ApiError('UNAUTHENTICATED', 'Your session ended. Sign in again.', {
          status: 401,
          ...(requestId ? { requestId } : {}),
        }),
      );
    if (!response.ok) {
      const envelope = ErrorEnvelopeSchema.safeParse(json);
      if (envelope.success) {
        const { code, message, retryable, issues } = envelope.data.error;
        throw new ApiError(code, message, {
          status: response.status,
          requestId: envelope.data.error.requestId,
          retryable,
          ...(issues ? { issues } : {}),
        });
      }
      throw new ApiError(
        response.status >= 500 ? 'UPSTREAM_UNAVAILABLE' : 'BAD_RESPONSE',
        'The service returned an unexpected error.',
        {
          status: response.status,
          retryable: response.status >= 500,
          ...(requestId ? { requestId } : {}),
        },
      );
    }

    const parsed = schema.safeParse(json);
    if (!parsed.success)
      throw new ApiError(
        'BAD_RESPONSE',
        'The service returned data this version of the site does not understand.',
        { status: response.status, ...(requestId ? { requestId } : {}) },
      );
    return parsed.data;
  }

  /** Safe reads retry with bounded exponential backoff and jitter; writes never auto-retry. */
  async function read<S extends z.ZodType>(
    path: string,
    schema: S,
  ): Promise<z.infer<S>> {
    for (let attempt = 1; ; attempt++) {
      try {
        return await once('GET', path, schema);
      } catch (error) {
        const retryable =
          error instanceof ApiError && error.options.retryable === true;
        if (!retryable || attempt >= RETRY_POLICY.maxAttempts) throw error;
        await sleep(retryDelayMs(attempt, random));
      }
    }
  }

  const casePath = (caseId: string) =>
    `/v1/cases/${encodeURIComponent(caseId)}`;
  const jobPath = (jobId: string) => `/v1/jobs/${encodeURIComponent(jobId)}`;

  return {
    createCase: (request: CreateCaseRequest) =>
      once('POST', '/v1/cases', CreateCaseResponseSchema, request),
    getCase: (caseId: string) => read(casePath(caseId), DentalCaseSchema),
    patchCase: (caseId: string, request: PatchCaseRequest) =>
      once('PATCH', casePath(caseId), CreateCaseResponseSchema, request),
    estimate: (caseId: string, expectedRevision: number) =>
      once('POST', `${casePath(caseId)}/estimates`, EstimateResultSchema, {
        expectedRevision,
      }),
    scenarios: (caseId: string, expectedRevision: number) =>
      once(
        'POST',
        `${casePath(caseId)}/scenarios`,
        ScenarioComparisonResultSchema,
        { expectedRevision },
      ),
    coverageComparison: (caseId: string, expectedRevision: number) =>
      once(
        'POST',
        `${casePath(caseId)}/coverage-comparison`,
        CoverageComparisonSchema,
        { expectedRevision },
      ),
    planComparison: (request: PlanComparisonRequest) =>
      once(
        'POST',
        `${casePath(request.caseId)}/plan-comparison`,
        PlanComparisonResultSchema,
        request,
      ),
    savePlanComparison: (
      caseId: string,
      request: SavePlanComparisonRequest,
      idempotencyKey: string,
    ) =>
      once(
        'POST',
        `${casePath(caseId)}/plan-comparisons`,
        SavePlanComparisonResponseSchema,
        request,
        { 'idempotency-key': idempotencyKey },
      ),
    listPlanComparisons: (caseId: string, expectedRevision: number) =>
      read(
        `${casePath(caseId)}/plan-comparisons?expectedRevision=${expectedRevision}`,
        PlanComparisonListSchema,
      ),
    getPlanComparison: (
      caseId: string,
      comparisonId: string,
      expectedRevision: number,
    ) =>
      read(
        `${casePath(caseId)}/plan-comparisons/${encodeURIComponent(comparisonId)}?expectedRevision=${expectedRevision}`,
        SavedPlanComparisonSchema,
      ),
    /** Create the idempotency key once per Save action and reuse it for retries of that action. */
    saveStrategy: (
      caseId: string,
      request: SaveStrategyRequest,
      idempotencyKey: string,
    ) =>
      once(
        'POST',
        `${casePath(caseId)}/strategies`,
        SaveStrategyResponseSchema,
        request,
        { 'idempotency-key': idempotencyKey },
      ),
    listStrategies: (caseId: string) =>
      read(`${casePath(caseId)}/strategies`, StrategyListSchema),
    ledger: (caseId: string, cursor?: string) =>
      read(
        `${casePath(caseId)}/ledger${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`,
        LedgerPageSchema,
      ),
    createUpload: (caseId: string, request: CreateUploadRequest) =>
      background(() =>
        once(
          'POST',
          `${casePath(caseId)}/uploads`,
          CreateUploadResponseSchema,
          request,
        ),
      ),
    createJob: (caseId: string, request: CreateJobRequest) =>
      background(() =>
        once(
          'POST',
          `${casePath(caseId)}/jobs`,
          CreateJobResponseSchema,
          request,
        ),
      ),
    getJob: (jobId: string) =>
      background(() => read(jobPath(jobId), AgentJobViewSchema)),
    answerJob: (jobId: string, request: JobAnswersRequest) =>
      background(() =>
        once(
          'POST',
          `${jobPath(jobId)}/answers`,
          CreateJobResponseSchema,
          request,
        ),
      ),
    retryJob: (jobId: string) =>
      background(() =>
        once('POST', `${jobPath(jobId)}/retry`, CreateJobResponseSchema, {}),
      ),
    /** Amazon Polly reads short app text aloud (accessibility). */
    speech: (text: string) =>
      background(() =>
        once('POST', '/v1/speech', SpeechResponseSchema, {
          text: text.slice(0, 1500),
        }),
      ),
    cancelJob: (jobId: string) =>
      background(() =>
        once('POST', `${jobPath(jobId)}/cancel`, AgentJobViewSchema, {}),
      ),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;

/** Normalizes anything thrown by an API call into an ApiError the UI can display. */
export function asApiError(caught: unknown): ApiError {
  return caught instanceof ApiError
    ? caught
    : new ApiError('INTERNAL', 'Something went wrong. Try again.');
}

/**
 * Sends a file to its presigned S3 POST slot. S3 enforces the size limit and content type; any
 * non-2xx response is an error. The file never passes through the API.
 */
export async function uploadToSlot(
  slot: CreateUploadResponse,
  file: Blob,
  fetchImpl: typeof fetch = (...args) => fetch(...args),
): Promise<void> {
  const form = new FormData();
  for (const [key, value] of Object.entries(slot.fields))
    form.append(key, value);
  form.append('file', file);
  let response: Response;
  try {
    response = await fetchImpl(slot.url, { method: 'POST', body: form });
  } catch {
    throw new ApiError(
      'NETWORK',
      'The upload could not reach storage. Check your connection and try again.',
      { retryable: true },
    );
  }
  if (!response.ok)
    throw new ApiError(
      'BAD_REQUEST',
      response.status === 400 || response.status === 403
        ? 'The upload was refused — the file may be too large or the wrong type.'
        : `Upload failed (${response.status}).`,
      { status: response.status },
    );
}
