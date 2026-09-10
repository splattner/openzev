import { Link } from 'react-router-dom'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faArrowRight } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import type { AttentionItem, ReadinessResponse, ReadinessSetupBlock, ReadinessStep } from '../types/api'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { PageSkeleton } from './PageSkeleton'
import { NEXT_ACTION_STEP_KEY, stepDetailText, attentionText } from '../features/overview/readinessPresentation'

/**
 * The period cockpit (nav-regroup phase 2, spec §7): where the billing period
 * stands and what the next action is. The backend resolves the cockpit period;
 * statuses are ok|warn|todo|done (data quality soft-gates, never `blocked`).
 * Details localize from `detail_data`; the English `detail` is an API fallback
 * never rendered. Null-period states: `setup`, `awaiting_first_period`, or an
 * all-done cockpit marked `caught_up`.
 *
 * Cross-period attention items (failed emails, overdue invoices, participant
 * validity) render as an alert list between the steps and the next-action
 * footer — the standalone AttentionCard was merged into this card.
 */

function SetupWarnings({ setup }: { setup: ReadinessSetupBlock | null | undefined }) {
    const { t } = useTranslation()
    if (!setup) return null
    const showSetupWarning = !setup.complete && !!setup.assignment_link
    const showIbanWarning = !setup.billing_settings_complete && !!setup.billing_settings_link
    if (!showSetupWarning && !showIbanWarning) return null
    return (
        <div className="cockpit-setup-warnings" role="status">
            {showSetupWarning ? (
                <p className="error-banner">
                    {t('pages.dashboard.cockpit.setupIncomplete')}{' '}
                    <Link to={setup.assignment_link as string}>
                        {t('pages.dashboard.cockpit.setupAssignLink')}
                    </Link>
                </p>
            ) : null}
            {showIbanWarning ? (
                <p className="warning-banner">
                    {t('pages.dashboard.cockpit.setupIban')}{' '}
                    <Link to={setup.billing_settings_link as string}>
                        {t('pages.dashboard.cockpit.setupIbanLink')}
                    </Link>
                </p>
            ) : null}
        </div>
    )
}

function stepBadgeClass(step: ReadinessStep): string {
    if (step.status === 'ok' || step.status === 'done') return 'badge badge-success'
    if (step.status === 'warn') return 'badge badge-warning'
    return 'badge badge-neutral'
}


function periodSuffix(item: AttentionItem, format: (v: string) => string): string {
    if (!item.period) return ''
    return ` (${format(item.period.start)} → ${format(item.period.end)})`
}

export function BillingCockpit({
    readinessQuery,
    attentionQuery,
    setupOnly = false,
  }: {
    setupOnly?: boolean
    readinessQuery: { isLoading: boolean; isError: boolean; data?: ReadinessResponse }
    attentionQuery?: { isLoading: boolean; isError: boolean; data?: AttentionItem[] }
}) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const readiness = readinessQuery.data
    const attentionItems = attentionQuery?.data ?? []
    const format = (value: string) => formatShortDate(value, settings)

    // Overview uses period cards for billing work; retain the independent
    // setup query so assignment and payment-setting guidance stays visible.
    if (setupOnly && readinessQuery.isLoading) return <PageSkeleton variant="card" />
    if (setupOnly && (readinessQuery.isError || !readiness)) {
        return <p className="card error-banner" role="status">{t('pages.dashboard.cockpit.failed')}</p>
    }
    if (setupOnly && readiness?.period) return <SetupWarnings setup={readiness.setup} />

    const alerts = (
        <>
            {attentionQuery?.isLoading && <PageSkeleton variant="tableRows" />}
            {attentionQuery?.isError && (
                <p className="error-banner" role="status">{t('pages.dashboard.attention.failed')}</p>
            )}
            {attentionItems.length > 0 && (
                <ul className="cockpit-alerts" aria-label={t('pages.dashboard.attention.title')}>
                    {attentionItems.map((item) => (
                        <li key={item.id} className="cockpit-alert">
                            <span className="badge badge-warning">
                                {t(`pages.dashboard.attention.labels.${item.type}`)}
                            </span>
                            <span className="cockpit-alert-text">
                                {attentionText(item, t, format)}
                                {periodSuffix(item, format)}
                            </span>
                            <Link
                                className="button button-secondary button-compact cockpit-alert-link"
                                to={item.link}
                                aria-label={attentionText(item, t, format)}
                            >
                                <FontAwesomeIcon icon={faArrowRight} fixedWidth />
                                {t('pages.dashboard.cockpit.openStep')}
                            </Link>
                        </li>
                    ))}
                </ul>
            )}
        </>
    )

    if (readinessQuery.isLoading) {
        return (
            <section className="card">
                <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.cockpit.title')}</h3>
                <PageSkeleton variant="tableRows" />
                {alerts}
            </section>
        )
    }
    if (readinessQuery.isError || !readiness) {
        return (
            <section className="card">
                <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.cockpit.title')}</h3>
                <p className="muted">{t('pages.dashboard.cockpit.failed')}</p>
                {alerts}
            </section>
        )
    }

    // First run (master data empty) → setup checklist, distinct from
    // awaiting_first_period (master data exists, nothing ended yet — setup
    // guidance still rides along).
    if (!readiness.period) {
        if (readiness.awaiting_first_period) {
            return (
                <section className="card">
                    <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.cockpit.title')}</h3>
                    <p className="muted">{t('pages.dashboard.cockpit.awaitingFirstPeriod')}</p>
                    <SetupWarnings setup={readiness.setup} />
                    {alerts}
                </section>
            )
        }
        if (readiness.setup) {
            const setup = readiness.setup
            return (
                <section className="card">
                    <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.cockpit.firstRunTitle')}</h3>
                    <p className="muted">{t('pages.dashboard.cockpit.firstRunDescription')}</p>
                    <ul className="cockpit-setup-list">
                        <li data-complete={setup.participants > 0}>
                            {setup.participants > 0 ? '✓ ' : '○ '}
                            <Link to="/participants">{t('pages.dashboard.cockpit.setupParticipants')}</Link>
                        </li>
                        <li data-complete={setup.metering_points > 0}>
                            {setup.metering_points > 0 ? '✓ ' : '○ '}
                            <Link to="/metering/points">{t('pages.dashboard.cockpit.setupMeteringPoints')}</Link>
                        </li>
                        <li data-complete={setup.tariffs > 0}>
                            {setup.tariffs > 0 ? '✓ ' : '○ '}
                            <Link to="/tariffs">{t('pages.dashboard.cockpit.setupTariffs')}</Link>
                        </li>
                        <li data-complete={setup.settings_complete}>
                            {setup.settings_complete ? '✓ ' : '○ '}
                            <Link to="/zev-settings/billing">{t('pages.dashboard.cockpit.setupSettings')}</Link>
                        </li>
                    </ul>
                    {alerts}
                </section>
            )
        }
        // Fallback: null period with no flags — awaiting message, no setup.
        return (
            <section className="card">
                <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.cockpit.title')}</h3>
                <p className="muted">{t('pages.dashboard.cockpit.awaitingFirstPeriod')}</p>
                {alerts}
            </section>
        )
    }

    const periodLabel = `${formatShortDate(readiness.period.start, settings)} → ${formatShortDate(
        readiness.period.end,
        settings,
    )}`
    const setup = readiness.setup ?? null
    const nextLabel =
        t(`pages.dashboard.cockpit.nextActionLabels.${readiness.next_action}`)
    const actionStepKey = NEXT_ACTION_STEP_KEY[readiness.next_action]
    const actionStep = actionStepKey
        ? readiness.steps.find((step) => step.key === actionStepKey)
        : undefined
    const nextLink = actionStep?.status === 'todo' || actionStep?.status === 'warn'
        ? actionStep.link
        : undefined
    const openSteps = readiness.steps.filter(
        (step) => step.status === 'warn' || step.status === 'todo',
    )
    const completedSteps = readiness.steps.filter(
        (step) => step.status === 'ok' || step.status === 'done',
    )

    if (openSteps.length === 0) {
        return (
            <section className="card cockpit-card-compact">
                <div className="cockpit-caught-up">
                    <strong>{t('pages.dashboard.cockpit.title')}</strong>
                    <span className="badge badge-success">
                        {t('pages.dashboard.cockpit.allDone')}
                    </span>
                    <span className="muted">{periodLabel}</span>
                </div>
                <SetupWarnings setup={setup} />
                {alerts}
            </section>
        )
    }

    return (
        <section className="card">
            <div className="cockpit-head">
                <div>
                    <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.cockpit.title')}</h3>
                    <p className="muted" style={{ margin: 0 }}>
                        {t('pages.dashboard.cockpit.description')}
                    </p>
                </div>
                <div className="cockpit-period">
                    <span className="muted">{t('pages.dashboard.cockpit.periodLabel')}</span>{' '}
                    <strong>{periodLabel}</strong>
                </div>
            </div>

            <SetupWarnings setup={setup} />

            <ol className="cockpit-steps">
                {openSteps.map((step) => {
                    const label = t(`pages.dashboard.cockpit.stepLabels.${step.key}`)
                    const isOpen = step.status === 'warn' || step.status === 'todo'
                    const detailText = stepDetailText(step, t)
                    return (
                        <li key={step.key} className="cockpit-step" data-status={step.status}>
                            <span className={`cockpit-step-badge ${stepBadgeClass(step)}`}>
                                {t(`pages.dashboard.cockpit.statusLabels.${step.status}`)}
                            </span>
                            <span className="cockpit-step-label">{label}</span>
                            {detailText ? (
                                <span className="cockpit-step-detail muted">{detailText}</span>
                            ) : null}
                            {isOpen && step.link ? (
                                <Link
                                    className="button button-secondary button-compact cockpit-step-link"
                                    to={step.link}
                                    aria-label={label}
                                >
                                    <FontAwesomeIcon icon={faArrowRight} fixedWidth />
                                    {t('pages.dashboard.cockpit.openStep')}
                                </Link>
                            ) : null}
                        </li>
                    )
                })}
            </ol>

            {completedSteps.length > 0 && (
                <details className="cockpit-completed">
                    <summary>
                        {t('pages.dashboard.cockpit.completedSummary', { count: completedSteps.length })}
                    </summary>
                    <ol className="cockpit-steps cockpit-completed-steps">
                        {completedSteps.map((step) => (
                            <li key={step.key} className="cockpit-step" data-status={step.status}>
                                <span className={`cockpit-step-badge ${stepBadgeClass(step)}`}>
                                    {t(`pages.dashboard.cockpit.statusLabels.${step.status}`)}
                                </span>
                                <span className="cockpit-step-label">
                                    {t(`pages.dashboard.cockpit.stepLabels.${step.key}`)}
                                </span>
                            </li>
                        ))}
                    </ol>
                </details>
            )}

            {alerts}

            <div className="cockpit-foot">
                <span className="muted">{t('pages.dashboard.cockpit.nextUp')}</span>
                {readiness.next_action !== 'none' && nextLink ? (
                    <Link className="button button-primary button-compact" to={nextLink}>
                        <FontAwesomeIcon icon={faArrowRight} fixedWidth />
                        {nextLabel}
                    </Link>
                ) : (
                    <span className="badge badge-info">{nextLabel}</span>
                )}
            </div>
        </section>
    )
}
