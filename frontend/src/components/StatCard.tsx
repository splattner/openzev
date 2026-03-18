export function StatCard({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
    return (
        <section className="stat-card">
            <p className="stat-label">{label}</p>
            <h3>{value}</h3>
            {hint ? <p className="muted">{hint}</p> : null}
        </section>
    )
}
