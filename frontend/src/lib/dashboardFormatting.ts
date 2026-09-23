import { formatKwh } from './numbers'

/** Period-bucket Y axes match tooltip precision (up to two decimals). */
export const kwhTick = (value: number): string => formatKwh(value, { maxDecimals: 2 })

/** Hourly-profile Y axes match tooltip precision (up to four decimals). */
export const hourlyKwhTick = (value: number): string => formatKwh(value, { maxDecimals: 4 })

/** Period-bucket tooltip (up to two decimals). */
export const kwhTooltipValue = (value: unknown): string =>
    `${formatKwh(Number(value), { maxDecimals: 2 })} kWh`

/** Hourly-profile tooltip (up to four decimals). */
export const hourlyKwhTooltipValue = (value: unknown): string =>
    `${formatKwh(Number(value), { maxDecimals: 4 })} kWh`

/** Dashboard KPI/table precision: up to two decimals. */
export const dashboardKwhStat = (value: number): string =>
    `${formatKwh(value, { maxDecimals: 2 })} kWh`

/** Share (0-100, one decimal) of consumption covered by the ZEV; null when nothing was consumed. */
export const fromZevRate = (fromZevKwh: number, totalConsumedKwh: number): number | null =>
    totalConsumedKwh > 0 ? Math.round((fromZevKwh / totalConsumedKwh) * 1000) / 10 : null
