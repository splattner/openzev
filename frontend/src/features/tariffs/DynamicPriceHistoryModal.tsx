import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CivilDateInput } from '../../components/CivilDateInput'
import { DataTable, type ColumnDef } from '../../components/DataTable'
import { FormModal } from '../../components/FormModal'
import { StatCard } from '../../components/StatCard'
import { fetchDynamicPriceHistory } from '../../lib/api/tariffs'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { AXIS_COLOR, CHART_GRIDLINE, CONS_COLORS } from '../../lib/chartTokens'
import { todayLocalIso } from '../../lib/dates'
import { queryKeys } from '../../lib/api/queryKeys'
import type { DynamicPricePoint, DynamicTariffSource } from '../../types/api'

function daysBefore(isoDate: string, days: number): string {
  const value = new Date(`${isoDate}T12:00:00Z`)
  value.setUTCDate(value.getUTCDate() - days)
  return value.toISOString().slice(0, 10)
}

type Props = {
  source: DynamicTariffSource | null
  onClose: () => void
}

export function DynamicPriceHistoryModal({ source, onClose }: Props) {
  const { t } = useTranslation()
  const { settings } = useAppSettings()
  const today = todayLocalIso()
  const [dateFrom, setDateFrom] = useState(daysBefore(today, 6))
  const [dateTo, setDateTo] = useState(today)

  const historyQuery = useQuery({
    queryKey: queryKeys.tariffs.dynamicPrices(source?.id ?? '', dateFrom, dateTo),
    queryFn: () => fetchDynamicPriceHistory(source!.id, dateFrom, dateTo),
    enabled: Boolean(source && dateFrom && dateTo),
  })

  const chartData = useMemo(() => (historyQuery.data?.points ?? []).map((point) => ({
    timestamp: new Date(point.valid_from).getTime(),
    price: Number(point.price_chf_per_kwh),
  })), [historyQuery.data])

  const columns = useMemo<ColumnDef<DynamicPricePoint, unknown>[]>(() => [
    {
      accessorKey: 'valid_from',
      header: t('pages.dynamicSources.history.from'),
      cell: ({ row }) => formatDateTime(row.original.valid_from, settings),
    },
    {
      accessorKey: 'valid_to',
      header: t('pages.dynamicSources.history.to'),
      cell: ({ row }) => formatDateTime(row.original.valid_to, settings),
    },
    {
      accessorKey: 'price_chf_per_kwh',
      header: t('pages.dynamicSources.history.price'),
      cell: ({ row }) => Number(row.original.price_chf_per_kwh).toFixed(5),
      meta: { numeric: true },
    },
  ], [settings, t])

  const stats = historyQuery.data?.stats

  return (
    <FormModal
      isOpen={Boolean(source)}
      title={t('pages.dynamicSources.history.title', { label: source?.label ?? '' })}
      onClose={onClose}
      maxWidth="1000px"
    >
      <div className="page-stack">
        <div className="form-grid">
          <label>
            <span>{t('pages.dynamicSources.history.dateFrom')}</span>
            <CivilDateInput value={dateFrom} onChange={(value) => setDateFrom(value ?? '')} />
          </label>
          <label>
            <span>{t('pages.dynamicSources.history.dateTo')}</span>
            <CivilDateInput value={dateTo} onChange={(value) => setDateTo(value ?? '')} />
          </label>
        </div>

        {historyQuery.isError && <div className="error-banner">{t('pages.dynamicSources.history.loadError')}</div>}

        {stats && (
          <div className="kpi-row">
            <StatCard label={t('pages.dynamicSources.history.points')} value={stats.point_count} flat />
            <StatCard
              label={t('pages.dynamicSources.history.average')}
              value={stats.average_chf_per_kwh == null ? '—' : Number(stats.average_chf_per_kwh).toFixed(5)}
              flat
            />
            <StatCard label={t('pages.dynamicSources.history.negative')} value={stats.negative_count} flat />
            <StatCard
              label={t('pages.dynamicSources.history.gaps')}
              value={stats.gap_count}
              tone={stats.gap_count > 0 ? 'warning' : 'success'}
            />
          </div>
        )}

        {chartData.length > 0 && (
          <section className="card">
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={chartData} margin={{ top: 8, right: 18, left: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRIDLINE} />
                <XAxis
                  dataKey="timestamp"
                  type="number"
                  scale="time"
                  domain={['dataMin', 'dataMax']}
                  tickFormatter={(value: number) => formatDateTime(new Date(value).toISOString(), settings)}
                  stroke={AXIS_COLOR}
                  fontSize={11}
                  minTickGap={48}
                />
                <YAxis stroke={AXIS_COLOR} fontSize={11} width={64} tickFormatter={(value) => Number(value).toFixed(3)} />
                <Tooltip
                  labelFormatter={(value) => formatDateTime(new Date(Number(value)).toISOString(), settings)}
                  formatter={(value) => [`${Number(value).toFixed(5)} CHF/kWh`, t('pages.dynamicSources.history.price')]}
                />
                <Line
                  dataKey="price"
                  type="stepAfter"
                  stroke={CONS_COLORS[0]}
                  dot={false}
                  activeDot={{ r: 4 }}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </section>
        )}

        {historyQuery.data && historyQuery.data.gaps.length > 0 && (
          <section className="warning-banner">
            <strong>{t('pages.dynamicSources.history.gapTitle')}</strong>
            <ul>
              {historyQuery.data.gaps.map((gap) => (
                <li key={gap.from}>{formatDateTime(gap.from, settings)} – {formatDateTime(gap.to, settings)}</li>
              ))}
            </ul>
          </section>
        )}

        <DataTable
          data={historyQuery.data?.points ?? []}
          columns={columns}
          getRowId={(point) => point.valid_from}
          loading={historyQuery.isLoading}
          initialPageSize={25}
          emptyMessage={t('pages.dynamicSources.history.empty')}
        />
      </div>
    </FormModal>
  )
}
