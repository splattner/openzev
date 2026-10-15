import type { Invoice, InvoicePeriodParticipantRow } from '../../types/api'
import { getLatestEmailLog } from './emailLogs'
import { isPartlyPaid } from './invoiceStatus'

/** Shared workflow state for progress, issues and filtering. */

/** The invoice that bills the row's period; a cancelled one no longer does. */
export function liveInvoice(row: InvoicePeriodParticipantRow): Invoice | null {
    return row.invoice && row.invoice.status !== 'cancelled' ? row.invoice : null
}

/** Status of the newest email attempt, from the annotation or the logs. */
function latestDeliveryStatus(invoice: Invoice | null): 'pending' | 'sent' | 'failed' | null {
    const status = invoice?.last_email_status ?? getLatestEmailLog(invoice)?.status
    return status === 'pending' || status === 'sent' || status === 'failed' ? status : null
}

/** Statuses whose email delivery is still the operator's concern. */
const DELIVERING = new Set(['approved', 'sent'])

/** Problems an operator has to act on before the row can be billed cleanly. */
type InvoiceRowIssue = 'metering' | 'conflict' | 'pdf' | 'delivery' | 'noEmail'

/** Locally pending invoice, PDF or email work the overview may not show yet. */
export type InvoiceRowWork = { generating?: boolean; pdfPending?: boolean; sending?: boolean }

/** A sent/paid invoice whose meters were unassigned since: nothing left to read. */
function settledWithoutMeters(row: InvoicePeriodParticipantRow, invoice: Invoice | null): boolean {
    return row.metering_points_total === 0 && !!invoice && ['sent', 'paid'].includes(invoice.status)
}

export function invoiceRowIssues(row: InvoicePeriodParticipantRow, work: InvoiceRowWork = {}): InvoiceRowIssue[] {
    const invoice = liveInvoice(row)
    const issues: InvoiceRowIssue[] = []
    if (!row.metering_data_complete && !settledWithoutMeters(row, invoice)) issues.push('metering')
    // A draft whose regeneration is blocked still bills the period; only a
    // row the conflict leaves without an invoice is a problem.
    if (!invoice && row.generation_eligibility?.state === 'blocked') issues.push('conflict')
    // While a new render runs, an old failure is no longer the news.
    if (invoice?.pdf_status === 'failed' && !invoice.pdf_url && !isPdfPending(invoice, work)) issues.push('pdf')
    if (invoice && DELIVERING.has(invoice.status) && latestDeliveryStatus(invoice) === 'failed' && !work.sending) issues.push('delivery')
    if (invoice?.status === 'approved' && !row.participant_email) issues.push('noEmail')
    return issues
}

function isPdfPending(invoice: Invoice, work: InvoiceRowWork): boolean {
    return !!work.pdfPending || invoice.pdf_status === 'pending'
}

export const INVOICE_PROGRESS_STEPS = ['metering', 'invoice', 'approved', 'sent', 'paid'] as const
export type InvoiceProgressStep = typeof INVOICE_PROGRESS_STEPS[number]
/** `active` is work under way (an email queued); `issue` needs the operator. */
export type InvoiceStepState = 'done' | 'open' | 'active' | 'issue'
/** Why a step is `active` or `issue`: the problem, or the work under way. */
export type InvoiceStepReason = InvoiceRowIssue | 'generating' | 'pdfPending' | 'sending' | 'noMeters' | 'partlyPaid'
export type InvoiceRowStep = { step: InvoiceProgressStep; state: InvoiceStepState; reason?: InvoiceStepReason }

const STATUS_ORDER = ['draft', 'approved', 'sent', 'paid']

/** Five workflow steps, or null when other invoices already bill the period. */
export function invoiceRowProgress(row: InvoicePeriodParticipantRow, work: InvoiceRowWork = {}): InvoiceRowStep[] | null {
    const invoice = liveInvoice(row)
    if (!invoice && row.generation_eligibility?.state === 'covered') return null

    const reached = (status: string) =>
        !!invoice && STATUS_ORDER.indexOf(invoice.status) >= STATUS_ORDER.indexOf(status)
    const delivery = latestDeliveryStatus(invoice)
    const delivering = !!invoice && DELIVERING.has(invoice.status)
    const issues = invoiceRowIssues(row, work)

    const invoiceStep = (): Omit<InvoiceRowStep, 'step'> => {
        if (!invoice) {
            if (work.generating) return { state: 'active', reason: 'generating' }
            return issues.includes('conflict') ? { state: 'issue', reason: 'conflict' } : { state: 'open' }
        }
        if (isPdfPending(invoice, work)) return { state: 'active', reason: 'pdfPending' }
        return issues.includes('pdf') ? { state: 'issue', reason: 'pdf' } : { state: 'done' }
    }

    const steps: Record<InvoiceProgressStep, Omit<InvoiceRowStep, 'step'>> = {
        metering: issues.includes('metering') ? { state: 'issue', reason: 'metering' }
            : !row.metering_data_complete && settledWithoutMeters(row, invoice) ? { state: 'done', reason: 'noMeters' }
                : { state: 'done' },
        invoice: invoiceStep(),
        approved: { state: reached('approved') ? 'done' : 'open' },
        sent: issues.includes('delivery') ? { state: 'issue', reason: 'delivery' }
            : work.sending || (delivering && delivery === 'pending') ? { state: 'active', reason: 'sending' }
                : issues.includes('noEmail') ? { state: 'issue', reason: 'noEmail' }
                    : { state: reached('sent') ? 'done' : 'open' },
        paid: isPartlyPaid(invoice) ? { state: 'active', reason: 'partlyPaid' }
            : { state: reached('paid') ? 'done' : 'open' },
    }
    return INVOICE_PROGRESS_STEPS.map((step) => ({ step, ...steps[step] }))
}

/** Parties that hold more than one of these rows (a flat and a parking space). */
export function repeatedParties(rows: InvoicePeriodParticipantRow[]): ReadonlySet<string> {
    const seen = new Set<string>()
    const repeated = new Set<string>()
    for (const { party_id: party } of rows) {
        if (seen.has(party)) repeated.add(party)
        seen.add(party)
    }
    return repeated
}
