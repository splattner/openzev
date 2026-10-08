import type { ReactNode } from 'react'

export type StatCardTone = 'success' | 'warning' | 'danger'

/** `accent` is the dark hero — at most one per view, exclusive with `tone`/`flat`. */
export type StatCardProps = {
    label: string
    /** The figure without its unit; `null` shows a dash and no unit. */
    value: string | number | null
    /** Set small after the figure (`kWh`, `%`). */
    unit?: string
    /** Set small before the figure (`CHF`). */
    currency?: string
    hint?: string
} & (
    | { accent?: true; tone?: never; flat?: never }
    | { accent?: false; tone?: StatCardTone; flat?: boolean }
) & (
    | { onPress?: never; pressed?: never }
    | { onPress: () => void; pressed: boolean }
)

/**
 * The figure and its unit as the documents set them: the number carries the
 * weight, the unit sits beside it in a smaller, quieter face. Text that is not
 * a figure (a date and time, a label) may wrap; a figure does not.
 */
function statValueParts(value: string | number | null, unit?: string, currency?: string): ReactNode {
    if (value === null) return <span className="stat-figure">—</span>
    if (typeof value === 'string' && !unit && !currency) {
        return <span className="stat-figure stat-figure--text">{value}</span>
    }
    return (
        <>
            {/* A no-break space: the unit never ends up on a line of its own. */}
            {currency ? <><span className="stat-unit">{currency}</span>{'\u00a0'}</> : null}
            <span className="stat-figure">{value}</span>
            {unit ? <>{'\u00a0'}<span className="stat-unit">{unit}</span></> : null}
        </>
    )
}

export function StatCard({ label, value, unit, currency, hint, accent, tone, flat, onPress, pressed }: StatCardProps) {
    const className = [
        'stat-card',
        accent && 'stat-card--accent',
        tone && `stat-card--${tone}`,
        flat && 'stat-card--flat',
        onPress && 'stat-card--interactive',
    ].filter(Boolean).join(' ')

    const figure = statValueParts(value, unit, currency)
    const body = (
        <>
            <span className="stat-label">{label}</span>
            {onPress
                ? <span className="stat-value">{figure}</span>
                : <h3 className="stat-value">{figure}</h3>}
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
