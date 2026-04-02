import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
    approveAllInvoices,
    approveInvoice,
    deleteInvoice,
    downloadAllPdfs,
    fetchEmailLogs,
    fetchInvoice,
    fetchInvoicePeriodOverview,
    formatApiError,
    generateAllPdfs,
    generateInvoice,
    generateInvoicePdf,
    generateInvoicesForZev,
    markInvoicePaid,
    markInvoiceSent,
    retryFailedEmail,
    sendAllInvoices,
    sendInvoiceEmail,
} from '../lib/api'
import { EmailLogsModal } from '../components/EmailLogsModal'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { useToast } from '../lib/toast'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import type { EmailLog } from '../types/api'

type BillingInterval = 'monthly' | 'quarterly' | 'semi_annual' | 'annual'

function invoiceStatusBadgeClass(status: string): string {
    if (status === 'paid') return 'badge badge-success'
    if (status === 'cancelled') return 'badge badge-danger'
    if (status === 'approved' || status === 'sent') return 'badge badge-info'
    return 'badge badge-neutral'
}

function emailStatusBadgeClass(status: string): string {
    if (status === 'sent') return 'badge badge-success'
    if (status === 'failed') return 'badge badge-danger'
    return 'badge badge-neutral'
}

function humanizeStatus(status: string): string {
    return status.replace('_', ' ').replace(/^./, (char) => char.toUpperCase())
}

function getLatestEmailLog(invoice: { email_logs?: Array<{ created_at: string; recipient: string; status: string; id: string }> } | null) {
    if (!invoice?.email_logs?.length) return null
    return [...invoice.email_logs].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0]
}

function toIsoDate(date: Date): string {
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
}

function startOfBillingPeriod(today: Date, interval: BillingInterval): Date {
    const year = today.getFullYear()
    const month = today.getMonth()

    if (interval === 'monthly') return new Date(year, month, 1)
    if (interval === 'quarterly') return new Date(year, Math.floor(month / 3) * 3, 1)
    if (interval === 'semi_annual') return new Date(year, month < 6 ? 0 : 6, 1)
    return new Date(year, 0, 1)
}

function endOfBillingPeriod(start: Date, interval: BillingInterval): Date {
    const monthsToAdd = interval === 'monthly' ? 1 : interval === 'quarterly' ? 3 : interval === 'semi_annual' ? 6 : 12
    const nextStart = new Date(start.getFullYear(), start.getMonth() + monthsToAdd, 1)
    return new Date(nextStart.getFullYear(), nextStart.getMonth(), 0)
}

function shiftBillingPeriod(startIso: string, interval: BillingInterval, direction: -1 | 1): { period_start: string; period_end: string } {
    const start = new Date(`${startIso}T00:00:00`)
    const monthsToShift = (interval === 'monthly' ? 1 : interval === 'quarterly' ? 3 : interval === 'semi_annual' ? 6 : 12) * direction
    const shiftedStart = new Date(start.getFullYear(), start.getMonth() + monthsToShift, 1)
    return {
        period_start: toIsoDate(shiftedStart),
        period_end: toIsoDate(endOfBillingPeriod(shiftedStart, interval)),
    }
}

export function InvoicesPage() {
    const EMAIL_STATUS_POLL_TIMEOUT_MS = 90_000
    const { t } = useTranslation()
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { settings } = useAppSettings()
    const { selectedZevId, selectedZev } = useManagedZev()
    const { user } = useAuth()

    const interval: BillingInterval = (selectedZev?.billing_interval as BillingInterval) ?? 'monthly'

    const [period, setPeriod] = useState<{ period_start: string; period_end: string }>({
        period_start: '',
        period_end: '',
    })

    const [pollingInvoiceId, setPollingInvoiceId] = useState<string | null>(null)
    const [emailPollingStartedAt, setEmailPollingStartedAt] = useState<number | null>(null)
    const [deleteModalInvoiceId, setDeleteModalInvoiceId] = useState<string | null>(null)
    const [selectedEmailLogs, setSelectedEmailLogs] = useState<EmailLog[]>([])
    const [showEmailModal, setShowEmailModal] = useState(false)
    const [selectedInvoiceNumber, setSelectedInvoiceNumber] = useState('')
    const [retiringEmailId, setRetiringEmailId] = useState<string | null>(null)

    useEffect(() => {
        if (!selectedZevId) {
            setPeriod({ period_start: '', period_end: '' })
            return
        }
        const start = startOfBillingPeriod(new Date(), interval)
        setPeriod({
            period_start: toIsoDate(start),
            period_end: toIsoDate(endOfBillingPeriod(start, interval)),
        })
    }, [selectedZevId, interval])

    const periodOverviewQuery = useQuery({
        queryKey: ['invoice-period-overview', selectedZevId, period.period_start, period.period_end],
        queryFn: () =>
            fetchInvoicePeriodOverview({
                zev_id: selectedZevId,
                period_start: period.period_start,
                period_end: period.period_end,
            }),
        enabled: !!selectedZevId && !!period.period_start && !!period.period_end,
        refetchInterval: pollingInvoiceId ? 2500 : false,
        refetchIntervalInBackground: true,
    })

    const generateMutation = useMutation({
        mutationFn: generateInvoice,
        onSuccess: () => {
            pushToast('Invoice generated.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoice-period-overview'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to generate invoice.'), 'error'),
    })

    const pdfMutation = useMutation({
        mutationFn: generateInvoicePdf,
        onSuccess: () => {
            pushToast('PDF generated.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoice-period-overview'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to generate PDF.'), 'error'),
    })

    const approveMutation = useMutation({
        mutationFn: approveInvoice,
        onSuccess: () => {
            pushToast('Invoice approved.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoice-period-overview'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to approve invoice.'), 'error'),
    })

    const deleteMutation = useMutation({
        mutationFn: deleteInvoice,
        onSuccess: () => {
            pushToast('Invoice deleted.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoice-period-overview'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to delete invoice.'), 'error'),
    })

    const emailMutation = useMutation({
        mutationFn: (invoiceId: string) => sendInvoiceEmail(invoiceId),
        onSuccess: (_result, invoiceId) => {
            pushToast('Email queued for sending.', 'success')
            setPollingInvoiceId(invoiceId)
            setEmailPollingStartedAt(Date.now())
            void queryClient.invalidateQueries({ queryKey: ['invoice-period-overview'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to send email.'), 'error'),
    })

    const markSentMutation = useMutation({
        mutationFn: markInvoiceSent,
        onSuccess: () => {
            pushToast(t('pages.invoices.markedSent'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoice-period-overview'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to mark invoice as sent.'), 'error'),
    })

    const markPaidMutation = useMutation({
        mutationFn: markInvoicePaid,
        onSuccess: () => {
            pushToast('Invoice marked as paid.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoice-period-overview'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to mark invoice as paid.'), 'error'),
    })

    const retryEmailMutation = useMutation({
        mutationFn: (params: { invoiceId: string; emailLogId: string }) =>
            retryFailedEmail(params.invoiceId, params.emailLogId),
        onSuccess: (_result, variables) => {
            pushToast('Email retry queued.', 'success')
            setPollingInvoiceId(variables.invoiceId)
            setEmailPollingStartedAt(Date.now())
            void queryClient.invalidateQueries({ queryKey: ['invoice-period-overview'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to retry email.'), 'error'),
    })

    // ── Batch mutations ──────────────────────────────────────────────

    const batchPayload = { zev_id: selectedZevId, period_start: period.period_start, period_end: period.period_end }

    const generateAllMutation = useMutation({
        mutationFn: () => generateInvoicesForZev(batchPayload),
        onSuccess: (invoices) => {
            pushToast(t('pages.invoices.batch.generatedAll', { n: invoices.length }), 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoice-period-overview'] })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.batch.generateAllFailed')), 'error'),
    })

    const approveAllMutation = useMutation({
        mutationFn: () => approveAllInvoices(batchPayload),
        onSuccess: (result) => {
            pushToast(t('pages.invoices.batch.approvedAll', { n: result.approved }), 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoice-period-overview'] })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.batch.approveAllFailed')), 'error'),
    })

    const sendAllMutation = useMutation({
        mutationFn: () => sendAllInvoices(batchPayload),
        onSuccess: (result) => {
            const msg = result.skipped > 0
                ? t('pages.invoices.batch.sentAllWithSkipped', { queued: result.queued, skipped: result.skipped })
                : t('pages.invoices.batch.sentAll', { n: result.queued })
            pushToast(msg, 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoice-period-overview'] })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.batch.sendAllFailed')), 'error'),
    })

    const generateAllPdfsMutation = useMutation({
        mutationFn: () => generateAllPdfs(batchPayload),
        onSuccess: (result) => {
            pushToast(t('pages.invoices.batch.generatedAllPdfs', { n: result.generated }), 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoice-period-overview'] })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.batch.generateAllPdfsFailed')), 'error'),
    })

    const downloadAllPdfsMutation = useMutation({
        mutationFn: () => downloadAllPdfs(batchPayload),
        onSuccess: (blob) => {
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = `invoices-${period.period_start}.zip`
            document.body.appendChild(a)
            a.click()
            document.body.removeChild(a)
            URL.revokeObjectURL(url)
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.batch.downloadFailed')), 'error'),
    })

    const anyBatchPending = generateAllMutation.isPending || approveAllMutation.isPending || sendAllMutation.isPending || generateAllPdfsMutation.isPending || downloadAllPdfsMutation.isPending

    // Polling effect for email status
    useEffect(() => {
        if (!pollingInvoiceId || !emailPollingStartedAt) return

        let pollCount = 0
        const maxPolls = 15 // 15 * 2 seconds = 30 seconds max

        const pollInterval = setInterval(async () => {
            pollCount++

            try {
                const invoice = await fetchInvoice(pollingInvoiceId)
                const lastEmailLog = getLatestEmailLog(invoice)
                const logTime = lastEmailLog?.created_at ? new Date(lastEmailLog.created_at).getTime() : 0
                const relatesToCurrentAttempt = !!lastEmailLog && logTime >= emailPollingStartedAt - 1000

                // Stop polling if this attempt has a final email status
                if (relatesToCurrentAttempt && (lastEmailLog.status === 'sent' || lastEmailLog.status === 'failed')) {
                    setPollingInvoiceId(null)
                    setEmailPollingStartedAt(null)
                    void queryClient.invalidateQueries({ queryKey: ['invoice-period-overview'] })
                    if (lastEmailLog.status === 'sent') {
                        pushToast('Email sent successfully!', 'success')
                    }
                    clearInterval(pollInterval)
                    return
                }

                // Stop if max polls reached
                if (pollCount >= maxPolls) {
                    setPollingInvoiceId(null)
                    setEmailPollingStartedAt(null)
                    pushToast('Email was queued, but status update is taking longer than expected.', 'error')
                    clearInterval(pollInterval)
                    return
                }

                // Update the query cache with the latest invoice data
                void queryClient.invalidateQueries({ queryKey: ['invoice-period-overview'] })
            } catch (error) {
                console.error('Error polling invoice status:', error)
            }
        }, 2000) // Poll every 2 seconds

        return () => clearInterval(pollInterval)
    }, [pollingInvoiceId, emailPollingStartedAt, queryClient, pushToast])

    useEffect(() => {
        if (!pollingInvoiceId || !emailPollingStartedAt) return
        const timeoutId = window.setTimeout(() => {
            setPollingInvoiceId(null)
            setEmailPollingStartedAt(null)
            pushToast('Email was queued, but status update is taking longer than expected.', 'error')
        }, EMAIL_STATUS_POLL_TIMEOUT_MS)

        return () => {
            window.clearTimeout(timeoutId)
        }
    }, [pollingInvoiceId, emailPollingStartedAt, pushToast])

    async function openEmailLogs(invoiceId: string, invoiceNumber: string) {
        try {
            const logs = await fetchEmailLogs(invoiceId)
            setSelectedEmailLogs(logs)
            setSelectedInvoiceNumber(invoiceNumber)
            setShowEmailModal(true)
        } catch {
            pushToast('Failed to load email logs.', 'error')
        }
    }

    function handleRetryEmail(invoiceId: string, emailLogId: string) {
        setRetiringEmailId(emailLogId)
        retryEmailMutation.mutate(
            { invoiceId, emailLogId },
            {
                onSettled: () => setRetiringEmailId(null),
            },
        )
    }

    const rows = useMemo(() => periodOverviewQuery.data?.rows ?? [], [periodOverviewQuery.data?.rows])

    const draftCount = useMemo(() => rows.filter((r) => r.invoice?.status === 'draft').length, [rows])
    const approvedCount = useMemo(() => rows.filter((r) => r.invoice?.status === 'approved').length, [rows])
    const invoiceCount = useMemo(() => rows.filter((r) => r.invoice).length, [rows])
    const pdfCount = useMemo(() => rows.filter((r) => r.invoice?.pdf_url).length, [rows])
    const isOwnerOrAdmin = user?.role === 'admin' || user?.role === 'zev_owner'

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

            <section className="card" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem' }}>
                <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => setPeriod((prev) => shiftBillingPeriod(prev.period_start, interval, -1))}
                    disabled={!period.period_start}
                >
                    {t('pages.invoices.prevPeriod')}
                </button>
                <div style={{ textAlign: 'center' }}>
                    <div style={{ fontWeight: 700 }}>{selectedZev?.name}</div>
                    <div className="muted" style={{ fontSize: '0.95rem' }}>
                        {period.period_start && period.period_end
                            ? `${formatShortDate(period.period_start, settings)} → ${formatShortDate(period.period_end, settings)}`
                            : '—'}
                    </div>
                    <div className="muted" style={{ fontSize: '0.85rem' }}>{t('pages.invoices.billingInterval')} {interval.replace('_', ' ')}</div>
                </div>
                <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => setPeriod((prev) => shiftBillingPeriod(prev.period_start, interval, 1))}
                    disabled={!period.period_start}
                >
                    {t('pages.invoices.nextPeriod')}
                </button>
            </section>

            {periodOverviewQuery.isLoading ? (
                <div className="card">{t('pages.invoices.loading')}</div>
            ) : periodOverviewQuery.isError ? (
                <div className="card error-banner">{t('pages.invoices.failed')}</div>
            ) : rows.length === 0 ? (
                <section className="card" style={{ display: 'grid', gap: '0.75rem' }}>
                    <h3 style={{ margin: 0 }}>{t('pages.invoices.emptyState.title')}</h3>
                    <p className="muted" style={{ margin: 0 }}>{t('pages.invoices.emptyState.description')}</p>
                    <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                        <Link className="button button-primary" to="/participants" style={{ textDecoration: 'none' }}>
                            {t('pages.invoices.emptyState.participantsAction')}
                        </Link>
                        <Link className="button button-secondary" to="/metering-points" style={{ textDecoration: 'none' }}>
                            {t('pages.invoices.emptyState.meteringPointsAction')}
                        </Link>
                        <Link className="button button-secondary" to="/tariffs" style={{ textDecoration: 'none' }}>
                            {t('pages.invoices.emptyState.tariffsAction')}
                        </Link>
                    </div>
                </section>
            ) : (
                <>
                {isOwnerOrAdmin && (
                    <section className="card" style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
                        <span style={{ fontWeight: 600, marginRight: '0.5rem' }}>{t('pages.invoices.batch.title')}</span>
                        <button
                            className="button button-primary"
                            type="button"
                            disabled={anyBatchPending}
                            onClick={() => generateAllMutation.mutate()}
                        >
                            {t('pages.invoices.batch.generateAll')}
                        </button>
                        <button
                            className="button"
                            type="button"
                            disabled={anyBatchPending || invoiceCount === 0}
                            onClick={() => generateAllPdfsMutation.mutate()}
                        >
                            {t('pages.invoices.batch.generateAllPdfs')} {invoiceCount > 0 && `(${invoiceCount})`}
                        </button>
                        <button
                            className="button"
                            type="button"
                            disabled={anyBatchPending || draftCount === 0}
                            onClick={() => approveAllMutation.mutate()}
                        >
                            {t('pages.invoices.batch.approveAll')} {draftCount > 0 && `(${draftCount})`}
                        </button>
                        <button
                            className="button"
                            type="button"
                            disabled={anyBatchPending || approvedCount === 0}
                            onClick={() => sendAllMutation.mutate()}
                        >
                            {t('pages.invoices.batch.sendAll')} {approvedCount > 0 && `(${approvedCount})`}
                        </button>
                        <button
                            className="button button-secondary"
                            type="button"
                            disabled={anyBatchPending || pdfCount === 0}
                            onClick={() => downloadAllPdfsMutation.mutate()}
                        >
                            {t('pages.invoices.batch.downloadAll')} {pdfCount > 0 && `(${pdfCount})`}
                        </button>
                    </section>
                )}
                <div className="table-card">
                    <table>
                        <thead>
                            <tr>
                                <th>{t('pages.invoices.col.participant')}</th>
                                <th>{t('pages.invoices.col.meteringData')}</th>
                                <th>{t('pages.invoices.col.invoice')}</th>
                                <th>{t('pages.invoices.col.status')}</th>
                                <th>{t('pages.invoices.col.email')}</th>
                                <th>{t('pages.invoices.col.total')}</th>
                                <th>{t('pages.invoices.col.pdf')}</th>
                                <th>{t('pages.invoices.col.actions')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((row) => {
                                const invoice = row.invoice
                                const latestEmailLog = getLatestEmailLog(invoice)
                                return (
                                    <tr key={row.participant_id}>
                                        <td>
                                            <strong>{row.participant_name}</strong>
                                            {row.participant_email ? <div className="muted">{row.participant_email}</div> : null}
                                        </td>
                                        <td>
                                            {row.metering_data_complete ? (
                                                <span className="badge badge-success">{t('pages.invoices.metering.complete')}</span>
                                            ) : (
                                                <>
                                                    <span className="badge badge-danger">{t('pages.invoices.metering.missing')}</span>
                                                    <div className="muted" style={{ fontSize: '0.85rem' }}>
                                                        {t('pages.invoices.metering.pointsWithData', { n: row.metering_points_with_data, total: row.metering_points_total })}
                                                    </div>
                                                    {row.missing_meter_ids.length > 0 && (
                                                        <div className="muted" style={{ fontSize: '0.8rem' }}>
                                                            Missing: {
                                                                row.missing_meter_details?.length
                                                                    ? row.missing_meter_details
                                                                        .map((item) => `${item.meter_id} (${item.missing_days} day${item.missing_days === 1 ? '' : 's'})`)
                                                                        .join(', ')
                                                                    : row.missing_meter_ids.join(', ')
                                                            }
                                                        </div>
                                                    )}
                                                </>
                                            )}
                                        </td>
                                        <td>{invoice ? invoice.invoice_number : <span className="muted">{t('pages.invoices.notCreated')}</span>}</td>
                                        <td>
                                            {invoice ? (
                                                <span className={invoiceStatusBadgeClass(invoice.status)}>{humanizeStatus(invoice.status)}</span>
                                            ) : (
                                                <span className="badge badge-neutral">{t('pages.invoices.notCreated')}</span>
                                            )}
                                        </td>
                                        <td>
                                            {invoice && latestEmailLog ? (
                                                <>
                                                    <span className={emailStatusBadgeClass(latestEmailLog.status)}>
                                                        {humanizeStatus(latestEmailLog.status)}
                                                    </span>
                                                    <div style={{ marginTop: '0.3rem' }}>
                                                        <button
                                                            className="button button-secondary"
                                                            style={{ fontSize: '0.75rem', padding: '0.3rem 0.5rem' }}
                                                            type="button"
                                                            onClick={() => openEmailLogs(invoice.id, invoice.invoice_number)}
                                                        >
                                                            {invoice.email_logs?.filter((log) => log.status === 'sent').length ?? 0}/{invoice.email_logs?.length ?? 0}
                                                        </button>
                                                        {(invoice.email_logs?.filter((log) => log.status === 'failed').length ?? 0) > 0 && (
                                                            <span style={{ color: '#ef4444', marginLeft: '0.3rem', fontSize: '0.85rem', fontWeight: 'bold' }}>
                                                                {t('pages.invoices.failedEmails', { n: invoice.email_logs?.filter((log) => log.status === 'failed').length })}
                                                            </span>
                                                        )}
                                                    </div>
                                                    {(invoice.email_logs?.length ?? 0) > 1 && (
                                                        <div className="muted" style={{ fontSize: '0.85rem' }}>
                                                            {t('pages.invoices.attempts', { n: invoice.email_logs?.length })}
                                                        </div>
                                                    )}
                                                </>
                                            ) : (
                                                <span className="muted">—</span>
                                            )}
                                        </td>
                                        <td>{invoice ? `CHF ${invoice.total_chf}` : <span className="muted">—</span>}</td>
                                        <td>
                                            {invoice ? (
                                                invoice.pdf_url ? (
                                                    <div style={{ display: 'flex', gap: '0.35rem' }}>
                                                        <a
                                                            href={invoice.pdf_url}
                                                            target="_blank"
                                                            rel="noreferrer"
                                                            className="button button-primary"
                                                            style={{ textDecoration: 'none', padding: '0.3rem 0.5rem' }}
                                                        >
                                                            {t('pages.invoices.openPdf')}
                                                        </a>
                                                        <button
                                                            className="button"
                                                            type="button"
                                                            disabled={pdfMutation.isPending}
                                                            onClick={() => pdfMutation.mutate(invoice.id)}
                                                        >
                                                            {t('pages.invoices.regenerate')}
                                                        </button>
                                                    </div>
                                                ) : (
                                                    <button
                                                        className="button"
                                                        type="button"
                                                        disabled={pdfMutation.isPending}
                                                        onClick={() => pdfMutation.mutate(invoice.id)}
                                                    >
                                                        {t('pages.invoices.generatePdf')}
                                                    </button>
                                                )
                                            ) : (
                                                <span className="muted">—</span>
                                            )}
                                        </td>
                                        <td>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                                                {(!invoice || invoice.status === 'draft' || invoice.status === 'cancelled') && (
                                                    <button
                                                        className="button button-primary"
                                                        type="button"
                                                        disabled={generateMutation.isPending}
                                                        onClick={() =>
                                                            generateMutation.mutate({
                                                                participant_id: row.participant_id,
                                                                period_start: period.period_start,
                                                                period_end: period.period_end,
                                                            })
                                                        }
                                                    >
                                                        {invoice ? t('pages.invoices.generateAgain') : t('pages.invoices.generateInvoice')}
                                                    </button>
                                                )}
                                                {invoice && (
                                                    <Link className="button" style={{ textDecoration: 'none' }} to={`/invoices/${invoice.id}`}>
                                                        {t('pages.invoices.openDetails')}
                                                    </Link>
                                                )}
                                                {invoice && invoice.status === 'draft' && (
                                                    <button
                                                        className="button"
                                                        type="button"
                                                        disabled={approveMutation.isPending}
                                                        onClick={() => approveMutation.mutate(invoice.id)}
                                                    >
                                                        {t('pages.invoices.approve')}
                                                    </button>
                                                )}
                                                {invoice && (invoice.status === 'draft' || invoice.status === 'cancelled' || user?.role === 'admin') && (
                                                    <button
                                                        className="button button-danger"
                                                        type="button"
                                                        disabled={deleteMutation.isPending}
                                                        onClick={() => setDeleteModalInvoiceId(invoice.id)}
                                                    >
                                                        {t('pages.invoices.delete')}
                                                    </button>
                                                )}
                                                {invoice && invoice.status === 'approved' && (
                                                    <button
                                                        className="button"
                                                        type="button"
                                                        disabled={markSentMutation.isPending}
                                                        onClick={() => markSentMutation.mutate(invoice.id)}
                                                    >
                                                        {t('pages.invoices.markSent')}
                                                    </button>
                                                )}
                                                {invoice && (invoice.status === 'approved' || invoice.status === 'sent') && (
                                                    <button
                                                        className="button"
                                                        type="button"
                                                        disabled={emailMutation.isPending || pollingInvoiceId === invoice.id}
                                                        onClick={() => {
                                                            emailMutation.mutate(invoice.id)
                                                        }}
                                                    >
                                                        {pollingInvoiceId === invoice.id ? t('pages.invoices.sending') : invoice.status === 'sent' ? t('pages.invoices.resendEmail') : t('pages.invoices.sendEmail')}
                                                    </button>
                                                )}
                                                {invoice && invoice.status === 'sent' && (
                                                    <button
                                                        className="button"
                                                        type="button"
                                                        disabled={markPaidMutation.isPending}
                                                        onClick={() => markPaidMutation.mutate(invoice.id)}
                                                    >
                                                        {t('pages.invoices.markPaid')}
                                                    </button>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                )
                            })}
                        </tbody>
                    </table>
                </div>
                </>
            )}

            {/* Delete Confirmation Modal */}
            {deleteModalInvoiceId && (
                <div
                    style={{
                        position: 'fixed',
                        inset: 0,
                        backgroundColor: 'rgba(0, 0, 0, 0.5)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        zIndex: 1000,
                    }}
                    onClick={() => setDeleteModalInvoiceId(null)}
                >
                    <div
                        style={{
                            backgroundColor: 'white',
                            borderRadius: '0.5rem',
                            boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1)',
                            maxWidth: '400px',
                            width: '90%',
                            padding: '2rem',
                        }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <h2 style={{ margin: '0 0 1rem 0', color: '#dc2626' }}>{t('pages.invoices.deleteModal.title')}</h2>
                        <p style={{ margin: '0 0 1.5rem 0', color: '#374151' }}>
                            {t('pages.invoices.deleteModal.message')}
                        </p>
                        <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
                            <button
                                className="button button-secondary"
                                type="button"
                                disabled={deleteMutation.isPending}
                                onClick={() => setDeleteModalInvoiceId(null)}
                            >
                                {t('common.cancel')}
                            </button>
                            <button
                                className="button button-danger"
                                type="button"
                                disabled={deleteMutation.isPending}
                                onClick={() => {
                                    deleteMutation.mutate(deleteModalInvoiceId, {
                                        onSuccess: () => setDeleteModalInvoiceId(null),
                                    })
                                }}
                            >
                                {deleteMutation.isPending ? t('pages.invoices.deleting') : t('pages.invoices.delete')}
                            </button>
                        </div>
                    </div>
                </div>
            )}

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
