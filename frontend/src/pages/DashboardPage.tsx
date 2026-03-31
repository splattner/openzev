import { Link } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import {
    Bar,
    BarChart,
    CartesianGrid,
    ComposedChart,
    Legend,
    Line,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts'
import {
    fetchInvoices,
    fetchMeteringDashboardSummary,
} from '../lib/api'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { StatCard } from '../components/StatCard'
import { DateRangeShortcutPicker } from '../components/DateRangeShortcutPicker'
import { EnergyFlowChart } from '../components/EnergyFlowChart'
import {
    daysAgoIso,
    todayIso,
} from '../lib/dateRangePresets'

export function DashboardPage() {
    const { t } = useTranslation()
    const { user } = useAuth()
    const { settings } = useAppSettings()
    const { managedZevs, selectedZevId, selectedZev, isLoading: managedZevLoading } = useManagedZev()

    const [dateFrom, setDateFrom] = useState(daysAgoIso(30))
    const [dateTo, setDateTo] = useState(todayIso())
    const [bucket, setBucket] = useState<'day' | 'hour' | 'month'>('day')
    const [selectedParticipantId, setSelectedParticipantId] = useState('')

    const isZevScopedRole = user?.role === 'admin' || user?.role === 'zev_owner'

    useEffect(() => {
        setSelectedParticipantId('')
    }, [selectedZevId])

    const summaryQuery = useQuery({
        queryKey: ['metering-dashboard-summary', user?.role, selectedZevId, selectedParticipantId, dateFrom, dateTo, bucket],
        queryFn: () =>
            fetchMeteringDashboardSummary({
                dateFrom,
                dateTo,
                bucket,
                zevId: isZevScopedRole ? selectedZevId : undefined,
                participantId: isZevScopedRole && selectedParticipantId ? selectedParticipantId : undefined,
            }),
        enabled: user?.role === 'participant' || (isZevScopedRole && !!selectedZevId),
    })
    const participantInvoicesQuery = useQuery({
        queryKey: ['participant-dashboard-invoices'],
        queryFn: fetchInvoices,
        enabled: user?.role === 'participant',
    })

    const summary = summaryQuery.data
    const selectedZevName = selectedZev?.name
    const selectedParticipantName = summary?.role === 'zev_owner' ? summary.selected_participant_name : undefined
    const ownerTimeline = useMemo(
        () => (summary?.role === 'zev_owner' ? summary.timeline : []),
        [summary],
    )
    const ownerChartData = useMemo(
        () => ownerTimeline.map((entry) => {
            const locally_consumed = Math.max(0, entry.consumed_kwh - entry.imported_kwh)
            const locally_produced = Math.max(0, entry.produced_kwh - entry.exported_kwh)
            const self_consumption_rate = entry.produced_kwh > 0
                ? parseFloat(((locally_produced / entry.produced_kwh) * 100).toFixed(1))
                : null
            return { ...entry, locally_consumed, locally_produced, self_consumption_rate }
        }),
        [ownerTimeline],
    )
    const participantTimeline = useMemo(
        () => (summary?.role === 'participant' ? summary.timeline : []),
        [summary],
    )
    const participantInvoicesWithPdf = useMemo(
        () =>
            (participantInvoicesQuery.data?.results ?? []).filter(
                (invoice) => invoice.status === 'approved' && !!invoice.pdf_url,
            ),
        [participantInvoicesQuery.data],
    )

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('dashboard.quickStart')}</p>
                <h2>{t('dashboard.title')}</h2>
                <p className="muted">{t('dashboard.description')}</p>
            </header>

            {(user?.role === 'admin' || user?.role === 'zev_owner') && (
                <section className="card">
                    <div className="inline-form grid grid-3">
                        <DateRangeShortcutPicker
                            from={dateFrom}
                            to={dateTo}
                            onChange={({ from, to }) => {
                                setDateFrom(from)
                                setDateTo(to)
                            }}
                        />
                        <label>
                            <span>{t('pages.dashboard.participant')}</span>
                            <select
                                value={selectedParticipantId}
                                onChange={(e) => setSelectedParticipantId(e.target.value)}
                            >
                                <option value="">{t('pages.dashboard.allParticipants')}</option>
                                {summary?.role === 'zev_owner' && summary.participant_stats.map((participant) => (
                                    <option key={participant.participant_id} value={participant.participant_id}>
                                        {participant.participant_name || participant.participant_id}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label>
                            <span>{t('pages.dashboard.resolution')}</span>
                            <select value={bucket} onChange={(e) => setBucket(e.target.value as 'day' | 'hour' | 'month')}>
                                <option value="hour">{t('pages.dashboard.hourly')}</option>
                                <option value="day">{t('pages.dashboard.daily')}</option>
                                <option value="month">{t('pages.dashboard.monthly')}</option>
                            </select>
                        </label>
                    </div>
                </section>
            )}

            {user?.role === 'participant' && (
                <section className="card">
                    <div className="inline-form grid grid-4">
                        <DateRangeShortcutPicker
                            from={dateFrom}
                            to={dateTo}
                            onChange={({ from, to }) => {
                                setDateFrom(from)
                                setDateTo(to)
                            }}
                        />
                        <label>
                            <span>{t('pages.dashboard.resolution')}</span>
                            <select value={bucket} onChange={(e) => setBucket(e.target.value as 'day' | 'hour' | 'month')}>
                                <option value="hour">{t('pages.dashboard.hourly')}</option>
                                <option value="day">{t('pages.dashboard.daily')}</option>
                                <option value="month">{t('pages.dashboard.monthly')}</option>
                            </select>
                        </label>
                    </div>
                </section>
            )}

            {isZevScopedRole && !selectedZevId && !managedZevLoading && (
                <div className="card">{t('pages.dashboard.noZev')}</div>
            )}

            {isZevScopedRole && selectedZevId && !selectedZev && !managedZevLoading && managedZevs.length > 0 && (
                <div className="card">{t('pages.dashboard.selectZev')}</div>
            )}

            {summaryQuery.isLoading && <div className="card">{t('pages.dashboard.loadingAnalytics')}</div>}
            {summaryQuery.isError && <div className="card error-banner">{t('pages.dashboard.failedAnalytics')}</div>}

            {summary && summary.role === 'zev_owner' && (
                <>
                    {summary.participant_stats.length > 0 && (
                        <section className="card">
                            <h3 style={{ marginTop: 0 }}>
                                {t('pages.dashboard.energyFlow.title')}
                                {selectedZevName ? ` — ${selectedZevName}` : ''}
                            </h3>
                            <EnergyFlowChart
                                totals={summary.zev_totals}
                                participantStats={summary.participant_stats}
                                highlightParticipantId={selectedParticipantId || undefined}
                            />
                        </section>
                    )}

                    <section className="card">
                        <h3 style={{ marginTop: 0 }}>
                            {t('pages.dashboard.energyBalance')}
                            {selectedZevName ? ` — ${selectedZevName}` : ''}
                            {selectedParticipantName ? ` — ${selectedParticipantName}` : ''}
                        </h3>
                        {ownerChartData.length === 0 ? (
                            <p className="muted">{t('pages.dashboard.noData')}</p>
                        ) : (
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
                                <div>
                                    <p style={{ margin: '0 0 0.5rem', fontWeight: 600, fontSize: '0.875rem', color: '#374151' }}>{t('pages.dashboard.consumption')}</p>
                                    <ResponsiveContainer width="100%" height={300}>
                                        <BarChart data={ownerChartData} margin={{ top: 4, right: 4, bottom: 4, left: 0 }}>
                                            <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                            <XAxis dataKey="bucket" tick={{ fontSize: 10 }} />
                                            <YAxis tick={{ fontSize: 10 }} unit=" kWh" width={60} />
                                            <Tooltip formatter={(v) => `${Number(v).toFixed(2)} kWh`} />
                                            <Legend />
                                            <Bar dataKey="locally_consumed" name={t('pages.dashboard.chart.fromZev')} stackId="c" fill="#16a34a" />
                                            <Bar dataKey="imported_kwh" name={t('pages.dashboard.chart.fromGrid')} stackId="c" fill="#f59e0b" radius={[3, 3, 0, 0]} />
                                        </BarChart>
                                    </ResponsiveContainer>
                                </div>
                                <div>
                                    <p style={{ margin: '0 0 0.5rem', fontWeight: 600, fontSize: '0.875rem', color: '#374151' }}>{t('pages.dashboard.production')}</p>
                                    <ResponsiveContainer width="100%" height={300}>
                                        <ComposedChart data={ownerChartData} margin={{ top: 4, right: 50, bottom: 4, left: 0 }}>
                                            <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                            <XAxis dataKey="bucket" tick={{ fontSize: 10 }} />
                                            <YAxis yAxisId="kwh" tick={{ fontSize: 10 }} unit=" kWh" width={60} />
                                            <YAxis yAxisId="pct" orientation="right" tick={{ fontSize: 10 }} unit="%" width={44} domain={[0, 100]} />
                                            <Tooltip
                                                formatter={(v, name) =>
                                                    name === 'Self-consumed %'
                                                        ? [`${Number(v).toFixed(1)}%`, name]
                                                        : [`${Number(v).toFixed(2)} kWh`, name]
                                                }
                                            />
                                            <Legend />
                                            <Bar yAxisId="kwh" dataKey="locally_produced" name={t('pages.dashboard.chart.usedLocally')} stackId="p" fill="#16a34a" />
                                            <Bar yAxisId="kwh" dataKey="exported_kwh" name={t('pages.dashboard.chart.exported')} stackId="p" fill="#8b5cf6" radius={[3, 3, 0, 0]} />
                                            <Line yAxisId="pct" type="monotone" dataKey="self_consumption_rate" name={t('pages.dashboard.chart.selfConsumedPct')} stroke="#0ea5e9" dot={false} strokeWidth={2} connectNulls />
                                        </ComposedChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>
                        )}
                    </section>

                    <section className="card">
                        <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.perParticipant')}</h3>
                        {summary.participant_stats.length === 0 ? (
                            <p className="muted">{t('pages.dashboard.noParticipantData')}</p>
                        ) : (
                            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                <thead>
                                    <tr>
                                        <th style={{ textAlign: 'left', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.col.participant')}</th>
                                        <th style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.col.consumption')}</th>
                                        <th style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.col.productionExport')}</th>
                                        <th style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.col.fromZev')}</th>
                                        <th style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.col.fromGrid')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {summary.participant_stats.map((participant) => (
                                        <tr
                                            key={participant.participant_id}
                                            onClick={() => setSelectedParticipantId(participant.participant_id)}
                                            style={{
                                                borderTop: '1px solid var(--color-border, #e5e7eb)',
                                                cursor: 'pointer',
                                                backgroundColor: selectedParticipantId === participant.participant_id ? 'var(--color-bg-hover, #f3f4f6)' : 'transparent',
                                                transition: 'background-color 150ms ease-in-out',
                                            }}
                                            onMouseEnter={(e) => {
                                                if (selectedParticipantId !== participant.participant_id) {
                                                    e.currentTarget.style.backgroundColor = 'var(--color-bg-hover, #f0f1f3)'
                                                }
                                            }}
                                            onMouseLeave={(e) => {
                                                if (selectedParticipantId !== participant.participant_id) {
                                                    e.currentTarget.style.backgroundColor = 'transparent'
                                                }
                                            }}
                                        >
                                            <td style={{ padding: '0.5rem 0.6rem' }}>{participant.participant_name || '-'}</td>
                                            <td style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>{participant.total_consumed_kwh.toFixed(2)} kWh</td>
                                            <td style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>{participant.total_produced_kwh.toFixed(2)} kWh</td>
                                            <td style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>{participant.from_zev_kwh.toFixed(2)} kWh</td>
                                            <td style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>{participant.from_grid_kwh.toFixed(2)} kWh</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                    </section>
                </>
            )}

            {summary && summary.role === 'participant' && (
                <>
                    <section style={{ display: 'grid', gap: '1rem', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
                        <StatCard label={t('pages.dashboard.participantStats.consumedFromZev')} value={`${summary.totals.consumed_from_zev_kwh.toFixed(2)} kWh`} />
                        <StatCard label={t('pages.dashboard.participantStats.importedFromGrid')} value={`${summary.totals.imported_from_grid_kwh.toFixed(2)} kWh`} />
                        <StatCard label={t('pages.dashboard.participantStats.totalConsumption')} value={`${summary.totals.total_consumed_kwh.toFixed(2)} kWh`} />
                    </section>

                    {summary.zev_participant_stats.length > 0 && summary.current_participant_id && (
                        <section className="card">
                            <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.energyFlow.title')}</h3>
                            <EnergyFlowChart
                                totals={summary.zev_totals}
                                participantStats={summary.zev_participant_stats}
                                highlightParticipantId={summary.current_participant_id}
                            />
                        </section>
                    )}

                    <section className="card" style={{ minHeight: 360 }}>
                        <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.consumptionSplit')}</h3>
                        {participantTimeline.length === 0 ? (
                            <p className="muted">{t('pages.dashboard.noData')}</p>
                        ) : (
                            <ResponsiveContainer width="100%" height={320}>
                                <BarChart data={participantTimeline} margin={{ top: 4, right: 4, bottom: 4, left: 0 }}>
                                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                    <XAxis dataKey="bucket" tick={{ fontSize: 11 }} />
                                    <YAxis tick={{ fontSize: 11 }} unit=" kWh" width={60} />
                                    <Tooltip formatter={(v) => `${Number(v).toFixed(2)} kWh`} />
                                    <Legend />
                                    <Bar dataKey="consumed_from_zev_kwh" name={t('pages.dashboard.chart.fromZev')} stackId="c" fill="#16a34a" />
                                    <Bar dataKey="imported_from_grid_kwh" name={t('pages.dashboard.chart.fromGrid')} stackId="c" fill="#f59e0b" radius={[3, 3, 0, 0]} />
                                </BarChart>
                            </ResponsiveContainer>
                        )}
                    </section>

                    <section className="card">
                        <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.invoicesSection')}</h3>
                        {participantInvoicesQuery.isLoading ? (
                            <p className="muted">{t('pages.dashboard.loadingInvoices')}</p>
                        ) : participantInvoicesQuery.isError ? (
                            <p className="muted">{t('pages.dashboard.failedInvoices')}</p>
                        ) : participantInvoicesWithPdf.length === 0 ? (
                            <p className="muted">{t('pages.dashboard.noInvoices')}</p>
                        ) : (
                            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                <thead>
                                    <tr>
                                        <th style={{ textAlign: 'left', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.invoiceCol.invoice')}</th>
                                        <th style={{ textAlign: 'left', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.invoiceCol.period')}</th>
                                        <th style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.invoiceCol.total')}</th>
                                        <th style={{ textAlign: 'left', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.invoiceCol.actions')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {participantInvoicesWithPdf.map((invoice) => (
                                        <tr key={invoice.id} style={{ borderTop: '1px solid var(--color-border, #e5e7eb)' }}>
                                            <td style={{ padding: '0.5rem 0.6rem' }}>{invoice.invoice_number}</td>
                                            <td style={{ padding: '0.5rem 0.6rem' }}>{formatShortDate(invoice.period_start, settings)} → {formatShortDate(invoice.period_end, settings)}</td>
                                            <td style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>CHF {invoice.total_chf}</td>
                                            <td style={{ padding: '0.5rem 0.6rem' }}>
                                                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                                    <Link
                                                        className="button button-primary"
                                                        style={{ textDecoration: 'none' }}
                                                        to={`/invoices/${invoice.id}`}
                                                    >
                                                        {t('pages.dashboard.viewDetails')}
                                                    </Link>
                                                    <a
                                                        href={invoice.pdf_url ?? undefined}
                                                        target="_blank"
                                                        rel="noreferrer"
                                                        className="button button-primary"
                                                        style={{ textDecoration: 'none', padding: '0.3rem 0.5rem', lineHeight: 1 }}
                                                        aria-label={`Open PDF for ${invoice.invoice_number}`}
                                                        title="Open PDF"
                                                    >
                                                        📄
                                                    </a>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                    </section>
                </>
            )}
        </div>
    )
}
