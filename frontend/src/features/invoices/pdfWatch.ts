import { useCallback, useState } from 'react'

import type { InvoicePeriodParticipantRow } from '../../types/api'

/**
 * Watching for invoice PDFs that are being rendered off the request.
 *
 * Creating an invoice queues its PDF (`generate_invoice_pdf_task`), and
 * "Regenerate all PDFs" queues a whole period, so the invoice row appears
 * before its document does. Nothing on the invoice records that a render is in
 * flight, so this is a client-side deadline rather than a status read: after an
 * action that queues one, poll the period overview while any invoice in it is
 * still missing a PDF.
 *
 * The watch gives up rather than polling forever. A render that failed leaves
 * `pdf_url` permanently null, which is indistinguishable from one still
 * running — the invoice carries no field that would tell them apart. Until it
 * does, "still pending after 90 seconds" is the only honest stopping rule.
 */

/** How long to keep watching after an action queued PDF work. */
export const PDF_WATCH_MS = 90_000

/**
 * How often to re-read the period overview while waiting. One render is well
 * under a second; this is paced for a worker chewing through a whole period.
 */
export const PDF_POLL_MS = 2_500

export type PdfWatch = { startedAt: number; until: number } | null

/** Invoices in this period that exist but have no PDF yet. */
export function countPendingPdfs(rows: InvoicePeriodParticipantRow[]): number {
    return rows.filter((row) => row.invoice && !row.invoice.pdf_url).length
}

export function usePdfWatch() {
    const [pdfWatch, setPdfWatch] = useState<PdfWatch>(null)

    const startPdfWatch = useCallback(() => {
        const now = Date.now()
        setPdfWatch({ startedAt: now, until: now + PDF_WATCH_MS })
    }, [])

    const stopPdfWatch = useCallback(() => setPdfWatch(null), [])

    return { pdfWatch, startPdfWatch, stopPdfWatch }
}

/**
 * Whether a settled watch should end.
 *
 * The `startedAt` grace is what makes this safe to call on every render: right
 * after the click the overview has not refetched yet, so a count of zero means
 * "nothing loaded" rather than "all done", and ending on it would stop the
 * watch before it ever polled.
 */
export function pdfWatchIsFinished(watch: NonNullable<PdfWatch>, pendingCount: number, now: number): boolean {
    if (now >= watch.until) return true
    return pendingCount === 0 && now - watch.startedAt > PDF_POLL_MS
}
