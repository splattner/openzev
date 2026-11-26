import type { Invoice } from '../../types/api'

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
