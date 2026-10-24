/**
 * Structured request log. Contains IDs, timing, status and error codes only — never request
 * bodies, plan values, documents, tokens or owner identifiers.
 */
export interface RequestLog {
  requestId: string;
  routeKey: string;
  statusCode: number;
  durationMs: number;
  errorCode?: string;
}

export function logRequest(entry: RequestLog): void {
  const level = entry.statusCode >= 500 ? 'error' : entry.statusCode >= 400 ? 'warn' : 'info';
  console.log(JSON.stringify({ level, message: 'request', ...entry }));
}

export function logEvent(level: 'info' | 'warn' | 'error', message: string, fields: Record<string, string | number | boolean> = {}): void {
  console.log(JSON.stringify({ level, message, ...fields }));
}

/**
 * Exceptions can contain submitted text in both `name` and `message`. Log only an exact,
 * reviewed operational classification; never truncate/serialize an untrusted exception.
 */
const SAFE_ERROR_NAMES: ReadonlySet<string> = new Set([
  'Error', 'TypeError', 'RangeError', 'ZodError', 'ModelError', 'HttpError',
  'AccessDeniedException', 'ResourceNotFoundException', 'ValidationException',
  'ThrottlingException', 'ServiceUnavailableException', 'InternalServerException',
  'ModelTimeoutException', 'ModelNotReadyException', 'ModelStreamErrorException',
  'ServiceQuotaExceededException', 'TimeoutError', 'AbortError',
  'ConditionalCheckFailedException', 'TransactionCanceledException',
  'ProvisionedThroughputExceededException', 'RequestLimitExceeded',
  'UnsupportedDocumentException', 'BadDocumentException', 'DocumentTooLargeException',
  'InvalidParameterException', 'TextractTimeout', 'ConflictException',
  'NoSuchKey', 'NotFound', 'UnrecognizedClientException', 'ExpiredTokenException',
]);

export function safeErrorName(error: unknown): string {
  const name = error instanceof Error ? error.name : undefined;
  return name !== undefined && SAFE_ERROR_NAMES.has(name) ? name : 'UnknownError';
}
