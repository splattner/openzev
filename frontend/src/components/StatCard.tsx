import type { ReactNode } from 'react'

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

// A formatted figure with a leading currency code ("CHF 84.69") or a trailing
// unit ("431.4 kWh", "47 %"). Anything else — dates, dashes, ratios — stays whole.
const FIGURE_WITH_UNIT = /^(?:([A-Z]{3})(\s+))?([\u2212-]?\d[\d'\u2019.,\u00a0\u202f]*)(?:(\s*)([^\d\s][^\d]*))?$/

/**
 * The figure and its unit as the documents set them: the number carries the
 * weight, the unit sits beside it in a smaller, quieter face. The text content
 * (and so what assistive technology reads) is unchanged.
 */
function statValueParts(value: string | number): ReactNode {
    const text = String(value)
    const match = FIGURE_WITH_UNIT.exec(text)
    if (!match) return <span className="stat-figure">{text}</span>
    const [, currency, currencyGap, figure, unitGap, unit] = match
    if (!currency && !unit) return <span className="stat-figure">{text}</span>
    return (
        <>
            {currency ? <span className="stat-unit">{currency}</span> : null}
            {currency ? currencyGap : null}
            <span className="stat-figure">{figure}</span>
            {unit ? unitGap : null}
            {unit ? <span className="stat-unit">{unit}</span> : null}
        </>
    )
}

export function StatCard({ label, value, hint, accent, tone, flat, onPress, pressed }: StatCardProps) {
    const className = [
        'stat-card',
        accent && 'stat-card--accent',
        tone && `stat-card--${tone}`,
        flat && 'stat-card--flat',
        onPress && 'stat-card--interactive',
    ].filter(Boolean).join(' ')

    const figure = statValueParts(value)
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
