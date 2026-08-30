import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { StatCard } from '../components/StatCard'
import { fetchDashboardStats } from '../lib/api/invoices'
import { queryKeys } from '../lib/api/queryKeys'
import { formatChf } from '../lib/numbers'

export function AdminDashboardPage() {
    const { t } = useTranslation()
    const { data: stats, isLoading, error } = useQuery({
        queryKey: queryKeys.invoices.dashboard(),
        queryFn: fetchDashboardStats,
        refetchInterval: 30000,
    })

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('nav.adminConsole')}</p>
                <h2>{t('nav.adminOverview')}</h2>
            </header>

            {isLoading && <p className="muted">{t('common.loading')}</p>}

            {error && <div className="card error-banner">{t('common.error')}</div>}

            {!isLoading && !error && !stats && <p className="muted">{t('common.noData')}</p>}

            {stats && (
                <>
                    <div className="grid grid-3">
                        <StatCard label={t('entity.zevs')} value={stats.zevs.total} />
                        <StatCard label={t('entity.participants')} value={stats.participants.total} />
                        <StatCard label={t('invoice.totalRevenue')} value={formatChf(stats.invoices.total_revenue)} accent />
                    </div>

                    <div className="card">
                        <h2>{t('invoice.statusBreakdown')}</h2>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem' }}>
                            {[
                                { key: 'draft', label: t('invoice.status.draft'), value: stats.invoices.draft },
                                { key: 'approved', label: t('invoice.status.approved'), value: stats.invoices.approved },
                                { key: 'sent', label: t('invoice.status.sent'), value: stats.invoices.sent },
                                { key: 'paid', label: t('invoice.status.paid'), value: stats.invoices.paid },
                                { key: 'cancelled', label: t('invoice.status.cancelled'), value: stats.invoices.cancelled },
                            ].map((status) => (
                                <div key={status.key} className={`status-tile status-tile-${status.key}`}>
                                    <div className="status-tile-label">{status.label}</div>
                                    <div className="status-tile-value">{status.value}</div>
                                </div>
                            ))}
                        </div>
                    </div>

                    <div className="card">
                        <h2>{t('email.statistics')}</h2>
                        <div className="grid grid-4">
                            <StatCard label={t('email.totalEmails')} value={stats.emails.total} flat />
                            <StatCard label={t('email.sent')} value={stats.emails.sent} flat tone={stats.emails.sent > 0 ? 'success' : undefined} />
                            <StatCard label={t('email.pending')} value={stats.emails.pending} flat tone={stats.emails.pending > 0 ? 'warning' : undefined} />
                            <StatCard label={t('email.failed')} value={stats.emails.failed} flat tone={stats.emails.failed > 0 ? 'danger' : undefined} />
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}
