import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faMoneyBillWave, faPlus, faTrash } from '@fortawesome/free-solid-svg-icons'
import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ConfirmDialog, consumeReportedError, useConfirmDialog } from '../../components/ConfirmDialog'
import { formatApiError } from '../../lib/api/errors'
import { deletePayment, markInvoicePaid, recordPayment } from '../../lib/api/invoices'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { formatChf, formatChfAmount } from '../../lib/numbers'
import { useToast } from '../../lib/toast'
import type { Invoice, Payment } from '../../types/api'
import { RecordPaymentModal } from './RecordPaymentModal'

/**
 * What was received for an invoice (#388): the payments, the amount still
 * owed and, for managers, recording or removing a payment. Payments are
 * booked against a sent invoice; it turns paid once they cover the total.
 */
export function InvoicePaymentsCard({
    invoice,
    canManage,
    onChanged,
}: {
    invoice: Invoice
    canManage: boolean
    /** Called with the invoice the server returned after a change. */
    onChanged: (invoice: Invoice) => void
}) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { pushToast } = useToast()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading } = useConfirmDialog()
    const [recording, setRecording] = useState(false)

    const payments = invoice.payments ?? []
    const outstanding = Number(invoice.outstanding_chf ?? 0)
    const canRecord = canManage && invoice.status === 'sent'
    // Once credit notes exist the payments they were issued against are fixed.
    const hasCredits = (invoice.credits ?? []).length > 0
    // A payout (negative total) or a zero total is settled in one step.
    const collectsMoney = Number(invoice.total_chf) > 0

    const recordMutation = useMutation({
        mutationFn: (values: { amount_chf: string; paid_on: string; note: string }) => recordPayment(invoice.id, values),
        onSuccess: (updated) => {
            setRecording(false)
            pushToast(t('pages.invoiceDetail.payments.recorded'), 'success')
            onChanged(updated)
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoiceDetail.payments.recordFailed')), 'error'),
    })
    const markPaidMutation = useMutation({
        mutationFn: () => markInvoicePaid(invoice.id),
        onSuccess: (updated) => {
            pushToast(t('pages.invoices.messages.markedPaid'), 'success')
            onChanged(updated)
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoices.messages.markPaidFailed')), 'error'),
    })
    const deleteMutation = useMutation({
        mutationFn: (payment: Payment) => deletePayment(invoice.id, payment.id),
        onSuccess: (updated) => {
            pushToast(t('pages.invoiceDetail.payments.removed'), 'success')
            onChanged(updated)
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoiceDetail.payments.removeFailed')), 'error'),
    })

    if (payments.length === 0 && !canRecord) return null

    return (
        <section className="card" aria-labelledby="invoice-payments-title">
            <div className="card-header">
                <h3 id="invoice-payments-title">{t('pages.invoiceDetail.payments.title')}</h3>
                {canRecord ? (
                    <div className="actions-row actions-row-wrap">
                        {collectsMoney ? (
                            <button type="button" className="button button-secondary" onClick={() => setRecording(true)}>
                                <FontAwesomeIcon icon={faPlus} fixedWidth />
                                {t('pages.invoiceDetail.payments.record')}
                            </button>
                        ) : null}
                        <button
                            type="button"
                            className="button button-primary"
                            disabled={markPaidMutation.isPending}
                            onClick={() => markPaidMutation.mutate()}
                        >
                            <FontAwesomeIcon icon={faMoneyBillWave} fixedWidth />
                            {payments.length > 0 ? t('pages.invoiceDetail.payments.markRestPaid') : t('pages.invoices.markPaid')}
                        </button>
                    </div>
                ) : null}
            </div>

            <p className="muted">
                {invoice.status === 'cancelled'
                    ? t('pages.invoiceDetail.payments.summaryCancelled', { paid: formatChf(Number(invoice.paid_chf ?? 0)) })
                    : t('pages.invoiceDetail.payments.summary', {
                        paid: formatChf(Number(invoice.paid_chf ?? 0)),
                        outstanding: formatChf(outstanding),
                    })}
            </p>

            {payments.length === 0 ? (
                <p className="muted m-0">{t('pages.invoiceDetail.payments.empty')}</p>
            ) : (
                <div className="table-scroll">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('pages.invoiceDetail.payments.paidOn')}</th>
                                <th className="numeric">{t('pages.invoiceDetail.payments.amount')}</th>
                                <th>{t('pages.invoiceDetail.payments.note')}</th>
                                <th>{t('pages.invoiceDetail.payments.recordedBy')}</th>
                                {canManage ? <th><span className="visually-hidden">{t('common.actions')}</span></th> : null}
                            </tr>
                        </thead>
                        <tbody>
                            {payments.map((payment) => (
                                <tr key={payment.id}>
                                    <td>{formatShortDate(payment.paid_on, settings)}</td>
                                    <td className="numeric">{formatChfAmount(Number(payment.amount_chf))}</td>
                                    <td>{payment.note || <span className="muted">{t(`pages.invoiceDetail.payments.source.${payment.source}`)}</span>}</td>
                                    <td>{payment.created_by_name ?? <span className="muted">-</span>}</td>
                                    {canManage ? (
                                        <td className="numeric">
                                            {invoice.status !== 'cancelled' && !hasCredits ? (
                                                <button
                                                    type="button"
                                                    className="table-inline-link"
                                                    aria-label={t('pages.invoiceDetail.payments.remove')}
                                                    title={t('pages.invoiceDetail.payments.remove')}
                                                    onClick={() => confirm({
                                                        title: t('pages.invoiceDetail.payments.removeTitle'),
                                                        message: t('pages.invoiceDetail.payments.removeMessage', {
                                                            amount: formatChf(Number(payment.amount_chf)),
                                                            date: formatShortDate(payment.paid_on, settings),
                                                        }),
                                                        confirmText: t('pages.invoiceDetail.payments.remove'),
                                                        isDangerous: true,
                                                        onConfirm: () => consumeReportedError(deleteMutation.mutateAsync(payment)),
                                                    })}
                                                >
                                                    <FontAwesomeIcon icon={faTrash} fixedWidth />
                                                </button>
                                            ) : null}
                                        </td>
                                    ) : null}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            <RecordPaymentModal
                isOpen={recording}
                isPending={recordMutation.isPending}
                outstandingChf={outstanding.toFixed(2)}
                onClose={() => setRecording(false)}
                onSubmit={(values) => recordMutation.mutate(values)}
            />
            {dialog && <ConfirmDialog {...dialog} isLoading={isLoading} onConfirm={handleConfirm} onCancel={handleCancel} />}
        </section>
    )
}
