import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { InvoicePeriodRowsTable } from '../features/invoices/InvoicePeriodRowsTable'
import { InvoiceBatchToolbar } from '../features/invoices/InvoiceBatchToolbar'
import { InvoiceDeleteModal } from '../features/invoices/InvoiceDeleteModal'
import { InvoicesEmptyState } from '../features/invoices/InvoicesEmptyState'
import { useInvoiceActions } from '../features/invoices/useInvoiceActions'
import { PeriodSelector } from '../components/PeriodSelector'
import { getPreviousBillingPeriod, type BillingInterval } from '../lib/billingPeriod'
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

    const interval: BillingInterval = (selectedZev?.billing_interval as BillingInterval) ?? 'monthly'

    const [period, setPeriod] = useState<{ period_start: string; period_end: string }>({
        period_start: '',
        period_end: '',
    })

    const [deleteModalInvoiceId, setDeleteModalInvoiceId] = useState<string | null>(null)
    const [selectedEmailLogs, setSelectedEmailLogs] = useState<EmailLog[]>([])
    const [showEmailModal, setShowEmailModal] = useState(false)
    const [selectedInvoiceNumber, setSelectedInvoiceNumber] = useState('')

    useEffect(() => {
        if (!selectedZevId) {
            setPeriod({ period_start: '', period_end: '' })
            return
        }
        // The last *complete* period, not the current one: invoices can only be
        // generated once a period has ended, so opening on the running period
        // shows an empty table and makes every billing run start by stepping back.
        const billable = getPreviousBillingPeriod(interval)
        setPeriod({ period_start: billable.from, period_end: billable.to })
    }, [selectedZevId, interval])

    const periodOverviewQuery = useQuery({
        queryKey: queryKeys.invoices.periodOverview(selectedZevId, period.period_start, period.period_end),
        queryFn: () =>
            fetchInvoicePeriodOverview({
                zev_id: selectedZevId,
                period_start: period.period_start,
                period_end: period.period_end,
            }),
        enabled: !!selectedZevId && !!period.period_start && !!period.period_end,
        refetchInterval: false,
        refetchIntervalInBackground: true,
    })

    const rows = periodOverviewQuery.data?.rows ?? []

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
    } = useInvoiceActions({
        selectedZevId,
        period,
        rows,
        userRole: user?.role,
        onOpenEmailLogs: handleOpenEmailLogs,
        onDeleteClick: (invoiceId) => setDeleteModalInvoiceId(invoiceId),
    })

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
                    onChange={({ from, to }) => setPeriod({ period_start: from, period_end: to })}
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

                    <InvoicePeriodRowsTable
                        rows={rows}
                        onOpenEmailLogs={handleOpenEmailLogs}
                        getPrimaryRowAction={getPrimaryRowAction}
                        getRowMenuItems={getRowMenuItems}
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
