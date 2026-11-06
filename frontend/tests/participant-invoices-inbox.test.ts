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

import { DocumentsPage } from '../src/pages/DocumentsPage'
import { issuedDocumentFor, issuedYears } from '../src/features/reports/ParticipantYearDocuments'

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

describe('DocumentsPage (invoices and credit notes carry their amounts and where they stand)', () => {
  it('lists an invoice with what is owed and a download, and no link to a live invoice', async () => {
    api.list.mockResolvedValue([invoiceRow()])
    const { container } = await mount(createElement(DocumentsPage))

    expect(api.list).toHaveBeenCalledWith()
    expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
    expect(container.querySelector('thead')?.textContent).toContain('inbox.col.amount')
    const row = container.querySelector('tbody tr')!.textContent!
    expect(row).toContain('INV-1')
    expect(row).toContain('CHF 108.10')
    // Credit set against the invoice: the amount due is shown beneath the total.
    expect(row).toContain('CHF 58.10')
    expect(row).toContain('invoice.payment.due')
    expect(container.querySelector('tbody a')).toBeNull()

    await act(async () => container.querySelector<HTMLButtonElement>('tbody button')!.click())
    expect(api.download).toHaveBeenCalledWith('d1')
  })

  it('shows only the account\'s own rows and leaves the amount column out when nothing has one', async () => {
    api.list.mockResolvedValue([
      invoiceRow({ id: 'd2', participant: 'someone-else', title: 'INV-2' }),
      { ...invoiceRow({ id: 'd3', kind: 'operator', title: 'House rules' }), invoice: null, invoice_figures: null },
    ])
    const { container } = await mount(createElement(DocumentsPage))

    expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
    expect(container.textContent).toContain('House rules')
    expect(container.textContent).not.toContain('INV-2')
    expect(container.querySelector('thead')?.textContent).not.toContain('inbox.col.amount')
  })

  it('says what an overdue and a cancelled invoice need from the participant', async () => {
    const figures = invoiceRow().invoice_figures!
    api.list.mockResolvedValue([
      invoiceRow({ id: 'late', title: 'INV-LATE', invoice_figures: { ...figures, due_date: '2020-01-01' } }),
      invoiceRow({ id: 'void', title: 'INV-VOID', invoice_figures: { ...figures, status: 'cancelled', outstanding_chf: '0.00' } }),
    ])
    const { container } = await mount(createElement(DocumentsPage))

    expect(container.textContent).toContain('invoice.payment.overdue')
    expect(container.textContent).toContain('invoice.status.cancelled')
  })

  it('flags an invoice with open reading corrections without showing their evidence', async () => {
    const figures = invoiceRow().invoice_figures!
    api.list.mockResolvedValue([invoiceRow({ invoice_figures: { ...figures, open_data_impact_count: 2 } })])
    const { container } = await mount(createElement(DocumentsPage))

    expect(container.textContent).toContain('pages.invoices.dataReview.badge')
  })

  it('shows a credit note with what is left, where it was set off and the invoice it corrects', async () => {
    api.list.mockResolvedValue([creditRow()])
    const { container } = await mount(createElement(DocumentsPage))

    const row = container.querySelector('tbody tr')!.textContent!
    expect(row).toContain('CN-00001')
    expect(row).toContain('CHF 50.00')
    expect(row).toContain('inbox.credit.remaining')
    expect(row).toContain('inbox.credit.forInvoice INV-0')
    expect(row).toContain('pages.invoiceDetail.credits.status.open')
    expect(row).toContain('pages.invoiceDetail.credits.appliedTo')
    await act(async () => container.querySelector<HTMLButtonElement>('tbody button')!.click())
    expect(api.download).toHaveBeenCalledWith('c1')
  })

  it('names the community per row for an account in several', async () => {
    auth.user = user(['Community A', 'Community B'])
    api.list.mockResolvedValue([invoiceRow(), invoiceRow({ id: 'd2', participant: 'p1-1', zev: 'z1', zev_name: 'Community B', title: 'INV-2' })])
    const { container } = await mount(createElement(DocumentsPage))

    expect(container.querySelector('.eyebrow')?.textContent).toBe('inbox.allCommunities')
    expect(container.querySelector('thead')?.textContent).toContain('inbox.col.community')
    expect(container.textContent).toContain('Community B')
  })

  it('renders a card per document for a phone alongside the table', async () => {
    api.list.mockResolvedValue([invoiceRow(), creditRow()])
    const { container } = await mount(createElement(DocumentsPage))

    expect(container.querySelectorAll('.doc-cards .doc-card')).toHaveLength(2)
    expect(container.querySelector('.doc-cards')!.textContent).toContain('CHF 108.10')
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

describe('issuedYears (the years a participant can pick)', () => {
  const own = new Set(['p1'])
  const row = (overrides: Partial<DeliveredDocument>) =>
    invoiceRow({ kind: 'annual_statement', invoice: null, invoice_status: null, invoice_figures: null, ...overrides })

  it('lists the years of the account\'s current documents of those kinds, newest first', () => {
    const rows = [
      row({ id: 'a', period_start: '2023-01-01' }),
      row({ id: 'b', period_start: '2025-01-01' }),
      row({ id: 'c', period_start: '2025-01-01', kind: 'financial_summary' }),
    ]
    expect(issuedYears(rows, ['annual_statement', 'financial_summary'], own)).toEqual([2025, 2023])
    expect(issuedYears(rows, ['financial_summary'], own)).toEqual([2025])
  })

  it('ignores other people, other communities, replaced and withdrawn documents and ones with no period', () => {
    const rows = [
      row({ id: 'a', participant: 'other', period_start: '2024-01-01' }),
      row({ id: 'b', zev: 'z9', period_start: '2024-01-01' }),
      row({ id: 'c', period_start: '2024-01-01', superseded_at: '2025-02-01T00:00:00Z' }),
      row({ id: 'd', period_start: '2024-01-01', withdrawn_at: '2025-02-01T00:00:00Z' }),
      row({ id: 'e', period_start: null }),
    ]
    expect(issuedYears(rows, ['annual_statement'], own, 'z0')).toEqual([])
  })
})
