import type { TariffInput } from '../../types/api'

export const FIXED_PRICE_LABELS: Partial<Record<TariffInput['billing_mode'], string>> = {
  monthly_fee: 'pages.tariffs.form.monthlyFee',
  yearly_fee: 'pages.tariffs.form.yearlyFee',
  per_metering_point_monthly_fee: 'pages.tariffs.form.mpMonthlyFee',
  per_metering_point_yearly_fee: 'pages.tariffs.form.mpYearlyFee',
  shared_monthly_fee: 'pages.tariffs.form.sharedMonthlyFee',
  shared_yearly_fee: 'pages.tariffs.form.sharedYearlyFee',
}
