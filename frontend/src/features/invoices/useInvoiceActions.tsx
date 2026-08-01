import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faCheck,
    faCheckDouble,
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
    fetchInvoice,
    generateAllPdfs,
    generateInvoice,
    generateInvoicePdf,
    generateInvoicesForZev,
    markInvoicePaid,
    markInvoiceSent,
    retryFailedEmail,
    sendAllInvoices,
    sendInvoiceEmail,
} from '../../lib/api/invoices'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { useToast } from '../../lib/toast'
import type { ActionMenuItem } from '../../components/ActionMenu'
import type { Invoice, InvoicePeriodParticipantRow } from '../../types/api'

const EMAIL_STATUS_POLL_TIMEOUT_MS = 90_000

export interface InvoiceActionStats {
    invoiceCount: number
    draftCount: number
    approvedCount: number
    pdfCount: number
    generationCandidateCount: number
}

export function getLatestEmailLog(invoice: { email_logs?: Array<{ created_at: string; recipient: string; status: string; id: string }> } | null) {
    if (!invoice?.email_logs?.length) return null
    return [...invoice.email_logs].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0]
}

export function hasDeletePermission(invoice: Invoice, role: string | undefined): boolean {
    return invoice.status === 'draft' || invoice.status === 'cancelled' || role === 'admin'
}

export function useInvoiceActions({
    selectedZevId,
    period,
    rows,
    userRole,
    onOpenEmailLogs,
    onDeleteClick,
}: {
    selectedZevId: string
    period: { period_start: string; period_end: string }
    rows: InvoicePeriodParticipantRow[]
    userRole: string | undefined
    onOpenEmailLogs: (invoiceId: string, invoiceNumber: string) => Promise<void>
    onDeleteClick: (invoiceId: string) => void
}) {
    const { t } = useTranslation()
    const queryClient = useQueryClient()
    const { pushToast } = useToast()

    // ── Email polling state ──────────────────────────────────────────────
    const [pollingInvoiceId, setPollingInvoiceId] = useState<string | null>(null)
    const [emailPollingStartedAt, setEmailPollingStartedAt] = useState<number | null>(null)
    const [retiringEmailId, setRetiringEmailId] = useState<string | null>(null)

    const periodOverviewInvalidationKey = useMemo(
        () => (
            selectedZevId
                ? queryKeys.invoices.periodOverview(selectedZevId, period.period_start, period.period_end)
                : (['invoices', 'period-overview'] as const)
        ),
        [selectedZevId, period.period_start, period.period_end],
    )

    // ── Single invoice mutations ──────────────────────────────────────────────

    const generateMutation = useMutation({
        mutationFn: generateInvoice,
        onSuccess: () => {
            pushToast(t('pages.invoices.messages.generated'), 'success')
            void queryClient.invalidateQueries({ queryKey: periodOverviewInvalidationKey })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.messages.generateFailed')), 'error'),
    })

    const pdfMutation = useMutation({
        mutationFn: generateInvoicePdf,
        onSuccess: () => {
            pushToast(t('pages.invoices.messages.pdfGenerated'), 'success')
            void queryClient.invalidateQueries({ queryKey: periodOverviewInvalidationKey })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.messages.generatePdfFailed')), 'error'),
    })

    const approveMutation = useMutation({
        mutationFn: approveInvoice,
        onSuccess: () => {
            pushToast(t('pages.invoices.messages.approved'), 'success')
            void queryClient.invalidateQueries({ queryKey: periodOverviewInvalidationKey })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.messages.approveFailed')), 'error'),
    })

    const deleteMutation = useMutation({
        mutationFn: deleteInvoice,
        onSuccess: () => {
            pushToast(t('pages.invoices.messages.deleted'), 'success')
            void queryClient.invalidateQueries({ queryKey: periodOverviewInvalidationKey })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.messages.deleteFailed')), 'error'),
    })

    const emailMutation = useMutation({
        mutationFn: (invoiceId: string) => sendInvoiceEmail(invoiceId),
        onSuccess: (_result, invoiceId) => {
            pushToast(t('pages.invoices.messages.emailQueued'), 'success')
            setPollingInvoiceId(invoiceId)
            setEmailPollingStartedAt(Date.now())
            void queryClient.invalidateQueries({ queryKey: periodOverviewInvalidationKey })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.messages.sendEmailFailed')), 'error'),
    })

    const markSentMutation = useMutation({
        mutationFn: markInvoiceSent,
        onSuccess: () => {
            pushToast(t('pages.invoices.markedSent'), 'success')
            void queryClient.invalidateQueries({ queryKey: periodOverviewInvalidationKey })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.messages.markSentFailed')), 'error'),
    })

    const markPaidMutation = useMutation({
        mutationFn: markInvoicePaid,
        onSuccess: () => {
            pushToast(t('pages.invoices.messages.markedPaid'), 'success')
            void queryClient.invalidateQueries({ queryKey: periodOverviewInvalidationKey })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.messages.markPaidFailed')), 'error'),
    })

    const retryEmailMutation = useMutation({
        mutationFn: (params: { invoiceId: string; emailLogId: string }) =>
            retryFailedEmail(params.invoiceId, params.emailLogId),
        onSuccess: (_result, variables) => {
            pushToast(t('pages.invoices.messages.retryQueued'), 'success')
            setPollingInvoiceId(variables.invoiceId)
            setEmailPollingStartedAt(Date.now())
            void queryClient.invalidateQueries({ queryKey: periodOverviewInvalidationKey })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.messages.retryEmailFailed')), 'error'),
    })

    // ── Batch mutations ──────────────────────────────────────────────

    const batchPayload = { zev_id: selectedZevId, period_start: period.period_start, period_end: period.period_end }

    // Bulk generation runs asynchronously on the backend; refresh the period
    // overview a few times so results appear without a manual reload.
    const scheduleOverviewRefresh = () => {
        for (const delay of [3000, 8000, 15000, 30000]) {
            window.setTimeout(() => {
                void queryClient.invalidateQueries({ queryKey: periodOverviewInvalidationKey })
            }, delay)
        }
    }

    const generateAllMutation = useMutation({
        mutationFn: () => generateInvoicesForZev(batchPayload),
        onSuccess: (result) => {
            pushToast(t('pages.invoices.batch.generateAllQueued', { n: result.participant_count }), 'success')
            void queryClient.invalidateQueries({ queryKey: periodOverviewInvalidationKey })
            scheduleOverviewRefresh()
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.batch.generateAllFailed')), 'error'),
    })

    const approveAllMutation = useMutation({
        mutationFn: () => approveAllInvoices(batchPayload),
        onSuccess: (result) => {
            pushToast(t('pages.invoices.batch.approvedAll', { n: result.approved }), 'success')
            void queryClient.invalidateQueries({ queryKey: periodOverviewInvalidationKey })
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
            void queryClient.invalidateQueries({ queryKey: periodOverviewInvalidationKey })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.batch.sendAllFailed')), 'error'),
    })

    const generateAllPdfsMutation = useMutation({
        mutationFn: () => generateAllPdfs(batchPayload),
        onSuccess: (result) => {
            pushToast(t('pages.invoices.batch.generateAllPdfsQueued', { n: result.invoice_count }), 'success')
            void queryClient.invalidateQueries({ queryKey: periodOverviewInvalidationKey })
            scheduleOverviewRefresh()
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

    // ── Polling effect for email status ──────────────────────────────────────────────

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
                    void queryClient.invalidateQueries({ queryKey: periodOverviewInvalidationKey })
                    if (lastEmailLog.status === 'sent') {
                        pushToast(t('pages.invoices.messages.emailSentSuccess'), 'success')
                    }
                    clearInterval(pollInterval)
                    return
                }

                // Stop if max polls reached
                if (pollCount >= maxPolls) {
                    setPollingInvoiceId(null)
                    setEmailPollingStartedAt(null)
                    pushToast(t('pages.invoices.messages.emailPollingTimeout'), 'error')
                    clearInterval(pollInterval)
                    return
                }

                // Update the query cache with the latest invoice data
                void queryClient.invalidateQueries({ queryKey: periodOverviewInvalidationKey })
            } catch (error) {
                console.error('Error polling invoice status:', error)
            }
        }, 2000) // Poll every 2 seconds

        return () => clearInterval(pollInterval)
    }, [pollingInvoiceId, emailPollingStartedAt, periodOverviewInvalidationKey, queryClient, pushToast, t])

    useEffect(() => {
        if (!pollingInvoiceId || !emailPollingStartedAt) return
        const timeoutId = window.setTimeout(() => {
            setPollingInvoiceId(null)
            setEmailPollingStartedAt(null)
            pushToast(t('pages.invoices.messages.emailPollingTimeout'), 'error')
        }, EMAIL_STATUS_POLL_TIMEOUT_MS)

        return () => {
            window.clearTimeout(timeoutId)
        }
    }, [pollingInvoiceId, emailPollingStartedAt, pushToast, t])

    // ── Helper callbacks ──────────────────────────────────────────────

    function handleRetryEmail(invoiceId: string, emailLogId: string) {
        setRetiringEmailId(emailLogId)
        retryEmailMutation.mutate(
            { invoiceId, emailLogId },
            {
                onSettled: () => setRetiringEmailId(null),
            },
        )
    }

    // ── Stats computation ──────────────────────────────────────────────

    const draftCount = useMemo(() => rows.filter((r) => r.invoice?.status === 'draft').length, [rows])
    const approvedCount = useMemo(() => rows.filter((r) => r.invoice?.status === 'approved').length, [rows])
    const invoiceCount = useMemo(() => rows.filter((r) => r.invoice).length, [rows])
    const pdfCount = useMemo(() => rows.filter((r) => r.invoice?.pdf_url).length, [rows])
    const generationCandidateCount = useMemo(
        () => rows.filter((row) => !row.invoice || row.invoice.status === 'cancelled').length,
        [rows],
    )
    const stats: InvoiceActionStats = {
        invoiceCount,
        draftCount,
        approvedCount,
        pdfCount,
        generationCandidateCount,
    }

    // ── Recommended batch action ──────────────────────────────────────────────

    // Ordered by the workflow itself — generate, then approve, then send.
    // Recommending approval first would skip participants who have no invoice
    // yet (a late joiner, or a generation that failed), because approve-all only
    // touches drafts: the button would report success and silently leave them
    // unbilled. PDFs are not a rung — they are produced with the invoice.
    const recommendedBatchAction: ActionMenuItem | null = useMemo(() => {
        if (generationCandidateCount > 0) {
            return {
                key: 'generate-all',
                label: t('pages.invoices.batch.generateAllCount', { count: generationCandidateCount }),
                icon: <FontAwesomeIcon icon={faFileInvoice} fixedWidth />,
                onClick: () => generateAllMutation.mutate(),
                disabled: anyBatchPending,
            }
        }
        if (draftCount > 0) {
            return {
                key: 'approve-all',
                label: t('pages.invoices.batch.approveAllCount', { count: draftCount }),
                icon: <FontAwesomeIcon icon={faCheckDouble} fixedWidth />,
                onClick: () => approveAllMutation.mutate(),
                disabled: anyBatchPending,
            }
        }
        if (approvedCount > 0) {
            return {
                key: 'send-all',
                label: t('pages.invoices.batch.sendAllCount', { count: approvedCount }),
                icon: <FontAwesomeIcon icon={faPaperPlane} fixedWidth />,
                onClick: () => sendAllMutation.mutate(),
                disabled: anyBatchPending,
            }
        }
        return null
    }, [
        anyBatchPending,
        approveAllMutation,
        approvedCount,
        draftCount,
        generateAllMutation,
        generationCandidateCount,
        sendAllMutation,
        t,
    ])

    // ── Batch menu items ──────────────────────────────────────────────

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

    // ── Row action helpers ──────────────────────────────────────────────

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
                onClick: () => onOpenEmailLogs(invoice.id, invoice.invoice_number),
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

        if (hasDeletePermission(invoice, userRole)) {
            items.push({
                key: 'delete',
                label: t('pages.invoices.delete'),
                icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
                section: t('pages.invoices.menuSections.danger'),
                onClick: () => onDeleteClick(invoice.id),
                disabled: deleteMutation.isPending,
                danger: true,
            })
        }

        return items
    }

    return {
        // Mutations
        generateMutation,
        pdfMutation,
        approveMutation,
        deleteMutation,
        emailMutation,
        markSentMutation,
        markPaidMutation,
        retryEmailMutation,
        // Batch mutations
        generateAllMutation,
        approveAllMutation,
        sendAllMutation,
        generateAllPdfsMutation,
        downloadAllPdfsMutation,
        anyBatchPending,
        // Polling state
        pollingInvoiceId,
        setPollingInvoiceId,
        emailPollingStartedAt,
        setEmailPollingStartedAt,
        retiringEmailId,
        // Stats & computed
        stats,
        recommendedBatchAction,
        batchMenuItems,
        // Callbacks
        getPrimaryRowAction,
        getRowMenuItems,
        handleRetryEmail,
    }
}
