export function StatCard({ label, value, hint, accent }: { label: string; value: string | number; hint?: string; accent?: boolean }) {
    return (
        <section className={accent ? 'stat-card stat-card--accent' : 'stat-card'}>
            <p className="stat-label">{label}</p>
            <h3>{value}</h3>
            {hint ? <p className={accent ? 'stat-card--accent-hint' : 'muted'}>{hint}</p> : null}
        </section>
    )
}
