import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchDynamicPriceHistory } from '../../lib/api/tariffs'
import { queryKeys } from '../../lib/api/queryKeys'
import { todayBusinessIso } from '../../lib/dates'
import type { DynamicPriceHistory, DynamicTariffSource } from '../../types/api'
import { elapsedPriceGaps } from './dynamicPriceGaps'
import { defaultHistoryDateRange, type TariffValidityContext } from './DynamicPriceHistoryModal'

/**
 * Past stretches the source has no price for, within the tariff's validity.
 *
 * Reads the window the price chart opens on, so the chart and this share one
 * cached response rather than asking twice.
 */
export function useElapsedPriceGaps(
    source: DynamicTariffSource,
    tariff: TariffValidityContext,
): DynamicPriceHistory['gaps'] {
    const { dateFrom, dateTo } = defaultHistoryDateRange(source, todayBusinessIso(), tariff)
    const query = useQuery({
        queryKey: queryKeys.tariffs.dynamicPrices(source.id, dateFrom, dateTo),
        queryFn: () => fetchDynamicPriceHistory(source.id, dateFrom, dateTo),
    })
    return useMemo(
        () => elapsedPriceGaps(query.data?.gaps ?? [], query.dataUpdatedAt),
        [query.data, query.dataUpdatedAt],
    )
}
