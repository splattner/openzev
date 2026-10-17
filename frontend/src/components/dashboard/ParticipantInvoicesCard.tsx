import { useTranslation } from 'react-i18next'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import type { Invoice } from '../../types/api'
import { InvoiceLink, InvoicePdfCell, InvoiceRowActions, InvoiceStatusBadge, InvoiceTotal } from '../InvoicePresentation'
import { Notice } from '../Notice'
import { PageSkeleton } from '../PageSkeleton'

interface ParticipantInvoicesCardProps {
    /** Undefined until a response arrives. */
    invoices: Invoice[] | undefined
    isError: boolean
    isRetrying: boolean
    onRetry: () => void
    showCommunity: boolean
}

export function ParticipantInvoicesCard({ invoices, isError, isRetrying, onRetry, showCommunity }: ParticipantInvoicesCardProps) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const errorNotice = (
        <Notice tone={invoices ? 'warning' : 'error'} onRetry={onRetry} isRetrying={isRetrying}>
            {t('pages.dashboard.failedInvoices')}
        </Notice>
    )
    if (isError && !invoices) return errorNotice

    return (
        <section className="card">
            <h3>{t(showCommunity ? 'pages.dashboard.invoicesAllCommunitiesSection' : 'pages.dashboard.invoicesSection')}</h3>
            {isError && errorNotice}
            {!invoices ? (
                <PageSkeleton variant="tableRows" />
            ) : invoices.length === 0 ? (
                <p className="muted">{t('pages.dashboard.noInvoices')}</p>
            ) : (
                <div className="table-scroll">
                    <table className="billing-workflow-table">
                        <thead>
                            <tr>
                                <th scope="col">{t('pages.dashboard.invoiceCol.invoice')}</th>
                                {showCommunity && <th scope="col">{t('pages.dashboard.invoiceCol.community')}</th>}
                                <th scope="col">{t('pages.dashboard.invoiceCol.period')}</th>
                                <th scope="col">{t('pages.dashboard.invoiceCol.total')}</th>
                                <th scope="col">{t('pages.dashboard.invoiceCol.status')}</th>
                                <th scope="col">{t('pages.dashboard.invoiceCol.actions')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {invoices.map((invoice) => (
                                <tr key={invoice.id}>
                                    <td className="invoice-number-cell"><InvoiceLink invoice={invoice} from="/" /></td>
                                    {showCommunity && <td>{invoice.zev_name}</td>}
                                    <td className="billing-period-cell">
                                        {formatShortDate(invoice.period_start, settings)} →{' '}
                                        {formatShortDate(invoice.period_end, settings)}
                                    </td>
                                    <td className="numeric"><InvoiceTotal invoice={invoice} /></td>
                                    <td><InvoiceStatusBadge status={invoice.status} paidChf={invoice.paid_chf} /></td>
                                    <td>
                                        <InvoiceRowActions>
                                            <InvoiceLink className="button button-secondary" invoice={invoice} from="/">
                                                {t('pages.dashboard.viewDetails')}
                                            </InvoiceLink>
                                            <InvoicePdfCell
                                                invoice={invoice}
                                                showReadyStatus={false}
                                                keepExistingDuringPending
                                                buttonClassName="button button-secondary"
                                                ariaLabel={t('pages.dashboard.openInvoicePdf', { number: invoice.invoice_number })}
                                            />
                                        </InvoiceRowActions>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </section>
    )
}
