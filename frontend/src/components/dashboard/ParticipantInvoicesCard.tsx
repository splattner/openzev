import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { openInvoicePdf } from '../../lib/api/invoices'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import type { Invoice } from '../../types/api'
import { PageSkeleton } from '../PageSkeleton'

interface ParticipantInvoicesCardProps {
    invoices: Invoice[]
    isLoading: boolean
    isError: boolean
    allCommunities: boolean
}

export function ParticipantInvoicesCard({ invoices, isLoading, isError, allCommunities }: ParticipantInvoicesCardProps) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()

    return (
        <section className="card">
            <h3 style={{ marginTop: 0 }}>{t(allCommunities ? 'pages.dashboard.invoicesAllCommunitiesSection' : 'pages.dashboard.invoicesSection')}</h3>
            {isLoading ? (
                <PageSkeleton variant="tableRows" />
            ) : isError ? (
                <p className="muted">{t('pages.dashboard.failedInvoices')}</p>
            ) : invoices.length === 0 ? (
                <p className="muted">{t('pages.dashboard.noInvoices')}</p>
            ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                        <tr>
                            <th style={{ textAlign: 'left', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.invoiceCol.invoice')}</th>
                            <th style={{ textAlign: 'left', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.invoiceCol.period')}</th>
                            <th style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.invoiceCol.total')}</th>
                            <th style={{ textAlign: 'left', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.invoiceCol.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {invoices.map((invoice) => (
                            <tr key={invoice.id} style={{ borderTop: '1px solid var(--border-default)' }}>
                                <td style={{ padding: '0.5rem 0.6rem' }}>{invoice.invoice_number}</td>
                                <td style={{ padding: '0.5rem 0.6rem' }}>{formatShortDate(invoice.period_start, settings)} → {formatShortDate(invoice.period_end, settings)}</td>
                                <td style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>CHF {invoice.total_chf}</td>
                                <td style={{ padding: '0.5rem 0.6rem' }}>
                                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                        <Link className="button button-primary" style={{ textDecoration: 'none' }} to={`/billing/invoices/${invoice.id}`} state={{ from: '/' }}>
                                            {t('pages.dashboard.viewDetails')}
                                        </Link>
                                        <button
                                            type="button"
                                            onClick={() => openInvoicePdf(invoice.id)}
                                            className="button button-primary"
                                            style={{ textDecoration: 'none', padding: '0.3rem 0.5rem', lineHeight: 1 }}
                                            aria-label={t('pages.dashboard.openInvoicePdf', { number: invoice.invoice_number })}
                                            title={t('common.openPdf')}
                                        >
                                            📄
                                        </button>
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </section>
    )
}
