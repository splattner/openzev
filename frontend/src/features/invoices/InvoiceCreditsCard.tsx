import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faFilePdf, faReceipt } from '@fortawesome/free-solid-svg-icons'
import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatApiError } from '../../lib/api/errors'
import { correctInvoice, openCreditPdf } from '../../lib/api/invoices'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { formatChfAmount } from '../../lib/numbers'
import { useToast } from '../../lib/toast'
import type { Invoice } from '../../types/api'
import { CorrectInvoiceModal, type CorrectInvoiceValues } from './CorrectInvoiceModal'
import { canCorrectInvoice, creditableChf } from './invoiceCredits'

/**
 * The credit notes issued for an invoice (#388) and, for managers, the
 * "Correct invoice" action that issues one. Hidden when there is nothing to
 * show and nothing to do.
 */
export function InvoiceCreditsCard({
    invoice,
    canManage,
    onChanged,
}: {
    invoice: Invoice
    canManage: boolean
    /** Called with the invoice the server returned after a correction. */
    onChanged: (invoice: Invoice) => void
}) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { pushToast } = useToast()
    const [correcting, setCorrecting] = useState(false)

    const credits = invoice.credits ?? []
    const canCorrect = canCorrectInvoice(invoice, canManage)
    const creditable = creditableChf(invoice)

    const correctMutation = useMutation({
        mutationFn: (values: CorrectInvoiceValues) => correctInvoice(invoice.id, values),
        onSuccess: ({ invoice: updated }) => {
            setCorrecting(false)
            pushToast(t('pages.invoiceDetail.credits.corrected'), 'success')
            onChanged(updated)
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoiceDetail.credits.correctFailed')), 'error'),
    })
    const pdfMutation = useMutation({
        mutationFn: (creditId: string) => openCreditPdf(creditId),
        onError: (error) => pushToast(formatApiError(error, t('pages.invoiceDetail.credits.pdfFailedToast')), 'error'),
    })

    if (credits.length === 0 && !canCorrect) return null

    return (
        <section className="card" aria-labelledby="invoice-credits-title">
            <div className="card-header">
                <h3 id="invoice-credits-title">{t('pages.invoiceDetail.credits.title')}</h3>
                {canCorrect ? (
                    <div className="actions-row actions-row-wrap">
                        <button type="button" className="button button-secondary" onClick={() => setCorrecting(true)}>
                            <FontAwesomeIcon icon={faReceipt} fixedWidth />
                            {t('pages.invoiceDetail.credits.correct')}
                        </button>
                    </div>
                ) : null}
            </div>

            {credits.length === 0 ? (
                <p className="muted m-0">{t('pages.invoiceDetail.credits.empty')}</p>
            ) : (
                <div className="table-scroll">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('pages.invoiceDetail.credits.number')}</th>
                                <th>{t('pages.invoiceDetail.credits.date')}</th>
                                <th>{t('pages.invoiceDetail.credits.type')}</th>
                                <th className="numeric">{t('pages.invoiceDetail.credits.amount')}</th>
                                <th>{t('pages.invoiceDetail.credits.reasonCol')}</th>
                                <th><span className="visually-hidden">{t('common.actions')}</span></th>
                            </tr>
                        </thead>
                        <tbody>
                            {credits.map((credit) => (
                                <tr key={credit.id}>
                                    <td>{credit.credit_number}</td>
                                    <td>{formatShortDate(credit.created_at.slice(0, 10), settings)}</td>
                                    <td>{t(`pages.invoiceDetail.credits.kind.${credit.kind}`)}</td>
                                    <td className="numeric">{formatChfAmount(Number(credit.amount_chf))}</td>
                                    <td>{credit.reason}</td>
                                    <td className="numeric">
                                        {credit.pdf_url ? (
                                            <button
                                                type="button"
                                                className="table-inline-link"
                                                aria-label={t('pages.invoiceDetail.credits.openPdf', { number: credit.credit_number })}
                                                title={t('pages.invoiceDetail.credits.openPdf', { number: credit.credit_number })}
                                                disabled={pdfMutation.isPending}
                                                onClick={() => pdfMutation.mutate(credit.id)}
                                            >
                                                <FontAwesomeIcon icon={faFilePdf} fixedWidth />
                                            </button>
                                        ) : (
                                            <span className="muted">
                                                {credit.pdf_status === 'failed'
                                                    ? t('pages.invoiceDetail.credits.pdfFailed')
                                                    : t('pages.invoiceDetail.credits.pdfPending')}
                                            </span>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            <CorrectInvoiceModal
                isOpen={correcting}
                isPending={correctMutation.isPending}
                creditableChf={creditable.toFixed(2)}
                onClose={() => setCorrecting(false)}
                onSubmit={(values) => correctMutation.mutate(values)}
            />
        </section>
    )
}
