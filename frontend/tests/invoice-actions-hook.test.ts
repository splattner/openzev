import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, createElement, useEffect } from 'react'
import { useInvoiceActions } from '../src/features/invoices/useInvoiceActions'
import { recordPayment } from '../src/lib/api/invoices'

const pushToast = vi.fn()
const invalidateQueries = vi.fn()
const onPdfQueued = vi.fn()
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

vi.mock('../src/lib/appSettings', async (importOriginal) => ({
  ...await importOriginal<typeof import('../src/lib/appSettings')>(),
  useAppSettings: () => ({ settings: { date_time_format: 'dd.MM.yyyy HH:mm' } }),
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
  openInvoicePdf: vi.fn(),
  recordPayment: vi.fn(),
  retryFailedEmail: vi.fn(),
  sendAllInvoices: vi.fn(),
  sendInvoiceEmail: vi.fn(),
}))

type HookOptions = Parameters<typeof useInvoiceActions>[0]

function createHarness(
  rowsOverride?: unknown[],
  periodOverride?: { period_start: string; period_end: string },
  extra: Partial<HookOptions> = {},
) {
  const latestResult = { current: null as ReturnType<typeof useInvoiceActions> | null }

  function Harness({ rows, options }: { rows?: unknown[]; options?: Partial<HookOptions> }) {
    const hookResult = useInvoiceActions({
      selectedZevId: 'zev-1',
      period: periodOverride ?? {
        period_start: '2026-05-01',
        period_end: '2026-05-31',
      },
      rows: (rows ?? rowsOverride) ?? [
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
      onRecordPaymentClick: vi.fn(),
      onPdfQueued,
      ...extra,
      ...options,
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
    onPdfQueued.mockClear()
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

  it.each(['dynamic_price_gap', 'invalid_dynamic_tariff'])(
    'shows structured %s failures for single and bulk generation', (code) => {
      const { Harness, getResult } = createHarness()
      act(() => root.render(createElement(Harness)))
      const error = { isAxiosError: true, response: { data: {
        code, tariff_name: 'Grid', missing_at: '2026-05-01T00:00:00Z',
      } } }
      for (const mutation of [getResult()!.generateMutation, getResult()!.generateAllMutation]) {
        const instance = mutationInstances.find((item) => item.mutate === mutation.mutate)!
        const onError = instance.options.onError as (error: unknown) => void
        act(() => onError(error))
        expect(getResult()!.tariffProblem).toBe(
          `pages.invoices.messages.${code === 'dynamic_price_gap' ? 'dynamicPriceGap' : 'invalidDynamicTariff'}`,
        )
        expect(pushToast).not.toHaveBeenCalled()
      }
    },
  )

  it('drops tariff recovery after a scope change and ignores a late generation error', () => {
    const { Harness, getResult } = createHarness()
    act(() => root.render(createElement(Harness)))
    const mutation = mutationInstances.find(item => item.mutate === getResult()!.generateMutation.mutate)!
    const variables = { participant_id: 'participant-1', period_start: '2026-05-01', period_end: '2026-05-31' }
    const context = (mutation.options.onMutate as (variables: unknown) => unknown)(variables)
    const error = { isAxiosError: true, response: { data: { code: 'invalid_dynamic_tariff', tariff_name: 'Grid' } } }
    const onError = mutation.options.onError as (error: unknown, variables: unknown, context: unknown) => void
    act(() => onError(error, variables, context))
    expect(getResult()!.tariffProblem).toBe('pages.invoices.messages.invalidDynamicTariff')
    act(() => root.render(createElement(Harness, { options: { selectedZevId: 'zev-2' } })))
    expect(getResult()!.tariffProblem).toBeNull()
    act(() => onError(error, variables, context))
    expect(getResult()!.tariffProblem).toBeNull()
  })

  it('prioritizes correction review in Actions and keeps ordinary workflow actions in the menu', () => {
    const row = { participant_id: 'participant-3', invoice: { id: 'invoice-approved', status: 'approved', needs_data_review: true, paid_chf: '0.00', email_logs: [] } } as any
    const { Harness, getResult } = createHarness([row])
    act(() => root.render(createElement(Harness)))
    const review = getResult()!.getPrimaryRowAction(row)
    expect(review?.key).toBe('review-corrections')
    act(() => review!.onClick())
    expect(mockNavigate).toHaveBeenCalledWith('/billing/invoices/invoice-approved', {
      state: { from: '/billing/invoices', period_start: '2026-05-01', period_end: '2026-05-31' },
    })
    expect(getResult()!.getRowMenuItems(row)).toEqual(expect.arrayContaining([
      expect.objectContaining({ key: 'send-email' }),
    ]))
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
        expect.objectContaining({ key: 'open-pdf', label: 'common.openPdf' }),
        expect.objectContaining({ key: 'regenerate-pdf' }),
        expect.objectContaining({ key: 'resend-email' }),
      ]),
    )
    // The row menu opens a stored document; without one there is nothing to open.
    expect(result!.getRowMenuItems({ participant_id: 'participant-2', invoice: { id: 'invoice-draft', status: 'draft', pdf_url: null, email_logs: [] } as any } as any)
      .map((item) => item.key)).not.toContain('open-pdf')
  })

  it('labels a partly paid row for the rest and books it through mark-paid', () => {
    const { Harness, getResult } = createHarness()
    act(() => root.render(createElement(Harness)))
    const sent = (paidChf: string, outstandingChf: string) => ({
      participant_id: 'participant-4',
      invoice: {
        id: 'invoice-sent', status: 'sent', paid_chf: paidChf, outstanding_chf: outstandingChf,
        total_chf: '100.00', amount_due_chf: '100.00',
      },
    } as any)

    expect(getResult()!.getPrimaryRowAction(sent('0.00', '100.00'))?.label).toBe('pages.invoices.markPaid')
    const restAction = getResult()!.getPrimaryRowAction(sent('25.00', '75.00'))
    expect(restAction?.label).toBe('pages.invoices.markRestPaid')

    const markPaid = getResult()!.markPaidMutation
    act(() => restAction!.onClick())
    expect(markPaid.mutate).toHaveBeenCalledWith('invoice-sent')
  })

  it('offers record payment in the row menu while a sent invoice still collects money', () => {
    const onRecordPaymentClick = vi.fn()
    const { Harness, getResult } = createHarness(undefined, undefined, { onRecordPaymentClick })
    act(() => root.render(createElement(Harness)))
    const result = getResult()!
    const row = (invoice: Record<string, unknown>) => ({ participant_id: 'participant-4', invoice } as any)

    const sent = row({
      id: 'invoice-sent', status: 'sent', pdf_url: null,
      paid_chf: '25.00', outstanding_chf: '75.00', total_chf: '100.00', amount_due_chf: '100.00',
    })
    const item = result.getRowMenuItems(sent).find((entry) => entry.key === 'record-payment')
    expect(item?.label).toBe('pages.invoiceDetail.payments.record')
    item?.onClick()
    expect(onRecordPaymentClick).toHaveBeenCalledWith('invoice-sent')

    // These invoices do not offer manual payment recording.
    const cases: Array<[string, Record<string, unknown>]> = [
      ['payout', {
        id: 'invoice-payout', status: 'sent',
        paid_chf: '0.00', outstanding_chf: '-40.00', amount_due_chf: '-40.00', total_chf: '-40.00',
      }],
      ['credit-covered', {
        id: 'invoice-covered', status: 'sent',
        paid_chf: '0.00', outstanding_chf: '0.00', amount_due_chf: '0.00', total_chf: '100.00',
        credit_applied_chf: '100.00',
      }],
      ['settled', {
        id: 'invoice-settled', status: 'sent',
        paid_chf: '100.00', outstanding_chf: '0.00', amount_due_chf: '100.00', total_chf: '100.00',
      }],
      ['missing-outstanding', {
        id: 'invoice-missing-balance', status: 'sent', amount_due_chf: '100.00', total_chf: '100.00',
      }],
      ['stale-outstanding', {
        id: 'invoice-stale', status: 'sent',
        paid_chf: '0.00', outstanding_chf: '75.00', amount_due_chf: '0.00', total_chf: '100.00',
        credit_applied_chf: '100.00',
      }],
      ['paid', {
        id: 'invoice-paid', status: 'paid',
        paid_chf: '100.00', outstanding_chf: '0.00', amount_due_chf: '100.00', total_chf: '100.00',
      }],
    ]
    for (const [name, invoice] of cases) {
      expect(result.getRowMenuItems(row(invoice)).map((entry) => entry.key), name).not.toContain('record-payment')
    }
  })

  it('books a row payment through the API and refreshes the list, cockpit and period', async () => {
    const { Harness, getResult } = createHarness()
    act(() => root.render(createElement(Harness)))
    const instance = mutationInstances.find((item) => item.mutate === getResult()!.recordPaymentMutation.mutate)!
    const variables = {
      invoiceId: 'invoice-sent',
      values: { amount_chf: '75.00', paid_on: '2026-05-10', note: 'E-Banking' },
    }
    act(() => getResult()!.recordRowPayment(variables.invoiceId, variables.values, vi.fn()))
    const submitted = instance.mutate.mock.calls[0][0]

    await (instance.options.mutationFn as (vars: typeof submitted) => Promise<unknown>)(submitted)
    expect(vi.mocked(recordPayment)).toHaveBeenCalledWith('invoice-sent', variables.values)

    invalidateQueries.mockClear()
    act(() => (instance.options.onSuccess as (result: unknown, vars: typeof submitted) => void)(undefined, submitted))
    expect(pushToast).toHaveBeenCalledWith('pages.invoiceDetail.payments.recorded', 'success')
    const invalidatedKeys = invalidateQueries.mock.calls.map((call) => (call[0] as { queryKey: unknown }).queryKey)
    expect(invalidatedKeys).toEqual(expect.arrayContaining([
      ['invoices', 'period-overview', 'zev-1', '2026-05-01', '2026-05-31'],
      ['invoices', 'list'],
      ['invoices', 'mine'],
      ['invoices', 'readiness', 'zev-1'],
      ['invoices', 'readiness-list', 'zev-1'],
      ['invoices', 'attention', 'zev-1'],
    ]))

    const onError = instance.options.onError as (error: unknown, vars: typeof submitted) => void
    act(() => onError(new Error('network down'), submitted))
    expect(pushToast).toHaveBeenLastCalledWith('pages.invoiceDetail.payments.recordFailed', 'error')
  })

  it('rejects a retained payment submission after write access is revoked', () => {
    const { Harness, getResult } = createHarness()
    act(() => root.render(createElement(Harness)))
    const instance = mutationInstances.find(item => item.mutate === getResult()!.recordPaymentMutation.mutate)!
    act(() => getResult()!.recordRowPayment('invoice-sent', { amount_chf: '10.00', paid_on: '2026-05-10', note: '' }, vi.fn()))
    const submitted = instance.mutate.mock.calls[0][0]
    act(() => root.render(createElement(Harness, { options: { canWrite: false } })))
    vi.mocked(recordPayment).mockClear()
    expect(() => (instance.options.mutationFn as (vars: typeof submitted) => unknown)(submitted))
      .toThrow('common.error')
    expect(recordPayment).not.toHaveBeenCalled()
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
    pushToast.mockClear()
    onPdfQueued.mockClear()
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
    participant_email: `${id}@example.test`,
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

  it('offers cancelled generation once while preserving PDF and delete actions', () => {
    const row = withStatus('p1', 'cancelled')
    const result = mountRows([row])
    expect(result.getPrimaryRowAction(row as any)?.key).toBe('generate')
    expect(result.getRowMenuItems(row as any).map(item => item.key)).toEqual(['delete', 'generate-pdf'])
  })

  it('no longer recommends a PDF pass — PDFs arrive with the invoice', () => {
    expect(recommend([withStatus('p1', 'sent'), withStatus('p2', 'sent')])).toBeNull()
  })

  it('excludes blocked and covered rows from generation candidates', () => {
    const result = mountRows([noInvoice('p1'), blocked('p2', 'inv-locked'), covered('p3', 'inv-cover')])
    expect(result.recommendedBatchAction?.label).toBe(
      'pages.invoices.batch.generateAllCount:1',
    )
  })

  it('keeps batch operations without eligible targets out of the menu', () => {
    const result = mountRows([noInvoice('p1'), withStatus('p2', 'draft'), withStatus('p3', 'sent')])
    expect(result.batchMenuItems.map(item => item.key)).toEqual(['generate-all', 'approve-all', 'generate-all-pdfs'])
    expect(mountRows([covered('p1', 'old'), blocked('p2', 'locked')]).batchMenuItems).toEqual([])
  })

  type Instance = (typeof mutationInstances)[number]
  const instanceOf = (mutation: { mutate: unknown }): Instance =>
    mutationInstances.findLast(instance => instance.mutate === mutation.mutate)!
  const submit = (instance: Instance, result: unknown, variables?: unknown) => {
    const context = (instance.options.onMutate as (variables?: unknown) => unknown)(variables)
    return { context, accept: () => act(() => (instance.options.onSuccess as (...args: unknown[]) => void)(result, variables, context)) }
  }
  const nextPeriod = { period_start: '2026-06-01', period_end: '2026-06-30' }
  const overviewInvalidations = (period = '2026-05-01') => invalidateQueries.mock.calls
    .filter(([{ queryKey }]) => queryKey[1] === 'period-overview' && queryKey.includes(period)).length

  type MutationKey = 'generateMutation' | 'generateAllMutation' | 'generateAllPdfsMutation' | 'sendAllMutation' | 'emailMutation'
  const base: Partial<HookOptions> = { accountId: 1, canWrite: true }

  /** One mounted hook instance; `update` re-renders it with new props. */
  function mountInstance(rows: unknown[]) {
    const { Harness, getResult } = createHarness(rows, undefined, base)
    const update = (options: Partial<HookOptions> = {}) => act(() => root.render(createElement(Harness, { options })))
    update()
    // TanStack Query calls the latest options' callbacks with the context
    // onMutate returned when the request was made.
    const latest = (key: MutationKey) => instanceOf(getResult()![key])
    const submit = (key: MutationKey, result: unknown, variables?: unknown) => {
      const context = (latest(key).options.onMutate as (variables?: unknown) => unknown)(variables)
      return {
        context,
        accept: () => act(() => (latest(key).options.onSuccess as (...args: unknown[]) => void)(result, variables, context)),
      }
    }
    return { update, submit, getResult }
  }

  it.each([['11.00', 'recalculatedChanged'], ['10.00', 'recalculatedUnchanged']])('reports regeneration from a previous total of %s', (total, message) => {
    const hook = mountInstance([{ ...noInvoice('p1'), invoice: { id: 'old', invoice_number: 'OLD', status: 'draft', total_chf: total } }])
    hook.submit('generateMutation', { id: 'new', total_chf: '10.00' }, { participant_id: 'p1' }).accept()
    expect(pushToast).toHaveBeenCalledWith(`pages.invoices.dataReview.${message}`, 'success')
  })

  it('snapshots generation targets and starts watching them on acceptance', () => {
    const hook = mountInstance([noInvoice('p1'), blocked('p2', 'locked')])
    const queued = hook.submit('generateAllMutation', { participant_count: 1 })
    expect((queued.context as { participantIds: string[] }).participantIds).toEqual(['p1'])
    queued.accept()
    expect(onPdfQueued).toHaveBeenCalledWith(['p1'])
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ['invoices', 'mine'] })
    // The busy rows report a queued batch; no toast repeats it.
    expect(pushToast).not.toHaveBeenCalled()
  })

  const transitions: Array<[string, Array<Partial<HookOptions>>]> = [
    ['period A → B', [{ period: nextPeriod }]],
    ['community A → B', [{ selectedZevId: 'zev-2' }]],
    ['account change', [{ accountId: 2 }]],
    ['write access revoked', [{ canWrite: false }]],
    ['period A → B → A', [{ period: nextPeriod }, {}]],
  ]
  const mutations: Array<[MutationKey, unknown, unknown]> = [
    ['generateAllMutation', { participant_count: 1 }, undefined],
    ['generateMutation', {}, { participant_id: 'p1' }],
    ['generateAllPdfsMutation', {}, undefined],
    ['sendAllMutation', { queued: 1, skipped: 0 }, undefined],
    ['emailMutation', {}, 'invoice-p3'],
  ]

  describe.each(transitions)('after %s in the same hook instance', (_name, steps) => {
    beforeEach(() => vi.useFakeTimers())
    afterEach(() => vi.useRealTimers())

    it.each(mutations)('ignores a late %s acceptance and refreshes only its origin', (key, result, variables) => {
      const rows = [noInvoice('p1'), withStatus('p2', 'draft'), { ...withStatus('p3', 'approved'), participant_email: 'p3@example.test' }]
      const hook = mountInstance(rows)
      const late = hook.submit(key, result, variables)
      for (const step of steps) hook.update(step)
      invalidateQueries.mockClear()
      late.accept()
      expect(onPdfQueued).not.toHaveBeenCalled()
      expect(pushToast).not.toHaveBeenCalled()
      expect(overviewInvalidations('2026-05-01')).toBeLessThanOrEqual(1)
      if (steps.length === 1 && steps[0].period) expect(overviewInvalidations('2026-06-01')).toBe(0)
      // No delivery tracking started: nothing polls, nothing is locked.
      invalidateQueries.mockClear()
      act(() => { vi.advanceTimersByTime(10_000) })
      expect(invalidateQueries).not.toHaveBeenCalled()
      expect(hook.getResult()!.getRowWork(rows[2] as any).sending).toBe(false)
    })
  })

  it('ignores an acceptance that arrives after the page unmounted', () => {
    const hook = mountInstance([noInvoice('p1')])
    const late = hook.submit('generateAllMutation', { participant_count: 1 })
    const onSuccess = instanceOf(hook.getResult()!.generateAllMutation).options.onSuccess as (...args: unknown[]) => void
    act(() => root.render(null))
    onSuccess({ participant_count: 1 }, undefined, late.context)
    expect(onPdfQueued).not.toHaveBeenCalled()
  })

  it('keeps generation disabled for accepted targets until their invoices arrive', () => {
    const { Harness, getResult } = createHarness(undefined, undefined, { generationParticipantIds: ['p1'] })
    const rows = [noInvoice('p1'), noInvoice('p2')]
    act(() => root.render(createElement(Harness, { rows })))
    const queued = getResult()!
    expect(queued.getRowWork(rows[0] as any).generating).toBe(true)
    expect(queued.getRowWork(rows[1] as any).generating).toBe(false)
    expect(queued.recommendedBatchAction?.disabled).toBe(true)
    expect(queued.getPrimaryRowAction(rows[0] as any)?.disabled).toBe(true)
    expect(queued.getPrimaryRowAction(rows[1] as any)?.disabled).toBe(false)

    act(() => root.render(createElement(Harness, { rows: [withStatus('p1', 'draft'), noInvoice('p2')] })))
    expect(getResult()!.batchMenuItems.find(item => item.key === 'generate-all')?.disabled).toBe(false)
  })

  it('promotes the first workflow action this range allows', () => {
    const { Harness, getResult } = createHarness([noInvoice('p1'), withStatus('p2', 'draft')], undefined, { canGenerate: false })
    act(() => root.render(createElement(Harness)))
    expect(getResult()!.recommendedBatchAction?.key).toBe('approve-all')
    expect(getResult()!.batchMenuItems.map(item => item.key)).not.toContain('generate-all')
  })

  describe('send all delivery tracking', () => {
    const approved = (id: string, logs: unknown[] = []) => ({
      ...withStatus(id, 'approved'), participant_email: `${id}@example.test`,
      invoice: { ...withStatus(id, 'approved').invoice, email_logs: logs },
    })
    const delivered = (id: string, status: string) => ({
      ...approved(id), invoice: { ...approved(id).invoice, status: status === 'sent' ? 'sent' : 'approved',
        email_logs: [{ id: `log-${id}`, status, created_at: '2026-06-01T10:00:00Z' }] },
    })

    beforeEach(() => {
      vi.useFakeTimers()
      invalidateQueries.mockClear()
      pushToast.mockClear()
    })
    afterEach(() => vi.useRealTimers())

    it('polls the period until every target has a terminal attempt', () => {
      const { Harness, getResult } = createHarness()
      act(() => root.render(createElement(Harness, { rows: [approved('p1'), approved('p2')] })))
      submit(instanceOf(getResult()!.sendAllMutation), { queued: 2, skipped: 0 }).accept()
      expect(getResult()!.batchMenuItems.find(item => item.key === 'send-all')?.disabled).toBe(true)
      invalidateQueries.mockClear()
      act(() => { vi.advanceTimersByTime(2_500) })
      expect(overviewInvalidations()).toBe(1)

      // One delivery settles; the other is still outstanding.
      act(() => root.render(createElement(Harness, { rows: [delivered('p1', 'sent'), approved('p2')] })))
      act(() => { vi.advanceTimersByTime(2_500) })
      expect(overviewInvalidations()).toBe(2)

      act(() => root.render(createElement(Harness, { rows: [delivered('p1', 'sent'), delivered('p2', 'failed')] })))
      invalidateQueries.mockClear()
      act(() => { vi.advanceTimersByTime(30_000) })
      expect(overviewInvalidations()).toBe(0)
      expect(pushToast).not.toHaveBeenCalledWith('pages.invoices.messages.emailPollingTimeout', 'error')
    })

    it('stops at the deadline and says delivery is still unknown', () => {
      const { Harness, getResult } = createHarness()
      act(() => root.render(createElement(Harness, { rows: [approved('p1')] })))
      submit(instanceOf(getResult()!.sendAllMutation), { queued: 1, skipped: 0 }).accept()
      act(() => { vi.advanceTimersByTime(90_000) })
      expect(pushToast).toHaveBeenCalledWith('pages.invoices.messages.emailPollingTimeout', 'error')
      invalidateQueries.mockClear()
      act(() => { vi.advanceTimersByTime(10_000) })
      expect(overviewInvalidations()).toBe(0)
    })

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

  it('offers no action on a covered row: its progress cell links the covering invoice', () => {
    const result = mountRows([covered('p1', 'inv-cover')])
    expect(result.getPrimaryRowAction({ participant_id: 'p1', invoice: null, generation_eligibility: { state: 'covered', invoice_id: 'inv-cover', invoice_number: 'T-1' } } as any)).toBeNull()
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
