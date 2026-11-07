import { describe, expect, it } from 'vitest'
import type { Invoice, InvoicePeriodParticipantRow } from '../src/types/api'
import { filterInvoiceRows, invoiceRowCounts } from '../src/features/invoices/invoiceRowFilters'
import { invoiceRowIssues, invoiceRowProgress, repeatedParties } from '../src/features/invoices/invoiceRowState'

const invoice: Invoice = {
    id: 'i1', invoice_number: 'INV-1', zev: 'z1', zev_name: 'Community A', participant: 'p1', participant_name: 'Anna',
    period_start: '2026-02-01', period_end: '2026-02-28', status: 'sent', total_chf: '12.30', pdf_url: '/stored.pdf',
}
const base: InvoicePeriodParticipantRow = {
    participant_id: 'p1', participant_name: 'Anna', participant_email: 'anna@example.test', metering_data_complete: true,
    participant_kind: 'person', participant_name_addition: '', participant_valid_from: '2026-01-01',
    participant_valid_to: null, party_id: 'party-1', metering_point_labels: [],
    metering_points_total: 1, metering_points_with_data: 1, missing_meter_ids: [], generation_eligibility: null,
    invoice: { ...invoice },
}

const rows: InvoicePeriodParticipantRow[] = [
    // Sent invoice with a stored document.
    base,
    // Draft without a document yet.
    { ...base, participant_id: 'p2', invoice: { ...invoice, id: 'i2', status: 'draft', pdf_url: null } },
    // Approved, document pending, last email failed: an issue.
    { ...base, participant_id: 'p3', invoice: { ...invoice, id: 'i3', status: 'approved', pdf_url: null, pdf_status: 'pending', last_email_status: 'failed' } },
    // No invoice at all: a candidate with missing data (an issue) and a covered period.
    { ...base, participant_id: 'p4', invoice: null, generation_eligibility: { state: 'eligible', invoice_id: null, invoice_number: null }, metering_data_complete: false },
    { ...base, participant_id: 'p5', invoice: null, generation_eligibility: { state: 'covered', invoice_id: 'old', invoice_number: 'OLD' } },
]

const ids = (list: InvoicePeriodParticipantRow[]) => list.map((row) => row.participant_id)
const states = (row: InvoicePeriodParticipantRow) =>
    Object.fromEntries((invoiceRowProgress(row) ?? []).map(({ step, state }) => [step, state]))

describe('invoice row filters', () => {
    it('keeps reading corrections in Issues even after payment', () => {
        const corrected = { ...base, invoice: { ...invoice, status: 'paid', needs_data_review: true } }
        expect(invoiceRowCounts([corrected]).issues).toBe(1)
        expect(filterInvoiceRows([corrected], 'issues')).toEqual([corrected])
        expect(invoiceRowProgress(corrected)?.[0]).toEqual({ step: 'metering', state: 'issue', reason: 'correction' })
        expect(states(corrected).paid).toBe('done')
        expect(states({ ...corrected, invoice: { ...corrected.invoice, needs_data_review: false } }).metering).toBe('done')
    })

    it('counts exactly the rows each segment and batch action names', () => {
        expect(invoiceRowCounts(rows)).toEqual({ all: 5, invoices: 3, drafts: 1, approved: 1, sent: 1, issues: 2, pdfs: 1 })
    })

    it('filters to the counted rows for every segment', () => {
        expect(ids(filterInvoiceRows(rows, 'drafts'))).toEqual(['p2'])
        expect(ids(filterInvoiceRows(rows, 'approved'))).toEqual(['p3'])
        expect(ids(filterInvoiceRows(rows, 'sent'))).toEqual(['p1'])
        expect(ids(filterInvoiceRows(rows, 'issues'))).toEqual(['p3', 'p4'])
    })

    it('removes a retried PDF failure from both Issues membership and its count', () => {
        const failed = { ...base, invoice: { ...invoice, status: 'draft', pdf_url: null, pdf_status: 'failed' as const } }
        const work = () => ({ pdfPending: true })
        expect(invoiceRowCounts([failed]).issues).toBe(1)
        expect(invoiceRowCounts([failed], work).issues).toBe(0)
        expect(filterInvoiceRows([failed], 'issues', work)).toEqual([])
        expect(invoiceRowIssues(failed, work())).toEqual([])
    })

    it('keeps the unfiltered period intact and returns the same rows unfiltered', () => {
        expect(filterInvoiceRows(rows, null)).toBe(rows)
        // A covered or un-invoiced row is only hidden by the filter that excludes it.
        expect(filterInvoiceRows(rows, 'drafts')).not.toContain(rows[3])
    })
})

describe('invoice row state', () => {
    it('walks a row through the workflow steps in order', () => {
        const draft = { ...base, invoice: { ...invoice, status: 'draft' } }
        expect(invoiceRowProgress(draft)?.map(({ step }) => step)).toEqual(['metering', 'invoice', 'approved', 'sent', 'paid'])
        expect(states(draft)).toEqual({ metering: 'done', invoice: 'done', approved: 'open', sent: 'open', paid: 'open' })
        expect(states({ ...base, invoice: { ...invoice, status: 'paid' } }))
            .toEqual({ metering: 'done', invoice: 'done', approved: 'done', sent: 'done', paid: 'done' })
        // Marked as sent without an email still counts as sent.
        expect(states(base).sent).toBe('done')
    })

    it('shows delivery under way and failed, and only while delivery is the operator\'s concern', () => {
        const approved = { ...base, invoice: { ...invoice, status: 'approved' } }
        expect(states({ ...approved, invoice: { ...approved.invoice, last_email_status: 'pending' } }).sent).toBe('active')
        expect(states({ ...approved, invoice: { ...approved.invoice, last_email_status: 'failed' } }).sent).toBe('issue')
        // The annotation wins over older logs; logs answer when it is missing.
        expect(states({ ...base, invoice: { ...invoice, last_email_status: 'failed', email_logs: [{ status: 'sent' } as never] } }).sent).toBe('issue')
        expect(states({ ...base, invoice: { ...invoice, email_logs: [
            { id: 'old', status: 'failed', created_at: '2026-01-01T10:00:00Z' } as never,
            { id: 'new', status: 'sent', created_at: '2026-01-01T11:00:00Z' } as never,
        ] } }).sent).toBe('done')
        // A paid invoice is settled: a later failed resend is not a problem.
        const paid = { ...base, invoice: { ...invoice, status: 'paid', last_email_status: 'failed' as const } }
        expect(states(paid).sent).toBe('done')
        expect(invoiceRowIssues(paid)).toEqual([])
    })

    it('does not flag settled invoices whose meters have been removed', () => {
        const historical = { ...base, metering_points_total: 0, metering_points_with_data: 0, metering_data_complete: false }
        for (const status of ['sent', 'paid']) {
            const row = { ...historical, invoice: { ...invoice, status } }
            expect(invoiceRowIssues(row)).toEqual([])
            expect(invoiceRowCounts([row]).issues).toBe(0)
        }
        expect(invoiceRowIssues({ ...historical, invoice: { ...invoice, status: 'draft' } })).toEqual(['metering'])
        // Not "complete": the step says why nothing is missing.
        const metering = invoiceRowProgress({ ...historical, invoice: { ...invoice, status: 'paid' } })![0]
        expect(metering).toEqual({ step: 'metering', state: 'done', reason: 'noMeters' })
    })

    it('flags an approved invoice nobody can be emailed', () => {
        const row = { ...base, participant_email: '', invoice: { ...invoice, status: 'approved' } }
        expect(invoiceRowIssues(row)).toEqual(['noEmail'])
        expect(invoiceRowProgress(row)!.find(step => step.step === 'sent')).toMatchObject({ state: 'issue', reason: 'noEmail' })
        expect(invoiceRowIssues({ ...row, invoice: { ...invoice, status: 'sent' } })).toEqual([])
    })

    it('shows local sending and hides an old delivery failure while it is retried', () => {
        const failed = { ...base, participant_email: 'a@example.test',
            invoice: { ...invoice, status: 'approved', last_email_status: 'failed' as const } }
        expect(invoiceRowIssues(failed)).toEqual(['delivery'])
        expect(invoiceRowIssues(failed, { sending: true })).toEqual([])
        expect(invoiceRowProgress(failed, { sending: true })!.find(step => step.step === 'sent'))
            .toMatchObject({ state: 'active', reason: 'sending' })
    })

    it('reports every problem a row has, once', () => {
        expect(invoiceRowIssues(base)).toEqual([])
        expect(invoiceRowIssues({
            ...base, metering_data_complete: false,
            invoice: { ...invoice, status: 'approved', pdf_url: null, pdf_status: 'failed', last_email_status: 'failed' },
        })).toEqual(['metering', 'pdf', 'delivery'])
        // A stored older document outlives a failed re-render.
        expect(invoiceRowIssues({ ...base, invoice: { ...invoice, pdf_status: 'failed' } })).toEqual([])
    })

    it('treats a blocked row without an invoice as locked, a covered one as having no workflow', () => {
        const blocked = { ...base, invoice: null, generation_eligibility: { state: 'blocked' as const, invoice_id: 'x', invoice_number: 'X' } }
        expect(states(blocked).invoice).toBe('issue')
        expect(invoiceRowIssues(blocked)).toEqual(['conflict'])
        // A draft whose regeneration is blocked still bills the period.
        expect(invoiceRowIssues({ ...blocked, invoice: { ...invoice, status: 'draft' } })).toEqual([])

        const covered = { ...base, invoice: null, generation_eligibility: { state: 'covered' as const, invoice_id: 'x', invoice_number: 'X' } }
        expect(invoiceRowProgress(covered)).toBeNull()
        // A cancelled invoice no longer bills the period.
        expect(invoiceRowProgress({ ...covered, invoice: { ...invoice, status: 'cancelled' } })).toBeNull()
        expect(states({ ...base, invoice: { ...invoice, status: 'cancelled' }, generation_eligibility: { state: 'eligible', invoice_id: null, invoice_number: null } }))
            .toEqual({ metering: 'done', invoice: 'open', approved: 'open', sent: 'open', paid: 'open' })
    })
})

describe('invoice step reasons', () => {
    const reasons = (row: InvoicePeriodParticipantRow, work = {}) =>
        Object.fromEntries((invoiceRowProgress(row, work) ?? []).filter(({ reason }) => reason).map(({ step, reason }) => [step, reason]))

    it('names the problem behind every step in trouble', () => {
        expect(reasons({
            ...base, metering_data_complete: false,
            invoice: { ...invoice, status: 'approved', pdf_url: null, pdf_status: 'failed', last_email_status: 'failed' },
        })).toEqual({ metering: 'metering', invoice: 'pdf', sent: 'delivery' })
        expect(reasons({ ...base, invoice: null, generation_eligibility: { state: 'blocked', invoice_id: 'x', invoice_number: 'X' } }))
            .toEqual({ invoice: 'conflict' })
    })

    it('names the work under way, which outranks an older failure', () => {
        const noInvoice = { ...base, invoice: null, generation_eligibility: { state: 'eligible' as const, invoice_id: null, invoice_number: null } }
        expect(invoiceRowProgress(noInvoice, { generating: true })?.[1]).toEqual({ step: 'invoice', state: 'active', reason: 'generating' })
        const failed = { ...base, invoice: { ...invoice, status: 'draft', pdf_url: null, pdf_status: 'failed' as const } }
        expect(reasons(failed, { pdfPending: true })).toEqual({ invoice: 'pdfPending' })
        expect(invoiceRowIssues(failed, { pdfPending: true })).toEqual([])
        expect(reasons({ ...base, invoice: { ...invoice, status: 'approved', last_email_status: 'pending' } })).toEqual({ sent: 'sending' })
    })
})

describe('repeated parties', () => {
    it('finds the parties holding more than one row', () => {
        const party = (id: string, partyId: string) => ({ ...base, participant_id: id, party_id: partyId })
        expect([...repeatedParties([party('a', 'x'), party('b', 'y'), party('c', 'x'), party('d', 'z'), party('e', 'w')])]).toEqual(['x'])
    })
})
