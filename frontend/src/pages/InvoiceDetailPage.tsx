import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { fetchInvoice } from '../lib/api'
import { formatShortDate, useAppSettings } from '../lib/appSettings'

function humanizeType(type: string): string {
    return type
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (char) => char.toUpperCase())
}

export function InvoiceDetailPage() {
    const { t } = useTranslation()
    const { invoiceId } = useParams<{ invoiceId: string }>()
    const { settings } = useAppSettings()

    const invoiceQuery = useQuery({
        queryKey: ['invoice', invoiceId],
        queryFn: () => fetchInvoice(invoiceId as string),
        enabled: !!invoiceId,
    })

    if (invoiceQuery.isLoading) {
        return <div className="card">Loading invoice details...</div>
    }
    if (invoiceQuery.isError || !invoiceQuery.data) {
        return <div className="card error-banner">Failed to load invoice details.</div>
    }

    const inv = invoiceQuery.data
    const groupedItems = Object.entries(
        (inv.items || []).reduce<Record<string, NonNullable<typeof inv.items>>>((groups, item) => {
            const key = item.tariff_category || 'energy'
            if (!groups[key]) {
                groups[key] = []
            }
            groups[key].push(item)
            return groups
        }, {}),
    )

    return (
        <div className="page-stack">
            <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
                <div>
                    <h2 style={{ marginBottom: '0.2rem' }}>Invoice {inv.invoice_number}</h2>
                    <p className="muted" style={{ margin: 0 }}>
                        {inv.participant_name} · {formatShortDate(inv.period_start, settings)} → {formatShortDate(inv.period_end, settings)}
                    </p>
                </div>
                <Link to="/invoices" className="button button-primary" style={{ textDecoration: 'none' }}>
                    {t('pages.invoiceDetail.backToInvoices')}
                </Link>
            </header>

            <section className="grid grid-4">
                <div className="card"><strong>{t('pages.invoiceDetail.status')}</strong><div>{inv.status}</div></div>
                <div className="card"><strong>{t('pages.invoiceDetail.total')}</strong><div>CHF {inv.total_chf}</div></div>
                <div className="card"><strong>{t('pages.invoiceDetail.subtotal')}</strong><div>CHF {inv.subtotal_chf ?? '-'}</div></div>
                <div className="card"><strong>{t('pages.invoiceDetail.vat')}</strong><div>CHF {inv.vat_chf ?? '-'}</div></div>
            </section>

            <section className="card">
                <h3 style={{ marginTop: 0 }}>{t('pages.invoiceDetail.energyTotals')}</h3>
                <div className="inline-form grid grid-4">
                    <div><strong>{t('pages.invoiceDetail.local')}</strong><div>{inv.total_local_kwh ?? '0'} kWh</div></div>
                    <div><strong>{t('pages.invoiceDetail.grid')}</strong><div>{inv.total_grid_kwh ?? '0'} kWh</div></div>
                    <div><strong>{t('pages.invoiceDetail.feedIn')}</strong><div>{inv.total_feed_in_kwh ?? '0'} kWh</div></div>
                </div>
            </section>

            <section className="table-card">
                <h3 style={{ marginTop: 0, padding: '1rem 1rem 0' }}>{t('pages.invoiceDetail.lineItems')}</h3>
                {groupedItems.length ? groupedItems.map(([category, items]) => {
                    const subtotal = items.reduce((sum, item) => sum + Number(item.total_chf), 0)
                    const categoryLabel = t(`pages.invoiceDetail.categories.${category}` as Parameters<typeof t>[0], { defaultValue: category })
                    return (
                        <div key={category} style={{ padding: '1rem' }}>
                            <h4 style={{ margin: '0 0 0.75rem' }}>{categoryLabel}</h4>
                            <table>
                                <thead>
                                    <tr>
                                        <th>{t('pages.invoiceDetail.col.type')}</th>
                                        <th>{t('pages.invoiceDetail.col.description')}</th>
                                        <th>{t('pages.invoiceDetail.col.quantity')}</th>
                                        <th>{t('pages.invoiceDetail.col.unit')}</th>
                                        <th>{t('pages.invoiceDetail.col.unitPrice')}</th>
                                        <th>{t('pages.invoiceDetail.col.total')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {items.map((item) => (
                                        <tr key={item.id}>
                                            <td>
                                                {t(`pages.invoiceDetail.itemTypes.${item.item_type}` as Parameters<typeof t>[0], {
                                                    defaultValue: humanizeType(item.item_type),
                                                })}
                                            </td>
                                            <td>{item.description}</td>
                                            <td>{item.quantity_kwh}</td>
                                            <td>{item.unit}</td>
                                            <td>{item.unit_price_chf}</td>
                                            <td>{item.total_chf}</td>
                                        </tr>
                                    ))}
                                    <tr>
                                        <td colSpan={5}><strong>{categoryLabel} subtotal</strong></td>
                                        <td><strong>{subtotal.toFixed(2)}</strong></td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    )
                }) : (
                    <div style={{ padding: '1rem' }}>{t('pages.invoiceDetail.noItems')}</div>
                )}
            </section>
        </div>
    )
}
