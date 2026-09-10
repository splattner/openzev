import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faFileInvoice } from '@fortawesome/free-solid-svg-icons'
import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { isInvoiceOverdue, selectOpenInvoices, sumTotalChf } from '../../features/invoices/openInvoices'
import { OPEN_INVOICE_STATUSES } from '../../features/invoices/invoiceStatus'
import { fetchInvoices } from '../../lib/api/invoices'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatIsoDate } from '../../lib/dates'
import { useManagedZev } from '../../lib/managedZev'
import { PageSkeleton } from '../PageSkeleton'

/** Short manager exception list; the full workflow stays in Billing. */
export function OpenInvoicesCard() {
    const { t } = useTranslation()
    const { selectedZevId } = useManagedZev()
    const statusFilter = OPEN_INVOICE_STATUSES.join(',')
    const invoicesQuery = useQuery({
        queryKey: queryKeys.invoices.list(selectedZevId || undefined, statusFilter),
        queryFn: () => fetchInvoices(selectedZevId || undefined, { status: statusFilter }),
        enabled: !!selectedZevId,
    })
    const today = useMemo(() => formatIsoDate(new Date()), [])
    const openInvoices = useMemo(
        () => selectOpenInvoices(invoicesQuery.data ?? []),
        [invoicesQuery.data],
    )
    const overdueCount = useMemo(
        () => openInvoices.filter((invoice) => isInvoiceOverdue(invoice, today)).length,
        [openInvoices, today],
    )

    return (
        <section className="card">
            <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.openInvoices.title')}</h3>
            {invoicesQuery.isLoading ? (
                <PageSkeleton variant="tableRows" />
            ) : invoicesQuery.isError ? (
                <p className="muted">{t('pages.dashboard.failedInvoices')}</p>
            ) : openInvoices.length === 0 ? (
                <p className="muted">{t('pages.dashboard.openInvoices.empty')}</p>
            ) : (
                <>
                    <ul className="open-invoices-list">
                        {openInvoices.slice(0, 5).map((invoice) => (
                            <li key={invoice.id}>
                                <span className="open-invoice-main">
                                    <span className="open-invoice-number">{invoice.invoice_number}</span>
                                    <span className="open-invoice-participant">{invoice.participant_name}</span>
                                </span>
                                <span className="open-invoice-amount">CHF {invoice.total_chf}</span>
                                {isInvoiceOverdue(invoice, today) ? (
                                    <span className="badge badge-danger">{t('pages.dashboard.openInvoices.overdue')}</span>
                                ) : (
                                    <span className="badge badge-info">{t('pages.dashboard.openInvoices.open')}</span>
                                )}
                            </li>
                        ))}
                    </ul>
                    <div className="open-invoices-foot">
                        <span>
                            {t('pages.dashboard.openInvoices.outstanding', {
                                openCount: openInvoices.length,
                                overdueCount,
                                amount: sumTotalChf(openInvoices).toFixed(2),
                            })}
                        </span>
                        <Link
                            className="button button-secondary button-compact"
                            to="/billing/invoices"
                        >
                            <FontAwesomeIcon icon={faFileInvoice} fixedWidth />
                            {t('pages.dashboard.openInvoices.viewAll')}
                        </Link>
                    </div>
                </>
            )}
        </section>
    )
}
