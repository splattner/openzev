import type { Credit, CreditStatus, Invoice } from '../../types/api'

/** What was received in cash for the invoice and not yet credited, in CHF (never negative). */
export function creditableChf(invoice: Pick<Invoice, 'paid_chf' | 'credits'>): number {
    const credited = (invoice.credits ?? []).reduce((sum, credit) => sum + Number(credit.amount_chf), 0)
    return Math.max(0, Math.round((Number(invoice.paid_chf ?? 0) - credited) * 100) / 100)
}

/** Credit notes set against the invoice that were not released again (CHF). */
export function appliedCreditChf(invoice: Pick<Invoice, 'credit_applications'>): number {
    const applied = (invoice.credit_applications ?? [])
        .filter((application) => application.released_at === null)
        .reduce((sum, application) => sum + Number(application.amount_chf), 0)
    return Math.round(applied * 100) / 100
}

/**
 * An invoice that received money is open to correction: paid, or sent with
 * payments. A payout (nothing to collect) is out of scope.
 */
function isCorrectable(invoice: Pick<Invoice, 'status' | 'paid_chf' | 'total_chf'>): boolean {
    const received = Number(invoice.paid_chf ?? 0)
    const eligible = invoice.status === 'paid' || (invoice.status === 'sent' && received > 0)
    // An invoice settled by credit alone is `paid` with no payment: `received` is 0 there.
    return eligible && Number(invoice.total_chf) > 0
}

/**
 * A manager can reverse an invoice when there is cash to credit back or credit
 * that was applied to it and can be released.
 */
export function canCorrectInvoice(
    invoice: Pick<Invoice, 'status' | 'paid_chf' | 'total_chf' | 'credits' | 'credit_applications'>,
    canManage: boolean,
): boolean {
    if (!canManage || !isCorrectable(invoice)) return false
    return creditableChf(invoice) > 0 || appliedCreditChf(invoice) > 0
}

/** A partial credit is capped by cash: an invoice settled by credit alone must be reversed instead. */
export function canAdjustInvoice(
    invoice: Pick<Invoice, 'status' | 'paid_chf' | 'total_chf' | 'credits' | 'credit_applications'>,
    canManage: boolean,
): boolean {
    return canManage && isCorrectable(invoice) && creditableChf(invoice) > 0
}

/** Money still to pay on an invoice after credit; the total when no amount due is known. */
export function amountDueChf(invoice: Pick<Invoice, 'total_chf' | 'amount_due_chf'>): number {
    return Number(invoice.amount_due_chf ?? invoice.total_chf)
}

/** Show the amount due beside the total when credit reduced it (a cancelled invoice asks for nothing). */
export function hasCreditApplied(
    invoice: Pick<Invoice, 'status' | 'total_chf' | 'credit_applied_chf' | 'amount_due_chf'>,
): boolean {
    return (
        invoice.status !== 'cancelled'
        && Number(invoice.credit_applied_chf ?? 0) > 0
        && amountDueChf(invoice) !== Number(invoice.total_chf)
    )
}

/** A manager can pay out what remains of an open credit. */
export function canRefundCredit(credit: Pick<Credit, 'status'>, canManage: boolean): boolean {
    return canManage && credit.status === 'open'
}

export const CREDIT_STATUS_BADGE: Record<CreditStatus, string> = {
    open: 'badge badge-info',
    used: 'badge badge-neutral',
    refunded: 'badge badge-success',
}
