import { useTranslation } from 'react-i18next'

export function ReportsEmptyState({ hasManagedZevs }: { hasManagedZevs: boolean }) {
    const { t } = useTranslation()

    return (
        <section className="card" style={{ display: 'grid', gap: '0.75rem' }}>
            <h3 style={{ margin: 0 }}>
                {t(hasManagedZevs ? 'pages.reports.selectZevTitle' : 'pages.reports.noZevTitle')}
            </h3>
            <p className="muted" style={{ margin: 0 }}>
                {t(hasManagedZevs ? 'pages.reports.selectZevDescription' : 'pages.reports.noZevDescription')}
            </p>
        </section>
    )
}