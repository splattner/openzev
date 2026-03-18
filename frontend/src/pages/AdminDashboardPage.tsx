import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchDashboardStats } from '../lib/api'

export function AdminDashboardPage() {
    const { t } = useTranslation()
    const { data: stats, isLoading, error } = useQuery({
        queryKey: ['dashboard'],
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

    const statusColors: Record<string, string> = {
        draft: '#6b7280',
        approved: '#3b82f6',
        sent: '#8b5cf6',
        paid: '#10b981',
        cancelled: '#ef4444',
    }

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('nav.adminConsole')}</p>
                <h1>{t('nav.adminOverview')}</h1>
            </header>

            {/* Key Metrics Row */}
            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '1.5rem', marginBottom: '2rem' }}>
                {/* ZEVs Card */}
                <div className="card">
                    <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '0.875rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6b7280' }}>
                        {t('entity.zevs')}
                    </h3>
                    <div style={{ fontSize: '2.25rem', fontWeight: '600', color: '#1f2937' }}>
                        {stats.zevs.total}
                    </div>
                </div>

                {/* Participants Card */}
                <div className="card">
                    <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '0.875rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6b7280' }}>
                        {t('entity.participants')}
                    </h3>
                    <div style={{ fontSize: '2.25rem', fontWeight: '600', color: '#1f2937' }}>
                        {stats.participants.total}
                    </div>
                </div>

                {/* Total Revenue Card */}
                <div className="card">
                    <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '0.875rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6b7280' }}>
                        {t('invoice.totalRevenue')}
                    </h3>
                    <div style={{ fontSize: '2.25rem', fontWeight: '600', color: '#10b981' }}>
                        CHF {stats.invoices.total_revenue.toFixed(2)}
                    </div>
                </div>

                {/* Pending Emails Card */}
                <div className="card">
                    <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '0.875rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6b7280' }}>
                        {t('email.pendingEmails')}
                    </h3>
                    <div style={{ fontSize: '2.25rem', fontWeight: '600', color: stats.emails.pending > 0 ? '#f59e0b' : '#10b981' }}>
                        {stats.emails.pending}
                    </div>
                    {stats.emails.failed > 0 && (
                        <div style={{ fontSize: '0.875rem', color: '#ef4444', marginTop: '0.25rem' }}>
                            {stats.emails.failed} {t('email.failed')}
                        </div>
                    )}
                </div>
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
                        <div key={status.key} style={{ padding: '1rem', backgroundColor: statusColors[status.key], borderRadius: '0.5rem', color: 'white' }}>
                            <div style={{ fontSize: '0.875rem', opacity: 0.9, marginBottom: '0.5rem' }}>
                                {status.label}
                            </div>
                            <div style={{ fontSize: '1.875rem', fontWeight: '600' }}>
                                {status.value}
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {/* Email Statistics */}
            <div className="card" style={{ marginBottom: '2rem' }}>
                <h2 style={{ marginTop: 0 }}>{t('email.statistics')}</h2>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem' }}>
                    <div style={{ padding: '1rem', backgroundColor: '#e0e7ff', borderRadius: '0.5rem' }}>
                        <div style={{ fontSize: '0.875rem', color: '#4f46e5', marginBottom: '0.5rem' }}>
                            {t('email.totalEmails')}
                        </div>
                        <div style={{ fontSize: '1.875rem', fontWeight: '600', color: '#4f46e5' }}>
                            {stats.emails.total}
                        </div>
                    </div>
                    <div style={{ padding: '1rem', backgroundColor: '#dcfce7', borderRadius: '0.5rem' }}>
                        <div style={{ fontSize: '0.875rem', color: '#15803d', marginBottom: '0.5rem' }}>
                            {t('email.sent')}
                        </div>
                        <div style={{ fontSize: '1.875rem', fontWeight: '600', color: '#15803d' }}>
                            {stats.emails.sent}
                        </div>
                    </div>
                    <div style={{ padding: '1rem', backgroundColor: '#fef3c7', borderRadius: '0.5rem' }}>
                        <div style={{ fontSize: '0.875rem', color: '#b45309', marginBottom: '0.5rem' }}>
                            {t('email.pending')}
                        </div>
                        <div style={{ fontSize: '1.875rem', fontWeight: '600', color: '#b45309' }}>
                            {stats.emails.pending}
                        </div>
                    </div>
                    <div style={{ padding: '1rem', backgroundColor: '#fee2e2', borderRadius: '0.5rem' }}>
                        <div style={{ fontSize: '0.875rem', color: '#991b1b', marginBottom: '0.5rem' }}>
                            {t('email.failed')}
                        </div>
                        <div style={{ fontSize: '1.875rem', fontWeight: '600', color: '#991b1b' }}>
                            {stats.emails.failed}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
