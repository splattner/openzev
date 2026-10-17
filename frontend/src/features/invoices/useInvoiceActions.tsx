import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
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
    faTriangleExclamation,
} from '@fortawesome/free-solid-svg-icons'
import {
    approveAllInvoices,
    approveInvoice,
    deleteInvoice,
    downloadAllPdfs,
    generateAllPdfs,
    generateInvoice,
    generateInvoicePdf,
    generateInvoicesForZev,
    markInvoicePaid,
    markInvoiceSent,
    openInvoicePdf,
    sendAllInvoices,
    sendInvoiceEmail,
} from '../../lib/api/invoices'
import { apiErrorPayload, dynamicPriceGapPayload, formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { downloadBlob } from '../../lib/downloadBlob'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { useToast } from '../../lib/toast'
import { useWriteScope } from '../../lib/useWriteScope'
import { liveInvoice, type InvoiceRowWork } from './invoiceRowState'
import { getLatestEmailLog } from './emailLogs'
import { useEmailDelivery } from './useEmailDelivery'
import { invoiceRowCounts } from './invoiceRowFilters'
import type { ActionMenuItem } from '../../components/ActionMenu'
import type { Invoice, InvoicePeriodParticipantRow } from '../../types/api'

/** Send all queues approved invoices that have a recipient. */
function isSendable(row: InvoicePeriodParticipantRow): boolean {
    return row.invoice?.status === 'approved' && !!row.participant_email
}

/**
 * Mirrors the backend: an invoice with payments is never deleted; admins may
 * delete any other; managers only a draft or cancelled invoice that was never
 * approved, since an issued one keeps its number for good (ADR 0037).
 */
export function hasDeletePermission(invoice: Invoice, role: string | undefined): boolean {
    if (Number(invoice.paid_chf ?? 0) !== 0) return false
    if (role === 'admin') return true
    return (invoice.status === 'draft' || invoice.status === 'cancelled') && !invoice.approved_at
}

export function useInvoiceActions({
    selectedZevId,
    period,
    rows,
    userRole,
    onDeleteClick,
    onPdfQueued,
    generationParticipantIds = [],
    canGenerate = true,
    canWrite = true,
    accountId,
}: {
    selectedZevId: string
    period: { period_start: string; period_end: string }
    rows: InvoicePeriodParticipantRow[]
    userRole: string | undefined
    generationParticipantIds?: string[]
    canGenerate?: boolean
    canWrite?: boolean
    accountId?: number
    onDeleteClick: (invoiceId: string) => void
    /** Called when an action queued PDF work the operator should see arrive. */
    onPdfQueued: (generationParticipantIds?: string[]) => void
}) {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { settings } = useAppSettings()

    const { scope, isCurrent } = useWriteScope({
        selectedZevId,
        scopeKey: `${period.period_start}|${period.period_end}`,
        accountId,
        canWrite,
    }, t('common.scopeGuard.loadFailed'))

    const periodOverviewInvalidationKey = useMemo(
        () => (
            selectedZevId
                ? queryKeys.invoices.periodOverview(selectedZevId, period.period_start, period.period_end)
                : (['invoices', 'period-overview'] as const)
        ),
        [selectedZevId, period.period_start, period.period_end],
    )

    const invalidatePeriodOverview = useCallback(() => {
        void queryClient.invalidateQueries({ queryKey: periodOverviewInvalidationKey })
    }, [periodOverviewInvalidationKey, queryClient])

    const invalidateInvoicesList = useCallback(() => {
        void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.lists() })
        void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.mine() })
    }, [queryClient])

    // Billing mutations also move Overview's period cards: readiness steps
    // and cross-period attention derive from the same invoice states.
    const invalidateCockpit = useCallback(() => {
        void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.readiness(selectedZevId) })
        void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.readinessList(selectedZevId) })
        void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.attention(selectedZevId) })
    }, [queryClient, selectedZevId])

    const refreshRelated = useCallback(() => {
        invalidateInvoicesList()
        invalidateCockpit()
    }, [invalidateInvoicesList, invalidateCockpit])
    const delivery = useEmailDelivery({ rows, scope, refreshOverview: invalidatePeriodOverview, refreshRelated })

    const showGenerationError = (error: unknown, fallback: string) => {
        const gap = dynamicPriceGapPayload(error)
        if (gap) {
            pushToast(t('pages.invoices.messages.dynamicPriceGap', {
                tariff: gap.tariff_name,
                timestamp: formatDateTime(gap.missing_at, settings),
            }), 'error')
        } else {
            const payload = apiErrorPayload(error)
            pushToast(payload?.code === 'invalid_dynamic_tariff'
                ? t('pages.invoices.messages.invalidDynamicTariff', { tariff: payload.tariff_name })
                : formatApiError(error, fallback), 'error')
        }
    }

    // ── Single invoice mutations ──────────────────────────────────────────────

    const generateMutation = useMutation({
        mutationFn: generateInvoice,
        onMutate: () => ({ scope, queryKey: periodOverviewInvalidationKey }),
        onSuccess: (_result, variables, submitted) => {
            void queryClient.invalidateQueries({ queryKey: submitted?.queryKey ?? periodOverviewInvalidationKey })
            if (submitted && !isCurrent(submitted.scope)) return
            pushToast(t('pages.invoices.messages.generated'), 'success')
            invalidateInvoicesList()
            // The invoice is saved; its PDF is queued and arrives later.
            onPdfQueued([variables.participant_id])
            invalidateCockpit()
        },
        onError: (error) => showGenerationError(error, t('pages.invoices.messages.generateFailed')),
    })

    const pdfMutation = useMutation({
        mutationFn: generateInvoicePdf,
        onSuccess: () => {
            pushToast(t('pages.invoices.messages.pdfGenerated'), 'success')
            invalidatePeriodOverview()
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.messages.generatePdfFailed')), 'error'),
    })

    const approveMutation = useMutation({
        mutationFn: approveInvoice,
        onSuccess: () => {
            pushToast(t('pages.invoices.messages.approved'), 'success')
            invalidatePeriodOverview()
            invalidateInvoicesList()
            invalidateCockpit()
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.messages.approveFailed')), 'error'),
    })

    const deleteMutation = useMutation({
        mutationFn: deleteInvoice,
        onSuccess: () => {
            pushToast(t('pages.invoices.messages.deleted'), 'success')
            invalidatePeriodOverview()
            invalidateInvoicesList()
            invalidateCockpit()
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.messages.deleteFailed')), 'error'),
    })

    const emailMutation = useMutation({
        mutationFn: (invoiceId: string) => sendInvoiceEmail(invoiceId),
        onMutate: (invoiceId) => ({
            scope,
            queryKey: periodOverviewInvalidationKey,
            previousLogId: getLatestEmailLog(rows.find(row => row.invoice?.id === invoiceId)?.invoice ?? null)?.id ?? null,
        }),
        onSuccess: (_result, invoiceId, submitted) => {
            void queryClient.invalidateQueries({ queryKey: submitted?.queryKey ?? periodOverviewInvalidationKey })
            if (submitted && !isCurrent(submitted.scope)) return
            pushToast(t('pages.invoices.messages.emailQueued'), 'success')
            delivery.track([{ invoiceId, previousLogId: submitted?.previousLogId ?? null, announce: true }])
            invalidateInvoicesList()
            invalidateCockpit()
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.messages.sendEmailFailed')), 'error'),
    })

    const markSentMutation = useMutation({
        mutationFn: markInvoiceSent,
        onSuccess: () => {
            pushToast(t('pages.invoices.markedSent'), 'success')
            invalidatePeriodOverview()
            invalidateInvoicesList()
            invalidateCockpit()
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.messages.markSentFailed')), 'error'),
    })

    const markPaidMutation = useMutation({
        mutationFn: (invoiceId: string) => markInvoicePaid(invoiceId),
        onSuccess: () => {
            pushToast(t('pages.invoices.messages.markedPaid'), 'success')
            invalidatePeriodOverview()
            invalidateInvoicesList()
            invalidateCockpit()
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.messages.markPaidFailed')), 'error'),
    })

    // ── Batch mutations ──────────────────────────────────────────────

    const batchPayload = { zev_id: selectedZevId, period_start: period.period_start, period_end: period.period_end }

    const generateAllMutation = useMutation({
        mutationFn: () => generateInvoicesForZev(batchPayload),
        onMutate: () => ({
            scope,
            queryKey: periodOverviewInvalidationKey,
            participantIds: rows.filter(row => row.generation_eligibility?.state === 'eligible').map(row => row.participant_id),
        }),
        onSuccess: (_result, _variables, queuedWork) => {
            void queryClient.invalidateQueries({ queryKey: queuedWork?.queryKey ?? periodOverviewInvalidationKey })
            invalidateInvoicesList()
            if (queuedWork && !isCurrent(queuedWork.scope)) return
            onPdfQueued(queuedWork?.participantIds)
            invalidateCockpit()
        },
        onError: (error) => showGenerationError(error, t('pages.invoices.batch.generateAllFailed')),
    })

    const approveAllMutation = useMutation({
        mutationFn: () => approveAllInvoices(batchPayload),
        onSuccess: (result) => {
            pushToast(t('pages.invoices.batch.approvedAll', { n: result.approved }), 'success')
            invalidatePeriodOverview()
            invalidateInvoicesList()
            invalidateCockpit()
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.batch.approveAllFailed')), 'error'),
    })

    const sendAllMutation = useMutation({
        mutationFn: () => sendAllInvoices(batchPayload),
        onMutate: () => ({
            scope,
            queryKey: periodOverviewInvalidationKey,
            targets: rows.filter(isSendable)
                .map(row => ({ invoiceId: row.invoice!.id, previousLogId: getLatestEmailLog(row.invoice)?.id ?? null })),
        }),
        onSuccess: (result, _variables, submitted) => {
            void queryClient.invalidateQueries({ queryKey: submitted?.queryKey ?? periodOverviewInvalidationKey })
            if (submitted && !isCurrent(submitted.scope)) return
            if (result.queued > 0 && submitted?.targets.length) delivery.track(submitted.targets)
            const msg = result.skipped > 0
                ? t('pages.invoices.batch.sentAllWithSkipped', { queued: result.queued, skipped: result.skipped })
                : t('pages.invoices.batch.sentAll', { n: result.queued })
            pushToast(msg, 'success')
            invalidateInvoicesList()
            invalidateCockpit()
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.batch.sendAllFailed')), 'error'),
    })

    const generateAllPdfsMutation = useMutation({
        mutationFn: () => generateAllPdfs(batchPayload),
        onMutate: () => ({ scope, queryKey: periodOverviewInvalidationKey }),
        onSuccess: (_result, _variables, submitted) => {
            void queryClient.invalidateQueries({ queryKey: submitted?.queryKey ?? periodOverviewInvalidationKey })
            if (submitted && !isCurrent(submitted.scope)) return
            onPdfQueued()
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.batch.generateAllPdfsFailed')), 'error'),
    })

    const downloadAllPdfsMutation = useMutation({
        mutationFn: () => downloadAllPdfs(batchPayload),
        onSuccess: (blob) => {
            downloadBlob(blob, `invoices-${period.period_start}.zip`)
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.batch.downloadFailed')), 'error'),
    })

    const anyBatchPending = generateAllMutation.isPending || approveAllMutation.isPending || sendAllMutation.isPending || generateAllPdfsMutation.isPending || downloadAllPdfsMutation.isPending

    // Row and batch sends share one lock: either path would queue the same
    // approved invoice again while the other's request or delivery is open.
    const isSending = (invoiceId: string) => delivery.isTracking(invoiceId)
        || (emailMutation.isPending && emailMutation.variables === invoiceId)
        || (sendAllMutation.isPending && rows.some(row => row.invoice?.id === invoiceId && isSendable(row)))
    const rowSendLocked = (invoiceId: string) => emailMutation.isPending || sendAllMutation.isPending || isSending(invoiceId)

    const getRowWork = (row: InvoicePeriodParticipantRow): InvoiceRowWork => ({
        generating: (generateMutation.isPending && generateMutation.variables?.participant_id === row.participant_id)
            || (generationParticipantIds.includes(row.participant_id) && !liveInvoice(row)),
        pdfPending: !!row.invoice && pdfMutation.isPending && pdfMutation.variables === row.invoice.id,
        sending: !!row.invoice && isSending(row.invoice.id),
    })
    const rowCounts = invoiceRowCounts(rows, getRowWork)
    const { invoices: invoiceCount, drafts: draftCount } = rowCounts
    const sendableCount = rows.filter(isSendable).length
    const generationCandidateCount = rows.filter(row => row.generation_eligibility?.state === 'eligible').length
    const generationPending = generateMutation.isPending || generationParticipantIds.some(id =>
        !rows.some(row => row.participant_id === id && liveInvoice(row)))

    const workflowActions: Array<ActionMenuItem & { recommendedLabel: string }> = [
        ...(canGenerate && generationCandidateCount > 0 ? [{
            key: 'generate-all',
            label: `${t('pages.invoices.batch.generateAll')} (${generationCandidateCount})`,
            recommendedLabel: t('pages.invoices.batch.generateAllCount', { count: generationCandidateCount }),
            icon: <FontAwesomeIcon icon={faFileInvoice} fixedWidth />,
            onClick: () => generateAllMutation.mutate(),
            disabled: anyBatchPending || generationPending,
        }] : []),
        ...(draftCount > 0 ? [{
            key: 'approve-all',
            label: `${t('pages.invoices.batch.approveAll')} (${draftCount})`,
            recommendedLabel: t('pages.invoices.batch.approveAllCount', { count: draftCount }),
            icon: <FontAwesomeIcon icon={faCheckDouble} fixedWidth />,
            onClick: () => approveAllMutation.mutate(),
            disabled: anyBatchPending,
        }] : []),
        ...(sendableCount > 0 ? [{
            key: 'send-all',
            label: `${t('pages.invoices.batch.sendAll')} (${sendableCount})`,
            recommendedLabel: t('pages.invoices.batch.sendAllCount', { count: sendableCount }),
            icon: <FontAwesomeIcon icon={faPaperPlane} fixedWidth />,
            onClick: () => sendAllMutation.mutate(),
            disabled: anyBatchPending || emailMutation.isPending || delivery.anyTracking,
        }] : []),
    ]
    const nextAction = workflowActions[0]
    const recommendedBatchAction = nextAction ? { ...nextAction, label: nextAction.recommendedLabel } : null
    const batchMenuItems: ActionMenuItem[] = [
        ...workflowActions,
        ...(invoiceCount > 0 ? [{
            key: 'generate-all-pdfs',
            label: `${t('pages.invoices.batch.generateAllPdfs')} (${invoiceCount})`,
            icon: <FontAwesomeIcon icon={faFilePdf} fixedWidth />,
            onClick: () => generateAllPdfsMutation.mutate(),
            disabled: anyBatchPending,
        }] : []),
    ]

    // ── Row action helpers ──────────────────────────────────────────────

    // Detail destinations keep the return period: the detail page's Back
    // button restores the exact viewed period from this state.
    function detailDestination(invoiceId: string) {
        return {
            pathname: `/billing/invoices/${invoiceId}`,
            state: {
                from: '/billing/invoices',
                period_start: period.period_start,
                period_end: period.period_end,
            },
        }
    }

    function getPrimaryRowAction(row: InvoicePeriodParticipantRow): ActionMenuItem | null {
        const invoice = row.invoice

        if (!invoice || invoice.status === 'cancelled') {
            const eligibility = row.generation_eligibility
            if (eligibility?.state === 'blocked' && eligibility.invoice_id) {
                const destination = detailDestination(eligibility.invoice_id)
                return {
                    key: 'review-conflict',
                    label: t('pages.invoices.reviewConflict'),
                    icon: <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />,
                    onClick: () => navigate(destination.pathname, { state: destination.state }),
                }
            }
            // A covered row names its invoice as a link in the progress column.
            if (eligibility && eligibility.state !== 'eligible') {
                return null
            }
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
                disabled: generateMutation.isPending || generateAllMutation.isPending || !!getRowWork(row).generating,
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
                label: isSending(invoice.id) ? t('pages.invoices.sending') : t('pages.invoices.sendEmail'),
                icon: <FontAwesomeIcon icon={faEnvelope} fixedWidth />,
                onClick: () => emailMutation.mutate(invoice.id),
                disabled: rowSendLocked(invoice.id),
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

        // Cancelled rows already offer generation or conflict review as primary.
        if (invoice.status === 'draft') {
            const eligibility = row.generation_eligibility
            const destination =
                eligibility && eligibility.state !== 'eligible' ? eligibility.invoice_id : null
            if (destination && (eligibility?.state === 'blocked' || eligibility?.state === 'covered')) {
                const detail = detailDestination(destination)
                items.push({
                    key: 'review-conflict',
                    label: t(
                        eligibility?.state === 'blocked'
                            ? 'pages.invoices.reviewConflict'
                            : 'pages.invoices.viewCoveringInvoice',
                    ),
                    icon: <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />,
                    section: t('pages.invoices.menuSections.invoice'),
                    onClick: () => navigate(detail.pathname, { state: detail.state }),
                })
            } else {
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
                    disabled: generateMutation.isPending || generateAllMutation.isPending || !!getRowWork(row).generating,
                })
            }
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

        if (hasDeletePermission(invoice, userRole)) {
            items.push({
                key: 'delete',
                label: t('pages.invoices.deleteInvoice'),
                icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
                section: t('pages.invoices.menuSections.invoice'),
                onClick: () => onDeleteClick(invoice.id),
                disabled: deleteMutation.isPending,
                danger: true,
            })
        }

        if (invoice.pdf_url) {
            items.push({
                key: 'open-pdf',
                label: t('common.openPdf'),
                icon: <FontAwesomeIcon icon={faFilePdf} fixedWidth />,
                section: t('pages.invoices.menuSections.pdf'),
                onClick: () => void openInvoicePdf(invoice.id),
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

        if (invoice.status === 'sent') {
            items.push({
                key: 'resend-email',
                label: t('pages.invoices.resendEmail'),
                icon: <FontAwesomeIcon icon={faEnvelope} fixedWidth />,
                section: t('pages.invoices.menuSections.email'),
                onClick: () => emailMutation.mutate(invoice.id),
                disabled: rowSendLocked(invoice.id),
            })
        }

        return items
    }

    return {
        generateMutation,
        pdfMutation,
        approveMutation,
        deleteMutation,
        emailMutation,
        markSentMutation,
        markPaidMutation,
        generateAllMutation,
        approveAllMutation,
        sendAllMutation,
        generateAllPdfsMutation,
        downloadAllPdfsMutation,
        anyBatchPending,
        rowCounts,
        recommendedBatchAction,
        batchMenuItems,
        getRowWork,
        getPrimaryRowAction,
        getRowMenuItems,
    }
}
