import { useId } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { AXIS_COLOR, CHART_GRIDLINE, CHART_LOCAL, FLOW_GRID_EXP, FLOW_LOCAL_CONS } from '../../lib/chartTokens'
import { CHART_AXIS_TICK, CHART_TOOLTIP_STYLE } from '../../lib/chartTheme'
import { dashboardKwhFigure, kwhTick } from '../../lib/dashboardFormatting'
import { formatKwh, formatPercent, formatPercentFigure } from '../../lib/numbers'
import { grossRate, withheldReasonKey } from '../../lib/supplementary'
import type { GrossEnergy } from '../../types/api'
import { StatCard } from '../StatCard'

interface Props {
    gross: GrossEnergy
    /** Whose figures: the signed-in participant's own, or a participant the owner selected. */
    whose: 'own' | 'participant'
    participantName?: string
    formatBucketLabel: (value: string) => string
    formatBucketTooltipLabel: (label: unknown) => string
    /** Hourly buckets over several days: label the axis once per day (`Mon 9.11.`) instead of at arbitrary hours. */
    dayAxis?: boolean
}

const zurichHour = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Zurich', hour: '2-digit', hourCycle: 'h23' })
const dayLabel = new Intl.DateTimeFormat(undefined, { timeZone: 'Europe/Zurich', weekday: 'short', day: 'numeric', month: 'numeric' })
const isMidnight = (bucket: string) => Number(zurichHour.format(new Date(bucket))) === 0

/**
 * What a net-metered participant's own system measured: production, consumption, import, export and
 * the two rates the meter alone cannot give. Labelled as reported by that system and never used for
 * billing. A rate with too little data behind it is a dash with the reason, not a low number.
 */
export function GrossEnergyCard({ gross, whose, participantName, formatBucketLabel, formatBucketTooltipLabel, dayAxis = false }: Props) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    // Two of these cards can be on one page (a manager's own and a selected participant's).
    const titleId = useId()
    const reasonKey = withheldReasonKey(gross)
    const selfSufficiency = grossRate(gross, 'self_sufficiency')
    const selfConsumption = grossRate(gross, 'self_consumption')
    const timeline = gross.timeline ?? []
    const dayTicks = dayAxis ? timeline.map((item) => item.bucket).filter(isMidnight) : undefined

    return (
        <section className="card chart-card" aria-labelledby={titleId}>
            <h3 id={titleId}>
                {t(whose === 'own' ? 'supplementary.gross.titleOwn' : 'supplementary.gross.titleParticipant')}
                {whose === 'participant' && participantName ? ` — ${participantName}` : ''}
            </h3>
            <p className="muted">
                {/* A vendor is named; "own system / file" is what the sentence already says. */}
                {gross.source_provider && gross.source_provider !== 'push'
                    ? t(whose === 'own' ? 'supplementary.gross.reportedOwn' : 'supplementary.gross.reportedParticipant', {
                        provider: t(`supplementary.provider.${gross.source_provider}`),
                    })
                    : t(whose === 'own' ? 'supplementary.gross.reportedOwnGeneric' : 'supplementary.gross.reportedParticipantGeneric')}
            </p>
            {gross.covered_from && gross.covered_to && (
                <p className="muted">
                    {t('supplementary.gross.basedOn', {
                        from: formatShortDate(gross.covered_from, settings),
                        to: formatShortDate(gross.covered_to, settings),
                        coverage: formatPercent(gross.coverage_pct),
                    })}
                </p>
            )}

            <div className="stat-grid stat-grid--wide">
                <StatCard
                    label={t('supplementary.gross.selfSufficiency')}
                    value={selfSufficiency === null ? null : formatPercentFigure(selfSufficiency)}
                    unit="%"
                    hint={reasonKey ? t(reasonKey) : t('supplementary.gross.selfSufficiencyHint')}
                />
                <StatCard
                    label={t('supplementary.gross.selfConsumptionRate')}
                    value={selfConsumption === null ? null : formatPercentFigure(selfConsumption)}
                    unit="%"
                    hint={reasonKey ? t(reasonKey) : t('supplementary.gross.selfConsumptionRateHint')}
                />
                <StatCard label={t('supplementary.gross.production')} value={dashboardKwhFigure(gross.production_kwh)} unit="kWh" />
                <StatCard label={t('supplementary.gross.consumption')} value={dashboardKwhFigure(gross.consumption_kwh)} unit="kWh" />
                <StatCard label={t('supplementary.gross.selfConsumption')} value={dashboardKwhFigure(gross.self_consumption_kwh)} unit="kWh" />
                <StatCard label={t('supplementary.gross.import')} value={dashboardKwhFigure(gross.import_kwh)} unit="kWh" />
                <StatCard label={t('supplementary.gross.export')} value={dashboardKwhFigure(gross.export_kwh)} unit="kWh" />
            </div>

            {timeline.length > 0 && (
                <ResponsiveContainer width="100%" height={280} style={{ marginTop: '1.25rem' }}>
                    <ComposedChart data={timeline} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
                        <CartesianGrid stroke={CHART_GRIDLINE} strokeDasharray="3 3" vertical={false} />
                        <XAxis
                            dataKey="bucket"
                            tick={CHART_AXIS_TICK}
                            stroke={AXIS_COLOR}
                            ticks={dayTicks}
                            interval={dayTicks ? 0 : undefined}
                            tickFormatter={dayTicks ? (bucket: string) => dayLabel.format(new Date(bucket)) : formatBucketLabel}
                        />
                        <YAxis tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} unit=" kWh" width={60} tickFormatter={kwhTick} />
                        <Tooltip
                            contentStyle={CHART_TOOLTIP_STYLE}
                            labelFormatter={formatBucketTooltipLabel}
                            formatter={(value) => (typeof value === 'number' ? `${formatKwh(value)}` : String(value))}
                        />
                        {/* Drawing order, not alphabetical: the order must not change with the language. */}
                        <Legend itemSorter={null} />
                        <Bar dataKey="production_kwh" name={t('supplementary.gross.production')} fill={CHART_LOCAL} />
                        <Bar dataKey="export_kwh" name={t('supplementary.gross.export')} fill={FLOW_GRID_EXP} radius={[3, 3, 0, 0]} />
                        <Line
                            type="monotone"
                            dataKey="self_consumption_kwh"
                            name={t('supplementary.gross.selfConsumption')}
                            stroke={FLOW_LOCAL_CONS}
                            dot={false}
                            strokeWidth={2}
                        />
                    </ComposedChart>
                </ResponsiveContainer>
            )}
        </section>
    )
}

/** Shown to a net-metered participant who has not connected a source: where to do it. */
export function GrossEnergyCallToAction() {
    const { t } = useTranslation()
    return (
        <section className="card" aria-labelledby="gross-energy-cta-title">
            <h3 id="gross-energy-cta-title">{t('supplementary.gross.ctaTitle')}</h3>
            <p className="muted">{t('supplementary.gross.ctaBody')}</p>
            <Link className="button button-primary button-compact" style={{ textDecoration: 'none' }} to="/me/metering-points">
                {t('supplementary.gross.ctaAction')}
            </Link>
        </section>
    )
}
