import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { InvoicePeriodRowsTable } from '../features/invoices/InvoicePeriodRowsTable'
import { InvoiceBatchToolbar } from '../features/invoices/InvoiceBatchToolbar'
import { InvoiceDeleteModal } from '../features/invoices/InvoiceDeleteModal'
import { InvoicesEmptyState } from '../features/invoices/InvoicesEmptyState'
import { useInvoiceActions } from '../features/invoices/useInvoiceActions'
import {
    PDF_POLL_MS,
    countPendingPdfs,
    pdfWatchIsFinished,
    usePdfWatch,
} from '../features/invoices/pdfWatch'
import { PeriodSelector } from '../components/PeriodSelector'
import {
    firstAlignedBillingPeriod,
    getPreviousBillingPeriod,
    invoiceRangeFromParams,
    type BillingInterval,
} from '../lib/billingPeriod'
import {
    fetchEmailLogs,
    fetchInvoicePeriodOverview,
} from '../lib/api/invoices'
import { queryKeys } from '../lib/api/queryKeys'
import { EmailLogsModal } from '../components/EmailLogsModal'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import type { EmailLog } from '../types/api'

export function InvoicesPage() {
    const { t } = useTranslation()
    const { selectedZevId, selectedZev } = useManagedZev()
    const { user } = useAuth()
    const [searchParams, setSearchParams] = useSearchParams()

    const interval: BillingInterval = (selectedZev?.billing_interval as BillingInterval) ?? 'monthly'
    const communityStart = selectedZev?.start_date ?? null
    const minPeriod = useMemo(
        () => firstAlignedBillingPeriod(communityStart, interval),
        [communityStart, interval],
    )

    const [period, setPeriod] = useState<{ period_start: string; period_end: string }>({
        period_start: '',
        period_end: '',
    })

    // Declared above the query because it paces it; the query's own rows are
    // what tell it when to stop, so the interval reads them from the query.
    const { pdfWatch, startPdfWatch, stopPdfWatch } = usePdfWatch()

    const [deleteModalInvoiceId, setDeleteModalInvoiceId] = useState<string | null>(null)
    const [selectedEmailLogs, setSelectedEmailLogs] = useState<EmailLog[]>([])
    const [showEmailModal, setShowEmailModal] = useState(false)
    const [selectedInvoiceNumber, setSelectedInvoiceNumber] = useState('')

    // Destination contract: the URL's exact period wins (cockpit + historical
    // attention links); otherwise the latest completed period.
    useEffect(() => {
        if (!selectedZevId) {
            setPeriod({ period_start: '', period_end: '' })
            return
        }
        const fromParams = invoiceRangeFromParams(
            searchParams.get('period_start'),
            searchParams.get('period_end'),
            communityStart,
        )
        if (fromParams) {
            setPeriod({ period_start: fromParams.from, period_end: fromParams.to })
            return
        }
        const previous = getPreviousBillingPeriod(interval)
        const useFirst = !!minPeriod && previous.from < minPeriod.from
        const fallback = useFirst && minPeriod
            ? { period_start: minPeriod.from, period_end: minPeriod.to }
            : { period_start: previous.from, period_end: previous.to }
        setPeriod(fallback)
    }, [selectedZevId, interval, searchParams, minPeriod, communityStart])

    function handlePeriodChange(next: { period_start: string; period_end: string }) {
        setPeriod(next)
        const params = new URLSearchParams(searchParams)
        params.set('period_start', next.period_start)
        params.set('period_end', next.period_end)
        setSearchParams(params, { replace: true })
    }

    const periodOverviewQuery = useQuery({
        queryKey: queryKeys.invoices.periodOverview(selectedZevId, period.period_start, period.period_end),
        queryFn: () =>
            fetchInvoicePeriodOverview({
                zev_id: selectedZevId,
                period_start: period.period_start,
                period_end: period.period_end,
            }),
        enabled: !!selectedZevId && !!period.period_start && !!period.period_end,
        // Poll only while an action's queued PDFs are still outstanding, and
        // read that from the query's own latest rows rather than from state
        // derived below — otherwise the interval would lag a render behind.
        refetchInterval: (query) =>
            pdfWatch && countPendingPdfs(query.state.data?.rows ?? []) > 0 ? PDF_POLL_MS : false,
        refetchIntervalInBackground: true,
    })

    const rows = periodOverviewQuery.data?.rows ?? []
    const pendingPdfCount = countPendingPdfs(rows)
    const isWaitingForPdfs = pdfWatch !== null && pendingPdfCount > 0

    // Generation eligibility rides on the rows themselves, so no second
    // request gates the actions: while the overview loads the table shows
    // its skeleton, and on failure the error banner — never a Generate
    // button that a missing readiness payload cannot qualify.

    // End the watch when every invoice has its document, or the deadline passes.
    useEffect(() => {
        if (!pdfWatch) return
        if (pdfWatchIsFinished(pdfWatch, pendingPdfCount, Date.now())) {
            stopPdfWatch()
            return
        }
        const timer = window.setTimeout(stopPdfWatch, pdfWatch.until - Date.now())
        return () => window.clearTimeout(timer)
    }, [pdfWatch, pendingPdfCount, stopPdfWatch])

    async function handleOpenEmailLogs(invoiceId: string, invoiceNumber: string) {
        try {
            const logs = await fetchEmailLogs(invoiceId)
            setSelectedEmailLogs(logs)
            setSelectedInvoiceNumber(invoiceNumber)
            setShowEmailModal(true)
        } catch {
            // Error is handled by the UI
        }
    }

    const {
        deleteMutation,
        downloadAllPdfsMutation,
        anyBatchPending,
        stats,
        recommendedBatchAction,
        batchMenuItems,
        getPrimaryRowAction,
        getRowMenuItems,
        handleRetryEmail,
        retiringEmailId,
        pdfGeneratingInvoiceId,
    } = useInvoiceActions({
        selectedZevId,
        period,
        rows,
        userRole: user?.role,
        onOpenEmailLogs: handleOpenEmailLogs,
        onDeleteClick: (invoiceId) => setDeleteModalInvoiceId(invoiceId),
        onPdfQueued: startPdfWatch,
    })

    /** Whether this row's document is being produced right now.
     *
     * The local mutation matters as well as the stored status: the per-invoice
     * regenerate renders inline, so the row is busy before any write lands. */
    const isPdfPending = (row: typeof rows[number]) => {
        if (!row.invoice) return false
        if (pdfGeneratingInvoiceId === row.invoice.id) return true
        return row.invoice.pdf_status === 'pending'
    }

    const isOwnerOrAdmin = user?.role === 'admin' || user?.role === 'zev_owner'

    const batchStats = [
        { key: 'invoices', label: t('pages.invoices.batch.summaryInvoices'), value: stats.invoiceCount },
        { key: 'drafts', label: t('pages.invoices.batch.summaryDrafts'), value: stats.draftCount },
        { key: 'approved', label: t('pages.invoices.batch.summaryApproved'), value: stats.approvedCount },
        { key: 'pdfs', label: t('pages.invoices.batch.summaryPdfs'), value: stats.pdfCount },
    ]

    if (!selectedZevId) {
        return (
            <div className="page-stack">
                <header>
                    <h2>{t('pages.invoices.title')}</h2>
                    <p className="muted">{t('pages.invoices.selectZev')}</p>
                </header>
            </div>
        )
    }

    return (
        <div className="page-stack">
            <header>
                {selectedZev?.name ? <p className="eyebrow">{selectedZev.name}</p> : null}
                <h2>{t('pages.invoices.title')}</h2>
                <p className="muted">{t('pages.invoices.description')}</p>
            </header>

            <section className="card">
                <PeriodSelector
                    interval={interval}
                    from={period.period_start}
                    to={period.period_end}
                    title={selectedZev?.name}
                    allowCustomRange={false}
                    minFrom={minPeriod?.from}
                    onChange={({ from, to }) => handlePeriodChange({ period_start: from, period_end: to })}
                />
            </section>

            {periodOverviewQuery.isLoading ? (
                <div className="card">{t('pages.invoices.loading')}</div>
            ) : periodOverviewQuery.isError ? (
                <div className="card error-banner">{t('pages.invoices.failed')}</div>
            ) : rows.length === 0 ? (
                <InvoicesEmptyState />
            ) : (
                <>
                    {/* Defense-in-depth: the /invoices route is already
                        owner/admin-only, but keep batch actions hidden from
                        participant/guest roles even if routing changes. */}
                    {isOwnerOrAdmin && (
                        <InvoiceBatchToolbar
                            stats={batchStats}
                            recommendedAction={recommendedBatchAction}
                            menuItems={batchMenuItems}
                            anyBatchPending={anyBatchPending}
                            pdfCount={stats.pdfCount}
                            onDownloadAll={() => downloadAllPdfsMutation.mutate()}
                        />
                    )}

                    {isWaitingForPdfs && (
                        <p className="muted" role="status" aria-live="polite">
                            {t('pages.invoices.pdfsGenerating', { n: pendingPdfCount })}
                        </p>
                    )}

                    <InvoicePeriodRowsTable
                        rows={rows}
                        period={period}
                        onOpenEmailLogs={handleOpenEmailLogs}
                        getPrimaryRowAction={getPrimaryRowAction}
                        getRowMenuItems={getRowMenuItems}
                        isPdfPending={isPdfPending}
                    />
                </>
            )}

            <InvoiceDeleteModal
                isOpen={deleteModalInvoiceId !== null}
                isPending={deleteMutation.isPending}
                onCancel={() => setDeleteModalInvoiceId(null)}
                onConfirm={() => {
                    if (!deleteModalInvoiceId) return
                    deleteMutation.mutate(deleteModalInvoiceId, {
                        onSuccess: () => setDeleteModalInvoiceId(null),
                    })
                }}
            />

            <EmailLogsModal
                invoiceNumber={selectedInvoiceNumber}
                emailLogs={selectedEmailLogs}
                isOpen={showEmailModal}
                onClose={() => setShowEmailModal(false)}
                onRetry={(emailLogId) => {
                    const currentInvoiceId = rows
                        .map((row) => row.invoice)
                        .find((invoice) => invoice?.invoice_number === selectedInvoiceNumber)?.id
                    if (currentInvoiceId) {
                        handleRetryEmail(currentInvoiceId, emailLogId)
                    }
                }}
                isRetrying={retiringEmailId !== null}
            />
        </div>
    )
}
