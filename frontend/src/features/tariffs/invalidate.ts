import type { QueryClient } from '@tanstack/react-query'
import { queryKeys } from '../../lib/api/queryKeys'

/**
 * Refetch everything a tariff mutation can affect.
 *
 * Kept in one place on purpose. The tariff page reads the *series* query, while
 * the flat list and period queries still back other callers — so a mutation
 * that invalidates only the key it happens to know about leaves the page showing
 * stale data until a manual refresh. Every tariff mutation funnels through here
 * so adding a new one cannot reintroduce that.
 *
 * A single mutation can reshape more than the row it touched: editing a
 * version's `valid_to` changes its series' gaps, and creating a version also
 * closes its predecessor — so the whole series query is refetched rather than
 * patched.
 */
export function invalidateTariffQueries(queryClient: QueryClient, selectedZevId?: string): void {
    const zevId = selectedZevId || undefined
    void queryClient.invalidateQueries({ queryKey: queryKeys.tariffs.series(zevId) })
    void queryClient.invalidateQueries({ queryKey: queryKeys.tariffs.list(zevId) })
    void queryClient.invalidateQueries({ queryKey: queryKeys.tariffs.periods() })
}
