import { describe, it, expect } from 'vitest'

import {
    PDF_POLL_MS,
    PDF_WATCH_MS,
    countPendingPdfs,
    pdfWatchIsFinished,
} from '../src/features/invoices/pdfWatch'
import type { InvoicePeriodParticipantRow } from '../src/types/api'

/**
 * The stopping rules for the PDF watch.
 *
 * Both are easy to get subtly wrong in ways that are invisible in a browser:
 * end too eagerly and the poll never runs (the overview has not refetched yet,
 * so "nothing pending" means "nothing loaded"); never end and a failed render
 * spins a request every 2.5s forever.
 */

const row = (overrides: Partial<InvoicePeriodParticipantRow['invoice']> | null) =>
    ({
        participant_id: Math.random().toString(),
        participant_name: 'Anna Muster',
        invoice: overrides === null ? null : ({ id: 'i1', pdf_url: null, ...overrides } as never),
        metering_data_complete: true,
        metering_points_total: 1,
        metering_points_with_data: 1,
        missing_meter_ids: [],
    }) as InvoicePeriodParticipantRow

describe('countPendingPdfs', () => {
    it('counts invoices that exist but have no document', () => {
        expect(countPendingPdfs([row({ pdf_url: null }), row({ pdf_url: '/x.pdf' })])).toBe(1)
    })

    it('ignores participants with no invoice at all', () => {
        // Nothing was queued for them, so they must not hold the watch open.
        expect(countPendingPdfs([row(null), row(null)])).toBe(0)
    })

    it('is zero when every invoice has its document', () => {
        expect(countPendingPdfs([row({ pdf_url: '/a.pdf' }), row({ pdf_url: '/b.pdf' })])).toBe(0)
    })
})

describe('pdfWatchIsFinished', () => {
    const started = 1_000_000
    const watch = { startedAt: started, until: started + PDF_WATCH_MS }

    it('does not end on the zero count that precedes the first refetch', () => {
        // The regression this guard exists for: ending here means never polling.
        expect(pdfWatchIsFinished(watch, 0, started + 100)).toBe(false)
    })

    it('ends once a settled refetch shows nothing pending', () => {
        expect(pdfWatchIsFinished(watch, 0, started + PDF_POLL_MS + 1)).toBe(true)
    })

    it('keeps waiting while documents are still missing', () => {
        expect(pdfWatchIsFinished(watch, 3, started + 30_000)).toBe(false)
    })

    it('gives up at the deadline even with documents still missing', () => {
        // A failed render leaves pdf_url null forever; without this the page
        // would poll for the rest of the session.
        expect(pdfWatchIsFinished(watch, 3, started + PDF_WATCH_MS)).toBe(true)
    })
})
