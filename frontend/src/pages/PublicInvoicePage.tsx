import { useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { groupItemsByCategory } from '../features/publicInvoice/grouping'
import { fetchPublicInvoice, publicInvoicePdfUrl, requestMagicLink } from '../lib/api/public'

/**
 * One invoice, opened from the QR printed on it. No account, no session.
 *
 * This page mounts outside `ProtectedRoute` and deliberately renders no app
 * chrome: the reader has no ZEV switcher, no navigation and nothing to log
 * into, and showing the shell of an application they cannot enter would be
 * worse than showing a document.
 */
export function PublicInvoicePage() {
    const { t, i18n } = useTranslation()
    const { prefix = '' } = useParams<{ prefix: string }>()
    const [searchParams] = useSearchParams()
    const secret = searchParams.get('s') ?? ''

    const { data, isPending, isError } = useQuery({
        queryKey: ['public-invoice', prefix, secret],
        queryFn: () => fetchPublicInvoice(prefix, secret),
        enabled: Boolean(prefix && secret),
        // A bad link does not become good by asking again, and every failure
        // here is a 404 rather than a transient error.
        retry: false,
    })

    const grouped = useMemo(() => (data ? groupItemsByCategory(data.items) : []), [data])

    const [linkRequested, setLinkRequested] = useState(false)
    const magicLink = useMutation({
        mutationFn: () => requestMagicLink(prefix, secret),
        // The backend answers 202 whatever happens, so there is no failure to
        // distinguish and nothing to report differently. Showing one outcome
        // is not a simplification here — it is the design.
        onSettled: () => setLinkRequested(true),
    })

    const formatMoney = (value: string) =>
        new Intl.NumberFormat(i18n.language, { minimumFractionDigits: 2 }).format(Number(value))

    const formatDate = (value: string) =>
        new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium' }).format(new Date(value))

    if (!prefix || !secret || isError) {
        return (
            <div className="center-screen">
                <div className="card public-invoice-card">
                    <h2>{t('pages.publicInvoice.invalidTitle')}</h2>
                    <p className="muted">{t('pages.publicInvoice.invalidBody')}</p>
                </div>
            </div>
        )
    }

    if (isPending || !data) {
        return (
            <div className="center-screen">
                <div className="card public-invoice-card">
                    <p className="muted">{t('pages.publicInvoice.loading')}</p>
                </div>
            </div>
        )
    }

    return (
        <div className="public-invoice-page">
            <main className="public-invoice-sheet">
                <header className="public-invoice-header">
                    <div>
                        <div className="public-invoice-zev">{data.zev_name}</div>
                        <h1>{t('pages.publicInvoice.title', { number: data.invoice_number })}</h1>
                        <p className="muted">
                            {formatDate(data.period_start)} – {formatDate(data.period_end)}
                        </p>
                    </div>
                    <div className="public-invoice-total">
                        <span
                            className={`public-invoice-status${data.is_paid ? ' is-paid' : ''}`}
                        >
                            {data.is_paid
                                ? t('pages.publicInvoice.paid')
                                : t('pages.publicInvoice.notPaid')}
                        </span>
                        <div className="public-invoice-amount">
                            <span className="public-invoice-currency">{data.currency}</span>
                            {formatMoney(data.total_chf)}
                        </div>
                    </div>
                </header>

                {data.energy_summary && (
                    <section className="public-invoice-kpis">
                        <div className="public-invoice-kpi">
                            <span className="kpi-label">{t('pages.publicInvoice.localEnergy')}</span>
                            <span className="kpi-value">
                                {data.energy_summary.local_kwh}
                                <small> kWh</small>
                            </span>
                        </div>
                        <div className="public-invoice-kpi">
                            <span className="kpi-label">{t('pages.publicInvoice.gridEnergy')}</span>
                            <span className="kpi-value">
                                {data.energy_summary.grid_kwh}
                                <small> kWh</small>
                            </span>
                        </div>
                        <div className="public-invoice-kpi">
                            <span className="kpi-label">{t('pages.publicInvoice.localShare')}</span>
                            <span className="kpi-value">
                                {data.energy_summary.local_share_pct}
                                <small> %</small>
                            </span>
                        </div>
                    </section>
                )}

                <section className="public-invoice-items">
                    {grouped.map((group) => (
                        <div key={group.category} className="public-invoice-group">
                            <h2>{t(`pages.publicInvoice.categories.${group.category}`)}</h2>
                            <table>
                                <tbody>
                                    {group.items.map((item, index) => (
                                        <tr key={`${group.category}-${index}`}>
                                            <td>{item.description}</td>
                                            <td className="numeric muted">
                                                {item.quantity} {item.unit}
                                            </td>
                                            <td className="numeric">{formatMoney(item.total_chf)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    ))}
                </section>

                <section className="public-invoice-more">
                    {linkRequested ? (
                        <p className="muted">{t('pages.publicInvoice.linkSent')}</p>
                    ) : (
                        <>
                            <p className="muted">{t('pages.publicInvoice.moreBody')}</p>
                            <button
                                type="button"
                                className="button button-primary"
                                disabled={magicLink.isPending}
                                onClick={() => magicLink.mutate()}
                            >
                                {t('pages.publicInvoice.requestLink')}
                            </button>
                        </>
                    )}
                </section>

                <footer className="public-invoice-footer">
                    {data.has_pdf && (
                        <a
                            className="button button-secondary"
                            href={publicInvoicePdfUrl(prefix, secret)}
                            target="_blank"
                            rel="noreferrer"
                        >
                            {t('pages.publicInvoice.downloadPdf')}
                        </a>
                    )}
                    <p className="muted public-invoice-note">
                        {t('pages.publicInvoice.recipientNote', { name: data.participant_name })}
                    </p>
                </footer>
            </main>
        </div>
    )
}
