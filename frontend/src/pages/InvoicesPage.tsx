import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faArrowLeft,
    faArrowRight,
    faCheck,
    faCheckDouble,
    faDownload,
    faEllipsis,
    faEnvelope,
    faFileInvoice,
    faFilePdf,
    faMoneyBillWave,
    faPaperPlane,
    faRotate,
    faTrash,
} from '@fortawesome/free-solid-svg-icons'
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
import { ActionMenu, type ActionMenuItem } from '../components/ActionMenu'
import { EmailLogsModal } from '../components/EmailLogsModal'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { useToast } from '../lib/toast'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import type { EmailLog, Invoice, InvoicePeriodParticipantRow } from '../types/api'

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

function hasDeletePermission(invoice: Invoice, role: string | undefined): boolean {
    return invoice.status === 'draft' || invoice.status === 'cancelled' || role === 'admin'
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
    const generationCandidateCount = useMemo(
        () => rows.filter((row) => !row.invoice || row.invoice.status === 'cancelled').length,
        [rows],
    )
    const pdfMissingCount = useMemo(
        () => rows.filter((row) => row.invoice && !row.invoice.pdf_url).length,
        [rows],
    )
    const isOwnerOrAdmin = user?.role === 'admin' || user?.role === 'zev_owner'

    const batchStats = [
        { key: 'invoices', label: t('pages.invoices.batch.summaryInvoices'), value: invoiceCount },
        { key: 'drafts', label: t('pages.invoices.batch.summaryDrafts'), value: draftCount },
        { key: 'approved', label: t('pages.invoices.batch.summaryApproved'), value: approvedCount },
        { key: 'pdfs', label: t('pages.invoices.batch.summaryPdfs'), value: pdfCount },
    ]

    const recommendedBatchAction: ActionMenuItem | null = useMemo(() => {
        if (draftCount > 0) {
            return {
                key: 'approve-all',
                label: t('pages.invoices.batch.approveAll'),
                icon: <FontAwesomeIcon icon={faCheckDouble} fixedWidth />,
                onClick: () => approveAllMutation.mutate(),
                disabled: anyBatchPending || draftCount === 0,
            }
        }
        if (approvedCount > 0) {
            return {
                key: 'send-all',
                label: t('pages.invoices.batch.sendAll'),
                icon: <FontAwesomeIcon icon={faPaperPlane} fixedWidth />,
                onClick: () => sendAllMutation.mutate(),
                disabled: anyBatchPending || approvedCount === 0,
            }
        }
        if (generationCandidateCount > 0) {
            return {
                key: 'generate-all',
                label: t('pages.invoices.batch.generateAll'),
                icon: <FontAwesomeIcon icon={faFileInvoice} fixedWidth />,
                onClick: () => generateAllMutation.mutate(),
                disabled: anyBatchPending || generationCandidateCount === 0,
            }
        }
        if (pdfMissingCount > 0) {
            return {
                key: 'generate-all-pdfs',
                label: t('pages.invoices.batch.generateAllPdfs'),
                icon: <FontAwesomeIcon icon={faFilePdf} fixedWidth />,
                onClick: () => generateAllPdfsMutation.mutate(),
                disabled: anyBatchPending || pdfMissingCount === 0,
            }
        }
        return null
    }, [
        anyBatchPending,
        approveAllMutation,
        approvedCount,
        draftCount,
        generateAllMutation,
        generateAllPdfsMutation,
        generationCandidateCount,
        pdfMissingCount,
        sendAllMutation,
        t,
    ])

    const batchMenuItems: ActionMenuItem[] = [
        {
            key: 'generate-all',
            label: `${t('pages.invoices.batch.generateAll')}${generationCandidateCount > 0 ? ` (${generationCandidateCount})` : ''}`,
            icon: <FontAwesomeIcon icon={faFileInvoice} fixedWidth />,
            onClick: () => generateAllMutation.mutate(),
            disabled: anyBatchPending || generationCandidateCount === 0,
        },
        {
            key: 'approve-all',
            label: `${t('pages.invoices.batch.approveAll')}${draftCount > 0 ? ` (${draftCount})` : ''}`,
            icon: <FontAwesomeIcon icon={faCheckDouble} fixedWidth />,
            onClick: () => approveAllMutation.mutate(),
            disabled: anyBatchPending || draftCount === 0,
        },
        {
            key: 'send-all',
            label: `${t('pages.invoices.batch.sendAll')}${approvedCount > 0 ? ` (${approvedCount})` : ''}`,
            icon: <FontAwesomeIcon icon={faPaperPlane} fixedWidth />,
            onClick: () => sendAllMutation.mutate(),
            disabled: anyBatchPending || approvedCount === 0,
        },
        {
            key: 'generate-all-pdfs',
            label: `${t('pages.invoices.batch.generateAllPdfs')}${invoiceCount > 0 ? ` (${invoiceCount})` : ''}`,
            icon: <FontAwesomeIcon icon={faFilePdf} fixedWidth />,
            onClick: () => generateAllPdfsMutation.mutate(),
            disabled: anyBatchPending || invoiceCount === 0,
        },
    ]

    function getPrimaryRowAction(row: InvoicePeriodParticipantRow): ActionMenuItem | null {
        const invoice = row.invoice

        if (!invoice || invoice.status === 'cancelled') {
            return {
                key: 'generate',
                label: invoice ? t('pages.invoices.generateAgain') : t('pages.invoices.generateInvoice'),
                icon: <FontAwesomeIcon icon={faFileInvoice} fixedWidth />,
                onClick: () =>
                    generateMutation.mutate({
                        participant_id: row.participant_id,
                        period_start: period.period_start,
                        period_end: period.period_end,
                    }),
                disabled: generateMutation.isPending,
            }
        }

        if (invoice.status === 'draft') {
            return {
                key: 'approve',
                label: t('pages.invoices.approve'),
                icon: <FontAwesomeIcon icon={faCheck} fixedWidth />,
                onClick: () => approveMutation.mutate(invoice.id),
                disabled: approveMutation.isPending,
            }
        }

        if (invoice.status === 'approved') {
            return {
                key: 'send-email',
                label: pollingInvoiceId === invoice.id ? t('pages.invoices.sending') : t('pages.invoices.sendEmail'),
                icon: <FontAwesomeIcon icon={faEnvelope} fixedWidth />,
                onClick: () => emailMutation.mutate(invoice.id),
                disabled: emailMutation.isPending || pollingInvoiceId === invoice.id,
            }
        }

        if (invoice.status === 'sent') {
            return {
                key: 'mark-paid',
                label: t('pages.invoices.markPaid'),
                icon: <FontAwesomeIcon icon={faMoneyBillWave} fixedWidth />,
                onClick: () => markPaidMutation.mutate(invoice.id),
                disabled: markPaidMutation.isPending,
            }
        }

        return null
    }

    function getRowMenuItems(row: InvoicePeriodParticipantRow): ActionMenuItem[] {
        const invoice = row.invoice
        if (!invoice) {
            return []
        }

        const items: ActionMenuItem[] = []

        if (invoice.status === 'draft' || invoice.status === 'cancelled') {
            items.push({
                key: 'generate-again',
                label: t('pages.invoices.regenerateInvoice'),
                icon: <FontAwesomeIcon icon={faRotate} fixedWidth />,
                section: t('pages.invoices.menuSections.invoice'),
                onClick: () =>
                    generateMutation.mutate({
                        participant_id: row.participant_id,
                        period_start: period.period_start,
                        period_end: period.period_end,
                    }),
                disabled: generateMutation.isPending,
            })
        }

        items.push({
            key: invoice.pdf_url ? 'regenerate-pdf' : 'generate-pdf',
            label: invoice.pdf_url ? t('pages.invoices.regeneratePdf') : t('pages.invoices.generatePdf'),
            icon: <FontAwesomeIcon icon={faFilePdf} fixedWidth />,
            section: t('pages.invoices.menuSections.pdf'),
            onClick: () => pdfMutation.mutate(invoice.id),
            disabled: pdfMutation.isPending,
        })

        if (invoice.email_logs?.length) {
            items.push({
                key: 'email-logs',
                label: t('pages.invoices.viewLogs'),
                icon: <FontAwesomeIcon icon={faEnvelope} fixedWidth />,
                section: t('pages.invoices.menuSections.email'),
                onClick: () => openEmailLogs(invoice.id, invoice.invoice_number),
            })
        }

        if (invoice.status === 'approved') {
            items.push({
                key: 'mark-sent',
                label: t('pages.invoices.markSent'),
                icon: <FontAwesomeIcon icon={faPaperPlane} fixedWidth />,
                section: t('pages.invoices.menuSections.invoice'),
                onClick: () => markSentMutation.mutate(invoice.id),
                disabled: markSentMutation.isPending,
            })
        }

        if (invoice.status === 'sent') {
            items.push({
                key: 'resend-email',
                label: t('pages.invoices.resendEmail'),
                icon: <FontAwesomeIcon icon={faEnvelope} fixedWidth />,
                section: t('pages.invoices.menuSections.email'),
                onClick: () => emailMutation.mutate(invoice.id),
                disabled: emailMutation.isPending || pollingInvoiceId === invoice.id,
            })
        }

        if (hasDeletePermission(invoice, user?.role)) {
            items.push({
                key: 'delete',
                label: t('pages.invoices.delete'),
                icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
                section: t('pages.invoices.menuSections.danger'),
                onClick: () => setDeleteModalInvoiceId(invoice.id),
                disabled: deleteMutation.isPending,
                danger: true,
            })
        }

        return items
    }

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
                    <FontAwesomeIcon icon={faArrowLeft} fixedWidth />
                    {t('pages.invoices.prevPeriod')}
                </button>
                <div style={{ textAlign: 'center' }}>
                    <div style={{ fontWeight: 700 }}>{selectedZev?.name}</div>
                    <div className="muted" style={{ fontSize: '0.95rem' }}>
                        {period.period_start && period.period_end
                            ? `${formatShortDate(period.period_start, settings)} → ${formatShortDate(period.period_end, settings)}`
                            : '—'}
                    </div>
                    <div className="muted" style={{ fontSize: '0.85rem' }}>
                        {t('pages.invoices.billingInterval')} {interval.replace('_', ' ')}
                    </div>
                </div>
                <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => setPeriod((prev) => shiftBillingPeriod(prev.period_start, interval, 1))}
                    disabled={!period.period_start}
                >
                    {t('pages.invoices.nextPeriod')}
                    <FontAwesomeIcon icon={faArrowRight} fixedWidth />
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
                        <section className="card invoice-batch-toolbar">
                            <div className="invoice-batch-header">
                                <div className="invoice-batch-title">{t('pages.invoices.batch.title')}</div>
                                <div className="invoice-batch-summary">
                                    {batchStats.map((stat) => (
                                        <span key={stat.key} className="invoice-batch-stat">
                                            <span className="invoice-batch-stat-label">{stat.label}</span>
                                            <span className="invoice-batch-stat-value">{stat.value}</span>
                                        </span>
                                    ))}
                                </div>
                            </div>
                            <div className="invoice-batch-actions">
                                {recommendedBatchAction && (
                                    <button
                                        className="button button-primary"
                                        type="button"
                                        disabled={recommendedBatchAction.disabled}
                                        onClick={recommendedBatchAction.onClick}
                                    >
                                        {recommendedBatchAction.icon}
                                        {recommendedBatchAction.label}
                                    </button>
                                )}
                                <button
                                    className="button button-secondary button-compact"
                                    type="button"
                                    disabled={anyBatchPending || pdfCount === 0}
                                    onClick={() => downloadAllPdfsMutation.mutate()}
                                >
                                    <FontAwesomeIcon icon={faDownload} fixedWidth />
                                    {t('pages.invoices.batch.downloadAll')} {pdfCount > 0 && `(${pdfCount})`}
                                </button>
                                <ActionMenu
                                    label={t('pages.invoices.moreBatchActions')}
                                    icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
                                    items={batchMenuItems.filter((item) => item.key !== recommendedBatchAction?.key)}
                                />
                            </div>
                        </section>
                    )}

                    <div className="table-card">
                        <table>
                            <thead>
                                <tr>
                                    <th>{t('pages.invoices.col.participant')}</th>
                                    <th>{t('pages.invoices.col.meteringData')}</th>
                                    <th>{t('pages.invoices.col.invoice')}</th>
                                    <th>{t('pages.invoices.col.email')}</th>
                                    <th>{t('pages.invoices.col.total')}</th>
                                    <th>{t('pages.invoices.col.pdf')}</th>
                                    <th className="invoice-actions-cell">{t('pages.invoices.col.actions')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {rows.map((row) => {
                                    const invoice = row.invoice
                                    const latestEmailLog = getLatestEmailLog(invoice)
                                    const primaryAction = getPrimaryRowAction(row)
                                    const rowMenuItems = getRowMenuItems(row)

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
                                                            {t('pages.invoices.metering.pointsWithData', {
                                                                n: row.metering_points_with_data,
                                                                total: row.metering_points_total,
                                                            })}
                                                        </div>
                                                        {row.missing_meter_ids.length > 0 && (
                                                            <ul className="metering-missing-list muted">
                                                                {row.missing_meter_details?.length
                                                                    ? row.missing_meter_details.map((item) => (
                                                                        <li key={item.meter_id}>
                                                                            {item.meter_id} ({item.missing_days} day{item.missing_days === 1 ? '' : 's'})
                                                                        </li>
                                                                    ))
                                                                    : row.missing_meter_ids.map((meterId) => <li key={meterId}>{meterId}</li>)}
                                                            </ul>
                                                        )}
                                                    </>
                                                )}
                                            </td>
                                            <td>
                                                {invoice ? (
                                                    <div className="invoice-cell-stack">
                                                        <span>{invoice.invoice_number}</span>
                                                        <span className={invoiceStatusBadgeClass(invoice.status)}>{humanizeStatus(invoice.status)}</span>
                                                    </div>
                                                ) : (
                                                    <div className="invoice-cell-stack">
                                                        <span className="muted">{t('pages.invoices.notCreated')}</span>
                                                        <span className="badge badge-neutral">{t('pages.invoices.notCreated')}</span>
                                                    </div>
                                                )}
                                            </td>
                                            <td>
                                                {invoice && latestEmailLog ? (
                                                    <div className="invoice-cell-stack">
                                                        <span className={emailStatusBadgeClass(latestEmailLog.status)}>
                                                            {humanizeStatus(latestEmailLog.status)}
                                                        </span>
                                                        <div>
                                                            <button
                                                                className="table-inline-action"
                                                                type="button"
                                                                onClick={() => openEmailLogs(invoice.id, invoice.invoice_number)}
                                                            >
                                                                <FontAwesomeIcon icon={faEnvelope} fixedWidth />
                                                                {t('pages.invoices.viewLogs')} ({invoice.email_logs?.length ?? 0})
                                                            </button>
                                                            {(invoice.email_logs?.filter((log) => log.status === 'failed').length ?? 0) > 0 && (
                                                                <span style={{ color: '#ef4444', marginLeft: '0.3rem', fontSize: '0.85rem', fontWeight: 'bold' }}>
                                                                    {t('pages.invoices.failedEmails', {
                                                                        n: invoice.email_logs?.filter((log) => log.status === 'failed').length,
                                                                    })}
                                                                </span>
                                                            )}
                                                        </div>
                                                        {(invoice.email_logs?.length ?? 0) > 1 && (
                                                            <div className="muted" style={{ fontSize: '0.85rem' }}>
                                                                {t('pages.invoices.attempts', { n: invoice.email_logs?.length })}
                                                            </div>
                                                        )}
                                                    </div>
                                                ) : (
                                                    <span className="muted">—</span>
                                                )}
                                            </td>
                                            <td>{invoice ? `CHF ${invoice.total_chf}` : <span className="muted">—</span>}</td>
                                            <td>
                                                {invoice ? (
                                                    invoice.pdf_url ? (
                                                        <div className="invoice-cell-stack">
                                                            <a
                                                                href={invoice.pdf_url}
                                                                target="_blank"
                                                                rel="noreferrer"
                                                                className="table-inline-link"
                                                            >
                                                                <FontAwesomeIcon icon={faFilePdf} fixedWidth />
                                                                {t('pages.invoices.openPdf')}
                                                            </a>
                                                            <span className="badge badge-success">{t('pages.invoices.pdfReady')}</span>
                                                        </div>
                                                    ) : (
                                                        <span className="badge badge-neutral">{t('pages.invoices.pdfMissing')}</span>
                                                    )
                                                ) : (
                                                    <span className="muted">—</span>
                                                )}
                                            </td>
                                            <td className="invoice-actions-cell">
                                                <div className="invoice-row-actions">
                                                    {primaryAction && (
                                                        <button
                                                            className="button button-primary button-compact"
                                                            type="button"
                                                            disabled={primaryAction.disabled}
                                                            onClick={primaryAction.onClick}
                                                        >
                                                            {primaryAction.icon}
                                                            {primaryAction.label}
                                                        </button>
                                                    )}
                                                    {invoice && (
                                                        <Link
                                                            className="button button-secondary button-compact"
                                                            style={{ textDecoration: 'none' }}
                                                            to={`/invoices/${invoice.id}`}
                                                        >
                                                            <FontAwesomeIcon icon={faFileInvoice} fixedWidth />
                                                            {t('pages.invoices.openDetails')}
                                                        </Link>
                                                    )}
                                                    {rowMenuItems.length > 0 && (
                                                        <ActionMenu
                                                            label={t('pages.invoices.moreActions')}
                                                            icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
                                                            items={rowMenuItems}
                                                        />
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
