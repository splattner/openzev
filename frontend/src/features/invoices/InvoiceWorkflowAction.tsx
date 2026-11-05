import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { InvoiceActionButton } from '../../components/InvoicePresentation'
import { IssueText } from '../../components/IssueText'
import { Notice } from '../../components/Notice'
import { approveInvoice, sendInvoiceEmail } from '../../lib/api/invoices'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { useAuth } from '../../lib/auth'
import { useToast } from '../../lib/toast'
import { useWriteScope } from '../../lib/useWriteScope'
import type { Invoice } from '../../types/api'
import { getLatestEmailLog } from './emailLogs'
import { nextInvoiceWorkflowAction } from './invoiceStatus'
import { useEmailDelivery } from './useEmailDelivery'

export function InvoiceWorkflowAction({ invoice, canManage, onChanged }: {
    invoice: Invoice
    canManage: boolean
    onChanged: (invoice: Invoice) => void
}) {
    const { t } = useTranslation()
    const { user } = useAuth()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const { scope, isCurrent, assertWritable } = useWriteScope({
        selectedZevId: invoice.zev, accountId: user?.id, scopeKey: invoice.id, canWrite: canManage,
    }, t('common.error'))
    const refreshInvoice = useCallback(() => {
        void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.detail(invoice.id) })
    }, [queryClient, invoice.id])
    const refreshRelated = useCallback(() => {
        void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.lists() })
        void queryClient.invalidateQueries({ queryKey: ['invoices', 'period-overview'] })
        void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.mine() })
        void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.credits() })
        for (const key of ['readiness', 'readiness-list', 'attention']) {
            void queryClient.invalidateQueries({ queryKey: ['invoices', key] })
        }
    }, [queryClient])
    const rows = useMemo(() => [{ invoice }], [invoice])
    const delivery = useEmailDelivery({ rows, scope, refreshOverview: refreshInvoice, refreshRelated, showTimeoutToast: false })
    const latestLog = getLatestEmailLog(invoice)
    const observedPendingLog = useRef<string | null>(null)
    const nextAction = nextInvoiceWorkflowAction(invoice)
    useEffect(() => {
        if (!canManage || nextAction !== 'send-email' || latestLog?.status !== 'pending' || observedPendingLog.current === latestLog.id) return
        observedPendingLog.current = latestLog.id
        if (!delivery.isTracking(invoice.id)) delivery.track([{ invoiceId: invoice.id, previousLogId: null }])
    }, [canManage, nextAction, latestLog, delivery, invoice.id])
    const mutation = useMutation({
        mutationFn: async ({ operation, submittedScope }: {
            operation: 'approve' | 'send-email'; submittedScope: typeof scope; previousLogId: string | null
        }) => {
            assertWritable(submittedScope)
            if (invoice.needs_data_review || nextInvoiceWorkflowAction(invoice) !== operation) throw new Error(t('common.error'))
            if (operation === 'approve') return approveInvoice(invoice.id)
            await sendInvoiceEmail(invoice.id)
            return null
        },
        onSuccess: (updated, { operation, submittedScope, previousLogId }) => {
            if (!isCurrent(submittedScope)) { refreshInvoice(); return }
            if (updated) onChanged(updated)
            else {
                delivery.track([{ invoiceId: invoice.id, previousLogId, announce: true }])
                refreshRelated()
                refreshInvoice()
            }
            pushToast(t(`pages.invoices.messages.${operation === 'approve' ? 'approved' : 'emailQueued'}`), 'success')
        },
        onError: (error, { operation, submittedScope }) => {
            if (isCurrent(submittedScope)) pushToast(formatApiError(error, t(`pages.invoices.messages.${operation === 'approve' ? 'approveFailed' : 'sendEmailFailed'}`)), 'error')
        },
    })
    // Sent invoices already have their next action in the payments card.
    if (!canManage || invoice.needs_data_review || nextAction === null || nextAction === 'mark-paid') return null
    const sending = nextAction === 'send-email' && !delivery.hasTimedOut && (delivery.isTracking(invoice.id) || latestLog?.status === 'pending')
    return (
        <div aria-busy={mutation.isPending || sending}>
            {delivery.hasTimedOut && <Notice tone="warning" onRetry={() => { refreshInvoice(); delivery.resumePolling() }}>{t('pages.invoices.messages.emailPollingTimeout')}</Notice>}
            {nextAction === 'send-email' && latestLog?.status === 'failed' && !sending && !delivery.hasTimedOut && <p className="m-0"><IssueText>{t('pages.invoices.issues.delivery')}</IssueText></p>}
            <div className="actions-row actions-row-end">
                <InvoiceActionButton compact={false} action={{
                    label: t(`pages.invoices.${sending || (nextAction === 'send-email' && mutation.isPending) ? 'sending' : nextAction === 'approve' ? 'approve' : 'sendEmail'}`),
                    disabled: mutation.isPending || sending || delivery.hasTimedOut,
                    onClick: () => mutation.mutate({ operation: nextAction, submittedScope: scope, previousLogId: latestLog?.id ?? null }),
                }} />
            </div>
        </div>
    )
}
