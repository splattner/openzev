import type { DynamicTariffSource, DynamicTariffType } from '../../types/api'

/**
 * The `energy_type` a tariff must carry to link to a source of this VSE
 * tariff type — mirrors `tariffs.models.ENERGY_TYPE_BY_DYNAMIC_TARIFF_TYPE`
 * on the backend, which is what `Tariff.clean()` actually enforces. Every
 * Billable types price grid consumption or ordinary feed-in compensation.
 */
const ENERGY_TYPE_BY_DYNAMIC_TARIFF_TYPE: Record<DynamicTariffType, 'grid' | 'feed_in' | null> = {
  electricity: 'grid',
  grid: 'grid',
  metering: 'grid',
  national_fees: 'grid',
  dso: 'grid',
  dso_complete: 'grid',
  integrated: 'grid',
  integrated_complete: 'grid',
  regional_fees: 'grid',
  feed_in: 'feed_in',
  refund: null,
}

export function impliedEnergyType(source: DynamicTariffSource): 'grid' | 'feed_in' | null {
  return ENERGY_TYPE_BY_DYNAMIC_TARIFF_TYPE[source.tariff_type]
}

/**
 * Sources the form's picker should offer.
 *
 * A brand-new tariff has not fixed its energy type yet, so every source is a
 * legitimate choice — picking one is what sets the type. An existing version
 * has already locked its energy type (identity fields don't change in place,
 * see TariffFormModal), so only sources that would still pass
 * `Tariff.clean()` are worth showing: offering one that would just fail on
 * save is worse than not offering it.
 */
export function dynamicSourceOptions(
  sources: DynamicTariffSource[],
  lockedEnergyType?: string | null,
): DynamicTariffSource[] {
  return sources.filter((source) => {
    const energyType = impliedEnergyType(source)
    return energyType !== null && (!lockedEnergyType || energyType === lockedEnergyType)
  })
}
