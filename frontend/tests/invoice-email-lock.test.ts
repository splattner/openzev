import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, createElement, useEffect } from 'react'
import { QueryClient, QueryClientProvider, notifyManager } from '@tanstack/react-query'
import { useInvoiceActions } from '../src/features/invoices/useInvoiceActions'
import type { InvoicePeriodParticipantRow } from '../src/types/api'

// Real TanStack mutations against held-open requests: the row and batch send
// paths must not both queue the same invoice.

// Deliver mutation state synchronously, independent of (fake) timers.
notifyManager.setScheduler(callback => callback())

const pushToast = vi.fn()
const t = (key: string) => key
const api = vi.hoisted(() => ({
  sendInvoiceEmail: vi.fn(),
  sendAllInvoices: vi.fn(),
}))

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast }) }))
vi.mock('../src/lib/appSettings', async (importOriginal) => ({
  ...await importOriginal<typeof import('../src/lib/appSettings')>(),
  useAppSettings: () => ({ settings: { date_time_format: 'dd.MM.yyyy HH:mm' } }),
}))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('../src/lib/api/invoices', () => ({
  approveAllInvoices: vi.fn(),
  approveInvoice: vi.fn(),
  deleteInvoice: vi.fn(),
  downloadAllPdfs: vi.fn(),
  generateAllPdfs: vi.fn(),
  generateInvoice: vi.fn(),
  generateInvoicePdf: vi.fn(),
  generateInvoicesForZev: vi.fn(),
  markInvoicePaid: vi.fn(),
  markInvoiceSent: vi.fn(),
  openInvoicePdf: vi.fn(),
  recordPayment: vi.fn(),
  ...api,
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

const approved = (id: string): InvoicePeriodParticipantRow => ({
  participant_id: id, participant_name: id, participant_email: `${id}@example.test`,
  participant_kind: 'person', participant_name_addition: '', participant_valid_from: '2026-01-01',
  participant_valid_to: null, party_id: id, metering_point_labels: [],
  metering_data_complete: true, metering_points_total: 1, metering_points_with_data: 1, missing_meter_ids: [],
  generation_eligibility: null,
  invoice: {
    id: `inv-${id}`, invoice_number: id, status: 'approved', email_logs: [], pdf_url: null,
    allowed_actions: ['mark_sent', 'send_email'],
  } as never,
})

type Hook = ReturnType<typeof useInvoiceActions>
const rows = [approved('p1'), approved('p2')]
const period = { period_start: '2026-05-01', period_end: '2026-05-31' }

type Options = Partial<Parameters<typeof useInvoiceActions>[0]>
const hook: { current: Hook | null } = { current: null }

function Harness({ options }: { options: Options }) {
  const result = useInvoiceActions({
    selectedZevId: 'zev-1', period, rows, accountId: 1, canWrite: true,
    onDeleteClick: vi.fn(), onRecordPaymentClick: vi.fn(), onPdfQueued: vi.fn(), ...options,
  })
  useEffect(() => { hook.current = result })
  return null
}

describe('row and batch email sending', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>
  let queryClient: QueryClient
  const render = (options: Options = {}) => act(() => root.render(
    createElement(QueryClientProvider, { client: queryClient }, createElement(Harness, { options }))))
  const rowSend = (id: string) => hook.current!.getPrimaryRowAction(rows.find(row => row.participant_id === id)!)!
  const sendAll = () => hook.current!.batchMenuItems.find(item => item.key === 'send-all')!

  beforeEach(() => {
    vi.clearAllMocks()
    hook.current = null
    queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.useRealTimers()
  })

  it('locks row sending while Send all is in flight and while its deliveries are open', async () => {
    const request = deferred<{ queued: number; skipped: number }>()
    api.sendAllInvoices.mockReturnValue(request.promise)
    render()
    expect(rowSend('p1').disabled).toBe(false)
    await act(async () => { sendAll().onClick() })
    expect(api.sendAllInvoices).toHaveBeenCalledTimes(1)
    expect(rowSend('p1').disabled).toBe(true)
    expect(rowSend('p2').disabled).toBe(true)
    expect(hook.current!.getRowWork(rows[0]).sending).toBe(true)

    await act(async () => { request.resolve({ queued: 2, skipped: 0 }) })
    // Accepted but not delivered: still locked, still shown as sending.
    expect(rowSend('p1').disabled).toBe(true)
    expect(rowSend('p1').label).toBe('pages.invoices.sending')
    expect(sendAll().disabled).toBe(true)
    expect(api.sendInvoiceEmail).not.toHaveBeenCalled()
  })

  it('locks Send all while a row email is in flight and while its delivery is polled', async () => {
    vi.useFakeTimers()
    const request = deferred<void>()
    api.sendInvoiceEmail.mockReturnValue(request.promise)
    render()
    expect(sendAll().disabled).toBe(false)
    await act(async () => { rowSend('p1').onClick() })
    expect(api.sendInvoiceEmail).toHaveBeenCalledWith('inv-p1')
    expect(sendAll().disabled).toBe(true)
    expect(rowSend('p2').disabled).toBe(true)

    await act(async () => { request.resolve() })
    expect(sendAll().disabled).toBe(true)
    expect(hook.current!.getRowWork(rows[0]).sending).toBe(true)
    expect(hook.current!.getRowWork(rows[1]).sending).toBe(false)
    expect(rowSend('p2').disabled).toBe(false)
    expect(api.sendAllInvoices).not.toHaveBeenCalled()
  })

  it('follows a row send through the overview and announces its delivery once', async () => {
    vi.useFakeTimers()
    api.sendInvoiceEmail.mockResolvedValue(undefined)
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    render()
    await act(async () => { rowSend('p1').onClick() })
    expect(hook.current!.getRowWork(rows[0]).sending).toBe(true)
    invalidate.mockClear()
    await act(async () => { vi.advanceTimersByTime(2_500) })
    expect(invalidate.mock.calls.some(([filters]) => (filters?.queryKey as string[])?.[1] === 'period-overview')).toBe(true)

    const delivered = { ...rows[0], invoice: { ...rows[0].invoice!, status: 'sent',
      email_logs: [{ id: 'log-1', status: 'sent', created_at: '2026-05-08T10:00:00Z', recipient: 'p1@example.test' }] } }
    render({ rows: [delivered, rows[1]] })
    expect(pushToast).toHaveBeenCalledWith('pages.invoices.messages.emailSentSuccess', 'success')
    expect(hook.current!.getRowWork(delivered as never).sending).toBe(false)
    invalidate.mockClear()
    await act(async () => { vi.advanceTimersByTime(10_000) })
    expect(invalidate).not.toHaveBeenCalled()
    expect(pushToast).toHaveBeenCalledTimes(2) // queued, then delivered
  })

  it('stops following a row send when the period changes', async () => {
    vi.useFakeTimers()
    api.sendInvoiceEmail.mockResolvedValue(undefined)
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    render()
    await act(async () => { rowSend('p1').onClick() })
    render({ period: { period_start: '2026-06-01', period_end: '2026-06-30' } })
    expect(sendAll().disabled).toBe(false)
    expect(hook.current!.getRowWork(rows[0]).sending).toBe(false)
    invalidate.mockClear()
    await act(async () => { vi.advanceTimersByTime(10_000) })
    expect(invalidate).not.toHaveBeenCalled()
  })
})
