/**
 * Screenshot automation configuration.
 *
 * Usage:
 *   npm run screenshots
 *
 * The `setup` project logs in once and saves the authenticated storage state
 * (see auth.setup.ts); the `capture` project depends on it and starts every
 * test from that state, so a full run costs one login instead of one per
 * test — the backend throttles `auth/token/` per IP at 40/hour.
 *
 * Environment variables (optional overrides):
 *   SCREENSHOT_BASE_URL  – default http://localhost:8080
 *   SCREENSHOT_API_URL   – default http://localhost:8001/api/v1
 *   SCREENSHOT_USER      – default admin
 *   SCREENSHOT_PASSWORD   – default admin1234
 *   SCREENSHOT_CHANNEL    – optional Playwright channel override. Defaults to
 *                           "chromium" (the headless shell renders PDFs blank).
 */
import { defineConfig } from '@playwright/test'
import { AUTH_STATE_PATH } from './screenshots/helpers'

export default defineConfig({
  testDir: './screenshots',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  workers: 1,
  use: {
    baseURL: process.env.SCREENSHOT_BASE_URL ?? 'http://localhost:8080',
    viewport: { width: 1440, height: 900 },
    actionTimeout: 10_000,
    locale: 'de-CH',
    colorScheme: 'light',
    screenshot: 'off', // we take them manually
    // Full chromium build: the headless shell renders inline PDFs blank.
    channel: process.env.SCREENSHOT_CHANNEL ?? 'chromium',
  },
  projects: [
    {
      name: 'setup',
      testMatch: /auth\.setup\.ts/,
      use: { storageState: undefined },
    },
    {
      name: 'capture',
      dependencies: ['setup'],
      testIgnore: /auth\.setup\.ts/,
      use: { storageState: AUTH_STATE_PATH },
    },
  ],
})
