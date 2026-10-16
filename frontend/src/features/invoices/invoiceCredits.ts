import type { Invoice } from '../../types/api'

/** What was received for the invoice and not yet credited, in CHF (never negative). */
export function creditableChf(invoice: Pick<Invoice, 'paid_chf' | 'credits'>): number {
    const credited = (invoice.credits ?? []).reduce((sum, credit) => sum + Number(credit.amount_chf), 0)
    return Math.max(0, Math.round((Number(invoice.paid_chf ?? 0) - credited) * 100) / 100)
}

/**
 * A manager can correct an invoice that received money: paid, or sent with
 * payments, and with something to collect (a payout is out of scope) and
 * something left to credit.
 */
export function canCorrectInvoice(
    invoice: Pick<Invoice, 'status' | 'paid_chf' | 'total_chf' | 'credits'>,
    canManage: boolean,
): boolean {
    if (!canManage) return false
    const received = Number(invoice.paid_chf ?? 0)
    const eligible = invoice.status === 'paid' || (invoice.status === 'sent' && received > 0)
    return eligible && Number(invoice.total_chf) > 0 && creditableChf(invoice) > 0
}
