/** Shared data for the user-guide captures, prepared before any of them runs. */
import { expect, test as setup } from '@playwright/test'
import { API_BASE, findDemoInvoice, getAdminToken } from './helpers'

// Reseeding wipes stored PDFs, and the invoice pages show whether one exists.
setup('render the invoice PDF the captures show', async ({ page }) => {
  const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
  const invoice = await findDemoInvoice(page.request, headers)
  if (invoice.pdf_url) return
  const resp = await page.request.post(`${API_BASE}/invoices/invoices/${invoice.id}/generate-pdf/`, { headers })
  expect(resp.ok(), `PDF generation failed (${resp.status()})`).toBeTruthy()
  expect((await findDemoInvoice(page.request, headers)).pdf_url, 'Invoice PDF still missing after generation').toBeTruthy()
})
