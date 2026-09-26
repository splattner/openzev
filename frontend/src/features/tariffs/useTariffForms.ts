import { z } from 'zod'
import { todayLocalIso } from '../../lib/dates'
import type { Tariff, TariffInput, TariffPeriod, TariffPeriodInput } from '../../types/api'

export type TariffFormValues = {
  name: string
  category: TariffInput['category']
  billing_mode: TariffInput['billing_mode']
  energy_type: NonNullable<TariffInput['energy_type']>
  fixed_price_chf: string
  /** Create-only: the percentage of the one flat band a new tariff starts with. */
  initial_percentage: string
  split_key: NonNullable<TariffInput['split_key']>
  valid_from: string
  valid_to: string
  notes: string
  /** A `DynamicTariffSource` id, or `''` to price from bands instead. */
  dynamic_source: string
  /** Floor under a fetched feed-in series; `''` for none. */
  minimum_price_chf_per_kwh: string
  /** Internal only, never sent to the API: whether this is a create form. */
  is_new: boolean
}

export type TariffPeriodFormValues = {
  tariff: string
  /** The selected tariff's billing mode: decides `price_chf_per_kwh` vs `percentage` below. */
  billing_mode: TariffInput['billing_mode']
  period_type: TariffPeriodInput['period_type']
  label: string
  price_chf_per_kwh: string
  percentage: string
  time_from: string
  time_to: string
  weekdays: string
  months: string
}

export const tariffFormSchema = z
  .object({
    name: z.string().trim().min(1),
    category: z.enum(['energy', 'grid_fees', 'levies', 'metering']),
    billing_mode: z.enum([
      'energy',
      'monthly_fee',
      'yearly_fee',
      'per_metering_point_monthly_fee',
      'per_metering_point_yearly_fee',
      'shared_monthly_fee',
      'shared_yearly_fee',
      'percentage_of_energy',
    ]),
    energy_type: z.enum(['local', 'grid', 'feed_in']),
    fixed_price_chf: z.string(),
    initial_percentage: z.string(),
    split_key: z.enum(['equal', 'weight']),
    valid_from: z.string().trim().min(1),
    valid_to: z.string(),
    notes: z.string(),
    dynamic_source: z.string(),
    minimum_price_chf_per_kwh: z.string(),
    is_new: z.boolean(),
  })
  .superRefine((values, ctx) => {
    const isEnergyBased = values.billing_mode === 'energy' || values.billing_mode === 'percentage_of_energy'

    if (
      values.minimum_price_chf_per_kwh &&
      Number.isNaN(Number(values.minimum_price_chf_per_kwh))
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['minimum_price_chf_per_kwh'],
        message: 'Minimum price must be a number.',
      })
    }

    if (isEnergyBased && !values.energy_type) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['energy_type'],
        message: 'Energy type is required.',
      })
    }

    // The initial percentage only exists on create (§5.5): once the tariff
    // exists, its bands — including the first one — are managed from the
    // drawer, and this field is hidden and irrelevant.
    if (values.billing_mode === 'percentage_of_energy' && values.is_new) {
      if (!values.initial_percentage) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['initial_percentage'],
          message: 'Percentage is required.',
        })
      }
      if (values.initial_percentage && Number.isNaN(Number(values.initial_percentage))) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['initial_percentage'],
          message: 'Percentage must be a number.',
        })
      }
    }

    if (!isEnergyBased) {
      if (!values.fixed_price_chf) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['fixed_price_chf'],
          message: 'Fixed price is required.',
        })
      }
      if (values.fixed_price_chf && Number.isNaN(Number(values.fixed_price_chf))) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['fixed_price_chf'],
          message: 'Fixed price must be a number.',
        })
      }
    }
  })

export const tariffPeriodFormSchema = z
  .object({
    tariff: z.string().trim().min(1),
    billing_mode: z.enum([
      'energy',
      'monthly_fee',
      'yearly_fee',
      'per_metering_point_monthly_fee',
      'per_metering_point_yearly_fee',
      'shared_monthly_fee',
      'shared_yearly_fee',
      'percentage_of_energy',
    ]),
    period_type: z.enum(['flat', 'high', 'low', 'band']),
    label: z.string(),
    price_chf_per_kwh: z.string(),
    percentage: z.string(),
    time_from: z.string(),
    time_to: z.string(),
    weekdays: z.string(),
    months: z.string(),
  })
  .superRefine((values, ctx) => {
    // A band carries a price or a percentage, never both — the same §4.1
    // rule the backend enforces, checked here too so the field can be
    // required without the server round trip.
    if (values.billing_mode === 'percentage_of_energy') {
      if (!values.percentage.trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['percentage'],
          message: 'Percentage is required.',
        })
      }
    } else if (!values.price_chf_per_kwh.trim()) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['price_chf_per_kwh'],
        message: 'Price is required.',
      })
    }
  })

export const defaultTariffFormValues: TariffFormValues = {
  name: '',
  category: 'energy',
  billing_mode: 'energy',
  energy_type: 'local',
  fixed_price_chf: '',
  initial_percentage: '',
  split_key: 'equal',
  valid_from: todayLocalIso(),
  valid_to: '',
  notes: '',
  dynamic_source: '',
  minimum_price_chf_per_kwh: '',
  is_new: true,
}

export const defaultTariffPeriodFormValues: TariffPeriodFormValues = {
  tariff: '',
  billing_mode: 'energy',
  period_type: 'flat',
  label: '',
  price_chf_per_kwh: '',
  percentage: '',
  time_from: '',
  time_to: '',
  weekdays: '',
  months: '',
}

export function mapTariffToFormValues(tariff: Tariff): TariffFormValues {
  return {
    name: tariff.name,
    category: tariff.category,
    billing_mode: tariff.billing_mode,
    energy_type: tariff.energy_type || 'local',
    fixed_price_chf: tariff.fixed_price_chf ? String(tariff.fixed_price_chf) : '',
    // Write-only and create-only: an existing tariff never carries it back,
    // and editing one never sends it (bands are managed from the drawer).
    initial_percentage: '',
    split_key: tariff.split_key || 'equal',
    valid_from: tariff.valid_from,
    valid_to: tariff.valid_to || '',
    notes: tariff.notes || '',
    dynamic_source: tariff.dynamic_source || '',
    minimum_price_chf_per_kwh: tariff.minimum_price_chf_per_kwh
      ? String(tariff.minimum_price_chf_per_kwh)
      : '',
    is_new: false,
  }
}

export function mapTariffFormValuesToInput(values: TariffFormValues, zevId: string): TariffInput {
  const isEnergyBased = values.billing_mode === 'energy' || values.billing_mode === 'percentage_of_energy'
  const isShared = values.billing_mode === 'shared_monthly_fee' || values.billing_mode === 'shared_yearly_fee'

  return {
    zev: zevId,
    name: values.name.trim(),
    category: values.category,
    billing_mode: values.billing_mode,
    energy_type: isEnergyBased ? values.energy_type : null,
    fixed_price_chf: isEnergyBased ? null : (values.fixed_price_chf || null),
    // Create-only (§5.5): sending it on update is rejected by the API, so it
    // is only ever included while creating a new percentage tariff.
    ...(values.is_new && values.billing_mode === 'percentage_of_energy'
      ? { initial_percentage: values.initial_percentage || null }
      : {}),
    split_key: isShared ? values.split_key : 'equal',
    valid_from: values.valid_from,
    valid_to: values.valid_to || null,
    notes: values.notes,
    // Only a plain energy tariff can be dynamic (Tariff.clean() rejects
    // anything else) — clearing it here as well as hiding the picker means a
    // stale value from switching billing modes can never reach the server.
    dynamic_source: values.billing_mode === 'energy' ? (values.dynamic_source || null) : null,
    // A minimum price only applies to a feed-in tariff priced from a fetched
    // series — same reasoning as dynamic_source above.
    minimum_price_chf_per_kwh:
      values.billing_mode === 'energy' && values.energy_type === 'feed_in' && values.dynamic_source
        ? (values.minimum_price_chf_per_kwh || null)
        : null,
  }
}

export function mapTariffPeriodToFormValues(
  period: TariffPeriod,
  billingMode: TariffInput['billing_mode'],
): TariffPeriodFormValues {
  return {
    tariff: period.tariff,
    billing_mode: billingMode,
    period_type: period.period_type,
    label: period.label ?? '',
    price_chf_per_kwh: period.price_chf_per_kwh != null ? String(period.price_chf_per_kwh) : '',
    percentage: period.percentage != null ? String(period.percentage) : '',
    time_from: period.time_from || '',
    time_to: period.time_to || '',
    weekdays: period.weekdays || '',
    months: period.months || '',
  }
}

export function mapTariffPeriodFormValuesToInput(values: TariffPeriodFormValues): TariffPeriodInput {
  const isPercentage = values.billing_mode === 'percentage_of_energy'
  return {
    tariff: values.tariff,
    period_type: values.period_type,
    // Only a `band` is named by hand; the others name themselves, and a label
    // left behind by a type change would surface on the contract.
    label: values.period_type === 'band' ? values.label : '',
    price_chf_per_kwh: isPercentage ? null : values.price_chf_per_kwh,
    percentage: isPercentage ? values.percentage : null,
    time_from: values.time_from || null,
    time_to: values.time_to || null,
    weekdays: values.weekdays,
    months: values.months,
  }
}
