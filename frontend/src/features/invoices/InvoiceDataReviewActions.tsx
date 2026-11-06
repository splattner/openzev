import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ConfirmDialog, consumeReportedError, useConfirmDialog } from '../../components/ConfirmDialog'
import { replaceInvoice, generateInvoice, previewInvoiceCalculation } from '../../lib/api/invoices'
import { apiErrorPayload, formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatChf } from '../../lib/numbers'
import { Notice } from '../../components/Notice'
import { useAuth } from '../../lib/auth'
import { useToast } from '../../lib/toast'
import { useWriteScope } from '../../lib/useWriteScope'
import { useManagedZev } from '../../lib/managedZev'
import type { Invoice } from '../../types/api'
import { InvoiceCorrectionButton } from './InvoiceCorrectionButton'
import { canCorrectInvoice } from './invoiceCredits'
import { InvoiceEnergyChanges } from './InvoiceEnergyChanges'

export function InvoiceDataReviewActions({ invoice, canManage, onChanged }: {
    invoice: Invoice
    canManage: boolean
    onChanged: (invoice: Invoice) => void
}) {
    const { t } = useTranslation()
    const { user } = useAuth()
    const queryClient = useQueryClient()
    const { setSelectedZevId } = useManagedZev()
    const { pushToast } = useToast()
    const navigate = useNavigate()
    const location = useLocation()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading } = useConfirmDialog()
    const { scope, assertWritable, isCurrent } = useWriteScope({
        selectedZevId: invoice.zev, accountId: user?.id, scopeKey: invoice.id, canWrite: canManage,
    }, t('common.error'))
    const canReplace = (invoice.status === 'approved' || invoice.status === 'sent')
        && invoice.payments?.length === 0 && Number(invoice.paid_chf ?? 0) === 0
    const canGenerate = invoice.status === 'draft' || (invoice.status === 'cancelled' && !invoice.replaced_by)
    const preview = useQuery({
        queryKey: queryKeys.invoices.calculationPreview(invoice.id),
        queryFn: ({ signal }) => previewInvoiceCalculation(invoice.id, signal),
        enabled: canManage && (canReplace || canGenerate),
        retry: false,
        refetchOnWindowFocus: false,
    })
    const mutation = useMutation({
        mutationFn: ({ operation, submittedScope }: { operation: 'replace' | 'generate'; submittedScope: typeof scope }) => {
            assertWritable(submittedScope)
            const calculation = queryClient.getQueryState(queryKeys.invoices.calculationPreview(invoice.id))
            if (calculation?.status !== 'success' || calculation.fetchStatus !== 'idle') throw new Error(t('pages.invoices.dataReview.previewFailed'))
            if (operation === 'replace' && canReplace) return replaceInvoice(invoice.id)
            if (operation === 'generate' && canGenerate) return generateInvoice({
                participant_id: invoice.participant,
                period_start: invoice.period_start,
                period_end: invoice.period_end,
            })
            throw new Error(t('common.error'))
        },
        onSuccess: (updated, { submittedScope }) => {
            if (!isCurrent(submittedScope)) return
            onChanged(updated)
            navigate(`/billing/invoices/${updated.id}`, { replace: true, state: {
                ...location.state,
                recalculation: { invoiceId: updated.id, before: {
                    invoice_number: invoice.invoice_number, total_chf: invoice.total_chf,
                    total_local_kwh: invoice.total_local_kwh, total_grid_kwh: invoice.total_grid_kwh,
                    total_feed_in_kwh: invoice.total_feed_in_kwh,
                } },
            } })
        },
        onError: (error, { submittedScope }) => {
            if (isCurrent(submittedScope)) pushToast(formatApiError(error, t('common.error')), 'error')
        },
    })
    if (!canManage) return null
    if (canCorrectInvoice(invoice, canManage)) {
        return <div className="actions-row actions-row-end"><InvoiceCorrectionButton invoice={invoice} canManage={canManage} onChanged={onChanged} /></div>
    }
    if (!canReplace && !canGenerate) return null
    const operation = canReplace ? 'replace' : 'generate'
    const label = invoice.status === 'draft' ? t('pages.invoices.regenerateInvoice') : t('pages.invoices.dataReview.replace')
    const tariffProblem = ['dynamic_price_gap', 'invalid_dynamic_tariff'].includes(String(apiErrorPayload(preview.error)?.code))
    const previewUnavailable = preview.status !== 'success' || preview.fetchStatus !== 'idle'
    const differenceCents = preview.data ? Math.round(Number(preview.data.total_chf) * 100) - Math.round(Number(invoice.total_chf) * 100) : 0
    const previewFeedback = preview.isError ? (
        <Notice tone="error" onRetry={() => void preview.refetch()} isRetrying={preview.isFetching}>
            <p className="m-0">{t('pages.invoices.dataReview.previewFailed')}</p>
            {tariffProblem && <button type="button" className="button button-secondary mt-05" onClick={() => {
                setSelectedZevId(invoice.zev)
                navigate('/tariffs')
            }}>{t('pages.invoices.emptyState.tariffsAction')}</button>}
        </Notice>
    ) : preview.isPending || preview.isFetching ? (
        <p className="muted m-0" role="status">{t('pages.invoices.dataReview.previewLoading')}</p>
    ) : (
        <div role="status">
            <p className="m-0">
                {t(`pages.invoices.dataReview.${differenceCents === 0 ? 'previewUnchanged' : 'previewAmount'}`)}{' '}
                {differenceCents !== 0 && <><span className="invoice-review-amount muted">{formatChf(Number(invoice.total_chf))}</span>{' → '}</>}
                <strong className="invoice-review-amount">{formatChf(Number(preview.data.total_chf))}</strong>
                {differenceCents !== 0 && <> · {t('pages.invoices.dataReview.previewDifference', {
                    amount: `${differenceCents > 0 ? '+' : '−'}${formatChf(Math.abs(differenceCents) / 100)}`,
                })}</>}
            </p>
            <InvoiceEnergyChanges before={invoice} after={preview.data} />
        </div>
    )
    return (
        <div className="invoice-review-actions">
            {previewFeedback}
            <button type="button" className="button button-primary" disabled={mutation.isPending || previewUnavailable} onClick={() => confirm({
                title: label,
                message: t(`pages.invoices.dataReview.${canReplace ? 'replaceConfirm' : 'regenerateConfirm'}`, { number: invoice.invoice_number }),
                confirmText: label,
                isDangerous: canReplace,
                onConfirm: () => consumeReportedError(mutation.mutateAsync({ operation, submittedScope: scope })),
            })}>
                {label}
            </button>
            {dialog && <ConfirmDialog {...dialog} confirmDisabled={previewUnavailable} isLoading={isLoading} onConfirm={() => { if (!previewUnavailable) void handleConfirm() }} onCancel={handleCancel}><div className="grid-span-full plain-feedback">{previewFeedback}</div></ConfirmDialog>}
        </div>
    )
}
