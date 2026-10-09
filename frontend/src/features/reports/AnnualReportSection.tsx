import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fetchAnnualReport } from '../../lib/api/invoices'
import { queryKeys } from '../../lib/api/queryKeys'
import { AXIS_COLOR, CHART_GRIDLINE, CHART_LOCAL, FLOW_LOCAL_CONS } from '../../lib/chartTokens'
import { CHART_AXIS_TICK, CHART_TOOLTIP_STYLE } from '../../lib/chartTheme'
import { formatChf, formatKwh, formatPercent } from '../../lib/numbers'
import { behindMeterHintKey } from '../../lib/supplementary'
import { StatCard } from '../../components/StatCard'
import { PageSkeleton } from '../../components/PageSkeleton'
import { BehindMeterBadge } from '../../components/BehindMeterBadge'
import { NetMeteredRate } from '../../components/dashboard/NetMeteredRate'
import type { AnnualReport, AnnualReportBalance } from '../../types/api'

const percentOrDash = (value: number | null | undefined) => (value == null ? '—' : formatPercent(value))
// A year's energy reads in whole kWh; decimals are noise at this scale.
const yearKwh = (value: number) => `${formatKwh(value, { maxDecimals: 0 })} kWh`
const chfOrDash = (value: string | null | undefined) => (value == null ? '—' : formatChf(Number(value)))

type AnnualReportSectionProps = {
    zevId: string
    year: number
}

/**
 * The annual ZEV report (spec 2026-09-annual-zev-report §7): the year's
 * balance and rates, their monthly trend against the previous year, and what
 * participation saved each participant according to their invoices.
 */
export function AnnualReportSection({ zevId, year }: AnnualReportSectionProps) {
    const { t } = useTranslation()
    const reportQuery = useQuery({
        queryKey: queryKeys.invoices.annualReport(zevId, year),
        queryFn: () => fetchAnnualReport({ zev_id: zevId, year }),
    })

    if (reportQuery.isPending) return <PageSkeleton variant="cardList" />
    if (reportQuery.isError) {
        return (
            <section className="card">
                <p className="error-text" role="alert" style={{ margin: 0 }}>{t('pages.reports.annualReport.error')}</p>
            </section>
        )
    }

    const report = reportQuery.data
    if (!report.has_data) {
        return (
            <section className="card">
                <h3 style={{ marginTop: 0 }}>{t('pages.reports.annualReport.title', { year })}</h3>
                <p className="muted" style={{ margin: 0 }}>{t('pages.reports.annualReport.noData', { year })}</p>
            </section>
        )
    }

    return (
        <>
            <AnnualReportKpis report={report} />
            <AnnualTrendCard report={report} />
            <ParticipantSavingsCard report={report} />
        </>
    )
}

function previousHint(
    t: ReturnType<typeof useTranslation>['t'],
    previous: AnnualReportBalance | null,
    key: 'self_consumption_rate' | 'self_sufficiency_rate',
    year: number,
) {
    const value = previous?.[key]
    return value == null ? undefined : t('pages.reports.annualReport.hints.previousYear', { rate: formatPercent(value), year: year - 1 })
}

function AnnualReportKpis({ report }: { report: AnnualReport }) {
    const { t } = useTranslation()
    const { totals, previous_totals: previous, year } = report
    return (
        <>
            <section className="kpi-row" aria-label={t('pages.reports.annualReport.title', { year })}>
                <StatCard
                    accent
                    label={t('pages.reports.annualReport.stats.selfConsumptionRate')}
                    value={percentOrDash(totals.self_consumption_rate)}
                    hint={previousHint(t, previous, 'self_consumption_rate', year)}
                />
                <StatCard
                    label={t('pages.reports.annualReport.stats.selfSufficiencyRate')}
                    value={percentOrDash(totals.self_sufficiency_rate)}
                    hint={previousHint(t, previous, 'self_sufficiency_rate', year)}
                />
                <StatCard label={t('pages.reports.annualReport.stats.produced')} value={yearKwh(totals.produced_kwh)} />
                <StatCard label={t('pages.reports.annualReport.stats.consumed')} value={yearKwh(totals.consumed_kwh)} />
                <StatCard
                    label={t('pages.reports.annualReport.stats.savings')}
                    value={chfOrDash(report.savings_total_chf)}
                    hint={t('pages.reports.annualReport.hints.savings')}
                />
            </section>
            {report.has_behind_meter_generation && <p className="muted">{t('behindMeter.zevNote')}</p>}
        </>
    )
}

function AnnualTrendCard({ report }: { report: AnnualReport }) {
    const { t, i18n } = useTranslation()
    const hasPrevious = report.previous_totals !== null
    const data = useMemo(() => {
        const monthName = new Intl.DateTimeFormat(i18n.language, { month: 'short', timeZone: 'UTC' })
        return report.months.map((m) => ({ ...m, label: monthName.format(new Date(Date.UTC(2000, m.month - 1, 15))) }))
    }, [report.months, i18n.language])

    const current = String(report.year)
    const previous = String(report.year - 1)
    return (
        <section className="card">
            <h3 style={{ marginTop: 0 }}>{t('pages.reports.annualReport.trend.title')}</h3>
            <p className="muted">{t('pages.reports.annualReport.trend.description')}</p>
            <ResponsiveContainer width="100%" height={300}>
                <LineChart data={data} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
                    <CartesianGrid stroke={CHART_GRIDLINE} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="label" tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} />
                    <YAxis tick={CHART_AXIS_TICK} stroke={AXIS_COLOR} unit="%" width={44} domain={[0, 100]} />
                    <Tooltip
                        contentStyle={CHART_TOOLTIP_STYLE}
                        formatter={(value) => (typeof value === 'number' ? formatPercent(value) : '—')}
                    />
                    <Legend />
                    <Line
                        type="monotone"
                        dataKey="self_consumption_rate"
                        name={t('pages.reports.annualReport.trend.selfConsumption', { year: current })}
                        stroke={CHART_LOCAL}
                        strokeWidth={2}
                    />
                    <Line
                        type="monotone"
                        dataKey="self_sufficiency_rate"
                        name={t('pages.reports.annualReport.trend.selfSufficiency', { year: current })}
                        stroke={FLOW_LOCAL_CONS}
                        strokeWidth={2}
                    />
                    {hasPrevious && (
                        <Line
                            type="monotone"
                            dataKey="previous_self_consumption_rate"
                            name={t('pages.reports.annualReport.trend.selfConsumption', { year: previous })}
                            stroke={CHART_LOCAL}
                            strokeDasharray="5 4"
                            strokeOpacity={0.6}
                            dot={false}
                        />
                    )}
                    {hasPrevious && (
                        <Line
                            type="monotone"
                            dataKey="previous_self_sufficiency_rate"
                            name={t('pages.reports.annualReport.trend.selfSufficiency', { year: previous })}
                            stroke={FLOW_LOCAL_CONS}
                            strokeDasharray="5 4"
                            strokeOpacity={0.6}
                            dot={false}
                        />
                    )}
                </LineChart>
            </ResponsiveContainer>
        </section>
    )
}

function ParticipantSavingsCard({ report }: { report: AnnualReport }) {
    const { t } = useTranslation()
    return (
        <section className="card">
            <h3 style={{ marginTop: 0 }}>{t('pages.reports.annualReport.participants.title')}</h3>
            <p className="muted">{t('pages.reports.annualReport.participants.description')}</p>
            {report.participants.length === 0 ? (
                <p className="muted">{t('pages.reports.annualReport.participants.empty')}</p>
            ) : (
                <div className="table-scroll">
                    <table className="participant-table participant-table--static">
                        <thead>
                            <tr>
                                <th>{t('pages.reports.annualReport.col.participant')}</th>
                                <th className="numeric">{t('pages.reports.annualReport.col.consumption')}</th>
                                <th className="numeric">{t('pages.reports.annualReport.col.fromZev')}</th>
                                <th className="numeric">{t('pages.reports.annualReport.col.selfSufficiency')}</th>
                                <th className="numeric">{t('pages.reports.annualReport.col.localCost')}</th>
                                <th className="numeric">{t('pages.reports.annualReport.col.gridCost')}</th>
                                <th className="numeric">{t('pages.reports.annualReport.col.savings')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {report.participants.map((row) => (
                                <tr key={row.participant_id}>
                                    <td>
                                        {row.participant_name || '-'}
                                        {row.has_behind_meter_generation && (
                                            <BehindMeterBadge hintKey={behindMeterHintKey('participant', row.gross_energy)} />
                                        )}
                                    </td>
                                    <td className="numeric">{yearKwh(row.consumed_kwh)}</td>
                                    <td className="numeric">{yearKwh(row.from_zev_kwh)}</td>
                                    <td className="numeric">
                                        {row.has_behind_meter_generation ? (
                                            <NetMeteredRate gross={row.gross_energy} />
                                        ) : (
                                            percentOrDash(row.self_sufficiency_rate)
                                        )}
                                    </td>
                                    <td className="numeric">{chfOrDash(row.savings?.local_chf)}</td>
                                    <td className="numeric">{chfOrDash(row.savings?.hypothetical_chf)}</td>
                                    <td className="numeric">{chfOrDash(row.savings?.saved_chf)}</td>
                                </tr>
                            ))}
                        </tbody>
                        {report.savings_total_chf !== null && (
                            <tfoot>
                                <tr>
                                    <td>{t('pages.reports.annualReport.participants.total')}</td>
                                    <td colSpan={5} />
                                    <td className="numeric">{chfOrDash(report.savings_total_chf)}</td>
                                </tr>
                            </tfoot>
                        )}
                    </table>
                </div>
            )}
            <p className="muted" style={{ marginBottom: 0, fontSize: '0.875rem' }}>
                {t('pages.reports.annualReport.participants.note')}
            </p>
        </section>
    )
}
