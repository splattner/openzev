import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { ReadinessResponse, ReadinessSetupBlock } from '../../types/api'
import { Notice } from '../../components/Notice'
import { PageSkeleton } from '../../components/PageSkeleton'

/** Assignment, billing-settings and issuer warnings, rendered beside period work. */
function SetupWarnings({ setup }: { setup: ReadinessSetupBlock | null | undefined }) {
    const { t } = useTranslation()
    if (!setup) return null
    const showSetupWarning = !setup.complete && !!setup.assignment_link
    const showIbanWarning = !setup.billing_settings_complete && !!setup.billing_settings_link
    const showIssuerWarning = !setup.issuer_complete && !!setup.issuer_link
    if (!showSetupWarning && !showIbanWarning && !showIssuerWarning) return null
    return (
        <div className="setup-guidance-warnings" role="status">
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
            {showIssuerWarning ? (
                <p className="warning-banner">
                    {t(setup.issuer_missing === 'address'
                        ? 'pages.dashboard.cockpit.setupIssuerAddress'
                        : 'pages.dashboard.cockpit.setupIssuer')}{' '}
                    <Link to={setup.issuer_link as string}>
                        {t('pages.dashboard.cockpit.setupIssuerLink')}
                    </Link>
                </p>
            ) : null}
        </div>
    )
}

function SetupChecklist({ setup }: { setup: NonNullable<ReadinessResponse['setup']> }) {
    const { t } = useTranslation()
    return (
        <ul className="setup-guidance-list">
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
    )
}

/** First-run guidance and setup warnings for the manager Overview. */
export function SetupGuidance({
    readinessQuery,
}: {
    readinessQuery: { isLoading: boolean; isError: boolean; data?: ReadinessResponse; isFetching?: boolean; refetch: () => unknown }
}) {
    const { t } = useTranslation()
    const readiness = readinessQuery.data

    if (readinessQuery.isLoading) return <PageSkeleton variant="card" />
    if (readinessQuery.isError || !readiness) {
        return <Notice tone="error" onRetry={() => void readinessQuery.refetch()} isRetrying={readinessQuery.isFetching}>{t('pages.dashboard.cockpit.failed')}</Notice>
    }

    if (readiness.period) return <SetupWarnings setup={readiness.setup} />

    if (readiness.awaiting_first_period || !readiness.setup) {
        return (
            <section className="card">
                <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.cockpit.title')}</h3>
                <p className="muted">{t('pages.dashboard.cockpit.awaitingFirstPeriod')}</p>
                <SetupWarnings setup={readiness.setup} />
            </section>
        )
    }

    return (
        <section className="card">
            <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.cockpit.firstRunTitle')}</h3>
            <p className="muted">{t('pages.dashboard.cockpit.firstRunDescription')}</p>
            <SetupChecklist setup={readiness.setup} />
        </section>
    )
}
