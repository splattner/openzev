import type { DynamicTariffSource, DynamicTariffType } from '../../types/api'

/**
 * The `energy_type` a tariff must carry to link to a source of this VSE
 * tariff type — mirrors `tariffs.models.ENERGY_TYPE_BY_DYNAMIC_TARIFF_TYPE`
 * on the backend, which is what `Tariff.clean()` actually enforces. Every
 * type prices grid consumption except `feed_in`, which pays for export.
 */
const ENERGY_TYPE_BY_DYNAMIC_TARIFF_TYPE: Record<DynamicTariffType, 'grid' | 'feed_in'> = {
  electricity: 'grid',
  grid: 'grid',
  integrated: 'grid',
  regional_fees: 'grid',
  feed_in: 'feed_in',
}

export function impliedEnergyType(source: DynamicTariffSource): 'grid' | 'feed_in' {
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
  if (!lockedEnergyType) return sources
  return sources.filter((source) => impliedEnergyType(source) === lockedEnergyType)
}
