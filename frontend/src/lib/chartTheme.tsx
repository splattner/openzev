import { CHART_INK, CHART_MUTED } from './chartTokens'

/**
 * Shared recharts grammar for the feasibility charts: tick/label typography,
 * tooltip card, legend swatch. Colors come from the generated chartTokens —
 * this file only centralizes the config *shapes* that recharts cannot take
 * from CSS variables. Screen-only: PDF charts have their own WeasyPrint
 * pipeline (see backend/invoices/pdf_charts.py).
 */

export const CHART_AXIS_TICK = { fontSize: 11, fill: CHART_INK } as const

export function chartAxisLabel(value: string) {
  return { value, position: 'insideBottom', offset: -5, fontSize: 11, fill: CHART_MUTED } as const
}

export const CHF_Y_AXIS_LABEL = {
  value: 'CHF',
  angle: -90,
  position: 'insideLeft',
  fontSize: 11,
  fill: CHART_MUTED,
} as const

export const CHART_TOOLTIP_STYLE = {
  background: 'var(--surface-card)',
  border: '1px solid var(--border-default)',
  borderRadius: 6,
  padding: '0.5rem 0.7rem',
  fontSize: '0.82rem',
} as const

export function ChartLegendSwatch({ color, opacity }: { color: string; opacity?: number }) {
  return (
    <span
      style={{
        display: 'inline-block',
        width: 9,
        height: 9,
        background: color,
        opacity,
        borderRadius: 2,
        marginRight: 4,
      }}
    />
  )
}
