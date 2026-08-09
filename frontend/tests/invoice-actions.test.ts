import { describe, expect, it } from 'vitest'
import { getLatestEmailLog } from '../src/features/invoices/emailLogs'
import { hasDeletePermission } from '../src/features/invoices/useInvoiceActions'
import type { Invoice } from '../src/types/api'

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

  it('allows deleting only draft, cancelled, or admin invoices', () => {
    const sentInvoice = { status: 'sent' } as Invoice
    const draftInvoice = { status: 'draft' } as Invoice
    const cancelledInvoice = { status: 'cancelled' } as Invoice

    expect(hasDeletePermission(sentInvoice, 'participant')).toBe(false)
    expect(hasDeletePermission(draftInvoice, 'participant')).toBe(true)
    expect(hasDeletePermission(cancelledInvoice, 'participant')).toBe(true)
    expect(hasDeletePermission(sentInvoice, 'admin')).toBe(true)
  })
})
