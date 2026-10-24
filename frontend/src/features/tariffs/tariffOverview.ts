/**
 * Pure helpers for the tariff overview PDF download.
 *
 * Kept out of TariffsPage so the mapping from the page's own validity filter
 * to the API's `scope` parameter — and the download filename — is testable
 * without mounting the page or hitting the network.
 */
/** The overview PDF's scope, chosen at the download. */
export type TariffValidityFilter = 'valid' | 'all'

export function tariffOverviewParams(
    zevId: string,
    validityFilter: TariffValidityFilter,
): { zev_id: string; scope: 'valid' | 'all' } {
    return { zev_id: zevId, scope: validityFilter === 'all' ? 'all' : 'valid' }
}

export function tariffOverviewFilename(asOfIso: string): string {
    return `tariff-overview-${asOfIso}.pdf`
}
