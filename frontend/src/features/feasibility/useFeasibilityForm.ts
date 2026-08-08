import { z } from 'zod'
import type { FeasibilityInput, FeasibilityPrefill } from '../../types/api'

export type InternalEnergyPriceMode = 'absolute' | 'percentage_of_retail'
type AnnualProductionMode = 'absolute' | 'from_kwp'
type EnergyInputMode = 'aggregate' | 'participants'

type ParticipantFormRow = {
  name: string
  annual_production_kwh: string
  annual_consumption_kwh: string
}

export const emptyParticipantRow: ParticipantFormRow = {
  name: '',
  annual_production_kwh: '0',
  annual_consumption_kwh: '0',
}

export type FeasibilityFormValues = {
  energy_input_mode: EnergyInputMode
  annual_production_mode: AnnualProductionMode
  annual_production_kwh: string
  pv_kwp: string
  specific_yield_kwh_per_kwp: string
  annual_consumption_kwh: string
  participants: ParticipantFormRow[]
  self_consumption_rate_pct: string
  retail_price_chf_per_kwh: string
  feed_in_price_chf_per_kwh: string
  internal_energy_price_mode: InternalEnergyPriceMode
  internal_energy_price_chf_per_kwh: string
  internal_energy_price_pct_of_retail: string
  annual_opex_chf: string
  capex_chf: string
  horizon_years: string
  discount_rate_pct: string
}

function isNonNegativeNumber(value: string): boolean {
  if (value.trim() === '') return false
  const n = Number(value)
  return !Number.isNaN(n) && n >= 0
}

function isPercentage(value: string): boolean {
  if (value.trim() === '') return false
  const n = Number(value)
  return !Number.isNaN(n) && n >= 0 && n <= 100
}

const participantRowSchema = z.object({
  name: z.string(),
  annual_production_kwh: z.string().refine(isNonNegativeNumber),
  annual_consumption_kwh: z.string().refine(isNonNegativeNumber),
})

export const feasibilityFormSchema = z.object({
  energy_input_mode: z.enum(['aggregate', 'participants']),
  annual_production_mode: z.enum(['absolute', 'from_kwp']),
  annual_production_kwh: z.string().refine(isNonNegativeNumber),
  pv_kwp: z.string().refine(isNonNegativeNumber),
  specific_yield_kwh_per_kwp: z.string().refine(isNonNegativeNumber),
  annual_consumption_kwh: z.string().refine(isNonNegativeNumber),
  participants: z.array(participantRowSchema),
  self_consumption_rate_pct: z.string().refine(isPercentage),
  retail_price_chf_per_kwh: z.string().refine(isNonNegativeNumber),
  feed_in_price_chf_per_kwh: z.string().refine(isNonNegativeNumber),
  internal_energy_price_mode: z.enum(['absolute', 'percentage_of_retail']),
  internal_energy_price_chf_per_kwh: z.string().refine(isNonNegativeNumber),
  internal_energy_price_pct_of_retail: z.string().refine(isNonNegativeNumber),
  annual_opex_chf: z.string().refine(isNonNegativeNumber),
  capex_chf: z.string().refine(isNonNegativeNumber),
  horizon_years: z.string().refine((v) => {
    const n = Number(v)
    return Number.isInteger(n) && n >= 1 && n <= 50
  }),
  discount_rate_pct: z.string().refine(isPercentage),
})

// Illustrative starting values plus Swiss planning-stage defaults mirroring
// backend/feasibility/defaults.py. Kept in sync manually — these only seed
// the form so it shows a live result immediately; the backend remains the
// single source of truth for the actual calculation.
export const defaultFeasibilityFormValues: FeasibilityFormValues = {
  energy_input_mode: 'aggregate',
  annual_production_mode: 'absolute',
  annual_production_kwh: '10000',
  pv_kwp: '10',
  specific_yield_kwh_per_kwp: '950',
  annual_consumption_kwh: '8000',
  participants: [],
  self_consumption_rate_pct: '50',
  retail_price_chf_per_kwh: '0.32',
  feed_in_price_chf_per_kwh: '0.09',
  internal_energy_price_mode: 'absolute',
  internal_energy_price_chf_per_kwh: '0.20',
  internal_energy_price_pct_of_retail: '62.5',
  annual_opex_chf: '300',
  capex_chf: '2000',
  horizon_years: '20',
  discount_rate_pct: '3',
}

// JS float arithmetic on arbitrary decimals (e.g. 0.35 * 45 / 100) routinely
// produces results like 0.15749999999999997 that need far more digits to
// round-trip than the value actually has. Sent through .toString() as-is,
// that blows past the backend DecimalField's max_digits and 400s. Round to
// the same decimal_places the target field expects before stringifying.
function toFixedString(value: number, decimalPlaces: number): string {
  return value.toFixed(decimalPlaces)
}

// Annual PV production can be entered directly (kWh) or derived from an
// installed capacity (kWp) times an assumed specific yield (kWh/kWp/year).
// Mirrors backend/feasibility/calculator.py's estimate_annual_production_kwh.
export function resolveAnnualProductionKwh(values: FeasibilityFormValues): number {
  if (values.annual_production_mode === 'from_kwp') {
    return Number(values.pv_kwp) * Number(values.specific_yield_kwh_per_kwp)
  }
  return Number(values.annual_production_kwh)
}

// The internal energy price can be set directly (CHF/kWh) or as a percentage
// of the retail price — e.g. "60% of Netzstrom". Resolves to the CHF/kWh
// value the backend actually expects, regardless of which mode is active.
export function resolveInternalEnergyPriceChf(values: FeasibilityFormValues): number {
  if (values.internal_energy_price_mode === 'percentage_of_retail') {
    return (Number(values.retail_price_chf_per_kwh) * Number(values.internal_energy_price_pct_of_retail)) / 100
  }
  return Number(values.internal_energy_price_chf_per_kwh)
}

function trimNumber(value: number, decimals: number): string {
  return String(Number(value.toFixed(decimals)))
}

// When the user flips the internal-energy-price mode, we convert the value so
// the *effective* CHF/kWh price is preserved, instead of showing whatever
// stale value the other field happened to hold. Returns the field to set and
// its converted value, or null when it can't convert (retail isn't a positive
// number to convert against) — in which case the mode just flips as before.
// `newMode` is the mode being switched TO.
export function convertedInternalPriceForMode(
  values: FeasibilityFormValues,
  newMode: InternalEnergyPriceMode,
): { field: 'internal_energy_price_chf_per_kwh' | 'internal_energy_price_pct_of_retail'; value: string } | null {
  const retail = Number(values.retail_price_chf_per_kwh)
  if (!Number.isFinite(retail) || retail <= 0) return null

  if (newMode === 'percentage_of_retail') {
    const absolute = Number(values.internal_energy_price_chf_per_kwh)
    if (!Number.isFinite(absolute)) return null
    return { field: 'internal_energy_price_pct_of_retail', value: trimNumber((absolute / retail) * 100, 4) }
  }

  const pct = Number(values.internal_energy_price_pct_of_retail)
  if (!Number.isFinite(pct)) return null
  return { field: 'internal_energy_price_chf_per_kwh', value: trimNumber((retail * pct) / 100, 5) }
}

// Rows with no name yet (mid-edit) are dropped rather than blocking the live
// recompute or being sent to an API that requires a name on every row.
function namedParticipantRows(values: FeasibilityFormValues): ParticipantFormRow[] {
  if (values.energy_input_mode !== 'participants') return []
  return values.participants.filter((row) => row.name.trim() !== '')
}

// Total production/consumption across the named participant rows — this is
// what actually drives the aggregate scenario math when energy_input_mode
// is 'participants', exactly mirroring how the backend's FeasibilityInput
// treats the participant list as additive: the caller (here) is responsible
// for keeping the aggregate totals consistent with the row list's sum.
export function resolveParticipantTotals(values: FeasibilityFormValues): { production: number; consumption: number } {
  const rows = namedParticipantRows(values)
  return {
    production: rows.reduce((sum, row) => sum + Number(row.annual_production_kwh || '0'), 0),
    consumption: rows.reduce((sum, row) => sum + Number(row.annual_consumption_kwh || '0'), 0),
  }
}

export function mapFormValuesToPayload(values: FeasibilityFormValues): FeasibilityInput {
  const rows = namedParticipantRows(values)
  const useParticipants = values.energy_input_mode === 'participants' && rows.length > 0
  const participantTotals = resolveParticipantTotals(values)

  return {
    // decimal_places below mirror each field's DecimalField in feasibility/serializers.py.
    annual_production_kwh: useParticipants
      ? toFixedString(participantTotals.production, 4)
      : toFixedString(resolveAnnualProductionKwh(values), 4),
    annual_consumption_kwh: useParticipants
      ? toFixedString(participantTotals.consumption, 4)
      : values.annual_consumption_kwh,
    self_consumption_rate: toFixedString(Number(values.self_consumption_rate_pct) / 100, 4),
    retail_price_chf_per_kwh: values.retail_price_chf_per_kwh,
    feed_in_price_chf_per_kwh: values.feed_in_price_chf_per_kwh,
    internal_energy_price_chf_per_kwh: toFixedString(resolveInternalEnergyPriceChf(values), 5),
    annual_opex_chf: values.annual_opex_chf,
    capex_chf: values.capex_chf,
    horizon_years: Number(values.horizon_years),
    discount_rate: toFixedString(Number(values.discount_rate_pct) / 100, 4),
    participants: useParticipants
      ? rows.map((row) => ({
          name: row.name,
          annual_production_kwh: toFixedString(Number(row.annual_production_kwh || '0'), 4),
          annual_consumption_kwh: toFixedString(Number(row.annual_consumption_kwh || '0'), 4),
        }))
      : [],
  }
}

// Applies a GET /feasibility/prefill/<zevId>/ response onto the current form:
// switches to participant mode with one row per real participant, and
// overrides any field the ZEV's real data could actually determine — a value
// prefill couldn't resolve (returned null) is left exactly as it was, same
// as any other field a user chooses not to touch. The self-consumption rate
// arrives as a 0..1 ratio and the form holds it as a 0..100 percent.
export function applyPrefillToFormValues(
  prefill: FeasibilityPrefill,
  current: FeasibilityFormValues,
): FeasibilityFormValues {
  const selfConsumptionPct =
    prefill.self_consumption_rate !== null
      ? String(Number((Number(prefill.self_consumption_rate) * 100).toFixed(2)))
      : current.self_consumption_rate_pct

  return {
    ...current,
    energy_input_mode: 'participants',
    participants: prefill.participants.map((p) => ({
      name: p.name,
      annual_production_kwh: p.annual_production_kwh,
      annual_consumption_kwh: p.annual_consumption_kwh,
    })),
    self_consumption_rate_pct: selfConsumptionPct,
    retail_price_chf_per_kwh: prefill.retail_price_chf_per_kwh ?? current.retail_price_chf_per_kwh,
    feed_in_price_chf_per_kwh: prefill.feed_in_price_chf_per_kwh ?? current.feed_in_price_chf_per_kwh,
    internal_energy_price_mode: 'absolute',
    internal_energy_price_chf_per_kwh:
      prefill.internal_energy_price_chf_per_kwh ?? current.internal_energy_price_chf_per_kwh,
  }
}
