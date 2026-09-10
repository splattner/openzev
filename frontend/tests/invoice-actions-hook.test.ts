import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, createElement, useEffect } from 'react'
import { useInvoiceActions } from '../src/features/invoices/useInvoiceActions'

const pushToast = vi.fn()
const invalidateQueries = vi.fn()
// Appends the interpolated count so tests can assert the scope a label claims,
// not just which label was chosen.
const t = (key: string, opts?: { count?: number }) =>
  opts?.count === undefined ? key : `${key}:${opts.count}`

const mutationInstances: Array<{
  mutate: ReturnType<typeof vi.fn>
  mutateAsync: ReturnType<typeof vi.fn>
  isPending: boolean
  options: Record<string, unknown>
}> = []

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t }),
}))

vi.mock('../src/lib/toast', () => ({
  useToast: () => ({ pushToast }),
}))

const mockNavigate = vi.fn()

vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}))

const ELIGIBLE = { state: 'eligible', invoice_id: null, invoice_number: null }

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries }),
  useMutation: (options: Record<string, unknown>) => {
    const instance = {
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
      options,
    }
    mutationInstances.push(instance)
    return instance
  },
}))

vi.mock('../src/lib/api/invoices', () => ({
  approveAllInvoices: vi.fn(),
  approveInvoice: vi.fn(),
  deleteInvoice: vi.fn(),
  downloadAllPdfs: vi.fn(),
  fetchInvoice: vi.fn(),
  generateAllPdfs: vi.fn(),
  generateInvoice: vi.fn(),
  generateInvoicePdf: vi.fn(),
  generateInvoicesForZev: vi.fn(),
  markInvoicePaid: vi.fn(),
  markInvoiceSent: vi.fn(),
  retryFailedEmail: vi.fn(),
  sendAllInvoices: vi.fn(),
  sendInvoiceEmail: vi.fn(),
}))

function createHarness(rowsOverride?: unknown[], periodOverride?: { period_start: string; period_end: string }) {
  const latestResult = { current: null as ReturnType<typeof useInvoiceActions> | null }

  function Harness() {
    const hookResult = useInvoiceActions({
      selectedZevId: 'zev-1',
      period: periodOverride ?? {
        period_start: '2026-05-01',
        period_end: '2026-05-31',
      },
      rows: rowsOverride ?? [
        {
          participant_id: 'participant-1',
          invoice: null,
          generation_eligibility: ELIGIBLE,
        },
        {
          participant_id: 'participant-2',
          invoice: {
            id: 'invoice-draft',
            status: 'draft',
            pdf_url: null,
            email_logs: [],
            invoice_number: 'INV-001',
          },
          generation_eligibility: null,
        },
        {
          participant_id: 'participant-3',
          invoice: {
            id: 'invoice-approved',
            status: 'approved',
            pdf_url: null,
            email_logs: [],
            invoice_number: 'INV-002',
          },
          generation_eligibility: null,
        },
        {
          participant_id: 'participant-4',
          invoice: {
            id: 'invoice-sent',
            status: 'sent',
            pdf_url: '/pdf/invoice-sent.pdf',
            email_logs: [
              {
                id: 'email-log-1',
                created_at: '2026-05-08T10:00:00Z',
                recipient: 'recipient@example.com',
                status: 'sent',
              },
            ],
            invoice_number: 'INV-003',
          },
          generation_eligibility: null,
        },
      ] as any,
      userRole: 'participant',
      onDeleteClick: vi.fn(),
    })

    useEffect(() => {
      latestResult.current = hookResult
    }, [hookResult])

    return null
  }

  return { Harness, getResult: () => latestResult.current }
}

describe('useInvoiceActions hook', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>

  beforeEach(() => {
    mutationInstances.length = 0
    pushToast.mockClear()
    invalidateQueries.mockClear()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => {
      root.unmount()
    })
    container.remove()
  })

  it('returns row actions and batch recommendation from hook state', () => {
    const { Harness, getResult } = createHarness()

    act(() => {
      root.render(createElement(Harness))
    })

    const result = getResult()
    expect(result).not.toBeNull()

    const noInvoiceAction = result!.getPrimaryRowAction({ participant_id: 'participant-1', invoice: null } as any)
    const draftAction = result!.getPrimaryRowAction({ participant_id: 'participant-2', invoice: { status: 'draft' } as any } as any)
    const approvedAction = result!.getPrimaryRowAction({ participant_id: 'participant-3', invoice: { id: 'invoice-approved', status: 'approved' } as any } as any)
    const sentAction = result!.getPrimaryRowAction({ participant_id: 'participant-4', invoice: { id: 'invoice-sent', status: 'sent' } as any } as any)

    expect(noInvoiceAction?.label).toBe('pages.invoices.generateInvoice')
    expect(draftAction?.label).toBe('pages.invoices.approve')
    expect(approvedAction?.label).toBe('pages.invoices.sendEmail')
    expect(sentAction?.label).toBe('pages.invoices.markPaid')
    // participant-1 has no invoice yet, so generation outranks approval.
    expect(result!.recommendedBatchAction?.label).toBe('pages.invoices.batch.generateAllCount:1')
    expect(result!.getRowMenuItems({ participant_id: 'participant-4', invoice: { id: 'invoice-sent', status: 'sent', pdf_url: '/pdf/invoice-sent.pdf', email_logs: [], invoice_number: 'INV-003' } as any } as any)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ key: 'regenerate-pdf' }),
        expect.objectContaining({ key: 'resend-email' }),
      ]),
    )
  })

})

/**
 * The recommendation must follow the workflow — generate, then approve, then
 * send. Recommending approval while participants still lack an invoice skips
 * them silently: approve-all only touches drafts, so the button reports success
 * and leaves the late joiner unbilled.
 */
describe('recommendedBatchAction ordering', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>

  beforeEach(() => {
    mutationInstances.length = 0
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => {
      root.unmount()
    })
    container.remove()
  })

  function recommend(rows: unknown[]) {
    const { Harness, getResult } = createHarness(rows)
    act(() => {
      root.render(createElement(Harness))
    })
    return getResult()!.recommendedBatchAction
  }

  function mountRows(rows: unknown[]) {
    const { Harness, getResult } = createHarness(rows)
    act(() => {
      root.render(createElement(Harness))
    })
    return getResult()!
  }

  const noInvoice = (id: string, eligibility: unknown = ELIGIBLE) => ({
    participant_id: id, invoice: null, generation_eligibility: eligibility,
  })
  const blocked = (id: string, invoiceId: string) => noInvoice(id, {
    state: 'blocked', invoice_id: invoiceId, invoice_number: 'T-1',
  })
  const covered = (id: string, invoiceId: string) => noInvoice(id, {
    state: 'covered', invoice_id: invoiceId, invoice_number: 'T-1',
  })

  const withStatus = (id: string, status: string) => ({
    participant_id: id,
    invoice: { id: `invoice-${id}`, status, pdf_url: null, email_logs: [], invoice_number: id },
    generation_eligibility: status === 'cancelled' ? ELIGIBLE : null,
  })

  it('recommends generation before approval when a participant has no invoice', () => {
    expect(recommend([noInvoice('p1'), withStatus('p2', 'draft'), withStatus('p3', 'draft')])?.label).toBe(
      'pages.invoices.batch.generateAllCount:1',
    )
  })

  it('recommends approval once every participant has an invoice', () => {
    expect(recommend([withStatus('p1', 'draft'), withStatus('p2', 'draft')])?.label).toBe(
      'pages.invoices.batch.approveAllCount:2',
    )
  })

  it('recommends sending once nothing is left in draft', () => {
    expect(recommend([withStatus('p1', 'approved'), withStatus('p2', 'approved')])?.label).toBe(
      'pages.invoices.batch.sendAllCount:2',
    )
  })

  it('recommends nothing once every invoice has been sent', () => {
    expect(recommend([withStatus('p1', 'sent'), withStatus('p2', 'paid')])).toBeNull()
  })

  it('counts a cancelled invoice as needing regeneration', () => {
    expect(recommend([withStatus('p1', 'cancelled'), withStatus('p2', 'sent')])?.label).toBe(
      'pages.invoices.batch.generateAllCount:1',
    )
  })

  it('no longer recommends a PDF pass — PDFs arrive with the invoice', () => {
    expect(recommend([withStatus('p1', 'sent'), withStatus('p2', 'sent')])).toBeNull()
  })

  it('excludes blocked and covered rows from generation candidates', () => {
    const result = mountRows([noInvoice('p1'), blocked('p2', 'inv-locked'), covered('p3', 'inv-cover')])
    expect(result.stats.generationCandidateCount).toBe(1)
    expect(result.recommendedBatchAction?.label).toBe(
      'pages.invoices.batch.generateAllCount:1',
    )
  })

  it('links a blocked row to its locked invoice instead of generating', () => {
    const result = mountRows([blocked('p1', 'inv-locked')])
    const action = result.getPrimaryRowAction({ participant_id: 'p1', invoice: null, generation_eligibility: { state: 'blocked', invoice_id: 'inv-locked', invoice_number: 'T-1' } } as any)
    expect(action?.key).toBe('review-conflict')
    expect(action?.label).toBe('pages.invoices.reviewConflict')
    action?.onClick()
    expect(mockNavigate).toHaveBeenCalledWith('/billing/invoices/inv-locked', {
      state: { from: '/billing/invoices', period_start: '2026-05-01', period_end: '2026-05-31' },
    })
  })

  it('links a covered row to its covering invoice instead of generating', () => {
    const result = mountRows([covered('p1', 'inv-cover')])
    const action = result.getPrimaryRowAction({ participant_id: 'p1', invoice: null, generation_eligibility: { state: 'covered', invoice_id: 'inv-cover', invoice_number: 'T-1' } } as any)
    expect(action?.key).toBe('view-covering-invoice')
    action?.onClick()
    expect(mockNavigate).toHaveBeenCalledWith('/billing/invoices/inv-cover', {
      state: { from: '/billing/invoices', period_start: '2026-05-01', period_end: '2026-05-31' },
    })
  })

  it('keeps a historical viewed period on conflict navigation for the return link', () => {
    const { Harness, getResult } = createHarness(
      [blocked('p1', 'inv-locked')],
      { period_start: '2026-02-01', period_end: '2026-02-28' },
    )
    act(() => {
      root.render(createElement(Harness))
    })
    const action = getResult()!.getPrimaryRowAction({
      participant_id: 'p1', invoice: null,
      generation_eligibility: { state: 'blocked', invoice_id: 'inv-locked', invoice_number: 'T-1' },
    } as any)
    action?.onClick()
    expect(mockNavigate).toHaveBeenCalledWith('/billing/invoices/inv-locked', {
      state: { from: '/billing/invoices', period_start: '2026-02-01', period_end: '2026-02-28' },
    })
  })
})
