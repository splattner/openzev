import type { DynamicTariffSource, DynamicTariffType } from '../../types/api'

/**
 * The `energy_type` a tariff must carry to link to a source of this VSE
 * tariff type — mirrors `tariffs.models.ENERGY_TYPE_BY_DYNAMIC_TARIFF_TYPE`
 * on the backend, which is what `Tariff.clean()` actually enforces. Every
 * type prices grid consumption except reimbursement types, which pay export.
 */
const ENERGY_TYPE_BY_DYNAMIC_TARIFF_TYPE: Record<DynamicTariffType, 'grid' | 'feed_in'> = {
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
  refund: 'feed_in',
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

/**
 * Which other VSE tariff types a component already contains, per the
 * mapping table in docs/specs/2026-09-dynamic-tariffs.md §3.3. `integrated`
 * bundles electricity with grid usage; v2's `dso`/`dso_complete`/
 * `integrated_complete` bundle grid usage with metering and the national/
 * regional surcharges. Billing an aggregate beside a separate tariff for one
 * of the types it already contains charges that money twice — this is what
 * a double-counting warning needs to name.
 */
const AGGREGATED_TARIFF_TYPES: Partial<Record<DynamicTariffType, DynamicTariffType[]>> = {
  integrated: ['electricity', 'grid'],
  dso: ['grid', 'metering', 'national_fees'],
  dso_complete: ['grid', 'metering', 'national_fees', 'regional_fees'],
  integrated_complete: ['electricity', 'grid', 'metering', 'national_fees', 'regional_fees'],
}

export function aggregatedTariffTypes(tariffType: DynamicTariffType): DynamicTariffType[] {
  return AGGREGATED_TARIFF_TYPES[tariffType] ?? []
}
