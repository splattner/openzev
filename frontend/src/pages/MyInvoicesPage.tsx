import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { fetchInvoices, openInvoicePdf } from '../lib/api/invoices'
import { queryKeys } from '../lib/api/queryKeys'
import { invoiceStatusBadgeClass } from '../features/invoices/invoiceStatus'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { formatChf } from '../lib/numbers'
import { PageSkeleton } from '../components/PageSkeleton'
import { useAuth } from '../lib/auth'

/**
 * Participant's own invoices (`/me/invoices`, nav-regroup phase 2): a
 * read-only list over the existing role-scoped backend list (no new grant).
 * PDFs never decide list membership — rows always show, the PDF action is
 * conditional on a stored document.
 */
export function MyInvoicesPage() {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { user } = useAuth()

    const invoicesQuery = useQuery({
        // No zev_id: the backend scopes participants to their own invoices.
        queryKey: queryKeys.invoices.mine(),
        queryFn: () => fetchInvoices(undefined),
    })
    const invoices = invoicesQuery.data ?? []
    // A multi-membership participant needs to know which community issued each
    // invoice; with a single membership the page header already names it.
    const showCommunity = (user?.zev_count ?? 0) > 1

    return (
        <div className="page-stack">
            <header>
                {/* Single membership: the community name is page context, like
                    every other participant page (spec §6). */}
                {user?.zev_count === 1 && user?.zev_name ? <p className="eyebrow">{user.zev_name}</p> : null}
                <h2>{t('pages.myInvoices.title')}</h2>
                <p className="muted">{t('pages.myInvoices.description')}</p>
            </header>

            {invoicesQuery.isLoading ? (
                <PageSkeleton variant="tableRows" />
            ) : invoicesQuery.isError ? (
                <div className="card error-banner">{t('pages.myInvoices.failed')}</div>
            ) : invoices.length === 0 ? (
                <div className="card">
                    <h3 style={{ marginTop: 0 }}>{t('pages.myInvoices.empty.title')}</h3>
                    <p className="muted">{t('pages.myInvoices.empty.description')}</p>
                </div>
            ) : (
                <section className="table-card">
                    <div className="table-scroll">
                        <table className="billing-workflow-table">
                            <thead>
                                <tr>
                                    <th scope="col">{t('pages.myInvoices.col.invoice')}</th>
                                    {showCommunity && <th scope="col">{t('pages.myInvoices.col.community')}</th>}
                                    <th scope="col">{t('pages.myInvoices.col.period')}</th>
                                    <th scope="col">{t('pages.myInvoices.col.total')}</th>
                                    <th scope="col">{t('pages.myInvoices.col.status')}</th>
                                    <th scope="col">{t('pages.myInvoices.col.actions')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {invoices.map((invoice) => (
                                    <tr key={invoice.id}>
                                        <td>{invoice.invoice_number}</td>
                                        {showCommunity && <td>{invoice.zev_name}</td>}
                                        <td className="billing-period-cell">
                                            {formatShortDate(invoice.period_start, settings)} →{' '}
                                            {formatShortDate(invoice.period_end, settings)}
                                        </td>
                                        <td>{formatChf(Number(invoice.total_chf))}</td>
                                        <td>
                                            <span className={invoiceStatusBadgeClass(invoice.status)}>
                                                {t(`invoice.status.${invoice.status}`)}
                                            </span>
                                        </td>
                                        <td>
                                            <div className="actions-row actions-row-wrap">
                                                <Link
                                                    className="button button-secondary"
                                                    to={`/billing/invoices/${invoice.id}`}
                                                    state={{ from: '/me/invoices' }}
                                                >
                                                    {t('pages.myInvoices.viewDetails')}
                                                </Link>
                                                {invoice.pdf_url ? (
                                                    <button
                                                        type="button"
                                                        className="button button-secondary"
                                                        onClick={() => openInvoicePdf(invoice.id)}
                                                        aria-label={t('pages.myInvoices.openPdf', {
                                                            number: invoice.invoice_number,
                                                        })}
                                                        title={t('common.openPdf')}
                                                    >
                                                        📄
                                                    </button>
                                                ) : null}
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </section>
            )}
        </div>
    )
}
