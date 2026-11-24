import { describe, expect, it } from 'vitest'
import { getLatestEmailLog } from '../src/features/invoices/emailLogs'
import { isAllowed, nextInvoiceWorkflowAction } from '../src/features/invoices/invoiceStatus'
import type { Credit, Invoice, InvoiceAction } from '../src/types/api'

describe('invoice action helpers', () => {
  it('returns the newest email log by created_at', () => {
    const invoice = {
      email_logs: [
        {
          id: 'log-old',
          created_at: '2026-05-07T08:00:00Z',
          recipient: 'old@example.com',
          status: 'queued',
        },
        {
          id: 'log-new',
          created_at: '2026-05-08T10:30:00Z',
          recipient: 'new@example.com',
          status: 'sent',
        },
      ],
    }

    expect(getLatestEmailLog(invoice)).toEqual({
      id: 'log-new',
      created_at: '2026-05-08T10:30:00Z',
      recipient: 'new@example.com',
      status: 'sent',
    })
  })

  it('returns null when no email logs are present', () => {
    expect(getLatestEmailLog(null)).toBeNull()
    expect(getLatestEmailLog({} as Invoice)).toBeNull()
  })

  it('takes the next workflow step from the actions the server allows', () => {
    const next = (allowed: InvoiceAction[]) => nextInvoiceWorkflowAction({ allowed_actions: allowed })

    expect(next(['approve', 'delete'])).toBe('approve')
    expect(next(['mark_sent', 'send_email'])).toBe('send-email')
    expect(next(['send_email', 'mark_paid', 'record_payment'])).toBe('mark-paid')
    // A viewer, a disabled ZEV or a settled invoice: nothing to move on.
    expect(next([])).toBeNull()
    expect(next(['correct', 'adjust'])).toBeNull()
  })

  it('offers nothing when an older backend sends no allowed_actions', () => {
    const legacy = { status: 'draft' } as unknown as Invoice
    expect(nextInvoiceWorkflowAction(legacy)).toBeNull()
    expect(isAllowed(legacy, 'delete')).toBe(false)
    expect(isAllowed({ status: 'open' } as unknown as Credit, 'refund')).toBe(false)
  })
})
