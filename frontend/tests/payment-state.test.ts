import { describe, expect, it } from 'vitest'
import { paymentState } from '../src/features/invoices/invoiceStatus'

const TODAY = '2026-11-02'

describe('paymentState (what a participant sees)', () => {
  it('is paid for a paid invoice', () => {
    expect(paymentState({ status: 'paid', due_date: '2026-10-01' }, TODAY)).toBe('paid')
  })

  it('is due while the due date has not passed', () => {
    expect(paymentState({ status: 'sent', due_date: TODAY, total_chf: '100.00' }, TODAY)).toBe('due')
    expect(paymentState({ status: 'sent', due_date: null, total_chf: '100.00' }, TODAY)).toBe('due')
  })

  it('is overdue the day after the due date', () => {
    expect(paymentState({ status: 'sent', due_date: '2026-11-01', total_chf: '100.00' }, TODAY)).toBe('overdue')
  })

  it('is paid when payments cover the amount due, whatever the status says', () => {
    expect(paymentState({
      status: 'sent', due_date: '2026-10-01', total_chf: '100.00', amount_due_chf: '100.00', outstanding_chf: '0.00',
    }, TODAY)).toBe('paid')
  })

  it('judges overdue on the amount still outstanding, not the total', () => {
    expect(paymentState({
      status: 'sent', due_date: '2026-10-01', total_chf: '100.00', amount_due_chf: '100.00', outstanding_chf: '40.00',
    }, TODAY)).toBe('overdue')
  })

  it('says nothing for drafts, cancelled invoices, payouts and zero amounts', () => {
    expect(paymentState({ status: 'draft', total_chf: '100.00' }, TODAY)).toBeNull()
    expect(paymentState({ status: 'cancelled', total_chf: '100.00' }, TODAY)).toBeNull()
    expect(paymentState({ status: 'sent', total_chf: '-12.00' }, TODAY)).toBeNull()
    expect(paymentState({ status: 'sent', total_chf: '100.00', amount_due_chf: '0.00' }, TODAY)).toBeNull()
  })
})
