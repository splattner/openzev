import { useCallback, useState } from 'react'

import type { InvoicePeriodParticipantRow } from '../../types/api'

/**
 * Watching for invoice PDFs that are being rendered off the request.
 *
 * Creating an invoice queues its PDF (`generate_invoice_pdf_task`), and
 * "Regenerate all PDFs" queues a whole period, so the invoice row appears
 * before its document does. `Invoice.pdf_status` records that, so the poll is
 * a status read: after an action that queues work, re-read the period overview
 * while any invoice in it is still `pending`.
 *
 * `pdf_status` gives the watch a terminal state to stop on: a failed render
 * settles to `failed` and stops being counted, so the common failure ends the
 * watch immediately instead of running it to the deadline. The deadline
 * remains as the backstop for the case no status can cover — a worker killed
 * mid-render leaves the row `pending` with nothing left to settle it.
 */

/** How long to keep watching after an action queued PDF work. */
export const PDF_WATCH_MS = 90_000

/**
 * How often to re-read the period overview while waiting. One render is well
 * under a second; this is paced for a worker chewing through a whole period.
 */
export const PDF_POLL_MS = 2_500

export type PdfWatch = { startedAt: number; until: number } | null

/**
 * Invoices in this period whose document is still being rendered.
 *
 * Reads `pdf_status` rather than inferring from a missing `pdf_url`: a failed
 * render also leaves `pdf_url` null, and counting those would hold the watch
 * open until its deadline on every poll for the rest of the period's life.
 */
export function countPendingPdfs(rows: InvoicePeriodParticipantRow[]): number {
    return rows.filter((row) => row.invoice?.pdf_status === 'pending').length
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
