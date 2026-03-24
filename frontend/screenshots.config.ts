/**
 * Screenshot automation configuration.
 *
 * Usage:
 *   npx playwright test --config screenshots.config.ts
 *
 * Environment variables (optional overrides):
 *   SCREENSHOT_BASE_URL  – default http://localhost:8080
 *   SCREENSHOT_USER      – default admin
 *   SCREENSHOT_PASSWORD   – default admin1234
 */
import { defineConfig } from '@playwright/test'

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
  },
})
