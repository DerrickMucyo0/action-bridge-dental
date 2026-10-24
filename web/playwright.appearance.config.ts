import { defineConfig } from '@playwright/test';
import base from './playwright.config';

/** Optional read-only snapshot server; defaults to the working application. */
export default defineConfig({
  ...base,
  testMatch: ['appearance.spec.ts', 'landing-responsive.spec.ts'],
  workers: 1,
  use: {
    ...base.use,
    reducedMotion: 'reduce',
    ...(process.env.APPEARANCE_BASE_URL
      ? { baseURL: process.env.APPEARANCE_BASE_URL }
      : {}),
  },
  webServer: process.env.APPEARANCE_BASE_URL ? undefined : base.webServer,
});
