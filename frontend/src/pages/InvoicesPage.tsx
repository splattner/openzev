import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { InvoicePeriodRowsTable } from '../features/invoices/InvoicePeriodRowsTable'
import { repeatedParties } from '../features/invoices/invoiceRowState'
import { InvoiceBatchActions } from '../features/invoices/InvoiceBatchActions'
import { InvoiceRowFilterTabs } from '../features/invoices/InvoiceRowFilterTabs'
import { InvoiceDeleteModal } from '../features/invoices/InvoiceDeleteModal'
import { InvoicesEmptyState } from '../features/invoices/InvoicesEmptyState'
import { useInvoiceActions } from '../features/invoices/useInvoiceActions'
import {
    countPendingInvoiceWork,
    pdfWatchIsFinished,
    pdfWatchRefetchInterval,
    usePdfWatch,
} from '../features/invoices/pdfWatch'
import { PeriodSelector } from '../components/PeriodSelector'
import {
    billingPeriodName,
    alignedPeriodEndingWith,
    firstAlignedBillingPeriod,
    isBillingAlignedPeriod,
    type BillingInterval,
} from '../lib/billingPeriod'
import { useBillingPeriodParams } from '../lib/useBillingPeriodParams'
import { filterInvoiceRows, type InvoiceRowFilter } from '../features/invoices/invoiceRowFilters'
import { fetchInvoicePeriodOverview } from '../lib/api/invoices'
import { queryKeys } from '../lib/api/queryKeys'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { useCommunityAccess, useScopeNote } from '../lib/communityAccess'
import { PageHeader } from '../components/PageHeader'
import { Notice } from '../components/Notice'
import { PageSkeleton } from '../components/PageSkeleton'
import { ScopeGuard } from '../components/ScopeGuard'

const READ_ONLY_ROW_ITEMS = new Set(['review-conflict', 'open-pdf'])
/** Actions that create invoices: offered for whole billing periods only. */
const GENERATING_ITEMS = new Set(['generate', 'generate-again', 'generate-all'])

export function InvoicesPage() {
    const { t } = useTranslation()
    const scopeNote = useScopeNote()
    const { selectedZev } = useManagedZev()
    return (
        <div className="page-stack">
            <PageHeader
                eyebrow={selectedZev?.name}
                communitySwitch
                scopeNote={scopeNote}
                title={t('pages.invoices.title')}
                description={t('pages.invoices.description')}
            />
            <InvoicesContent />
        </div>
    )
}

/** Period-scoped billing body; its standalone page or hub owns the header. */
export function InvoicesContent() {
    const { t, i18n } = useTranslation()
    const { selectedZevId, selectedZev } = useManagedZev()
    const { user } = useAuth()

    const interval: BillingInterval = (selectedZev?.billing_interval as BillingInterval) ?? 'monthly'
    const communityStart = selectedZev?.start_date ?? null
    const minPeriod = useMemo(
        () => firstAlignedBillingPeriod(communityStart, interval),
        [communityStart, interval],
    )

    const { period: range, setPeriod, isReady: periodReady } = useBillingPeriodParams({
        interval,
        ready: !!selectedZev,
        scopeId: selectedZevId,
        fallback: 'previous-complete',
        minimumRangeStart: communityStart,
        minimumFallback: minPeriod,
        scopeChange: 'align',
    })
    const period = { period_start: range.from, period_end: range.to }
    // Historical links keep their exact range; this page generates whole periods.
    const wholePeriod = !range.from || isBillingAlignedPeriod(range.from, range.to, interval)
    const enclosingPeriod = wholePeriod ? null : alignedPeriodEndingWith(range, interval)

    // The watch controls the overview refetch interval.
    const { pdfWatch, pdfWatchExpired, startPdfWatch, stopPdfWatch, expirePdfWatch } = usePdfWatch()
    useEffect(() => {
        stopPdfWatch()
    }, [user?.id, selectedZevId, period.period_start, period.period_end, stopPdfWatch])

    const [deleteModalInvoiceId, setDeleteModalInvoiceId] = useState<string | null>(null)
    // Row filters narrow one period of one community: never let a filter leak
    // into another period, community or account.
    const [rowFilter, setRowFilter] = useState<InvoiceRowFilter>(null)

    // A deletion dialog targets one community's invoice: never let it survive
    // an account, community, write-access, or period change.
    const { isZevScope: isManagedScope, canWriteSelectedCommunity } = useCommunityAccess()
    useEffect(() => {
        setDeleteModalInvoiceId(null)
    }, [user?.id, selectedZevId, canWriteSelectedCommunity, period.period_start, period.period_end])

    useEffect(() => {
        setRowFilter(null)
    }, [user?.id, selectedZevId, period.period_start, period.period_end])

    const periodOverviewQuery = useQuery({
        queryKey: queryKeys.invoices.periodOverview(selectedZevId, period.period_start, period.period_end),
        queryFn: () =>
            fetchInvoicePeriodOverview({
                zev_id: selectedZevId,
                period_start: period.period_start,
                period_end: period.period_end,
            }),
        enabled: periodReady && !!selectedZevId,
        // Read the query's own rows; derived state would lag a render behind.
        refetchInterval: (query) => pdfWatchRefetchInterval(pdfWatch, query.state.data?.rows ?? []),
        refetchIntervalInBackground: true,
    })

    const rows = periodOverviewQuery.data?.rows ?? []
    const pendingWorkCount = countPendingInvoiceWork(rows, pdfWatch)
    const isWaitingForPdfs = pdfWatch !== null && pendingWorkCount > 0

    const pendingWorkRef = useRef(pendingWorkCount)
    useEffect(() => {
        pendingWorkRef.current = pendingWorkCount
    }, [pendingWorkCount])

    // End the watch when every invoice has its document. A deadline that
    // passes first is reported: the work may still finish, or never will.
    useEffect(() => {
        if (!pdfWatch) return
        if (pdfWatchIsFinished(pdfWatch, pendingWorkCount, Date.now())) {
            if (pendingWorkCount > 0) expirePdfWatch()
            else stopPdfWatch()
            return
        }
        const timer = window.setTimeout(() => (pendingWorkRef.current > 0 ? expirePdfWatch() : stopPdfWatch()), pdfWatch.until - Date.now())
        return () => window.clearTimeout(timer)
    }, [pdfWatch, pendingWorkCount, stopPdfWatch, expirePdfWatch])

    const {
        deleteMutation,
        downloadAllPdfsMutation,
        anyBatchPending,
        rowCounts,
        recommendedBatchAction,
        batchMenuItems,
        getPrimaryRowAction,
        getRowMenuItems,
        getRowWork,
    } = useInvoiceActions({
        selectedZevId,
        period,
        rows,
        userRole: user?.role,
        accountId: user?.id,
        canWrite: canWriteSelectedCommunity,
        canGenerate: wholePeriod,
        generationParticipantIds: pdfWatch?.generationParticipantIds,
        onDeleteClick: (invoiceId) => setDeleteModalInvoiceId(invoiceId),
        onPdfQueued: startPdfWatch,
    })

    // Read-only accounts keep conflict review and the PDF.
    const offered = (item: { key: string }) =>
        (canWriteSelectedCommunity || READ_ONLY_ROW_ITEMS.has(item.key)) && (wholePeriod || !GENERATING_ITEMS.has(item.key))
    const primaryRowAction = (row: typeof rows[number]) => {
        const action = getPrimaryRowAction(row)
        return action && offered(action) ? action : null
    }
    const rowMenuItems = (row: Parameters<typeof getRowMenuItems>[0]) => getRowMenuItems(row).filter(offered)
    const batchAction = recommendedBatchAction && offered(recommendedBatchAction) ? recommendedBatchAction : null
    const batchItems = batchMenuItems.filter(offered)

    // The filter narrows what the table shows. Batch actions keep reading the
    // whole period (`rows`), so narrowing the view never narrows an operation.
    const visibleRows = filterInvoiceRows(rows, rowFilter, getRowWork)

    const content = (
        <div className="invoice-period-view">
            <div className="invoice-command-bar">
                <PeriodSelector
                    interval={interval}
                    from={period.period_start}
                    to={period.period_end}
                    allowCustomRange={false}
                    minFrom={minPeriod?.from}
                    onChange={setPeriod}
                    compact
                />

                {isManagedScope && rows.length > 0 && (
                    <InvoiceBatchActions
                        recommendedAction={batchAction}
                        menuItems={batchItems}
                        pdfCount={rowCounts.pdfs}
                        anyBatchPending={anyBatchPending}
                        onDownloadAll={() => downloadAllPdfsMutation.mutate()}
                    />
                )}
            </div>

            {enclosingPeriod && (
                <Notice tone="warning">
                    <p>{t('pages.invoices.unalignedPeriod.notice')}</p>
                    <div className="actions-row">
                        <button
                            type="button"
                            className="button button-secondary button-compact"
                            onClick={() => setPeriod(enclosingPeriod)}
                        >
                            {t('pages.invoices.unalignedPeriod.show', {
                                period: billingPeriodName(enclosingPeriod.from, enclosingPeriod.to, i18n.resolvedLanguage || i18n.language),
                            })}
                        </button>
                    </div>
                </Notice>
            )}

            {pdfWatchExpired && <Notice tone="warning">{t('pages.invoices.workUnresolved')}</Notice>}

            {periodOverviewQuery.isError && periodOverviewQuery.data && (
                <Notice tone="warning" onRetry={() => void periodOverviewQuery.refetch()} isRetrying={periodOverviewQuery.isFetching}>{t('pages.invoices.failed')}</Notice>
            )}
            {!period.period_start || !period.period_end || periodOverviewQuery.isLoading ? (
                <PageSkeleton variant="table" />
            ) : periodOverviewQuery.isError && !periodOverviewQuery.data ? (
                <Notice tone="error" onRetry={() => void periodOverviewQuery.refetch()} isRetrying={periodOverviewQuery.isFetching}>{t('pages.invoices.failed')}</Notice>
            ) : rows.length === 0 ? (
                <InvoicesEmptyState />
            ) : (
                <>
                    <div className="invoice-filter-bar">
                        <InvoiceRowFilterTabs counts={rowCounts} activeFilter={rowFilter} onFilterChange={setRowFilter} />
                        {rowFilter !== null && visibleRows.length > 0 && (
                            <p className="muted" role="status">
                                {t('pages.invoices.filters.showing', { shown: visibleRows.length, total: rows.length })}{' '}
                                <button type="button" className="table-inline-link" onClick={() => setRowFilter(null)}>
                                    {t('pages.invoices.filters.clear')}
                                </button>
                            </p>
                        )}
                    </div>

                    {/* One announcement for all pending rows. */}
                    <p className="visually-hidden" role="status">
                        {isWaitingForPdfs ? t('pages.invoices.workPending', { count: pendingWorkCount }) : ''}
                    </p>

                    {visibleRows.length === 0 ? (
                        <p className="muted" role="status">
                            {t('pages.invoices.filters.noMatches')}{' '}
                            <button type="button" className="table-inline-link" onClick={() => setRowFilter(null)}>
                                {t('pages.invoices.filters.clear')}
                            </button>
                        </p>
                    ) : (
                        <InvoicePeriodRowsTable
                            rows={visibleRows}
                            period={period}
                            getPrimaryRowAction={primaryRowAction}
                            getRowMenuItems={rowMenuItems}
                            getRowWork={getRowWork}
                            repeatedPartyIds={repeatedParties(rows)}
                        />
                    )}
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
        </div>
    )

    return <ScopeGuard skeleton="tableRows">{content}</ScopeGuard>
}
