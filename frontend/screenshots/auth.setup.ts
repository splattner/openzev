/**
 * One-time authentication for the whole capture run.
 *
 * Runs as the `setup` project before the capture project (see
 * screenshots.config.ts) and saves the admin's authenticated storage state —
 * the httpOnly JWT cookies — plus the sidebar preference to
 * `screenshots/.auth/admin.json`. Every capture test then starts logged in
 * from that state instead of performing its own login: the backend throttles
 * `auth/token/` per IP at 40/hour, which a login-per-test suite burns through
 * in a single run.
 */
import { expect, test as setup } from '@playwright/test'
import fs from 'fs'
import path from 'path'
import { AUTH_STATE_PATH, API_BASE, BASE, USER, PASS } from './helpers'

setup('authenticate as admin', async ({ request }) => {
  const resp = await request.post(`${API_BASE}/auth/token/`, {
    data: { email: USER, password: PASS },
  })
  expect(resp.ok(), `Login failed (${resp.status()})`).toBeTruthy()

  // No page was opened, so the state has cookies only — add the sidebar
  // preference the captures used to set per context via addInitScript.
  const state = await request.storageState()
  expect(state.cookies.some(cookie => cookie.name === 'openzev_access'),
    'openzev_access cookie missing after login').toBe(true)
  state.origins = [
    {
      origin: new URL(BASE).origin,
      localStorage: [{ name: 'openzev.sidebarCollapsed', value: 'false' }],
    },
  ]

  fs.mkdirSync(path.dirname(AUTH_STATE_PATH), { recursive: true })
  fs.writeFileSync(AUTH_STATE_PATH, JSON.stringify(state))
})
