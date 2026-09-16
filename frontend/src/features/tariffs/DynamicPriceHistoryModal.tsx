import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CivilDateInput } from '../../components/CivilDateInput'
import { DataTable, type ColumnDef } from '../../components/DataTable'
import { FormModal } from '../../components/FormModal'
import { StatCard } from '../../components/StatCard'
import { fetchDynamicPriceHistory } from '../../lib/api/tariffs'
import { formatDateTime, formatShortDate, useAppSettings } from '../../lib/appSettings'
import { AXIS_COLOR, CHART_GRIDLINE, CONS_COLORS } from '../../lib/chartTokens'
import { formatIsoDate, todayLocalIso } from '../../lib/dates'
import { queryKeys } from '../../lib/api/queryKeys'
import type { DynamicPriceHistory, DynamicPricePoint, DynamicTariffSource, Tariff } from '../../types/api'

/** What the history view needs from the tariff it was opened for, if any. */
export type TariffValidityContext = Pick<Tariff, 'valid_from' | 'valid_to' | 'minimum_price_chf_per_kwh'>

function daysBefore(isoDate: string, days: number): string {
  const value = new Date(`${isoDate}T12:00:00Z`)
  value.setUTCDate(value.getUTCDate() - days)
  return value.toISOString().slice(0, 10)
}

/**
 * The last civil date a tariff's own prices should be shown for.
 *
 * An open-ended tariff (`valid_to` null) is bounded at "today", since nothing
 * is published beyond it yet — except for a not-yet-started tariff, where
 * "today" would sit *before* `valid_from` and invert the range; there, the
 * bound is `valid_from` itself, an intentionally empty one-day window.
 */
function validityUpperBound(tariff: TariffValidityContext, today: string): string {
  const openEndedBound = tariff.valid_from > today ? tariff.valid_from : today
  return tariff.valid_to && tariff.valid_to < openEndedBound ? tariff.valid_to : openEndedBound
}

/**
 * Clip a range to a tariff's own validity window.
 *
 * A dynamic source is shared globally (ADR 0018) — its stored series can run
 * years before a given tariff ever linked to it, and past any date the
 * tariff was closed on. Opened from the tariff page, "price history" means
 * this tariff's prices, so neither end belongs in view: showing them reads
 * as the tariff having billed at a price it never charged anyone at.
 */
function clampToValidity(
  range: { dateFrom: string, dateTo: string },
  tariff: TariffValidityContext,
  today: string,
): { dateFrom: string, dateTo: string } {
  const upperBound = validityUpperBound(tariff, today)
  const dateFrom = range.dateFrom < tariff.valid_from ? tariff.valid_from : range.dateFrom
  const dateTo = range.dateTo > upperBound ? upperBound : range.dateTo
  // The source's own default window and the tariff's validity can be
  // disjoint entirely (a brand-new tariff on a source with years of prior
  // history) — clamping each end independently would then invert the range.
  return dateFrom > dateTo ? { dateFrom: tariff.valid_from, dateTo: upperBound } : { dateFrom, dateTo }
}

/**
 * The date range a freshly opened history view should start on.
 *
 * A quarter-hourly VSE source defaults to the last week, which is a
 * reasonable recent slice. A BFE reference-price source publishes one point
 * per quarter (or month), so the same default almost always lands on an
 * unpublished period and looks like nothing was ever fetched — default to
 * the source's own covered range instead. Either way, opened for a specific
 * tariff, the range is then clipped to that tariff's own validity.
 */
export function defaultHistoryDateRange(
  source: DynamicTariffSource,
  today: string,
  tariff?: TariffValidityContext | null,
): { dateFrom: string, dateTo: string } {
  const base = source.api_version === 'bfe_rmp' && source.covers_from && source.covers_to
    ? {
      // covers_to is the exclusive end of the last interval, which always
      // lands on a local month boundary here — the inclusive last covered
      // day is the one before it.
      dateFrom: formatIsoDate(new Date(source.covers_from)),
      dateTo: daysBefore(formatIsoDate(new Date(source.covers_to)), 1),
    }
    : { dateFrom: daysBefore(today, 6), dateTo: today }
  return tariff ? clampToValidity(base, tariff, today) : base
}

/**
 * Floor each point at the tariff's minimum, the same way
 * `TariffResolver.price_at` bills it (`backend/invoices/engine.py`) — a
 * fetched price below the floor is displayed at the floor, not at what the
 * series actually published.
 */
export function applyMinimumPrice(
  points: DynamicPricePoint[],
  minimumPriceChfPerKwh: string | null | undefined,
): DynamicPricePoint[] {
  if (!minimumPriceChfPerKwh) return points
  const floor = Number(minimumPriceChfPerKwh)
  return points.map((point) => (
    Number(point.price_chf_per_kwh) < floor
      ? { ...point, price_chf_per_kwh: minimumPriceChfPerKwh }
      : point
  ))
}

/**
 * Recompute the price-derived stats from (already floored) points.
 *
 * `gap_count` is about coverage, not price, so it is passed through from the
 * server response rather than recomputed.
 */
export function statsFromPoints(points: DynamicPricePoint[], gapCount: number): DynamicPriceHistory['stats'] {
  const prices = points.map((point) => Number(point.price_chf_per_kwh))
  if (prices.length === 0) {
    return {
      point_count: 0, minimum_chf_per_kwh: null, maximum_chf_per_kwh: null,
      average_chf_per_kwh: null, negative_count: 0, gap_count: gapCount,
    }
  }
  const sum = prices.reduce((total, price) => total + price, 0)
  return {
    point_count: prices.length,
    minimum_chf_per_kwh: Math.min(...prices).toFixed(5),
    maximum_chf_per_kwh: Math.max(...prices).toFixed(5),
    average_chf_per_kwh: (sum / prices.length).toFixed(5),
    negative_count: prices.filter((price) => price < 0).length,
    gap_count: gapCount,
  }
}

type PanelProps = {
  source: DynamicTariffSource
  /** The tariff this history was opened for, if any — see `TariffValidityContext`. */
  tariff?: TariffValidityContext | null
}

/**
 * The date-range picker, stats, chart and point table for one dynamic
 * source's fetched prices. Split out from `DynamicPriceHistoryModal` so the
 * tariff detail drawer can show it inline — there is room for it there, and
 * it is the one thing on that drawer a click used to be needed for (#728) —
 * while the dynamic-sources admin table, which opens it out of context from
 * a table row rather than an already-open detail view, still wants it as a
 * modal.
 */
export function DynamicPriceHistoryPanel({ source, tariff }: PanelProps) {
  const { t } = useTranslation()
  const { settings } = useAppSettings()
  const today = todayLocalIso()
  const [dateFrom, setDateFrom] = useState(daysBefore(today, 6))
  const [dateTo, setDateTo] = useState(today)

  useEffect(() => {
    const range = defaultHistoryDateRange(source, today, tariff)
    setDateFrom(range.dateFrom)
    setDateTo(range.dateTo)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source.id, tariff?.valid_from, tariff?.valid_to])

  const historyQuery = useQuery({
    queryKey: queryKeys.tariffs.dynamicPrices(source.id, dateFrom, dateTo),
    queryFn: () => fetchDynamicPriceHistory(source.id, dateFrom, dateTo),
    enabled: Boolean(dateFrom && dateTo),
  })

  const points = useMemo(
    () => applyMinimumPrice(historyQuery.data?.points ?? [], tariff?.minimum_price_chf_per_kwh),
    [historyQuery.data, tariff?.minimum_price_chf_per_kwh],
  )

  const chartData = useMemo(() => points.map((point) => ({
    timestamp: new Date(point.valid_from).getTime(),
    price: Number(point.price_chf_per_kwh),
  })), [points])

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

  const hasFloor = Boolean(tariff?.minimum_price_chf_per_kwh)
  const stats = hasFloor && historyQuery.data
    ? statsFromPoints(points, historyQuery.data.stats.gap_count)
    : historyQuery.data?.stats
  const validityMin = tariff?.valid_from
  const validityMax = tariff ? validityUpperBound(tariff, today) : undefined

  return (
    <div className="page-stack">
      <div className="form-grid">
        <label>
          <span>{t('pages.dynamicSources.history.dateFrom')}</span>
          <CivilDateInput
            value={dateFrom}
            onChange={(value) => setDateFrom(value ?? '')}
            minDate={validityMin}
            maxDate={validityMax}
          />
        </label>
        <label>
          <span>{t('pages.dynamicSources.history.dateTo')}</span>
          <CivilDateInput
            value={dateTo}
            onChange={(value) => setDateTo(value ?? '')}
            minDate={validityMin}
            maxDate={validityMax}
          />
        </label>
      </div>

      {tariff && (
        <p className="muted" style={{ margin: 0 }}>
          {t('pages.dynamicSources.history.validityScope', {
            from: formatShortDate(tariff.valid_from, settings),
            to: tariff.valid_to ? formatShortDate(tariff.valid_to, settings) : t('pages.tariffs.openEnded'),
          })}
          {hasFloor && ` ${t('pages.dynamicSources.history.minimumApplied', {
            price: Number(tariff.minimum_price_chf_per_kwh).toFixed(5),
          })}`}
        </p>
      )}

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
        data={points}
        columns={columns}
        getRowId={(point) => point.valid_from}
        loading={historyQuery.isLoading}
        initialPageSize={25}
        emptyMessage={t('pages.dynamicSources.history.empty')}
      />
    </div>
  )
}

type ModalProps = {
  source: DynamicTariffSource | null
  onClose: () => void
  /** The tariff this history was opened for, if any — see `TariffValidityContext`. */
  tariff?: TariffValidityContext | null
}

/** The admin dynamic-sources table opens this out of context, from a row
 * action rather than an already-open detail view — so unlike the tariff
 * drawer, it still gets a modal around the same panel. */
export function DynamicPriceHistoryModal({ source, onClose, tariff }: ModalProps) {
  const { t } = useTranslation()
  return (
    <FormModal
      isOpen={Boolean(source)}
      title={t('pages.dynamicSources.history.title', { label: source?.label ?? '' })}
      onClose={onClose}
      maxWidth="1000px"
    >
      {source && <DynamicPriceHistoryPanel source={source} tariff={tariff} />}
    </FormModal>
  )
}
