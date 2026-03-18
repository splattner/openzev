import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { fetchInvoice } from '../lib/api'
import { formatShortDate, useAppSettings } from '../lib/appSettings'

const categoryLabels: Record<string, string> = {
    energy: 'Energy',
    grid_fees: 'Grid Fees',
    levies: 'Levies',
}

export function InvoiceDetailPage() {
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

    const invoice = invoiceQuery.data
    const groupedItems = Object.entries(
        (invoice.items || []).reduce<Record<string, NonNullable<typeof invoice.items>>>((groups, item) => {
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
                    <h2 style={{ marginBottom: '0.2rem' }}>Invoice {invoice.invoice_number}</h2>
                    <p className="muted" style={{ margin: 0 }}>
                        {invoice.participant_name} · {formatShortDate(invoice.period_start, settings)} → {formatShortDate(invoice.period_end, settings)}
                    </p>
                </div>
                <Link to="/invoices" className="button button-primary" style={{ textDecoration: 'none' }}>
                    Back to Invoices
                </Link>
            </header>

            <section className="grid grid-4">
                <div className="card"><strong>Status</strong><div>{invoice.status}</div></div>
                <div className="card"><strong>Total</strong><div>CHF {invoice.total_chf}</div></div>
                <div className="card"><strong>Subtotal</strong><div>CHF {invoice.subtotal_chf ?? '-'}</div></div>
                <div className="card"><strong>VAT</strong><div>CHF {invoice.vat_chf ?? '-'}</div></div>
            </section>

            <section className="card">
                <h3 style={{ marginTop: 0 }}>Energy Totals</h3>
                <div className="inline-form grid grid-4">
                    <div><strong>Local</strong><div>{invoice.total_local_kwh ?? '0'} kWh</div></div>
                    <div><strong>Grid</strong><div>{invoice.total_grid_kwh ?? '0'} kWh</div></div>
                    <div><strong>Feed-in</strong><div>{invoice.total_feed_in_kwh ?? '0'} kWh</div></div>
                </div>
            </section>

            <section className="table-card">
                <h3 style={{ marginTop: 0, padding: '1rem 1rem 0' }}>Line Items</h3>
                {groupedItems.length ? groupedItems.map(([category, items]) => {
                    const subtotal = items.reduce((sum, item) => sum + Number(item.total_chf), 0)
                    return (
                        <div key={category} style={{ padding: '1rem' }}>
                            <h4 style={{ margin: '0 0 0.75rem' }}>{categoryLabels[category] || category}</h4>
                            <table>
                                <thead>
                                    <tr>
                                        <th>Type</th>
                                        <th>Description</th>
                                        <th>Quantity</th>
                                        <th>Unit</th>
                                        <th>Unit Price (CHF)</th>
                                        <th>Total (CHF)</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {items.map((item) => (
                                        <tr key={item.id}>
                                            <td>{item.item_type}</td>
                                            <td>{item.description}</td>
                                            <td>{item.quantity_kwh}</td>
                                            <td>{item.unit}</td>
                                            <td>{item.unit_price_chf}</td>
                                            <td>{item.total_chf}</td>
                                        </tr>
                                    ))}
                                    <tr>
                                        <td colSpan={5}><strong>{categoryLabels[category] || category} subtotal</strong></td>
                                        <td><strong>{subtotal.toFixed(2)}</strong></td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    )
                }) : (
                    <div style={{ padding: '1rem' }}>No invoice items.</div>
                )}
            </section>
        </div>
    )
}
