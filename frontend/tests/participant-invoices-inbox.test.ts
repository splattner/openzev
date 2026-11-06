import { act, createElement, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DeliveredDocument } from '../src/types/api'

const api = vi.hoisted(() => ({ list: vi.fn(), download: vi.fn() }))
const auth = vi.hoisted(() => ({
  user: null as unknown,
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/api/inbox', () => ({ listInboxDocuments: api.list, downloadInboxDocument: api.download }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: auth.user }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/appSettings', () => ({ useAppSettings: () => ({ settings: {} }), formatShortDate: (date: string) => date }))

import { MyInvoicesPage } from '../src/pages/MyInvoicesPage'
import { issuedDocumentFor } from '../src/features/reports/ParticipantYearDocuments'

function user(zevs: string[] = ['Community A'], participant = 'p1') {
  return {
    id: 5, role: 'user', username: 'p@example.com',
    memberships: zevs.map((name, index) => ({
      zev: `z${index}`, zev_name: name, zev_disabled: false, access: null,
      participants: [{ id: index === 0 ? participant : `${participant}-${index}`, valid_from: '2026-01-01', valid_to: null, live: true }],
    })),
  }
}

function invoiceRow(overrides: Partial<DeliveredDocument> = {}): DeliveredDocument {
  return {
    id: 'd1', zev: 'z0', zev_name: 'Community A', participant: 'p1', participant_name: 'Anna', kind: 'invoice',
    title: 'INV-1', document_number: 'INV-1', period_start: '2026-02-01', period_end: '2026-02-28',
    file_name: 'invoice_INV-1.pdf', size_bytes: 1000, sha256: 'x', delivered_at: '2026-03-01T10:00:00Z',
    delivered_by_name: null, superseded_at: null, superseded_by: null, withdrawn_at: null, batch_id: null,
    invoice: 'i1', invoice_status: 'sent', contract_issue: null, credit_figures: null,
    invoice_figures: {
      status: 'sent', due_date: '2099-01-01', total_chf: '108.10', credit_applied_chf: '50.00', amount_due_chf: '58.10',
      paid_chf: '0.00', outstanding_chf: '58.10', open_data_impact_count: 0,
    },
    ...overrides,
  }
}

function creditRow(overrides: Partial<DeliveredDocument> = {}): DeliveredDocument {
  return invoiceRow({
    id: 'c1', kind: 'credit_note', title: 'CN-00001', document_number: 'CN-00001', invoice: null,
    invoice_status: null, invoice_figures: null, file_name: 'credit_CN-00001.pdf',
    credit_figures: {
      amount_chf: '50.00', remaining_chf: '30.00', status: 'open', source_invoice_number: 'INV-0',
      applied_to: [{ invoice_number: 'INV-1', amount_chf: '20.00' }],
    },
    ...overrides,
  })
}

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))
beforeEach(() => {
  vi.clearAllMocks()
  auth.user = user()
  api.list.mockResolvedValue([])
  api.download.mockResolvedValue(new Blob(['%PDF']))
})

async function mount(body: ReactNode) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  await act(async () => root.render(createElement(MemoryRouter, null,
    createElement(QueryClientProvider, { client }, createElement(MantineProvider, null, body)),
  )))
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)) })
  cleanups.push(() => { act(() => root.unmount()); client.clear(); container.remove() })
  return { container, client }
}

describe('MyInvoicesPage (the invoice and credit note rows of the inbox)', () => {
  it('lists the account\'s invoices with what is owed and a download, and no link to a live invoice', async () => {
    api.list.mockResolvedValue([invoiceRow()])
    const { container } = await mount(createElement(MyInvoicesPage))

    expect(api.list).toHaveBeenCalledWith()
    expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
    expect(container.textContent).toContain('INV-1')
    expect(container.textContent).toContain('CHF 108.10')
    // Credit set against the invoice: the amount due is shown beneath the total.
    expect(container.textContent).toContain('CHF 58.10')
    expect(container.textContent).toContain('invoice.payment.due')
    expect(container.textContent).not.toContain('invoice.status.sent')
    expect(container.querySelector('tbody a')).toBeNull()

    await act(async () => container.querySelector<HTMLButtonElement>('tbody button')!.click())
    expect(api.download).toHaveBeenCalledWith('d1')
  })

  it('keeps only rows addressed to the account\'s own participations and only invoices in the invoice table', async () => {
    api.list.mockResolvedValue([
      invoiceRow(),
      invoiceRow({ id: 'd2', participant: 'someone-else', title: 'INV-2' }),
      { ...invoiceRow({ id: 'd3', kind: 'operator', title: 'House rules' }), invoice: null, invoice_figures: null },
    ])
    const { container } = await mount(createElement(MyInvoicesPage))

    expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
    expect(container.textContent).toContain('INV-1')
    expect(container.textContent).not.toContain('INV-2')
    expect(container.textContent).not.toContain('House rules')
  })

  it('marks an overdue invoice and a cancelled one by what the participant needs to know', async () => {
    const figures = invoiceRow().invoice_figures!
    api.list.mockResolvedValue([
      invoiceRow({ id: 'late', title: 'INV-LATE', invoice_figures: { ...figures, due_date: '2020-01-01' } }),
      invoiceRow({ id: 'void', title: 'INV-VOID', invoice_figures: { ...figures, status: 'cancelled', outstanding_chf: '0.00' } }),
    ])
    const { container } = await mount(createElement(MyInvoicesPage))

    expect(container.textContent).toContain('invoice.payment.overdue')
    expect(container.textContent).toContain('invoice.status.cancelled')
  })

  it('flags an invoice with open reading corrections without showing their evidence', async () => {
    const figures = invoiceRow().invoice_figures!
    api.list.mockResolvedValue([invoiceRow({ invoice_figures: { ...figures, open_data_impact_count: 2 } })])
    const { container } = await mount(createElement(MyInvoicesPage))

    expect(container.textContent).toContain('pages.invoices.dataReview.badge')
  })

  it('lists credit notes with what is left and where it was set off', async () => {
    api.list.mockResolvedValue([invoiceRow(), creditRow()])
    const { container } = await mount(createElement(MyInvoicesPage))

    const credits = container.querySelector('#my-credits-title')!.closest('section')!
    expect(credits.textContent).toContain('CN-00001')
    expect(credits.textContent).toContain('INV-0')
    expect(credits.textContent).toContain('30.00')
    expect(credits.textContent).toContain('pages.invoiceDetail.credits.status.open')
    expect(credits.textContent).toContain('pages.invoiceDetail.credits.appliedTo')
    await act(async () => credits.querySelector<HTMLButtonElement>('tbody button')!.click())
    expect(api.download).toHaveBeenCalledWith('c1')
  })

  it('shows the empty state only when nothing was delivered', async () => {
    const { container } = await mount(createElement(MyInvoicesPage))
    expect(container.textContent).toContain('pages.myInvoices.empty.title')
  })

  it('names the community per row for an account in several', async () => {
    auth.user = user(['Community A', 'Community B'])
    api.list.mockResolvedValue([invoiceRow(), invoiceRow({ id: 'd2', participant: 'p1-1', zev: 'z1', zev_name: 'Community B', title: 'INV-2' })])
    const { container } = await mount(createElement(MyInvoicesPage))

    expect(container.querySelector('.eyebrow')?.textContent).toBe('pages.myInvoices.allCommunities')
    expect(container.textContent).toContain('pages.myInvoices.col.community')
    expect(container.textContent).toContain('Community B')
  })

  it('keeps the rows and warns when a later load fails', async () => {
    api.list.mockResolvedValue([invoiceRow()])
    const { container, client } = await mount(createElement(MyInvoicesPage))
    api.list.mockRejectedValue(new Error('Offline'))
    await act(async () => { await client.refetchQueries() })
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)) })

    expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
    expect(container.querySelector('.warning-banner')).not.toBeNull()
  })

  it('shows only the error when the first load fails', async () => {
    api.list.mockRejectedValue(new Error('Offline'))
    const { container } = await mount(createElement(MyInvoicesPage))

    expect(container.querySelector('.error-banner')).not.toBeNull()
    expect(container.querySelector('table')).toBeNull()
  })
})

describe('issuedDocumentFor (the annual document a participant reads)', () => {
  const own = new Set(['p1'])
  const statement = (overrides: Partial<DeliveredDocument> = {}) =>
    invoiceRow({
      id: 's1', kind: 'annual_statement', title: 'Annual statement 2025', invoice: null, invoice_status: null,
      invoice_figures: null, period_start: '2025-01-01', period_end: '2025-12-31', ...overrides,
    })

  it('finds the current document of that kind and year', () => {
    const found = issuedDocumentFor([statement()], 'annual_statement', 2025, own)
    expect(found?.id).toBe('s1')
  })

  it('has nothing for another year, kind or person', () => {
    expect(issuedDocumentFor([statement()], 'annual_statement', 2024, own)).toBeUndefined()
    expect(issuedDocumentFor([statement()], 'financial_summary', 2025, own)).toBeUndefined()
    expect(issuedDocumentFor([statement({ participant: 'other' })], 'annual_statement', 2025, own)).toBeUndefined()
  })

  it('skips a superseded or withdrawn document and takes the newest of the rest', () => {
    const found = issuedDocumentFor([
      statement({ id: 'old', delivered_at: '2026-01-10T00:00:00Z', superseded_at: '2026-02-01T00:00:00Z' }),
      statement({ id: 'gone', withdrawn_at: '2026-02-01T00:00:00Z' }),
      statement({ id: 'first', delivered_at: '2026-02-01T00:00:00Z' }),
      statement({ id: 'latest', delivered_at: '2026-03-01T00:00:00Z' }),
    ], 'annual_statement', 2025, own)
    expect(found?.id).toBe('latest')
  })

  it('reads within one community when asked to', () => {
    const rows = [statement({ id: 'a', zev: 'z0' }), statement({ id: 'b', zev: 'z1' })]
    expect(issuedDocumentFor(rows, 'annual_statement', 2025, own, 'z1')?.id).toBe('b')
  })
})
