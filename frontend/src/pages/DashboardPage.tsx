import { Link } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import {
    CartesianGrid,
    Legend,
    Line,
    LineChart,
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
                            <span>Participant</span>
                            <select
                                value={selectedParticipantId}
                                onChange={(e) => setSelectedParticipantId(e.target.value)}
                            >
                                <option value="">All participants</option>
                                {summary?.role === 'zev_owner' && summary.participant_stats.map((participant) => (
                                    <option key={participant.participant_id} value={participant.participant_id}>
                                        {participant.participant_name || participant.participant_id}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label>
                            <span>Resolution</span>
                            <select value={bucket} onChange={(e) => setBucket(e.target.value as 'day' | 'hour' | 'month')}>
                                <option value="hour">Hourly</option>
                                <option value="day">Daily</option>
                                <option value="month">Monthly</option>
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
                            <span>Resolution</span>
                            <select value={bucket} onChange={(e) => setBucket(e.target.value as 'day' | 'hour' | 'month')}>
                                <option value="hour">Hourly</option>
                                <option value="day">Daily</option>
                                <option value="month">Monthly</option>
                            </select>
                        </label>
                    </div>
                </section>
            )}

            {isZevScopedRole && !selectedZevId && !managedZevLoading && (
                <div className="card">No ZEV available for your account.</div>
            )}

            {isZevScopedRole && selectedZevId && !selectedZev && !managedZevLoading && managedZevs.length > 0 && (
                <div className="card">Please select a ZEV from the global selector in the sidebar.</div>
            )}

            {summaryQuery.isLoading && <div className="card">Loading dashboard analytics…</div>}
            {summaryQuery.isError && <div className="card error-banner">Failed to load metering analytics.</div>}

            {summary && summary.role === 'zev_owner' && (
                <>
                    <section className="grid grid-4">
                        <StatCard label="Produced in ZEV" value={`${summary.totals.produced_kwh.toFixed(2)} kWh`} />
                        <StatCard label="Consumed in ZEV" value={`${summary.totals.consumed_kwh.toFixed(2)} kWh`} />
                        <StatCard label="Imported from Grid" value={`${summary.totals.imported_kwh.toFixed(2)} kWh`} />
                        <StatCard label="Exported to Grid" value={`${summary.totals.exported_kwh.toFixed(2)} kWh`} />
                    </section>

                    <section className="card" style={{ minHeight: 360 }}>
                        <h3 style={{ marginTop: 0 }}>
                            Energy Balance
                            {selectedZevName ? ` — ${selectedZevName}` : ''}
                            {selectedParticipantName ? ` — ${selectedParticipantName}` : ''}
                        </h3>
                        {ownerTimeline.length === 0 ? (
                            <p className="muted">No metering data for selected period.</p>
                        ) : (
                            <ResponsiveContainer width="100%" height={320}>
                                <LineChart data={ownerTimeline}>
                                    <CartesianGrid strokeDasharray="3 3" />
                                    <XAxis dataKey="bucket" tick={{ fontSize: 11 }} />
                                    <YAxis tick={{ fontSize: 11 }} />
                                    <Tooltip />
                                    <Legend />
                                    <Line type="monotone" dataKey="produced_kwh" name="Produced" stroke="#16a34a" strokeWidth={2} dot={false} />
                                    <Line type="monotone" dataKey="consumed_kwh" name="Consumed" stroke="#0284c7" strokeWidth={2} dot={false} />
                                    <Line type="monotone" dataKey="imported_kwh" name="Imported" stroke="#f59e0b" strokeWidth={2} dot={false} />
                                    <Line type="monotone" dataKey="exported_kwh" name="Exported" stroke="#8b5cf6" strokeWidth={2} dot={false} />
                                </LineChart>
                            </ResponsiveContainer>
                        )}
                    </section>

                    <section className="card">
                        <h3 style={{ marginTop: 0 }}>Per Participant</h3>
                        {summary.participant_stats.length === 0 ? (
                            <p className="muted">No participant-level data for selected period.</p>
                        ) : (
                            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                <thead>
                                    <tr>
                                        <th style={{ textAlign: 'left', padding: '0.5rem 0.6rem' }}>Participant</th>
                                        <th style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>Consumption</th>
                                        <th style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>Production/Export</th>
                                        <th style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>From ZEV</th>
                                        <th style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>From Grid</th>
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
                        <StatCard label="Consumed from ZEV" value={`${summary.totals.consumed_from_zev_kwh.toFixed(2)} kWh`} />
                        <StatCard label="Imported from Grid" value={`${summary.totals.imported_from_grid_kwh.toFixed(2)} kWh`} />
                        <StatCard label="Total Consumption" value={`${summary.totals.total_consumed_kwh.toFixed(2)} kWh`} />
                    </section>

                    <section className="card" style={{ minHeight: 360 }}>
                        <h3 style={{ marginTop: 0 }}>Consumption Split</h3>
                        {participantTimeline.length === 0 ? (
                            <p className="muted">No metering data for selected period.</p>
                        ) : (
                            <ResponsiveContainer width="100%" height={320}>
                                <LineChart data={participantTimeline}>
                                    <CartesianGrid strokeDasharray="3 3" />
                                    <XAxis dataKey="bucket" tick={{ fontSize: 11 }} />
                                    <YAxis tick={{ fontSize: 11 }} />
                                    <Tooltip />
                                    <Legend />
                                    <Line type="monotone" dataKey="consumed_from_zev_kwh" name="From ZEV" stroke="#16a34a" strokeWidth={2} dot={false} />
                                    <Line type="monotone" dataKey="imported_from_grid_kwh" name="From Grid" stroke="#f59e0b" strokeWidth={2} dot={false} />
                                    <Line type="monotone" dataKey="total_consumed_kwh" name="Total" stroke="#0284c7" strokeWidth={2} dot={false} />
                                </LineChart>
                            </ResponsiveContainer>
                        )}
                    </section>

                    <section className="card">
                        <h3 style={{ marginTop: 0 }}>Invoices</h3>
                        {participantInvoicesQuery.isLoading ? (
                            <p className="muted">Loading invoices…</p>
                        ) : participantInvoicesQuery.isError ? (
                            <p className="muted">Failed to load invoices.</p>
                        ) : participantInvoicesWithPdf.length === 0 ? (
                            <p className="muted">No invoices available.</p>
                        ) : (
                            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                <thead>
                                    <tr>
                                        <th style={{ textAlign: 'left', padding: '0.5rem 0.6rem' }}>Invoice</th>
                                        <th style={{ textAlign: 'left', padding: '0.5rem 0.6rem' }}>Period</th>
                                        <th style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>Total</th>
                                        <th style={{ textAlign: 'left', padding: '0.5rem 0.6rem' }}>Actions</th>
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
                                                        View details
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
