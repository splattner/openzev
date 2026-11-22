/**
 * Screenshot automation configuration.
 *
 * Usage:
 *   npm run screenshots
 *
 * The `setup` project logs in once and saves the authenticated storage state
 * (see auth.setup.ts); the other projects depend on it and start every test
 * from that state, so a full run costs one login instead of one per test —
 * the backend throttles `auth/token/` per IP at 40/hour. `capture` (the
 * user-guide set) runs after `capture-data`; `browser` (the rest) does not.
 *
 * Environment variables (optional overrides):
 *   SCREENSHOT_BASE_URL  – default http://localhost:8080
 *   SCREENSHOT_API_URL   – default http://localhost:8080/api/v1
 *                            (docker-compose.dev.yml: override with http://localhost:8001/api/v1)
 *   SCREENSHOT_USER      – default admin@openzev.local
 *   SCREENSHOT_PASSWORD   – default admin1234
 *   SCREENSHOT_CHANNEL    – optional Playwright channel override. Defaults to
 *                           "chromium" (the headless shell renders PDFs blank).
 */
import { defineConfig } from '@playwright/test'
import os from 'node:os'
import { AUTH_STATE_PATH } from './screenshots/helpers'

export default defineConfig({
  testDir: './screenshots',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  retries: 0,
  // Half the cores, capped at 8: more workers overload the dev backend and
  // flake (12 failed hub-workflow-links). Override per run with --workers=N.
  workers: Math.min(8, Math.max(1, Math.floor(os.cpus().length / 2))),
  use: {
    baseURL: process.env.SCREENSHOT_BASE_URL ?? 'http://localhost:8080',
    viewport: { width: 1440, height: 900 },
    actionTimeout: 10_000,
    locale: 'de-CH',
    colorScheme: 'light',
    // Recharts' default isAnimationActive ('auto') honours this, so charts
    // render without animating.
    reducedMotion: 'reduce',
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
      name: 'capture-data',
      dependencies: ['setup'],
      testMatch: /capture\.setup\.ts/,
      use: { storageState: AUTH_STATE_PATH },
    },
    {
      name: 'capture',
      dependencies: ['capture-data'],
      testMatch: /capture\.spec\.ts/,
      use: { storageState: AUTH_STATE_PATH },
    },
    {
      name: 'shot',
      dependencies: ['setup'],
      testMatch: /shot\.spec\.ts$/,
      use: { storageState: AUTH_STATE_PATH },
    },
    {
      name: 'browser',
      dependencies: ['setup'],
      testMatch: /\.spec\.ts$/,
      testIgnore: /(capture|shot)\.spec\.ts$/,
      use: { storageState: AUTH_STATE_PATH },
    },
  ],
})
