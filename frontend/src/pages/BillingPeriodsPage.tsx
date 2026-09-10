import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { BillingPeriodCard } from '../components/BillingPeriodCard'
import { PageSkeleton } from '../components/PageSkeleton'
import { groupPeriodCards, periodKey } from '../features/overview/periodCards'
import { attentionText } from '../features/overview/readinessPresentation'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { fetchReadinessList } from '../lib/api/readiness'
import { queryKeys } from '../lib/api/queryKeys'
import { useManagedZev } from '../lib/managedZev'
import type { AttentionItem } from '../types/api'

type AttentionQuery = { data?: AttentionItem[]; isLoading: boolean; isError: boolean }

/** A single home for each period's work, including cross-period exceptions. */
export function BillingPeriodsPage({ attentionQuery }: { attentionQuery?: AttentionQuery } = {}) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { selectedZevId } = useManagedZev()
    const periodsQuery = useQuery({
        queryKey: queryKeys.invoices.readinessList(selectedZevId || undefined),
        queryFn: () => fetchReadinessList(selectedZevId!),
        enabled: !!selectedZevId,
    })

    if (!selectedZevId) return <div className="card">{t('pages.dashboard.selectZev')}</div>

    const { open, current, completed, community } = groupPeriodCards(
        periodsQuery.data ?? [], attentionQuery?.data ?? [],
    )
    const format = (value: string) => formatShortDate(value, settings)
    // Unknown alert state must not present a period as fully processed.
    const alertsKnown = !attentionQuery || (!attentionQuery.isLoading && !attentionQuery.isError)
    const loaded = !periodsQuery.isLoading && !periodsQuery.isError && alertsKnown

    return (
        <section className="billing-periods page-stack" id="billing-periods">
            {periodsQuery.isLoading && <PageSkeleton variant="cardList" />}
            {periodsQuery.isError && <p className="card error-banner" role="status">{t('pages.billingPeriods.failed')}</p>}
            {attentionQuery?.isLoading && <PageSkeleton variant="card" />}
            {attentionQuery?.isError && <p className="card error-banner" role="status">{t('pages.dashboard.attention.failed')}</p>}
            {community.length > 0 && (
                <section className="card overview-community-notices">
                    <h3>{t('pages.overview.cards.communityNotices')}</h3>
                    <ul>{community.map((item) => (
                        <li key={item.id}><Link to={item.link}>{attentionText(item, t, format)}</Link></li>
                    ))}</ul>
                </section>
            )}
            {open.length > 0 ? (
                <section aria-labelledby="overview-period-work-title">
                    <h3 className="eyebrow overview-period-section-title" id="overview-period-work-title">{t('pages.overview.cards.workTitle')}</h3>
                    <div className="overview-period-grid">
                        {open.map((entry) => <BillingPeriodCard key={periodKey(entry.period)} entry={entry} />)}
                    </div>
                </section>
            ) : loaded && completed.length > 0 && community.length === 0 ? (
                <div className="card overview-caught-up">
                    <span className="badge badge-success">{t('pages.overview.cards.upToDate')}</span>
                    <h3>{t('pages.overview.cards.noWork')}</h3>
                </div>
            ) : null}
            {current.map(({ period }) => (
                <div className="card billing-current-period" key={periodKey(period)}>
                    <div>
                        <p className="eyebrow">{t('pages.billingPeriods.currentTitle')}</p>
                        <strong className="billing-current-period-range">{format(period.start)} – {format(period.end)}</strong>
                        <p className="muted">{t('pages.billingPeriods.collectingDescription')}</p>
                    </div>
                    <span className="badge badge-info">{t('pages.billingPeriods.status.collecting')}</span>
                </div>
            ))}
            {completed.length > 0 && alertsKnown && (
                <details className="overview-period-details overview-period-history">
                    <summary>{t('pages.billingPeriods.completedSummary', { count: completed.length })}</summary>
                    <ul>{[...completed].reverse().map(({ period }) => (
                        <li key={periodKey(period)}>
                            <span className="overview-history-range">{format(period.start)} – {format(period.end)}</span>
                            <Link className="button button-secondary button-compact" to={`/billing/invoices?period_start=${period.start}&period_end=${period.end}`}>
                                {t('pages.billingPeriods.openInvoices')}
                            </Link>
                        </li>
                    ))}</ul>
                </details>
            )}
        </section>
    )
}
