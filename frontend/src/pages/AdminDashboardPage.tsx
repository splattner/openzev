import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import type { ReactNode } from 'react'
import { fetchDashboardStats } from '../lib/api/invoices'
import { queryKeys } from '../lib/api/queryKeys'

const KPI_LABEL_STYLE = {
    margin: '0 0 0.5rem 0',
    fontSize: '0.875rem',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    color: 'var(--text-muted)',
} as const

/** One key-metric tile on the admin overview (uppercase label + big value). */
function KpiCard({ label, value, valueColor, children }: {
    label: string
    value: ReactNode
    valueColor?: string
    children?: ReactNode
}) {
    return (
        <div className="card">
            <h3 style={KPI_LABEL_STYLE}>{label}</h3>
            <div style={{ fontSize: '2.25rem', fontWeight: '600', color: valueColor ?? 'var(--text-primary)' }}>
                {value}
            </div>
            {children}
        </div>
    )
}

export function AdminDashboardPage() {
    const { t } = useTranslation()
    const { data: stats, isLoading, error } = useQuery({
        queryKey: queryKeys.invoices.dashboard(),
        queryFn: fetchDashboardStats,
        refetchInterval: 30000, // Refresh every 30 seconds
    })

    if (isLoading) {
        return (
            <div className="page-stack">
                <header>
                    <p className="eyebrow">{t('nav.adminConsole')}</p>
                    <h1>{t('nav.adminOverview')}</h1>
                </header>
                <p>{t('common.loading')}</p>
            </div>
        )
    }

    if (error) {
        return (
            <div className="page-stack">
                <header>
                    <p className="eyebrow">{t('nav.adminConsole')}</p>
                    <h1>{t('nav.adminOverview')}</h1>
                </header>
                <div className="alert alert-error">{t('common.error')}</div>
            </div>
        )
    }

    if (!stats) {
        return (
            <div className="page-stack">
                <header>
                    <p className="eyebrow">{t('nav.adminConsole')}</p>
                    <h1>{t('nav.adminOverview')}</h1>
                </header>
                <p>No data available</p>
            </div>
        )
    }

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('nav.adminConsole')}</p>
                <h1>{t('nav.adminOverview')}</h1>
            </header>

            {/* Key Metrics Row */}
            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '1.5rem', marginBottom: '2rem' }}>
                <KpiCard label={t('entity.zevs')} value={stats.zevs.total} />
                <KpiCard label={t('entity.participants')} value={stats.participants.total} />
                <KpiCard
                    label={t('invoice.totalRevenue')}
                    valueColor="var(--success-600)"
                    value={`CHF ${stats.invoices.total_revenue.toFixed(2)}`}
                />
                <KpiCard
                    label={t('email.pendingEmails')}
                    value={stats.emails.pending}
                    valueColor={stats.emails.pending > 0 ? 'var(--warning-800)' : 'var(--success-600)'}
                >
                    {stats.emails.failed > 0 && (
                        <div style={{ fontSize: '0.875rem', color: 'var(--danger-600)', marginTop: '0.25rem' }}>
                            {stats.emails.failed} {t('email.failed')}
                        </div>
                    )}
                </KpiCard>
            </div>

            {/* Invoice Status Breakdown */}
            <div className="card" style={{ marginBottom: '2rem' }}>
                <h2 style={{ marginTop: 0 }}>{t('invoice.statusBreakdown')}</h2>
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

            {/* Email Statistics */}
            <div className="card" style={{ marginBottom: '2rem' }}>
                <h2 style={{ marginTop: 0 }}>{t('email.statistics')}</h2>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem' }}>
                    <div style={{ padding: '1rem', backgroundColor: 'var(--brand-pale)', borderRadius: '0.5rem' }}>
                        <div style={{ fontSize: '0.875rem', color: 'var(--brand-deep)', marginBottom: '0.5rem' }}>
                            {t('email.totalEmails')}
                        </div>
                        <div style={{ fontSize: '1.875rem', fontWeight: '600', color: 'var(--brand-deep)' }}>
                            {stats.emails.total}
                        </div>
                    </div>
                    <div style={{ padding: '1rem', backgroundColor: 'var(--success-100)', borderRadius: '0.5rem' }}>
                        <div style={{ fontSize: '0.875rem', color: 'var(--success-700)', marginBottom: '0.5rem' }}>
                            {t('email.sent')}
                        </div>
                        <div style={{ fontSize: '1.875rem', fontWeight: '600', color: 'var(--success-700)' }}>
                            {stats.emails.sent}
                        </div>
                    </div>
                    <div style={{ padding: '1rem', backgroundColor: 'var(--warning-100)', borderRadius: '0.5rem' }}>
                        <div style={{ fontSize: '0.875rem', color: 'var(--warning-800)', marginBottom: '0.5rem' }}>
                            {t('email.pending')}
                        </div>
                        <div style={{ fontSize: '1.875rem', fontWeight: '600', color: 'var(--warning-800)' }}>
                            {stats.emails.pending}
                        </div>
                    </div>
                    <div style={{ padding: '1rem', backgroundColor: 'var(--danger-100)', borderRadius: '0.5rem' }}>
                        <div style={{ fontSize: '0.875rem', color: 'var(--danger-700)', marginBottom: '0.5rem' }}>
                            {t('email.failed')}
                        </div>
                        <div style={{ fontSize: '1.875rem', fontWeight: '600', color: 'var(--danger-700)' }}>
                            {stats.emails.failed}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
