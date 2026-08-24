import { describe, expect, it } from 'vitest'
import { isInvoiceOverdue, selectOpenInvoices, sumTotalChf } from '../src/features/invoices/openInvoices'

describe('openInvoices helpers', () => {
  it('selects only approved and sent as open', () => {
    const invoices = [
      { id: '1', status: 'draft', total_chf: '10.00', due_date: '2026-01-01' },
      { id: '2', status: 'approved', total_chf: '20.00', due_date: '2026-01-01' },
      { id: '3', status: 'sent', total_chf: '30.00', due_date: '2026-01-01' },
      { id: '4', status: 'paid', total_chf: '40.00', due_date: '2026-01-01' },
      { id: '5', status: 'cancelled', total_chf: '50.00', due_date: '2026-01-01' },
    ] as any
    const open = selectOpenInvoices(invoices)
    expect(open.map((i) => i.id)).toEqual(['2', '3'])
  })

  it('detects overdue when due_date is before today and status is open', () => {
    const overdue = { status: 'sent', due_date: '2026-01-01' } as any
    const notOverdue = { status: 'sent', due_date: '2026-01-03' } as any
    const notOpen = { status: 'draft', due_date: '2026-01-01' } as any
    expect(isInvoiceOverdue(overdue, '2026-01-02')).toBe(true)
    expect(isInvoiceOverdue(notOverdue, '2026-01-02')).toBe(false)
    expect(isInvoiceOverdue(notOpen, '2026-01-02')).toBe(false)
    expect(isInvoiceOverdue({ status: 'sent', due_date: '2026-01-02' }, '2026-01-02')).toBe(false)
  })

  it('treats a missing due_date as not overdue', () => {
    expect(isInvoiceOverdue({ status: 'sent', due_date: null }, '2026-01-02')).toBe(false)
    expect(isInvoiceOverdue({ status: 'sent', due_date: '' }, '2026-01-02')).toBe(false)
  })

  it('does not consider paid as overdue', () => {
    const paid = { status: 'paid', due_date: '2026-01-01' } as any
    expect(isInvoiceOverdue(paid, '2026-01-02')).toBe(false)
  })

  it('sums total_chf correctly', () => {
    const invoices = [
      { total_chf: '10.50' },
      { total_chf: '20.25' },
      { total_chf: null },
    ] as any
    expect(sumTotalChf(invoices)).toBeCloseTo(30.75)
  })
})
