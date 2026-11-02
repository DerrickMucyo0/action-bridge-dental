import { defineConfig } from '@playwright/test';
import base from './playwright.config';

export default defineConfig({
  ...base,
  testMatch: [
    '**/core-background-jobs.spec.ts',
    '**/core-public-account-actions.spec.ts',
  ],
  testIgnore: [],
  outputDir: 'test-results/core',
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report/core', open: 'never' }],
  ],
  webServer: {
    command: 'npx vite --host 127.0.0.1 --port 5174 --strictPort',
    url: 'http://127.0.0.1:5174',
    reuseExistingServer: false,
    env: {
      VITE_API_BASE_URL: 'https://api.test.invalid/dev',
      VITE_COGNITO_CLIENT_ID: 'testclientid0123456789abcd',
      VITE_COGNITO_REGION: 'us-east-2',
      VITE_BACKGROUND_JOBS_ENABLED: 'false',
      VITE_PUBLIC_ACCOUNT_ACTIONS_ENABLED: 'false',
    },
  },
});
