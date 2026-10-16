import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { formatChfAmount } from '../../lib/numbers'
import type { Invoice } from '../../types/api'
import { amountDueChf, hasCreditApplied } from './invoiceCredits'

/**
 * How the amount due comes about (#388): the invoice total, each credit note
 * set against it and what is left to pay, set out as the PDF prints it.
 * Renders nothing unless credit was applied.
 */
export function InvoiceAppliedCreditsCard({ invoice }: {
    invoice: Pick<Invoice, 'status' | 'total_chf' | 'credit_applied_chf' | 'amount_due_chf' | 'credit_applications'>
}) {
    const { t } = useTranslation()
    if (!hasCreditApplied(invoice)) return null
    const applications = (invoice.credit_applications ?? []).filter((application) => application.released_at === null)

    return (
        <section className="card" aria-labelledby="invoice-applied-credits-title">
            <div className="card-header">
                <h3 id="invoice-applied-credits-title">{t('pages.invoiceDetail.appliedCredits.title')}</h3>
            </div>
            <p className="muted">{t('pages.invoiceDetail.appliedCredits.description')}</p>
            <div className="table-scroll">
                <table className="data-table credit-statement">
                    <thead>
                        <tr>
                            <th>{t('pages.invoiceDetail.appliedCredits.item')}</th>
                            <th className="numeric">{t('pages.invoiceDetail.appliedCredits.amount')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>{t('pages.invoiceDetail.appliedCredits.invoiceTotal')}</td>
                            <td className="numeric">{formatChfAmount(Number(invoice.total_chf))}</td>
                        </tr>
                        {applications.map((application) => (
                            <tr key={application.id}>
                                <td>
                                    {t('pages.invoiceDetail.appliedCredits.credit', { number: application.credit_number })}
                                    {application.credit_source_invoice && application.credit_source_invoice_number ? (
                                        <small className="muted credit-statement-source">
                                            {t('pages.invoiceDetail.appliedCredits.fromInvoice')}{' '}
                                            <Link to={`/billing/invoices/${application.credit_source_invoice}`}>
                                                {application.credit_source_invoice_number}
                                            </Link>
                                        </small>
                                    ) : null}
                                </td>
                                <td className="numeric">{formatChfAmount(-Number(application.amount_chf))}</td>
                            </tr>
                        ))}
                    </tbody>
                    <tfoot>
                        <tr>
                            <td>{t('pages.invoiceDetail.appliedCredits.amountDue')}</td>
                            <td className="numeric">{formatChfAmount(amountDueChf(invoice))}</td>
                        </tr>
                    </tfoot>
                </table>
            </div>
        </section>
    )
}
