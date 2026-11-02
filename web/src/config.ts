/**
 * Public client settings. VITE_* values are embedded in the built site, so they must never contain
 * secrets. Live mode only: a missing or malformed value shows a configuration error, never a
 * silent switch to sample data.
 */
export interface AppConfig {
  apiBaseUrl: string;
  cognitoClientId: string;
  cognitoRegion: string;
  backgroundJobsEnabled: boolean;
  publicAccountActionsEnabled: boolean;
}

export type ConfigResult =
  { ok: true; config: AppConfig } | { ok: false; problems: string[] };

export function readConfig(env: {
  apiBaseUrl: string | undefined;
  cognitoClientId: string | undefined;
  cognitoRegion: string | undefined;
  backgroundJobsEnabled?: string | undefined;
  publicAccountActionsEnabled?: string | undefined;
}): ConfigResult {
  const problems: string[] = [];
  const apiBaseUrl = env.apiBaseUrl?.trim().replace(/\/+$/, '') ?? '';
  if (
    !/^https:\/\/[^\s/]+(\/[^\s]*)?$/.test(apiBaseUrl) ||
    /\/v1$/.test(apiBaseUrl)
  )
    problems.push(
      'VITE_API_BASE_URL must be the https API URL including the stage, without /v1.',
    );
  const cognitoClientId = env.cognitoClientId?.trim() ?? '';
  if (!/^[a-z0-9]{20,40}$/i.test(cognitoClientId))
    problems.push('VITE_COGNITO_CLIENT_ID is missing or malformed.');
  const cognitoRegion = env.cognitoRegion?.trim() ?? '';
  if (!/^[a-z]{2}-[a-z]+-\d$/.test(cognitoRegion))
    problems.push('VITE_COGNITO_REGION is missing or malformed.');
  const backgroundSetting = env.backgroundJobsEnabled?.trim();
  if (
    backgroundSetting !== undefined &&
    !['true', 'false'].includes(backgroundSetting)
  )
    problems.push(
      'VITE_BACKGROUND_JOBS_ENABLED must be true or false when set.',
    );
  // Existing deployments retain their current behavior. Core staging explicitly
  // sets false; a malformed value is a configuration error, never a mock mode.
  const backgroundJobsEnabled = backgroundSetting !== 'false';
  const accountSetting = env.publicAccountActionsEnabled?.trim();
  if (
    accountSetting !== undefined &&
    !['true', 'false'].includes(accountSetting)
  )
    problems.push(
      'VITE_PUBLIC_ACCOUNT_ACTIONS_ENABLED must be true or false when set.',
    );
  // Independent of background services: existing full sites retain self-service.
  // Restricted release candidates explicitly disable these UI/transport actions.
  const publicAccountActionsEnabled = accountSetting !== 'false';
  return problems.length > 0
    ? { ok: false, problems }
    : {
        ok: true,
        config: {
          apiBaseUrl,
          cognitoClientId,
          cognitoRegion,
          backgroundJobsEnabled,
          publicAccountActionsEnabled,
        },
      };
}

export const appConfig: ConfigResult = readConfig({
  apiBaseUrl: import.meta.env?.VITE_API_BASE_URL,
  cognitoClientId: import.meta.env?.VITE_COGNITO_CLIENT_ID,
  cognitoRegion: import.meta.env?.VITE_COGNITO_REGION,
  backgroundJobsEnabled: import.meta.env?.VITE_BACKGROUND_JOBS_ENABLED,
  publicAccountActionsEnabled: import.meta.env
    ?.VITE_PUBLIC_ACCOUNT_ACTIONS_ENABLED,
});

export const backgroundJobsEnabled =
  appConfig.ok && appConfig.config.backgroundJobsEnabled;

export const publicAccountActionsEnabled =
  appConfig.ok && appConfig.config.publicAccountActionsEnabled;
