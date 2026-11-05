/**
 * Single source for the "open invoice" concept: an invoice that has been
 * approved or sent but is not yet settled (paid/cancelled/draft).
 */
import { todayBusinessIso } from '../../lib/dates'

const OPEN_INVOICE_STATUSES: readonly string[] = ['approved', 'sent']

function isOpenInvoiceStatus(status: string): boolean {
  return OPEN_INVOICE_STATUSES.includes(status)
}

/**
 * A sent invoice with some, but not all, of its amount received (#388).
 * Not a status of its own: derived from the recorded payments.
 */
export function isPartlyPaid(invoice: { status: string; paid_chf?: string } | null | undefined): boolean {
  return !!invoice && invoice.status === 'sent' && Number(invoice.paid_chf ?? 0) !== 0
}

/**
 * What the recipient needs to know about an invoice: whether to pay, and by
 * when. The workflow status (approved, sent) is a staff matter; a participant
 * sees only this (audience-specific labels). `null` where there is nothing to
 * pay or say: a draft, a cancelled invoice, a payout or a zero amount.
 */
export type PaymentState = 'due' | 'overdue' | 'paid'

export function paymentState(
  invoice: {
    status: string
    due_date?: string | null
    paid_chf?: string
    outstanding_chf?: string
    total_chf?: string
    amount_due_chf?: string
  },
  today: string = todayBusinessIso(),
): PaymentState | null {
  if (invoice.status === 'paid') return 'paid'
  if (!isOpenInvoiceStatus(invoice.status)) return null
  const amountDue = Number(invoice.amount_due_chf ?? invoice.total_chf ?? 0)
  if (!(amountDue > 0)) return null
  if (invoice.outstanding_chf !== undefined && Number(invoice.outstanding_chf) <= 0) return 'paid'
  return invoice.due_date && invoice.due_date < today ? 'overdue' : 'due'
}

/** Neutral staff-table tag; cancelled labels use plain red text. */
export const INVOICE_STATUS_BADGE_CLASS = 'badge badge-tag'

export function nextInvoiceWorkflowAction(invoice: { status: string }): 'approve' | 'send-email' | 'mark-paid' | null {
  if (invoice.status === 'draft') return 'approve'
  if (invoice.status === 'approved') return 'send-email'
  if (invoice.status === 'sent') return 'mark-paid'
  return null
}

