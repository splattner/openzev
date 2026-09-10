import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { formatDateTime } from '../lib/appSettings'
import { formatBytes } from '../lib/numbers'
import { queryKeys } from '../lib/api/queryKeys'
import { fetchSystemHealth } from '../lib/api/auth'
import { PageSkeleton } from '../components/PageSkeleton'
import type { SystemHealthStatus } from '../types/api'

/**
 * System-health tab of the admin Overview hub (nav-regroup phase 3): a
 * read-only snapshot of database, Celery and email-backend status. Mirrors the
 * readiness cockpit's graceful-degradation philosophy — a probe that cannot
 * run reports "unknown" with a reason instead of failing the tab.
 */

type ProbeProps = {
    status: SystemHealthStatus
    title: string
    children: React.ReactNode
}

function HealthDot({ status }: { status: SystemHealthStatus }) {
    return <span className={`dot dot-${status === 'ok' ? 'success' : status === 'degraded' ? 'warning' : 'info'}`} aria-hidden="true" />
}

function ProbeCard({ status, title, children }: ProbeProps) {
    const { t } = useTranslation()
    return (
        <div className="card system-health-probe">
            <h3 style={{ marginTop: 0 }}>
                <HealthDot status={status} /> {title}
            </h3>
            <p className="muted">
                {t(`pages.adminOverview.health.status.${status}`)}
            </p>
            {children}
        </div>
    )
}

export function AdminSystemHealthPanel() {
    const { t } = useTranslation()
    const { data: health, isLoading, isError } = useQuery({
        queryKey: queryKeys.auth.systemHealth(),
        queryFn: fetchSystemHealth,
        // Health is a point-in-time snapshot, not a live monitor: refetch when
        // the admin revisits the tab rather than on a timer.
        staleTime: 60_000,
    })

    if (isLoading) {
        return <PageSkeleton variant="table" />
    }

    if (isError || !health) {
        return <div className="card error-banner">{t('common.error')}</div>
    }

    return (
        <div className="page-stack">
            <div className="grid grid-3">
                <ProbeCard status={health.database.status} title={t('pages.adminOverview.health.database.title')}>
                    <p className="muted" style={{ margin: 0 }}>
                        {health.database.engine}
                        {health.database.size_bytes != null && (
                            <> · {formatBytes(health.database.size_bytes)}</>
                        )}
                    </p>
                </ProbeCard>
                <ProbeCard status={health.celery.status} title={t('pages.adminOverview.health.celery.title')}>
                    <p className="muted" style={{ margin: 0 }}>
                        {health.celery.workers_responding == null
                            ? t('pages.adminOverview.health.celery.noWorkers')
                            : t('pages.adminOverview.health.celery.workers', { count: health.celery.workers_responding })}
                        {health.celery.queue_depth != null && (
                            <> · {t('pages.adminOverview.health.celery.queueDepth', { count: health.celery.queue_depth })}</>
                        )}
                    </p>
                    {health.celery.detail && <p className="muted text-error">{health.celery.detail}</p>}
                </ProbeCard>
                <ProbeCard status={health.email.status} title={t('pages.adminOverview.health.email.title')}>
                    <p className="muted" style={{ margin: 0 }}>
                        {t(`pages.adminOverview.health.email.mode.${health.email.mode}`)}
                    </p>
                </ProbeCard>
            </div>

            <p className="muted">
                {t('pages.adminOverview.health.checkedAt', { time: formatDateTime(health.checked_at) })}
            </p>
        </div>
    )
}
