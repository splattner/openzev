/** Shared data for the user-guide captures, prepared before any of them runs. */
import { expect, test as setup } from '@playwright/test'
import fs from 'fs'
import type { TariffSeries } from '../src/types/api'
import { API_BASE, SCHEDULED_CHANGE_FILE, SCHEDULED_TARIFF, findDemoInvoice, getAdminToken, resolveDemoZevId } from './helpers'

// Reseeding wipes stored PDFs, and the invoice pages show whether one exists.
setup('render the invoice PDF the captures show', async ({ page }) => {
  const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
  const invoice = await findDemoInvoice(page.request, headers)
  if (invoice.pdf_url) return
  const resp = await page.request.post(`${API_BASE}/invoices/invoices/${invoice.id}/generate-pdf/`, { headers })
  expect(resp.ok(), `PDF generation failed (${resp.status()})`).toBeTruthy()
  expect((await findDemoInvoice(page.request, headers)).pdf_url, 'Invoice PDF still missing after generation').toBeTruthy()
})

// The seed has no scheduled price change, which is what the tariff list's next-change
// line and the detail pane's Upcoming card show. Schedule one a month ahead, 5 % up,
// unless the demo already has one; capture.teardown.ts removes it again.
setup('schedule the price change the tariff captures show', async ({ page }) => {
  const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
  const zevId = await resolveDemoZevId(page)
  const listed = await page.request.get(`${API_BASE}/tariffs/tariffs/series/?zev_id=${zevId}`, { headers })
  expect(listed.ok(), `Tariff series request failed (${listed.status()})`).toBeTruthy()
  const series = (await listed.json() as TariffSeries[]).find(row => row.name === SCHEDULED_TARIFF)
  expect(series, `${SCHEDULED_TARIFF} missing — run seed_demo`).toBeTruthy()
  const today = new Date().toISOString().slice(0, 10)
  if (series!.versions.some(version => version.valid_from > today)) return
  const current = series!.versions.find(version => version.id === series!.active_version_id)
  expect(current, `${SCHEDULED_TARIFF} has no version in force`).toBeTruthy()

  const start = new Date(Date.now() + 30 * 86_400_000).toISOString().slice(0, 10)
  const created = await page.request.post(`${API_BASE}/tariffs/tariffs/${current!.id}/new-version/`, { headers, data: { valid_from: start } })
  expect(created.ok(), `Scheduling a price change failed (${created.status()})`).toBeTruthy()
  const added = await created.json() as { id: string; periods?: { id: string; price_chf_per_kwh: string }[] }
  const refreshed = await page.request.get(`${API_BASE}/tariffs/tariffs/series/?zev_id=${zevId}`, { headers })
  const version = (await refreshed.json() as TariffSeries[]).find(row => row.name === SCHEDULED_TARIFF)!
    .versions.find(candidate => candidate.id === added.id)!
  for (const period of version.periods) {
    const price = (Number(period.price_chf_per_kwh) * 1.05).toFixed(5)
    const patched = await page.request.patch(`${API_BASE}/tariffs/periods/${period.id}/`, { headers, data: { price_chf_per_kwh: price } })
    expect(patched.ok(), `Raising a band price failed (${patched.status()})`).toBeTruthy()
  }
  fs.writeFileSync(SCHEDULED_CHANGE_FILE, JSON.stringify({ created: added.id, predecessor: current!.id, predecessorValidTo: current!.valid_to }))
})
