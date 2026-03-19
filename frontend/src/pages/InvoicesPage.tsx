import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
    approveInvoice,
    deleteInvoice,
    fetchEmailLogs,
    fetchInvoice,
    fetchInvoicePeriodOverview,
    formatApiError,
    generateInvoice,
    generateInvoicePdf,
    markInvoicePaid,
    retryFailedEmail,
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
        if (!selectedZev) {
            setPeriod({ period_start: '', period_end: '' })
            return
        }
        const start = startOfBillingPeriod(new Date(), interval)
        setPeriod({
            period_start: toIsoDate(start),
            period_end: toIsoDate(endOfBillingPeriod(start, interval)),
        })
    }, [selectedZev?.id, interval])

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

    if (!selectedZevId) {
        return (
            <div className="page-stack">
                <header>
                    <h2>Invoices</h2>
                    <p className="muted">Select a ZEV in the global selector to manage billing periods and invoices.</p>
                </header>
            </div>
        )
    }

    return (
        <div className="page-stack">
            <header>
                <h2>Invoices</h2>
                <p className="muted">Period-based invoicing for the selected ZEV using its configured billing interval.</p>
            </header>

            <section className="card" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem' }}>
                <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => setPeriod((prev) => shiftBillingPeriod(prev.period_start, interval, -1))}
                    disabled={!period.period_start}
                >
                    ← Previous period
                </button>
                <div style={{ textAlign: 'center' }}>
                    <div style={{ fontWeight: 700 }}>{selectedZev?.name}</div>
                    <div className="muted" style={{ fontSize: '0.95rem' }}>
                        {period.period_start && period.period_end
                            ? `${formatShortDate(period.period_start, settings)} → ${formatShortDate(period.period_end, settings)}`
                            : '—'}
                    </div>
                    <div className="muted" style={{ fontSize: '0.85rem' }}>Billing interval: {interval.replace('_', ' ')}</div>
                </div>
                <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => setPeriod((prev) => shiftBillingPeriod(prev.period_start, interval, 1))}
                    disabled={!period.period_start}
                >
                    Next period →
                </button>
            </section>

            {periodOverviewQuery.isLoading ? (
                <div className="card">Loading period overview…</div>
            ) : periodOverviewQuery.isError ? (
                <div className="card error-banner">Failed to load period overview.</div>
            ) : (
                <div className="table-card">
                    <table>
                        <thead>
                            <tr>
                                <th>Participant</th>
                                <th>Metering data</th>
                                <th>Invoice</th>
                                <th>Status</th>
                                <th>Email</th>
                                <th>Total</th>
                                <th>PDF</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.length ? rows.map((row) => {
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
                                                <span className="badge badge-success">Complete</span>
                                            ) : (
                                                <>
                                                    <span className="badge badge-danger">Missing</span>
                                                    <div className="muted" style={{ fontSize: '0.85rem' }}>
                                                        {row.metering_points_with_data}/{row.metering_points_total} points with data
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
                                        <td>{invoice ? invoice.invoice_number : <span className="muted">Not created</span>}</td>
                                        <td>
                                            {invoice ? (
                                                <span className={invoiceStatusBadgeClass(invoice.status)}>{humanizeStatus(invoice.status)}</span>
                                            ) : (
                                                <span className="badge badge-neutral">Not created</span>
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
                                                                ({invoice.email_logs?.filter((log) => log.status === 'failed').length} failed)
                                                            </span>
                                                        )}
                                                    </div>
                                                    {(invoice.email_logs?.length ?? 0) > 1 && (
                                                        <div className="muted" style={{ fontSize: '0.85rem' }}>
                                                            {invoice.email_logs?.length} attempts
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
                                                            Open PDF
                                                        </a>
                                                        <button
                                                            className="button"
                                                            type="button"
                                                            disabled={pdfMutation.isPending}
                                                            onClick={() => pdfMutation.mutate(invoice.id)}
                                                        >
                                                            Regenerate
                                                        </button>
                                                    </div>
                                                ) : (
                                                    <button
                                                        className="button"
                                                        type="button"
                                                        disabled={pdfMutation.isPending}
                                                        onClick={() => pdfMutation.mutate(invoice.id)}
                                                    >
                                                        Generate PDF
                                                    </button>
                                                )
                                            ) : (
                                                <span className="muted">—</span>
                                            )}
                                        </td>
                                        <td>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
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
                                                    {invoice ? 'Generate again' : 'Generate invoice'}
                                                </button>
                                                {invoice && (
                                                    <Link className="button" style={{ textDecoration: 'none' }} to={`/invoices/${invoice.id}`}>
                                                        Open details
                                                    </Link>
                                                )}
                                                {invoice && invoice.status === 'draft' && (
                                                    <button
                                                        className="button"
                                                        type="button"
                                                        disabled={approveMutation.isPending}
                                                        onClick={() => approveMutation.mutate(invoice.id)}
                                                    >
                                                        Approve
                                                    </button>
                                                )}
                                                {invoice && (invoice.status === 'draft' || invoice.status === 'cancelled' || user?.role === 'admin') && (
                                                    <button
                                                        className="button button-danger"
                                                        type="button"
                                                        disabled={deleteMutation.isPending}
                                                        onClick={() => setDeleteModalInvoiceId(invoice.id)}
                                                    >
                                                        Delete
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
                                                        {pollingInvoiceId === invoice.id ? 'Sending...' : invoice.status === 'sent' ? 'Resend Email' : 'Send Email'}
                                                    </button>
                                                )}
                                                {invoice && (invoice.status === 'approved' || invoice.status === 'sent') && (
                                                    <button
                                                        className="button"
                                                        type="button"
                                                        disabled={markPaidMutation.isPending}
                                                        onClick={() => markPaidMutation.mutate(invoice.id)}
                                                    >
                                                        Mark Paid
                                                    </button>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                )
                            }) : (
                                <tr>
                                    <td colSpan={8}>No participants found for this period.</td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
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
                        <h2 style={{ margin: '0 0 1rem 0', color: '#dc2626' }}>Delete Invoice</h2>
                        <p style={{ margin: '0 0 1.5rem 0', color: '#374151' }}>
                            Are you sure you want to delete this invoice? This action cannot be undone.
                        </p>
                        <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
                            <button
                                className="button button-secondary"
                                type="button"
                                disabled={deleteMutation.isPending}
                                onClick={() => setDeleteModalInvoiceId(null)}
                            >
                                Cancel
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
                                {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
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
