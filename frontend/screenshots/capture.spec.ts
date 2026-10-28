/**
 * Automated screenshot generation for user-guide documentation.
 *
 * Run:
 *   cd frontend
 *   npm run screenshots
 *
 * Screenshots are saved to: docs/user-guide/screenshots/ as 256-colour PNGs
 *
 * Environment variables:
 *   SCREENSHOT_BASE_URL  – default http://localhost:8080
 *   SCREENSHOT_USER      – default "admin"
 *   SCREENSHOT_PASSWORD  – default "admin1234"
 */
import { test, expect, type Page } from '@playwright/test'
import path from 'path'
import { fileURLToPath } from 'url'
import type { DynamicTariffSource, TariffSeries } from '../src/types/api'
import {
  assertPdfLoaded,
  closePdfSidebar,
  findDemoInvoice,
  getAdminToken,
  goToPreviousPeriod,
  impersonateDemoParticipant,
  navigateTo,
  pinDemoZev,
  quantizePng,
  resetHover,
  resolveDemoZevId,
  screenshotFull as captureFull,
  screenshotViewport as captureViewport,
  API_BASE,
  DEMO_ZEV_NAME,
  MISSING_DEMO_ZEV,
  SECOND_DEMO_ZEV_NAME,
} from './helpers'

const DEMO_ZEV_NAMES = [DEMO_ZEV_NAME, SECOND_DEMO_ZEV_NAME]


const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const SCREENSHOT_DIR = path.resolve(__dirname, '../../docs/user-guide/screenshots')

const screenshotFull = async (page: Page, name: string) => {
  await captureFull(page, SCREENSHOT_DIR, name)
  await quantizePng(path.join(SCREENSHOT_DIR, `${name}.png`))
}
const screenshotViewport = async (page: Page, name: string) => {
  await captureViewport(page, SCREENSHOT_DIR, name)
  await quantizePng(path.join(SCREENSHOT_DIR, `${name}.png`))
}

/**
 * Capture the invoice detail page from the top down to the bottom of `lastCard`,
 * without the sidebar. For a page whose subject is a card above the embedded
 * document, which a full-page capture would bury under a PDF viewer.
 */
async function screenshotAbovePdf(page: Page, name: string, lastCard: string) {
  await expect(page.locator('.skeleton-block:visible')).toHaveCount(0, { timeout: 30_000 })
  await resetHover(page)
  const box = await page.locator(lastCard).boundingBox()
  expect(box, `${lastCard} is not on the page`).toBeTruthy()
  const viewport = page.viewportSize()!
  const sidebar = 224
  const height = Math.ceil(box!.y + box!.height) + 12
  expect(height, `${name}: card ends below the viewport`).toBeLessThanOrEqual(viewport.height)
  const file = path.join(SCREENSHOT_DIR, `${name}.png`)
  await page.screenshot({ path: file, clip: { x: sidebar, y: 0, width: viewport.width - sidebar, height } })
  await quantizePng(file)
}

const DEMO_DYNAMIC_TARIFF = 'Netznutzung dynamisch'
const SEED_HINT = 'run `manage.py seed_demo` with its default end date before capturing screenshots'

/** Fail early when the seeded dynamic tariff or its prices are missing. */
async function requireDemoDynamicSource(page: Page): Promise<DynamicTariffSource> {
  const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
  const zevId = await resolveDemoZevId(page)
  const response = await page.request.get(`${API_BASE}/tariffs/tariffs/series/?zev_id=${zevId}`, { headers })
  expect(response.ok(), `Tariff series request failed (${response.status()})`).toBe(true)
  const series = await response.json() as TariffSeries[]
  const tariff = series.find(row => row.name === DEMO_DYNAMIC_TARIFF)?.versions[0]
  expect(tariff?.dynamic_source, `Dynamic demo tariff missing — ${SEED_HINT}`).toBeTruthy()
  const sourceResponse = await page.request.get(`${API_BASE}/tariffs/dynamic-sources/${tariff!.dynamic_source}/`, { headers })
  expect(sourceResponse.ok(), `Dynamic source request failed (${sourceResponse.status()})`).toBe(true)
  const source = await sourceResponse.json() as DynamicTariffSource
  expect(source.point_count, `Dynamic demo prices missing — ${SEED_HINT}`).toBeGreaterThan(0)
  return source
}

// ---------------------------------------------------------------------------
// Screenshot tests — one test per page / state
//
// Every test starts from the authenticated storage state the `setup` project
// saved (see screenshots.config.ts), so tests must not log in themselves.
//
// No test may change data another capture shows; shared fixtures belong in
// capture.setup.ts.
// ---------------------------------------------------------------------------

// Keep this outside the authenticated suite: its beforeEach pins the demo ZEV.
test.describe('Unauthenticated Screenshots', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('01-login', async ({ page }) => {
    await navigateTo(page, '/login')
    const cookies = await page.context().cookies(API_BASE)
    expect(cookies.some(cookie => cookie.name === 'openzev_access'),
      'Login capture must stay signed out').toBe(false)
    await page.waitForSelector('form')
    await screenshotFull(page, '01-login')
  })
})

test.describe('User Guide Screenshots', () => {
  test.beforeEach(async ({ page }) => {
    expect(await pinDemoZev(page), MISSING_DEMO_ZEV).toBe(true)
  })

  // 02 — Manager Overview
  test('02-dashboard', async ({ page }) => {
    await navigateTo(page, '/')
    await page.waitForSelector('#billing-periods', { timeout: 15_000 })
    await screenshotFull(page, '02-dashboard')
  })

  // 02c — Manager Energy balance (the former dashboard statistics surface)
  test('02c-energy-balance', async ({ page }) => {
    await navigateTo(page, '/dashboard')
    await page.waitForSelector('.period-selector', { timeout: 10_000 })
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/dashboard-summary/') && response.ok()),
      goToPreviousPeriod(page),
    ])
    await page.waitForSelector('.sankey-participant-label', { timeout: 15_000 })
    await screenshotFull(page, '02c-energy-balance')
  })

  // 02b — Participant Dashboard (via impersonation)
  test('02b-participant-dashboard', async ({ page }) => {
    await impersonateDemoParticipant(page)
    await navigateTo(page, '/')
    await page.waitForSelector('.card, .stat-card', { timeout: 10_000 })
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/dashboard-summary/') && response.ok()),
      goToPreviousPeriod(page),
    ])
    await page.waitForSelector('.sankey-participant-label', { timeout: 15_000 })
    await screenshotFull(page, '02b-participant-dashboard')
  })

  // 03 — Participants
  test('03-participants', async ({ page }) => {
    await navigateTo(page, '/participants')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshotFull(page, '03-participants')
  })

  // 03b — Participant create form with the allocation weight filled in, so
  // the guide can show how a weighted cost split is entered. Weight 2 is what
  // seed_demo gives most flats.
  test('03b-participant-allocation-weight', async ({ page }) => {
    await navigateTo(page, '/participants')
    await page.waitForSelector('table, .card', { timeout: 10_000 })

    await page
      .getByRole('button', {
        name: /new participant|neuer teilnehmer|nouveau participant|nuovo partecipante/i,
      })
      .click()
    // The modal is up once its footer button is reachable; waiting on the
    // overlay's inline z-index would tie the test to the modal's styling.
    const createButton = page.getByRole('button', { name: /create|erstellen|créer|creare/i })
    await createButton.waitFor({ timeout: 5_000 })

    // The weight input sits inside its label, so it is reachable by the
    // translated label text instead of being "the only numeric input".
    await page
      .getByLabel(/allocation weight|zuteilungsgewicht|attribution|allocazione/i)
      .fill('2')
    // Scroll to the modal's footer so the weight field, its hint text and the
    // action buttons share the frame instead of the field hugging the edge.
    await createButton.scrollIntoViewIfNeeded()
    await page.waitForTimeout(300)
    await screenshotViewport(page, '03b-participant-allocation-weight')
  })

  // 03c — The participant form for an organisation: the type switch, the
  // organisation name and the contact person, and the second name line.
  test('03c-participant-organisation', async ({ page }) => {
    await navigateTo(page, '/participants')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await page
      .getByRole('button', {
        name: /new participant|neuer teilnehmer|nouveau participant|nuovo partecipante/i,
      })
      .click()
    await page.locator('select:has(option[value="organisation"])').selectOption('organisation')
    await page.locator('input[name="organisation_name"]').fill('Bäckerei Muster GmbH')
    await page.locator('input[name="first_name"]').fill('Lea')
    await page.locator('input[name="last_name"]').fill('Muster')
    await page.locator('input[name="name_addition"]').fill('Filiale Aarestrasse')
    await page.waitForTimeout(300)
    await screenshotViewport(page, '03c-participant-organisation')
  })

  // 04 — Metering Points
  test('04-metering-points', async ({ page }) => {
    await navigateTo(page, '/metering-points')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshotFull(page, '04-metering-points')
  })

  // 04b — Metering Points with Assign Participant modal, captured against the
  // seeded unassigned metering point (CH-DEMO-CONS-0003) — no fixture needed.
  test('04b-metering-points-assign', async ({ page }) => {
    await navigateTo(page, '/metering-points')
    await page.waitForSelector('.metering-point-card, table, .card', { timeout: 10_000 })

    const pointCard = page.locator('.metering-point-card').filter({ hasText: 'CH-DEMO-CONS-0003' }).first()
    await expect(pointCard).toBeVisible({ timeout: 10_000 })

    const assignBtn = pointCard.getByRole('button', {
      name: /assign|zuweisen|assigner|assegna/i,
    })
    await assignBtn.click()

    // Wait for modal overlay to appear
    await page.waitForSelector('div[style*="z-index: 1000"]', { timeout: 5_000 })
    await page.waitForTimeout(500)
    await screenshotViewport(page, '04b-metering-points-assign')
  })

  // 05 — Metering Data / Charts (with a metering point selected)
  test('05-metering-data', async ({ page }) => {
    await navigateTo(page, '/metering/chart')
    await page.waitForSelector('.card', { timeout: 10_000 })
    // Select the first metering point that can carry readings — skipping the
    // "whole ZEV total" option (value __zev_total__, see
    // ALL_METERING_POINTS_VALUE in MeteringChartPage.tsx), which is the
    // management default and the first option, and would hide the Raw
    // Readings Table this screenshot is meant to show.
    const mpSelect = page.locator('select').first()
    const options = mpSelect.locator('option')
    await expect(mpSelect.locator('option[value]:not([value=""]):not([value="__zev_total__"])').first(),
      `Demo metering points missing — ${SEED_HINT}`).toBeAttached()
    const count = await options.count()
    for (let i = 0; i < count; i++) {
      const label = await options.nth(i).textContent()
      const value = await options.nth(i).getAttribute('value')
      if (value && value !== '__zev_total__' && label) {
        await mpSelect.selectOption(value)
        await page.waitForTimeout(1000)

        // Step back to the last complete period: the current one holds only the
        // days elapsed so far, which makes for a sparse chart.
        await goToPreviousPeriod(page)

        // Safety net if the seeded window ever moves: keep stepping back until a
        // period with readings is found, so the capture never depends on today.
        const prevPeriod = page.locator('button:has(svg[data-icon="arrow-left"])').first()
        for (let attempt = 0; attempt < 5; attempt++) {
          if (await page.locator('.recharts-wrapper').count()) break
          await prevPeriod.click()
          await page.waitForTimeout(1500)
        }
        break
      }
    }

    await page.waitForSelector('.recharts-wrapper', { timeout: 15_000 })
    await page.waitForTimeout(1000)
    await screenshotFull(page, '05-metering-data')
  })

  // 06 — ZEV Settings
  test('06-zev-settings', async ({ page }) => {
    await navigateTo(page, '/zev-settings')
    await page.waitForSelector('form, .card', { timeout: 10_000 })
    await screenshotFull(page, '06-zev-settings')
  })

  // Phase 3 surfaces have their own guide captures so tab placement and
  // selected-community/platform context stay visible in the documentation.
  for (const [name, route] of [
    ['06b-zev-billing-settings', '/zev-settings/billing'],
    ['06d-zev-people', '/zev-settings/people'],
    ['08e-billing-emails', '/billing/emails'],
    ['10b-admin-health', '/admin/health'],
  ]) {
    test(name, async ({ page }) => {
      await navigateTo(page, route)
      await expect(page.locator('[role="tab"][aria-selected="true"]')).toBeVisible()
      await screenshotFull(page, name)
    })
  }

  test('06c-zev-documents-settings', async ({ page }) => {
    await navigateTo(page, '/zev-settings/documents')
    await expect(page.locator('[data-zev-field="email_body_template"] textarea')).toBeVisible()
    await page.locator('[data-zev-field="email_body_template"] button').click()
    await expect(page.locator('[data-zev-field="email_body_template"] .zev-email-default-preview')).toBeVisible()
    await screenshotFull(page, '06c-zev-documents-settings')
  })

  // 07 — Tariffs
  test('07-tariffs', async ({ page }) => {
    await navigateTo(page, '/tariffs')
    await page.waitForSelector('.tariff-table, .empty-state', { timeout: 10_000 })
    await screenshotFull(page, '07-tariffs')
  })

  // 07b — A tariff's detail pane: the version in force, the scheduled change opened
  // beside it and the history with its price chart (capture.setup.ts schedules the
  // change).
  test('07b-tariff-versions', async ({ page }) => {
    await navigateTo(page, '/tariffs')
    const row = page.getByRole('button', { name: 'Grid Energy HT/NT', expanded: false }).first()
    await row.waitFor({ timeout: 10_000 })
    await row.click()
    const pane = page.locator('.detail-pane')
    await pane.locator('.tariff-version-toggle').click()
    // Waiting on the chart rather than the history: it renders only for a series
    // with more than one version, so it also asserts the seed still has them.
    await pane.locator('.disclosure > summary').last().click()
    await pane.locator('.tariff-price-history').waitFor({ timeout: 10_000 })
    await page.waitForTimeout(1000)  // let Recharts finish laying out
    await screenshotFull(page, '07b-tariff-versions')
  })

  // 07e — The same tariff with the scheduled change folded to its line, the way the
  // pane opens from the list's current row.
  test('07e-tariff-scheduled-change', async ({ page }) => {
    await navigateTo(page, '/tariffs')
    const row = page.getByRole('button', { name: 'Grid Energy HT/NT', expanded: false }).first()
    await row.waitFor({ timeout: 10_000 })
    await row.click()
    const pane = page.locator('.detail-pane')
    await expect(pane.locator('.tariff-version-toggle[aria-expanded="false"]'), `Scheduled change missing — ${SEED_HINT}`).toBeVisible()
    await screenshotFull(page, '07e-tariff-scheduled-change')
  })

  // 07f — The create form with its Bands section: an HT/NT tariff with both bands
  // entered before saving. Nothing is saved.
  test('07f-tariff-create-bands', async ({ page }) => {
    await navigateTo(page, '/tariffs')
    await page.getByRole('button', { name: 'Neuer Tarif' }).first().click()
    const pane = page.locator('.detail-pane')
    await pane.getByLabel('Name', { exact: true }).fill('Netzstrom HT/NT')
    const bands = pane.locator('.tariff-draft-bands')
    for (const [type, price, from, to] of [['high', '0.2850', '06:00', '22:00'], ['low', '0.1950', '22:00', '06:00']]) {
      await bands.getByRole('button', { name: 'Band hinzufügen' }).click()
      const editor = bands.locator('.tariff-draft-band-editor')
      await editor.locator('select').first().selectOption(type)
      await editor.locator('input[type="number"]').fill(price)
      await editor.locator('input[type="time"]').first().fill(from)
      await editor.locator('input[type="time"]').nth(1).fill(to)
      await editor.getByRole('button', { name: 'Band übernehmen' }).click()
    }
    await expect(bands.locator('.tariff-period-row')).toHaveCount(2)
    await screenshotFull(page, '07f-tariff-create-bands')
  })

  // 07d — A dynamic tariff's detail pane: its source with the details
  // disclosure opened. The fetched prices sit in a second disclosure whose
  // point table would make the capture several screens tall, so it stays shut.
  test('07d-tariff-dynamic-source', async ({ page }) => {
    await requireDemoDynamicSource(page)
    await navigateTo(page, '/tariffs')
    const row = page.getByRole('button', { name: DEMO_DYNAMIC_TARIFF, expanded: false }).first()
    await row.waitFor({ timeout: 10_000 })
    await row.click()
    const pane = page.locator('.detail-pane')
    const details = pane.locator('.tariff-period-section .disclosure > summary').first()
    await details.click()
    await expect(pane.locator('.tariff-period-section .disclosure[open]'), `Dynamic source details missing — ${SEED_HINT}`).toBeVisible()
    await screenshotFull(page, '07d-tariff-dynamic-source')
  })

  // The fetched-price history modal that once had its own shot is gone: the same
  // content renders inline in the pane 07d already captures.

  // 08 — Invoices (period overview)
  test('08-invoices', async ({ page }) => {
    await navigateTo(page, '/billing/invoices')
    await page.waitForSelector('.period-selector', { timeout: 10_000 })
    // The page opens on the last complete period — exactly where seed_demo
    // bills — so no period navigation here (see goToPreviousPeriod docstring).
    await screenshotFull(page, '08-invoices')
  })

  // 08b — Invoice Detail page
  test('08b-invoice-detail', async ({ page }) => {
    const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
    const invoice = await findDemoInvoice(page.request, headers)
    expect(invoice.pdf_url, 'Invoice PDF missing — capture.setup.ts renders it').toBeTruthy()

    // screenshotFull grows the viewport to the content height, so the embedded
    // PDF viewer — which Chromium only paints inside the viewport — renders.
    await navigateTo(page, `/billing/invoices/${invoice.id}`)
    await page.waitForSelector('.invoice-figures', { timeout: 10_000 })
    await page.waitForSelector('iframe[title]', { timeout: 15_000 })
    await assertPdfLoaded(page)
    await closePdfSidebar(page)
    await screenshotFull(page, '08b-invoice-detail')
  })

  // 08f — Payments card of a partly paid invoice. Cropped above the embedded
  // document: the card is the subject, and the crop keeps the capture
  // independent of whether the invoice's PDF has been rendered.
  test('08f-invoice-payments', async ({ page }) => {
    const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
    const resp = await page.request.get(`${API_BASE}/invoices/invoices/?status=sent&page_size=100`, { headers })
    expect(resp.ok(), `Invoice list request failed (${resp.status()})`).toBeTruthy()
    const { results } = await resp.json() as {
      results: Array<{ id: string; zev_name: string; paid_chf: string; outstanding_chf: string }>
    }
    const invoice = results.find(row =>
      row.zev_name === DEMO_ZEV_NAME && Number(row.paid_chf) > 0 && Number(row.outstanding_chf) > 0)
    expect(invoice, `No partly paid ${DEMO_ZEV_NAME} invoice — ${SEED_HINT}`).toBeTruthy()

    await navigateTo(page, `/billing/invoices/${invoice!.id}`)
    await page.locator('#invoice-payments-title').waitFor({ timeout: 10_000 })
    await screenshotAbovePdf(page, '08f-invoice-payments', '[aria-labelledby="invoice-payments-title"]')
  })

  // 08g — Credit note card of a reversed invoice: the credit note, where it
  // was used, and the link to the replacement invoice under the title.
  test('08g-invoice-credit-note', async ({ page }) => {
    const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
    const listCredits = async () => {
      const resp = await page.request.get(`${API_BASE}/invoices/credits/`, { headers })
      expect(resp.ok(), `Credit list request failed (${resp.status()})`).toBeTruthy()
      const { results } = await resp.json() as {
        results: Array<{ kind: string; source_invoice: string; pdf_url: string | null }>
      }
      return results.find(credit => credit.kind === 'reversal')
    }
    let credit = await listCredits()
    expect(credit, `No reversal credit note — ${SEED_HINT}`).toBeTruthy()
    // The credit note PDF is rendered by the Celery worker; its row reads
    // "PDF in preparation" until then.
    for (let attempt = 0; attempt < 10 && !credit?.pdf_url; attempt++) {
      await page.waitForTimeout(1500)
      credit = await listCredits()
    }
    expect(credit?.pdf_url, 'Credit note PDF missing — is the Celery worker running?').toBeTruthy()

    await navigateTo(page, `/billing/invoices/${credit!.source_invoice}`)
    await page.locator('#invoice-credits-title').waitFor({ timeout: 10_000 })
    await screenshotAbovePdf(page, '08g-invoice-credit-note', '[aria-labelledby="invoice-credits-title"]')
  })

  // 08h — Record payment dialog, filled in with a partial amount against the
  // same partly paid invoice 08f shows.
  test('08h-record-payment-dialog', async ({ page }) => {
    const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
    const resp = await page.request.get(`${API_BASE}/invoices/invoices/?status=sent&page_size=100`, { headers })
    expect(resp.ok(), `Invoice list request failed (${resp.status()})`).toBeTruthy()
    const { results } = await resp.json() as {
      results: Array<{ id: string; zev_name: string; paid_chf: string; outstanding_chf: string }>
    }
    const invoice = results.find(row =>
      row.zev_name === DEMO_ZEV_NAME && Number(row.paid_chf) > 0 && Number(row.outstanding_chf) > 0)
    expect(invoice, `No partly paid ${DEMO_ZEV_NAME} invoice — ${SEED_HINT}`).toBeTruthy()

    await navigateTo(page, `/billing/invoices/${invoice!.id}`)
    await page.locator('#invoice-payments-title').waitFor({ timeout: 10_000 })
    await page.locator('[aria-labelledby="invoice-payments-title"]')
      .getByRole('button', { name: /zahlung erfassen/i }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await dialog.locator('input[type="number"]').fill((Number(invoice!.outstanding_chf) / 2).toFixed(2))
    await dialog.locator('input[type="text"]').last().fill('Zahlung per Überweisung')
    await screenshotViewport(page, '08h-record-payment-dialog')
  })

  // 08i — Correct invoice dialog on a paid invoice that has no credit note yet,
  // with a reason entered for the default "reverse the invoice" choice.
  test('08i-correct-invoice-dialog', async ({ page }) => {
    const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
    const invoicesResp = await page.request.get(`${API_BASE}/invoices/invoices/?status=paid&page_size=100`, { headers })
    expect(invoicesResp.ok(), `Invoice list request failed (${invoicesResp.status()})`).toBeTruthy()
    const creditsResp = await page.request.get(`${API_BASE}/invoices/credits/`, { headers })
    expect(creditsResp.ok(), `Credit list request failed (${creditsResp.status()})`).toBeTruthy()
    const { results: invoices } = await invoicesResp.json() as {
      results: Array<{ id: string; zev_name: string; total_chf: string }>
    }
    const { results: credits } = await creditsResp.json() as { results: Array<{ source_invoice: string }> }
    const credited = new Set(credits.map(credit => credit.source_invoice))
    const invoice = invoices.find(row =>
      row.zev_name === DEMO_ZEV_NAME && Number(row.total_chf) > 0 && !credited.has(row.id))
    expect(invoice, `No paid ${DEMO_ZEV_NAME} invoice to correct — ${SEED_HINT}`).toBeTruthy()

    await navigateTo(page, `/billing/invoices/${invoice!.id}`)
    await page.locator('#invoice-credits-title').waitFor({ timeout: 10_000 })
    await page.locator('[aria-labelledby="invoice-credits-title"]')
      .getByRole('button', { name: /rechnung korrigieren/i }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await dialog.locator('textarea').fill('Falscher Zählerstand, Rechnung neu erstellt')
    await screenshotViewport(page, '08i-correct-invoice-dialog')
  })

  // 08c — Participant My Invoices (via impersonation)
  // 08j — the period's one-off charges, under its invoices. The demo bills the
  // seeded charges in the last complete quarter, so the section shows them
  // together with the note that approved invoices freeze the period.
  test('08j-period-charges', async ({ page }) => {
    await navigateTo(page, '/billing/invoices')
    const section = page.locator('.period-charges')
    await expect(section.locator('tbody tr').first(), `Period charges missing — ${SEED_HINT}`).toBeVisible({ timeout: 10_000 })
    await resetHover(page)
    await section.screenshot({ path: path.join(SCREENSHOT_DIR, '08j-period-charges.png') })
    await quantizePng(path.join(SCREENSHOT_DIR, '08j-period-charges.png'))
  })

  test('08c-my-invoices', async ({ page }) => {
    await impersonateDemoParticipant(page, { requireSentInvoice: true })
    await navigateTo(page, '/me/invoices')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    // Rows appear even without a PDF — the state the guide's list section shows.
    await page.waitForSelector('tbody tr, .invoice-row', { timeout: 10_000 })
    await page.waitForTimeout(400)
    await screenshotFull(page, '08c-my-invoices')
  })

  // 09 — Imports
  test('09-imports', async ({ page }) => {
    await navigateTo(page, '/metering/imports')
    await page.waitForSelector('.card', { timeout: 10_000 })
    await screenshotFull(page, '09-imports')
  })

  // 09b — SDAT-CH import protocol: the seeded correction import shows the
  // guide's structured outcome ("Corrections applied"), observation
  // accounting, stable findings and the delivery identity.
  test('09b-import-protocol', async ({ page }) => {
    await navigateTo(page, '/metering/imports')
    await page.waitForSelector('tbody tr', { timeout: 10_000 })
    const row = page.locator('tbody tr', { hasText: 'e66-correction' })
    await expect(row).toHaveCount(1)
    await row.getByRole('button', {
      name: /open protocol|protokoll/i,
    }).click()
    await page.waitForSelector('div[role="dialog"]', { timeout: 10_000 })
    await page.waitForSelector('div[role="dialog"] .badge', { timeout: 10_000 })
    // A taller viewport shows outcome badge, accounting and findings together;
    // at 900px the findings sit below the fold of the scrolling dialog.
    await page.setViewportSize({ width: 1440, height: 1400 })
    await page.waitForTimeout(400)
    await screenshotViewport(page, '09b-import-protocol')
  })

  // 10 — Admin Dashboard
  test('10-admin-dashboard', async ({ page }) => {
    await navigateTo(page, '/admin')
    await page.waitForSelector('.card', { timeout: 10_000 })
    await screenshotFull(page, '10-admin-dashboard')
  })

  // 11 — Admin Accounts
  test('11-admin-accounts', async ({ page }) => {
    await navigateTo(page, '/admin/accounts/users')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshotFull(page, '11-admin-accounts')
  })

  // 12 — Admin Regional Settings
  test('12-admin-regional-settings', async ({ page }) => {
    await navigateTo(page, '/admin/system-settings?tab=regional')
    await page.waitForSelector('form, .card', { timeout: 10_000 })
    await screenshotFull(page, '12-admin-regional-settings')
  })

  // 13 — Admin VAT Settings (4th tab of System Settings)
  test('13-admin-vat-settings', async ({ page }) => {
    await navigateTo(page, '/admin/system-settings?tab=vat')
    await page.waitForURL('**/admin/system-settings?tab=vat', { timeout: 10_000 })
    await page.waitForSelector('form, table, .card', { timeout: 10_000 })
    await screenshotFull(page, '13-admin-vat-settings')
  })

  // 14 — Admin PDF Templates
  test('14-admin-pdf-templates', async ({ page }) => {
    await navigateTo(page, '/admin/pdf-templates')
    await page.waitForSelector('.card, textarea', { timeout: 10_000 })
    await page.waitForSelector('iframe[title]', { timeout: 15_000 })
    await assertPdfLoaded(page)
    await closePdfSidebar(page)
    await screenshotFull(page, '14-admin-pdf-templates')
  })

  // 14b — Admin Email Templates
  test('14b-admin-email-templates', async ({ page }) => {
    await navigateTo(page, '/admin/email-templates')
    await page.waitForSelector('.card, textarea', { timeout: 10_000 })
    await screenshotFull(page, '14b-admin-email-templates')
  })

  // 15 — Admin ZEV List
  // Only the two demo communities: a developer's own ZEVs on the same stack
  // (real names, real addresses) must never end up in the published guide.
  test('15-admin-zevs', async ({ page }) => {
    await page.route(/\/zev\/zevs\/(\?.*)?$/, async (route) => {
      const response = await route.fetch()
      const body = await response.json() as { results?: Array<{ name: string }>, count?: number } | Array<{ name: string }>
      const demo = (zev: { name: string }) => DEMO_ZEV_NAMES.includes(zev.name)
      const filtered = Array.isArray(body)
        ? body.filter(demo)
        : { ...body, results: body.results?.filter(demo), count: body.results?.filter(demo).length }
      await route.fulfill({ response, json: filtered })
    })
    await navigateTo(page, '/admin/zevs')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshotFull(page, '15-admin-zevs')
  })

  // 16 — Account: one capture per tab (the tab lives in ?tab=)
  test('16-account-profile', async ({ page }) => {
    await navigateTo(page, '/account?tab=profile')
    // Panels stay mounted (hidden), so wait for a *visible* card, not the first.
    await page.locator('.card:visible').first().waitFor({ timeout: 10_000 })
    await screenshotFull(page, '16-account-profile')
  })

  test('16b-account-security', async ({ page }) => {
    await navigateTo(page, '/account?tab=security')
    await page.locator('.card:visible').first().waitFor({ timeout: 10_000 })
    await screenshotFull(page, '16b-account-security')
  })

  test('16c-account-api-keys', async ({ page }) => {
    await navigateTo(page, '/account?tab=api-keys')
    await page.locator('.card:visible').first().waitFor({ timeout: 10_000 })
    await screenshotFull(page, '16c-account-api-keys')
  })

  // 17 — Admin Invoices
  test('17-admin-invoices', async ({ page }) => {
    await navigateTo(page, '/admin/invoices')
    await page.waitForSelector('.data-table, .card', { timeout: 10_000 })
    // The card is there while the list still loads; wait for the list itself.
    await expect(page.getByText(/werden geladen|loading/i)).toHaveCount(0, { timeout: 15_000 })
    await screenshotFull(page, '17-admin-invoices')
  })

  // 17b — Admin Dynamic Price Sources
  // The same disabled synthetic source as the dynamic tariff pane above.
  test('17b-admin-dynamic-sources', async ({ page }) => {
    const source = await requireDemoDynamicSource(page)
    await navigateTo(page, '/admin/dynamic-sources')
    await expect(page.getByRole('row').filter({ hasText: source.label })).toBeVisible()
    await screenshotFull(page, '17b-admin-dynamic-sources')
  })

  // 23 — Reports (owner view on the demo ZEV)
  test('23-reports', async ({ page }) => {
    await navigateTo(page, '/reports')
    // Demo readings belong to this year; the product defaults to the previous year.
    await page.getByRole('combobox', { name: 'Jahr', exact: true }).selectOption(String(new Date().getFullYear()))
    // The annual report aggregates a year of readings; wait for its figures.
    await page.waitForSelector('.kpi-row', { timeout: 30_000 })
    await screenshotFull(page, '23-reports')
  })

  test('23b-participant-annual-statement', async ({ page }) => {
    await impersonateDemoParticipant(page)
    await navigateTo(page, '/me/statement')
    await page.getByRole('combobox', { name: 'Jahr', exact: true }).selectOption(String(new Date().getFullYear()))
    await page.waitForSelector('#yearly-documents-preview iframe[title]', { timeout: 30_000 })
    await assertPdfLoaded(page)
    await closePdfSidebar(page)
    await screenshotFull(page, '23b-participant-annual-statement')
  })
})
