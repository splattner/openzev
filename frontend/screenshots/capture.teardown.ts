/** Leaves the demo data as the seed made it, once the user-guide captures are done. */
import { expect, test as teardown } from '@playwright/test'
import fs from 'fs'
import { API_BASE, SCHEDULED_CHANGE_FILE, getAdminToken } from './helpers'

teardown('remove the price change the tariff captures scheduled', async ({ page }) => {
  if (!fs.existsSync(SCHEDULED_CHANGE_FILE)) return
  const { created, predecessor, predecessorValidTo } = JSON.parse(fs.readFileSync(SCHEDULED_CHANGE_FILE, 'utf8')) as {
    created: string; predecessor: string; predecessorValidTo: string | null
  }
  const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
  const removed = await page.request.delete(`${API_BASE}/tariffs/tariffs/${created}/`, { headers })
  expect(removed.ok(), `Removing the scheduled version failed (${removed.status()})`).toBeTruthy()
  // Scheduling closed the version in force the day before; give it its end back.
  const restored = await page.request.patch(`${API_BASE}/tariffs/tariffs/${predecessor}/`, { headers, data: { valid_to: predecessorValidTo } })
  expect(restored.ok(), `Restoring the current version failed (${restored.status()})`).toBeTruthy()
  fs.rmSync(SCHEDULED_CHANGE_FILE)
})
