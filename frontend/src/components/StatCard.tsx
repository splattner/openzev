export type StatCardTone = 'success' | 'warning' | 'danger'

/** `accent` is the dark hero — at most one per view, exclusive with `tone`/`flat`. */
export type StatCardProps = {
    label: string
    value: string | number
    hint?: string
} & (
    | { accent?: true; tone?: never; flat?: never }
    | { accent?: false; tone?: StatCardTone; flat?: boolean }
) & (
    | { onPress?: never; pressed?: never }
    | { onPress: () => void; pressed: boolean }
)

export function StatCard({ label, value, hint, accent, tone, flat, onPress, pressed }: StatCardProps) {
    const className = [
        'stat-card',
        accent && 'stat-card--accent',
        tone && `stat-card--${tone}`,
        flat && 'stat-card--flat',
        onPress && 'stat-card--interactive',
    ].filter(Boolean).join(' ')

    const body = (
        <>
            <span className="stat-label">{label}</span>
            {onPress
                ? <span className="stat-value">{value}</span>
                : <h3 className="stat-value">{value}</h3>}
            {hint ? (
                onPress
                    ? <span className={accent ? 'stat-card--accent-hint' : 'muted'}>{hint}</span>
                    : <p className={accent ? 'stat-card--accent-hint' : 'muted'}>{hint}</p>
            ) : null}
        </>
    )

    if (onPress) {
        return (
            <button type="button" className={className} aria-pressed={pressed} onClick={onPress}>
                {body}
            </button>
        )
    }

    return <section className={className}>{body}</section>
}
