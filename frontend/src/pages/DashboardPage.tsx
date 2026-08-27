import { Link } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery } from '@tanstack/react-query'
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
    fetchHourlyProfile,
    fetchMeteringDashboardSummary,
} from '../lib/api/metering'
import { downloadAnnualStatement, downloadAllAnnualStatements, downloadFinancialSummary, fetchInvoices, openInvoicePdf } from '../lib/api/invoices'
import { queryKeys } from '../lib/api/queryKeys'
import { downloadBlob } from '../lib/downloadBlob'
import { formatIsoDate } from '../lib/dates'
import { isInvoiceOverdue, selectOpenInvoices, sumTotalChf } from '../features/invoices/openInvoices'
import { OPEN_INVOICE_STATUSES } from '../features/invoices/invoiceStatus'
import { formatMeteringBucketLabel } from '../lib/meteringLabels'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { PageSkeleton } from '../components/PageSkeleton'
import { StatCard } from '../components/StatCard'
import { PeriodSelector } from '../components/PeriodSelector'
import { EnergyFlowChart } from '../components/EnergyFlowChart'
import {
    type BillingInterval,
    getCurrentBillingPeriod,
} from '../lib/billingPeriod'
import { CHART_GRID, CHART_LABEL, CHART_LOCAL, FLOW_GRID_EXP, FLOW_LOCAL_CONS } from '../lib/chartTokens'

export function DashboardPage() {
    const { t } = useTranslation()
    const { user } = useAuth()
    const { settings } = useAppSettings()
    const { managedZevs, selectedZevId, selectedZev, isLoading: managedZevLoading } = useManagedZev()

    const interval: BillingInterval = (selectedZev?.billing_interval as BillingInterval) ?? 'monthly'
    const [period, setPeriod] = useState<{ from: string; to: string }>(() => getCurrentBillingPeriod(interval))
    const [bucket, setBucket] = useState<'day' | 'hour' | 'month'>('day')
    const [selectedParticipantId, setSelectedParticipantId] = useState('')
    const [annualStatementYear, setAnnualStatementYear] = useState(new Date().getFullYear() - 1)
    const availableYears = Array.from({ length: 5 }, (_, i) => new Date().getFullYear() - i)

    const isZevScopedRole = user?.role === 'admin' || user?.role === 'zev_owner'

    const formatBucketLabel = (value: string) => formatMeteringBucketLabel(value, bucket, settings)
    const formatBucketTooltipLabel = (label: unknown) => formatBucketLabel(String(label ?? ''))

    useEffect(() => {
        setSelectedParticipantId('')
    }, [selectedZevId])

    useEffect(() => {
        setPeriod(getCurrentBillingPeriod(interval))
    }, [selectedZevId, interval])

    const summaryQuery = useQuery({
        queryKey: queryKeys.metering.dashboardSummary({
            role: user?.role,
            zevId: selectedZevId,
            participantId: selectedParticipantId,
            from: period.from,
            to: period.to,
            bucket,
        }),
        queryFn: () =>
            fetchMeteringDashboardSummary({
                dateFrom: period.from,
                dateTo: period.to,
                bucket,
                zevId: isZevScopedRole ? selectedZevId : undefined,
                participantId: isZevScopedRole && selectedParticipantId ? selectedParticipantId : undefined,
            }),
        enabled: user?.role === 'participant' || (isZevScopedRole && !!selectedZevId),
    })
    const openInvoiceStatusFilter = isZevScopedRole ? OPEN_INVOICE_STATUSES.join(',') : undefined
    const invoicesQuery = useQuery({
        queryKey: queryKeys.invoices.list(selectedZevId || undefined, openInvoiceStatusFilter),
        queryFn: () => fetchInvoices(selectedZevId || undefined, { status: openInvoiceStatusFilter }),
        // Participants see their own invoices server-side; owner/admin read
        // the selected ZEV's invoices for the open-invoice exception list.
        enabled: user?.role === 'participant' || (isZevScopedRole && !!selectedZevId),
    })
    const hourlyProfileQuery = useQuery({
        queryKey: queryKeys.metering.hourlyProfile(period.from, period.to, selectedZevId || undefined, selectedParticipantId || undefined),
        queryFn: () =>
            fetchHourlyProfile({
                dateFrom: period.from,
                dateTo: period.to,
                zevId: isZevScopedRole ? selectedZevId : undefined,
                participantId: isZevScopedRole && selectedParticipantId ? selectedParticipantId : undefined,
            }),
        enabled: user?.role === 'participant' || (isZevScopedRole && !!selectedParticipantId),
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
    const hourlyProfile = hourlyProfileQuery.data?.hourly_profile ?? null
    const hourlyProfileData = useMemo(
        () => hourlyProfile?.map((entry) => ({
            ...entry,
            label: `${String(entry.hour).padStart(2, '0')}:00`,
        })) ?? [],
        [hourlyProfile],
    )
    const participantInvoicesWithPdf = useMemo(
        () =>
            (invoicesQuery.data ?? []).filter(
                (invoice) => ['approved', 'sent', 'paid'].includes(invoice.status) && !!invoice.pdf_url,
            ),
        [invoicesQuery.data],
    )
    const today = useMemo(() => formatIsoDate(new Date()), [])
    const openInvoices = useMemo(
        () => selectOpenInvoices(invoicesQuery.data ?? []),
        [invoicesQuery.data],
    )
    const openOverdueCount = useMemo(
        () => openInvoices.filter((invoice) => isInvoiceOverdue(invoice, today)).length,
        [openInvoices, today],
    )
    const ownerSelfConsumption = useMemo(() => {
        if (summary?.role !== 'zev_owner') return null
        const { produced_kwh, exported_kwh } = summary.zev_totals
        if (produced_kwh <= 0) return null
        const localKwh = Math.max(0, produced_kwh - exported_kwh)
        return { pct: (localKwh / produced_kwh) * 100, localKwh, producedKwh: produced_kwh }
    }, [summary])

    const annualStatementMutation = useMutation({
        mutationFn: (year: number) => downloadAnnualStatement({ year }),
        onSuccess: (blob, year) => {
            downloadBlob(blob, `annual-statement-${year}.pdf`)
        },
    })

    const allAnnualStatementsMutation = useMutation({
        mutationFn: (year: number) => downloadAllAnnualStatements({ year, zev_id: selectedZevId! }),
        onSuccess: (blob, year) => {
            downloadBlob(blob, `annual-statements-${year}.zip`)
        },
    })

    const financialSummaryMutation = useMutation({
        mutationFn: (year: number) => downloadFinancialSummary({ year, zev_id: selectedZevId || undefined }),
        onSuccess: (blob, year) => {
            downloadBlob(blob, `financial-summary-${year}.pdf`)
        },
    })

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('dashboard.quickStart')}</p>
                <h2>{t('dashboard.title')}</h2>
                <p className="muted">{t('dashboard.description')}</p>
            </header>

            {(user?.role === 'admin' || user?.role === 'zev_owner') && (
                <section className="card">
                    <div className="grid">
                        <PeriodSelector
                            interval={interval}
                            from={period.from}
                            to={period.to}
                            onChange={setPeriod}
                        />
                        <div className="inline-form grid grid-2">
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
                    </div>
                </section>
            )}

            {user?.role === 'participant' && (
                <section className="card">
                    <div className="grid">
                        <PeriodSelector
                            interval={interval}
                            from={period.from}
                            to={period.to}
                            onChange={setPeriod}
                        />
                        <div className="inline-form" style={{ maxWidth: '320px' }}>
                            <label>
                                <span>{t('pages.dashboard.resolution')}</span>
                                <select value={bucket} onChange={(e) => setBucket(e.target.value as 'day' | 'hour' | 'month')}>
                                    <option value="hour">{t('pages.dashboard.hourly')}</option>
                                    <option value="day">{t('pages.dashboard.daily')}</option>
                                    <option value="month">{t('pages.dashboard.monthly')}</option>
                                </select>
                            </label>
                        </div>
                    </div>
                </section>
            )}

            {isZevScopedRole && !selectedZevId && !managedZevLoading && (
                <div className="card">{t('pages.dashboard.noZev')}</div>
            )}

            {isZevScopedRole && selectedZevId && !selectedZev && !managedZevLoading && managedZevs.length > 0 && (
                <div className="card">{t('pages.dashboard.selectZev')}</div>
            )}

            {summaryQuery.isLoading && <PageSkeleton variant="kpiRow" />}
            {summaryQuery.isError && <div className="card error-banner">{t('pages.dashboard.failedAnalytics')}</div>}

            {summary && summary.role === 'zev_owner' && (
                <>
                    {/* Hero + KPI row (spec §5.1): always ZEV-wide, even when a
                        participant drill-down filters the charts below. */}
                    <section className="kpi-row">
                        <StatCard
                            accent
                            label={t('pages.dashboard.stats.selfConsumptionRate')}
                            value={ownerSelfConsumption ? `${ownerSelfConsumption.pct.toFixed(1)} %` : '—'}
                            hint={ownerSelfConsumption
                                ? t('pages.dashboard.hints.selfConsumption', {
                                    local: ownerSelfConsumption.localKwh.toFixed(0),
                                    total: ownerSelfConsumption.producedKwh.toFixed(0),
                                })
                                : undefined}
                        />
                        <StatCard label={t('pages.dashboard.stats.producedInZev')} value={`${summary.zev_totals.produced_kwh.toFixed(2)} kWh`} />
                        <StatCard label={t('pages.dashboard.stats.consumedInZev')} value={`${summary.zev_totals.consumed_kwh.toFixed(2)} kWh`} />
                        <StatCard label={t('pages.dashboard.stats.importedFromGrid')} value={`${summary.zev_totals.imported_kwh.toFixed(2)} kWh`} />
                        <StatCard label={t('pages.dashboard.stats.exportedToGrid')} value={`${summary.zev_totals.exported_kwh.toFixed(2)} kWh`} />
                    </section>

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

                    {/* Short exception list (spec §5.1): open invoices still
                        awaiting payment, filtered server-side so later pages
                        are not dropped; selectOpenInvoices is a client-side
                        fallback. */}
                    <section className="card">
                        <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.openInvoices.title')}</h3>
                        {invoicesQuery.isLoading ? (
                            <PageSkeleton variant="tableRows" />
                        ) : invoicesQuery.isError ? (
                            <p className="muted">{t('pages.dashboard.failedInvoices')}</p>
                        ) : openInvoices.length === 0 ? (
                            <p className="muted">{t('pages.dashboard.openInvoices.empty')}</p>
                        ) : (
                            <>
                                <ul className="open-invoices-list">
                                    {openInvoices.slice(0, 5).map((invoice) => (
                                        <li key={invoice.id}>
                                            <span className="open-invoice-main">
                                                <span className="open-invoice-number">{invoice.invoice_number}</span>
                                                <span className="open-invoice-participant">{invoice.participant_name}</span>
                                            </span>
                                            <span className="open-invoice-amount">CHF {invoice.total_chf}</span>
                                            {isInvoiceOverdue(invoice, today) ? (
                                                <span className="badge badge-danger">{t('pages.dashboard.openInvoices.overdue')}</span>
                                            ) : (
                                                <span className="badge badge-info">{t('pages.dashboard.openInvoices.open')}</span>
                                            )}
                                        </li>
                                    ))}
                                </ul>
                                <div className="open-invoices-foot">
                                    <span>
                                        {t('pages.dashboard.openInvoices.outstanding', {
                                            openCount: openInvoices.length,
                                            overdueCount: openOverdueCount,
                                            amount: sumTotalChf(openInvoices).toFixed(2),
                                        })}
                                    </span>
                                    <Link to="/invoices">{t('pages.dashboard.openInvoices.viewAll')}</Link>
                                </div>
                            </>
                        )}
                    </section>

                    <section className="card">
                        <h3 style={{ marginTop: 0 }}>
                            {t('pages.dashboard.energyBalance')}
                            {selectedZevName ? ` — ${selectedZevName}` : ''}
                            {selectedParticipantName ? ` — ${selectedParticipantName}` : ''}
                        </h3>
                        {ownerChartData.length === 0 ? (
                            <p className="muted">{t('pages.dashboard.noData')}</p>
                        ) : (
                            <div className="form-grid" style={{ gap: '2rem' }}>
                                <div>
                                    <p style={{ margin: '0 0 0.5rem', fontWeight: 600, fontSize: '0.875rem', color: CHART_LABEL }}>{t('pages.dashboard.consumption')}</p>
                                    <ResponsiveContainer width="100%" height={300}>
                                        <BarChart data={ownerChartData} margin={{ top: 4, right: 4, bottom: 4, left: 0 }}>
                                            <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                            <XAxis dataKey="bucket" tick={{ fontSize: 10 }} tickFormatter={formatBucketLabel} />
                                            <YAxis tick={{ fontSize: 10 }} unit=" kWh" width={60} />
                                            <Tooltip formatter={(v) => `${Number(v).toFixed(2)} kWh`} labelFormatter={formatBucketTooltipLabel} />
                                            <Legend />
                                            <Bar dataKey="locally_consumed" name={t('pages.dashboard.chart.fromZev')} stackId="c" fill={CHART_LOCAL} />
                                            <Bar dataKey="imported_kwh" name={t('pages.dashboard.chart.fromGrid')} stackId="c" fill={CHART_GRID} radius={[3, 3, 0, 0]} />
                                        </BarChart>
                                    </ResponsiveContainer>
                                </div>
                                <div>
                                    <p style={{ margin: '0 0 0.5rem', fontWeight: 600, fontSize: '0.875rem', color: CHART_LABEL }}>{t('pages.dashboard.production')}</p>
                                    <ResponsiveContainer width="100%" height={300}>
                                        <ComposedChart data={ownerChartData} margin={{ top: 4, right: 50, bottom: 4, left: 0 }}>
                                            <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                            <XAxis dataKey="bucket" tick={{ fontSize: 10 }} tickFormatter={formatBucketLabel} />
                                            <YAxis yAxisId="kwh" tick={{ fontSize: 10 }} unit=" kWh" width={60} />
                                            <YAxis yAxisId="pct" orientation="right" tick={{ fontSize: 10 }} unit="%" width={44} domain={[0, 100]} />
                                            <Tooltip
                                                labelFormatter={formatBucketTooltipLabel}
                                                formatter={(v, name) =>
                                                    name === 'Self-consumed %'
                                                        ? [`${Number(v).toFixed(1)}%`, name]
                                                        : [`${Number(v).toFixed(2)} kWh`, name]
                                                }
                                            />
                                            <Legend />
                                            <Bar yAxisId="kwh" dataKey="locally_produced" name={t('pages.dashboard.chart.usedLocally')} stackId="p" fill={CHART_LOCAL} />
                                            <Bar yAxisId="kwh" dataKey="exported_kwh" name={t('pages.dashboard.chart.exported')} stackId="p" fill={FLOW_GRID_EXP} radius={[3, 3, 0, 0]} />
                                            <Line yAxisId="pct" type="monotone" dataKey="self_consumption_rate" name={t('pages.dashboard.chart.selfConsumedPct')} stroke={FLOW_LOCAL_CONS} dot={false} strokeWidth={2} connectNulls />
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
                                                borderTop: '1px solid var(--border-default)',
                                                cursor: 'pointer',
                                                backgroundColor: selectedParticipantId === participant.participant_id ? 'var(--surface)' : 'transparent',
                                                transition: 'background-color 150ms ease-in-out',
                                            }}
                                            onMouseEnter={(e) => {
                                                if (selectedParticipantId !== participant.participant_id) {
                                                    e.currentTarget.style.backgroundColor = 'var(--surface)'
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

                    {selectedParticipantId && hourlyProfileData.length > 0 && (
                        <section className="card" style={{ minHeight: 360 }}>
                            <h3 style={{ marginTop: 0 }}>
                                {t('pages.dashboard.hourlyProfile.title')}
                                {selectedParticipantName ? ` — ${selectedParticipantName}` : ''}
                            </h3>
                            <p className="muted" style={{ marginTop: 0, fontSize: '0.875rem' }}>{t('pages.dashboard.hourlyProfile.description')}</p>
                            <ResponsiveContainer width="100%" height={320}>
                                <BarChart data={hourlyProfileData} margin={{ top: 4, right: 4, bottom: 4, left: 0 }}>
                                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                    <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                                    <YAxis tick={{ fontSize: 11 }} unit=" kWh" width={60} />
                                    <Tooltip formatter={(v) => `${Number(v).toFixed(4)} kWh`} />
                                    <Legend />
                                    <Bar dataKey="from_zev_kwh" name={t('pages.dashboard.chart.fromZev')} stackId="c" fill={CHART_LOCAL} />
                                    <Bar dataKey="from_grid_kwh" name={t('pages.dashboard.chart.fromGrid')} stackId="c" fill={CHART_GRID} radius={[3, 3, 0, 0]} />
                                </BarChart>
                            </ResponsiveContainer>
                        </section>
                    )}

                    <section className="card">
                        <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.annualStatement.title')}</h3>
                        <p className="muted" style={{ marginBottom: '1rem' }}>{t('pages.dashboard.annualStatement.ownerDescription')}</p>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                <span>{t('pages.dashboard.annualStatement.year')}</span>
                                <select
                                    value={annualStatementYear}
                                    onChange={(e) => setAnnualStatementYear(Number(e.target.value))}
                                    style={{ width: 'auto' }}
                                >
                                    {availableYears.map((y) => (
                                        <option key={y} value={y}>{y}</option>
                                    ))}
                                </select>
                            </label>
                            <button
                                className="button button-primary"
                                disabled={allAnnualStatementsMutation.isPending}
                                onClick={() => allAnnualStatementsMutation.mutate(annualStatementYear)}
                            >
                                {allAnnualStatementsMutation.isPending
                                    ? t('pages.dashboard.annualStatement.downloading')
                                    : t('pages.dashboard.annualStatement.downloadAll')}
                            </button>
                        </div>
                        {allAnnualStatementsMutation.isError && (
                            <p className="muted" style={{ color: 'var(--danger-600)', marginTop: '0.5rem' }}>
                                {t('pages.dashboard.annualStatement.error')}
                            </p>
                        )}
                    </section>

                    <section className="card">
                        <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.financialSummary.title')}</h3>
                        <p className="muted" style={{ marginBottom: '1rem' }}>{t('pages.dashboard.financialSummary.description')}</p>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                <span>{t('pages.dashboard.financialSummary.year')}</span>
                                <select
                                    value={annualStatementYear}
                                    onChange={(e) => setAnnualStatementYear(Number(e.target.value))}
                                    style={{ width: 'auto' }}
                                >
                                    {availableYears.map((y) => (
                                        <option key={y} value={y}>{y}</option>
                                    ))}
                                </select>
                            </label>
                            <button
                                className="button button-primary"
                                disabled={financialSummaryMutation.isPending}
                                onClick={() => financialSummaryMutation.mutate(annualStatementYear)}
                            >
                                {financialSummaryMutation.isPending
                                    ? t('pages.dashboard.financialSummary.downloading')
                                    : t('pages.dashboard.financialSummary.download')}
                            </button>
                        </div>
                        {financialSummaryMutation.isError && (
                            <p className="muted" style={{ color: 'var(--danger-600)', marginTop: '0.5rem' }}>
                                {t('pages.dashboard.financialSummary.error')}
                            </p>
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
                                    <XAxis dataKey="bucket" tick={{ fontSize: 11 }} tickFormatter={formatBucketLabel} />
                                    <YAxis tick={{ fontSize: 11 }} unit=" kWh" width={60} />
                                    <Tooltip formatter={(v) => `${Number(v).toFixed(2)} kWh`} labelFormatter={formatBucketTooltipLabel} />
                                    <Legend />
                                    <Bar dataKey="consumed_from_zev_kwh" name={t('pages.dashboard.chart.fromZev')} stackId="c" fill={CHART_LOCAL} />
                                    <Bar dataKey="imported_from_grid_kwh" name={t('pages.dashboard.chart.fromGrid')} stackId="c" fill={CHART_GRID} radius={[3, 3, 0, 0]} />
                                </BarChart>
                            </ResponsiveContainer>
                        )}
                    </section>

                    {hourlyProfileData.length > 0 && (
                        <section className="card" style={{ minHeight: 360 }}>
                            <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.hourlyProfile.title')}</h3>
                            <p className="muted" style={{ marginTop: 0, fontSize: '0.875rem' }}>{t('pages.dashboard.hourlyProfile.description')}</p>
                            <ResponsiveContainer width="100%" height={320}>
                                <BarChart data={hourlyProfileData} margin={{ top: 4, right: 4, bottom: 4, left: 0 }}>
                                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                    <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                                    <YAxis tick={{ fontSize: 11 }} unit=" kWh" width={60} />
                                    <Tooltip formatter={(v) => `${Number(v).toFixed(4)} kWh`} />
                                    <Legend />
                                    <Bar dataKey="from_zev_kwh" name={t('pages.dashboard.chart.fromZev')} stackId="c" fill={CHART_LOCAL} />
                                    <Bar dataKey="from_grid_kwh" name={t('pages.dashboard.chart.fromGrid')} stackId="c" fill={CHART_GRID} radius={[3, 3, 0, 0]} />
                                </BarChart>
                            </ResponsiveContainer>
                        </section>
                    )}

                    <section className="card">
                        <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.invoicesSection')}</h3>
                        {invoicesQuery.isLoading ? (
                            <PageSkeleton variant="tableRows" />
                        ) : invoicesQuery.isError ? (
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
                                        <tr key={invoice.id} style={{ borderTop: '1px solid var(--border-default)' }}>
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
                                                    <button
                                                        type="button"
                                                        onClick={() => openInvoicePdf(invoice.id)}
                                                        className="button button-primary"
                                                        style={{ textDecoration: 'none', padding: '0.3rem 0.5rem', lineHeight: 1 }}
                                                        aria-label={t('pages.dashboard.openInvoicePdf', { number: invoice.invoice_number })}
                                                        title={t('common.openPdf')}
                                                    >
                                                        📄
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                    </section>

                    <section className="card">
                        <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.annualStatement.title')}</h3>
                        <p className="muted" style={{ marginBottom: '1rem' }}>{t('pages.dashboard.annualStatement.description')}</p>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                <span>{t('pages.dashboard.annualStatement.year')}</span>
                                <select
                                    value={annualStatementYear}
                                    onChange={(e) => setAnnualStatementYear(Number(e.target.value))}
                                    style={{ width: 'auto' }}
                                >
                                    {availableYears.map((y) => (
                                        <option key={y} value={y}>{y}</option>
                                    ))}
                                </select>
                            </label>
                            <button
                                className="button button-primary"
                                disabled={annualStatementMutation.isPending}
                                onClick={() => annualStatementMutation.mutate(annualStatementYear)}
                            >
                                {annualStatementMutation.isPending
                                    ? t('pages.dashboard.annualStatement.downloading')
                                    : t('pages.dashboard.annualStatement.download')}
                            </button>
                        </div>
                        {annualStatementMutation.isError && (
                            <p className="muted" style={{ color: 'var(--danger-600)', marginTop: '0.5rem' }}>
                                {t('pages.dashboard.annualStatement.error')}
                            </p>
                        )}
                    </section>

                    <section className="card">
                        <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.financialSummary.title')}</h3>
                        <p className="muted" style={{ marginBottom: '1rem' }}>{t('pages.dashboard.financialSummary.description')}</p>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                <span>{t('pages.dashboard.financialSummary.year')}</span>
                                <select
                                    value={annualStatementYear}
                                    onChange={(e) => setAnnualStatementYear(Number(e.target.value))}
                                    style={{ width: 'auto' }}
                                >
                                    {availableYears.map((y) => (
                                        <option key={y} value={y}>{y}</option>
                                    ))}
                                </select>
                            </label>
                            <button
                                className="button button-primary"
                                disabled={financialSummaryMutation.isPending}
                                onClick={() => financialSummaryMutation.mutate(annualStatementYear)}
                            >
                                {financialSummaryMutation.isPending
                                    ? t('pages.dashboard.financialSummary.downloading')
                                    : t('pages.dashboard.financialSummary.download')}
                            </button>
                        </div>
                        {financialSummaryMutation.isError && (
                            <p className="muted" style={{ color: 'var(--danger-600)', marginTop: '0.5rem' }}>
                                {t('pages.dashboard.financialSummary.error')}
                            </p>
                        )}
                    </section>
                </>
            )}
        </div>
    )
}
