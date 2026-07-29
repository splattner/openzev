import { z } from 'zod'
import type { Tariff, TariffInput, TariffPeriod, TariffPeriodInput } from '../../types/api'

export type TariffFormValues = {
  name: string
  category: TariffInput['category']
  billing_mode: TariffInput['billing_mode']
  energy_type: NonNullable<TariffInput['energy_type']>
  fixed_price_chf: string
  percentage: string
  valid_from: string
  valid_to: string
  notes: string
}

export type TariffPeriodFormValues = {
  tariff: string
  period_type: TariffPeriodInput['period_type']
  price_chf_per_kwh: string
  time_from: string
  time_to: string
  weekdays: string
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
    percentage: z.string(),
    valid_from: z.string().trim().min(1),
    valid_to: z.string(),
    notes: z.string(),
  })
  .superRefine((values, ctx) => {
    const isEnergyBased = values.billing_mode === 'energy' || values.billing_mode === 'percentage_of_energy'

    if (isEnergyBased && !values.energy_type) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['energy_type'],
        message: 'Energy type is required.',
      })
    }

    if (values.billing_mode === 'percentage_of_energy') {
      if (!values.percentage) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['percentage'],
          message: 'Percentage is required.',
        })
      }
      if (values.percentage && Number.isNaN(Number(values.percentage))) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['percentage'],
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

export const tariffPeriodFormSchema = z.object({
  tariff: z.string().trim().min(1),
  period_type: z.enum(['flat', 'high', 'low']),
  price_chf_per_kwh: z.string().trim().min(1),
  time_from: z.string(),
  time_to: z.string(),
  weekdays: z.string(),
})

export const defaultTariffFormValues: TariffFormValues = {
  name: '',
  category: 'energy',
  billing_mode: 'energy',
  energy_type: 'local',
  fixed_price_chf: '',
  percentage: '',
  valid_from: new Date().toISOString().slice(0, 10),
  valid_to: '',
  notes: '',
}

export const defaultTariffPeriodFormValues: TariffPeriodFormValues = {
  tariff: '',
  period_type: 'flat',
  price_chf_per_kwh: '',
  time_from: '',
  time_to: '',
  weekdays: '',
}

export function mapTariffToFormValues(tariff: Tariff): TariffFormValues {
  return {
    name: tariff.name,
    category: tariff.category,
    billing_mode: tariff.billing_mode,
    energy_type: tariff.energy_type || 'local',
    fixed_price_chf: tariff.fixed_price_chf ? String(tariff.fixed_price_chf) : '',
    percentage: tariff.percentage ? String(tariff.percentage) : '',
    valid_from: tariff.valid_from,
    valid_to: tariff.valid_to || '',
    notes: tariff.notes || '',
  }
}

export function mapTariffFormValuesToInput(values: TariffFormValues, zevId: string): TariffInput {
  const isEnergyBased = values.billing_mode === 'energy' || values.billing_mode === 'percentage_of_energy'

  return {
    zev: zevId,
    name: values.name.trim(),
    category: values.category,
    billing_mode: values.billing_mode,
    energy_type: isEnergyBased ? values.energy_type : null,
    fixed_price_chf: isEnergyBased ? null : (values.fixed_price_chf || null),
    percentage: values.billing_mode === 'percentage_of_energy' ? (values.percentage || null) : null,
    valid_from: values.valid_from,
    valid_to: values.valid_to || null,
    notes: values.notes,
  }
}

export function mapTariffPeriodToFormValues(period: TariffPeriod): TariffPeriodFormValues {
  return {
    tariff: period.tariff,
    period_type: period.period_type,
    price_chf_per_kwh: String(period.price_chf_per_kwh),
    time_from: period.time_from || '',
    time_to: period.time_to || '',
    weekdays: period.weekdays || '',
  }
}

export function mapTariffPeriodFormValuesToInput(values: TariffPeriodFormValues): TariffPeriodInput {
  return {
    tariff: values.tariff,
    period_type: values.period_type,
    price_chf_per_kwh: values.price_chf_per_kwh,
    time_from: values.time_from || null,
    time_to: values.time_to || null,
    weekdays: values.weekdays,
  }
}
