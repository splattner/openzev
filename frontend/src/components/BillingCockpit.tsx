import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import type { AttentionItem, ReadinessResponse, ReadinessSetupBlock, ReadinessStep } from '../types/api'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { PageSkeleton } from './PageSkeleton'

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
                        {t('pages.dashboard.cockpit.setupAssignLink')} →
                    </Link>
                </p>
            ) : null}
            {showIbanWarning ? (
                <p className="warning-banner">
                    {t('pages.dashboard.cockpit.setupIban')}{' '}
                    <Link to={setup.billing_settings_link as string}>
                        {t('pages.dashboard.cockpit.setupIbanLink')} →
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

/** Maps a next_action back to the step that owns it (for its open link). */
const NEXT_ACTION_STEP_KEY: Record<string, string> = {
    fix_metering: 'metering',
    fix_assignments: 'assignments',
    fix_tariffs: 'tariffs',
    generate: 'generated',
    review_generation_conflicts: 'generation_conflicts',
    approve: 'approved',
    send: 'sent',
    track_payments: 'paid',
}

function stepDetailText(step: ReadinessStep, t: TFunction): string | null {
    const d = (key: string, vars: Record<string, unknown> = {}) =>
        t(`pages.dashboard.cockpit.stepDetails.${key}`, vars)
    switch (step.key) {
        case 'metering':
            if (step.status !== 'warn') return null
            return d('meteringWarn', {
                count: step.count,
                days: step.detail_data?.missing_days ?? 0,
            })
        case 'assignments':
            if (step.status !== 'warn') return null
            return d('assignmentsWarn', { readings: step.count })
        case 'tariffs':
            if (step.status === 'todo') return d('tariffsTodo')
            if (step.status === 'warn') {
                return d('tariffsWarn', { days: step.count, total: step.total ?? 0 })
            }
            return null
        case 'generated':
            if (step.status !== 'todo') return null
            return d('generatedTodo', {
                missing: step.detail_data?.missing ?? Math.max(0, (step.total ?? 0) - step.count),
                total: step.total ?? 0,
            })
        case 'generation_conflicts': {
            if (step.status !== 'warn') return null
            const names = (step.detail_data?.conflicts ?? [])
                .slice(0, 3)
                .map((conflict) => conflict.participant_name)
                .join(', ')
            return d('conflictsWarn', {
                count: step.detail_data?.conflict_count ?? step.count,
                names,
            })
        }
        case 'approved':
            if (step.status !== 'todo') return null
            return d('approvedTodo', { count: step.count })
        case 'sent': {
            if (step.status !== 'todo') return null
            const parts: string[] = []
            if (step.count > 0) parts.push(d('sentTodo', { count: step.count }))
            if (step.failed) parts.push(d('emailFailedTodo', { failed: step.failed }))
            return parts.length > 0 ? parts.join(' · ') : null
        }
        case 'paid':
            if (step.status !== 'todo') return null
            return d('paidTodo', {
                unpaid: step.detail_data?.unpaid ?? (step.total ?? 0) - step.count,
                total: step.total ?? 0,
            })
        default:
            return null
    }
}

/** Cross-period alerts only: the attention types the cockpit cannot show as
 * steps. Localized from the structured fields — the English `label` fallback
 * is never rendered. */
function attentionText(item: AttentionItem, t: TFunction, format: (v: string) => string): string {
    switch (item.type) {
        case 'email_failed':
            return t('pages.dashboard.attention.text.emailFailed', {
                number: item.invoice_number,
                recipient: item.recipient,
            })
        case 'invoice_overdue':
            return t('pages.dashboard.attention.text.invoiceOverdue', {
                number: item.invoice_number,
                due: format(item.due_date ?? ''),
            })
        case 'participant_validity':
            return item.expired
                ? t('pages.dashboard.attention.text.participantExpired', {
                      name: item.participant_name,
                      validTo: format(item.valid_to ?? ''),
                  })
                : t('pages.dashboard.attention.text.participantExpiring', {
                      name: item.participant_name,
                      validTo: format(item.valid_to ?? ''),
                  })
        default:
            return item.label
    }
}

function periodSuffix(item: AttentionItem, format: (v: string) => string): string {
    if (!item.period) return ''
    return ` (${format(item.period.start)} → ${format(item.period.end)})`
}

export function BillingCockpit({
    readinessQuery,
    attentionQuery,
  }: {
    readinessQuery: { isLoading: boolean; isError: boolean; data?: ReadinessResponse }
    attentionQuery?: { isLoading: boolean; isError: boolean; data?: AttentionItem[] }
}) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const readiness = readinessQuery.data
    const attentionItems = attentionQuery?.data ?? []
    const format = (value: string) => formatShortDate(value, settings)

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
                            <Link className="cockpit-alert-link" to={item.link} aria-label={attentionText(item, t, format)}>
                                {t('pages.dashboard.cockpit.openStep')} →
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
                            <Link to="/metering-points">{t('pages.dashboard.cockpit.setupMeteringPoints')}</Link>
                        </li>
                        <li data-complete={setup.tariffs > 0}>
                            {setup.tariffs > 0 ? '✓ ' : '○ '}
                            <Link to="/tariffs">{t('pages.dashboard.cockpit.setupTariffs')}</Link>
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
                {readiness.steps.map((step) => {
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
                                <Link className="cockpit-step-link" to={step.link} aria-label={label}>
                                    {t('pages.dashboard.cockpit.openStep')} →
                                </Link>
                            ) : null}
                        </li>
                    )
                })}
            </ol>

            {alerts}

            <div className="cockpit-foot">
                {readiness.next_action !== 'none' && nextLink ? (
                    <Link className="badge badge-info" to={nextLink}>
                        {nextLabel} →
                    </Link>
                ) : (
                    <span className="badge badge-info">{nextLabel}</span>
                )}
                <span className="muted">
                    {readiness.next_action === 'none'
                        ? t('pages.dashboard.cockpit.allDone')
                        : t('pages.dashboard.cockpit.nextUp')}
                </span>
            </div>
        </section>
    )
}
