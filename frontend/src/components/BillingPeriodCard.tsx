import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { groupInvoiceAlerts, isOpenStep, primaryPeriodStep, type PeriodCardEntry } from '../features/overview/periodCards'
import { attentionText, stepDetailText } from '../features/overview/readinessPresentation'

export function BillingPeriodCard({ entry }: { entry: PeriodCardEntry }) {
    const { t, i18n } = useTranslation()
    const { settings } = useAppSettings()
    const { period, readiness, alerts } = entry
    const format = (date: string) => formatShortDate(date, settings)
    const primary = primaryPeriodStep(entry)
    const overdue = alerts.filter((item) => item.type === 'invoice_overdue').length
    const failed = Math.max(
        alerts.filter((item) => item.type === 'email_failed').length,
        period.ended === false ? 0 : readiness?.steps.find((step) => step.key === 'sent')?.failed ?? 0,
    )
    const warnings = period.ended === false ? [] : (readiness?.steps ?? []).filter(
        (step) => step.status === 'warn' && step !== primary,
    )
    const tone = overdue ? 'danger' : failed || warnings.length || primary?.status === 'warn' ? 'warning' : 'info'
    const status = overdue ? t('pages.dashboard.openInvoices.overdue')
        : failed ? t('pages.overview.cards.deliveryFailed')
            : primary?.status === 'warn' || warnings.length ? t('pages.billingPeriods.status.attention')
                : readiness?.next_action === 'approve' ? t('pages.overview.cards.readyForReview')
                    : t('pages.billingPeriods.status.inProgress')
    const invoicesUrl = `/billing/invoices?period_start=${period.start}&period_end=${period.end}`
    const destination = primary?.link || alerts[0]?.link || invoicesUrl
    const actionLabel = primary?.link && readiness
        ? readiness.next_action === 'approve' ? t('pages.overview.cards.reviewInvoices')
            : t(`pages.dashboard.cockpit.nextActionLabels.${readiness.next_action}`)
        : alerts.length ? overdue ? t('pages.overview.cards.viewPayments') : t('pages.overview.cards.reviewDelivery')
            : t('pages.billingPeriods.openInvoices')
    // Delivery failures have a single visible aggregate; don't repeat them in
    // the readiness sentence as well as the attention summary.
    const detail = primary ? stepDetailText({ ...primary, failed: 0 }, t) : null
    const month = new Intl.DateTimeFormat(i18n?.resolvedLanguage || 'en', { month: 'long', timeZone: 'UTC' })
    const startMonth = month.format(new Date(`${period.start}T00:00:00Z`))
    const endMonth = month.format(new Date(`${period.end}T00:00:00Z`))
    const sameMonth = period.start.slice(0, 7) === period.end.slice(0, 7)
    const sameYear = period.start.slice(0, 4) === period.end.slice(0, 4)
    const year = sameYear ? period.start.slice(0, 4) : `${period.start.slice(0, 4)}–${period.end.slice(0, 4)}`
    const detailSteps = period.ended === false ? [] : (readiness?.steps ?? []).filter(
        (step) => step !== primary && !warnings.includes(step),
    )

    const pendingSteps = detailSteps.filter(isOpenStep)
    const completedSteps = detailSteps.filter((step) => !isOpenStep(step))

    return (
        <article className={`card overview-period-card overview-period-card--${tone}`}>
            <header>
                <p className="eyebrow">{year}</p>
                <h3>{sameMonth ? startMonth : `${startMonth} – ${endMonth}`}</h3>
                <p className="overview-period-range muted">{format(period.start)} – {format(period.end)}</p>
            </header>
            <span className={`badge badge-${tone}`}>{status}</span>
            <div className="overview-period-work">
                {detail && !(primary?.key === 'paid' && overdue) ? <p className="overview-period-lead">{detail}</p> : null}
                {!detail && primary && readiness ? (
                    <p className="overview-period-lead">{t(`pages.dashboard.cockpit.nextActionLabels.${readiness.next_action}`)}</p>
                ) : null}
                {overdue > 0 && <p className="overview-period-lead">{t('pages.overview.cards.overdue', { count: overdue })}</p>}
                {failed > 0 && <p className="overview-period-lead">{t('pages.overview.cards.failed', { count: failed })}</p>}
                {warnings.map((step) => (
                    <p key={step.key} className="overview-period-warning">
                        {step.link ? <Link to={step.link}>{stepDetailText(step, t) || t(`pages.dashboard.cockpit.stepLabels.${step.key}`)}</Link>
                            : stepDetailText(step, t) || t(`pages.dashboard.cockpit.stepLabels.${step.key}`)}
                    </p>
                ))}
            </div>
            <Link className={`button button-${tone === 'info' && primary?.link ? 'primary' : 'secondary'}`} to={destination}>
                {actionLabel}
            </Link>
            {(detailSteps.length > 0 || alerts.length > 0 || (primary?.key === 'paid' && overdue > 0)) && (
                <details className="overview-period-details">
                    <summary>{t('pages.overview.cards.details')}</summary>
                    <ul className="overview-period-pending">
                        {primary?.key === 'paid' && overdue > 0 && detail && <li>{detail}</li>}
                        {pendingSteps.map((step) => (
                            <li key={step.key}>
                                <div className="overview-step-heading">
                                    {step.link ? (
                                        <Link className="overview-step-link" to={step.link}>
                                            {t(`pages.dashboard.cockpit.stepLabels.${step.key}`)}
                                        </Link>
                                    ) : <strong>{t(`pages.dashboard.cockpit.stepLabels.${step.key}`)}</strong>}
                                    <span className={`badge badge-${step.status === 'warn' ? 'warning' : 'info'}`}>
                                        {t(`pages.dashboard.cockpit.statusLabels.${step.status}`)}
                                    </span>
                                </div>
                                <span className="muted">{stepDetailText({ ...step, failed: 0 }, t) || t(`pages.dashboard.cockpit.statusLabels.${step.status}`)}</span>
                                {step.link && (
                                    <Link className="overview-step-action" to={step.link}>{t('pages.dashboard.cockpit.openStep')}</Link>
                                )}
                            </li>
                        ))}
                        {groupInvoiceAlerts(alerts).map((group) => (
                            <li key={group[0].invoice_id || group[0].id}>
                                <Link to={group[0].link}>{group[0].invoice_number || t('pages.billingPeriods.openInvoices')}</Link>
                                {group.map((item) => <span key={item.id} className="muted">{attentionText(item, t, format)}</span>)}
                            </li>
                        ))}
                    </ul>
                    {completedSteps.length > 0 && (
                        <div className="overview-period-verified">
                            <p className="overview-detail-label">{t('pages.overview.cards.verified')}</p>
                            <ul>
                                {completedSteps.map((step) => (
                                    <li key={step.key}>
                                        <span aria-hidden="true" className="overview-step-check">✓</span>
                                        <span>{t(`pages.dashboard.cockpit.stepLabels.${step.key}`)}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                </details>
            )}
        </article>
    )
}
