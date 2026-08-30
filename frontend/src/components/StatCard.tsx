export type StatCardTone = 'success' | 'warning' | 'danger'

/** `accent` is the dark hero — at most one per view, exclusive with `tone`/`flat`. */
export type StatCardProps = {
    label: string
    value: string | number
    hint?: string
} & (
    | { accent?: true; tone?: never; flat?: never }
    | { accent?: false; tone?: StatCardTone; flat?: boolean }
)

export function StatCard({ label, value, hint, accent, tone, flat }: StatCardProps) {
    const className = [
        'stat-card',
        accent && 'stat-card--accent',
        tone && `stat-card--${tone}`,
        flat && 'stat-card--flat',
    ].filter(Boolean).join(' ')

    return (
        <section className={className}>
            <p className="stat-label">{label}</p>
            <h3>{value}</h3>
            {hint ? <p className={accent ? 'stat-card--accent-hint' : 'muted'}>{hint}</p> : null}
        </section>
    )
}
