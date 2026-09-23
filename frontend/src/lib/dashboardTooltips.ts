import { formatKwh, formatPercent } from './numbers'

// Identify the percentage series by dataKey; names are translated.
export function formatProductionMixTooltip(
    value: unknown,
    name: string,
    dataKey: unknown,
    selfConsumedLabel: string,
): [string, string] {
    if (dataKey === 'self_consumption_rate') {
        return [formatPercent(Number(value)), selfConsumedLabel]
    }
    return [`${formatKwh(Number(value), { maxDecimals: 2 })} kWh`, name]
}

// Same idea for the consumption charts' "from ZEV %" line.
export function formatConsumptionMixTooltip(
    value: unknown,
    name: string,
    dataKey: unknown,
    fromZevPctLabel: string,
): [string, string] {
    if (dataKey === 'from_zev_rate') {
        return [formatPercent(Number(value)), fromZevPctLabel]
    }
    return [`${formatKwh(Number(value), { maxDecimals: 2 })} kWh`, name]
}
