import { Controller, useWatch, type Control, type UseFormReturn } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { CivilTimeInput } from '../../components/CivilTimeInput'
import type { ItemFieldErrors } from '../../lib/api/errors'
import type { CoverageBand } from './bandCoverage'
import { RecurrenceChips } from './RecurrenceChips'
import { MONTH_KEYS, WEEKDAY_KEYS } from './recurrence'
import type { TariffPeriodFormValues } from './useTariffForms'

type TariffBandFieldsProps = {
  form: UseFormReturn<TariffPeriodFormValues>
  /** What the server said about this band, by field: shown beside the field it names. */
  serverErrors?: ItemFieldErrors
}

/**
 * The fields of one price band, shared by the band form of an existing tariff
 * and the band editor of the create form. Renders into the caller's
 * `form-grid`.
 */
export function TariffBandFields({ form, serverErrors }: TariffBandFieldsProps) {
  const { t } = useTranslation()
  // useWatch rather than form.watch(): the latter returns a fresh function on
  // every render, which the React Compiler refuses to memoize around.
  const periodType = useWatch({ control: form.control, name: 'period_type' })
  const weekdays = useWatch({ control: form.control, name: 'weekdays' })
  const months = useWatch({ control: form.control, name: 'months' })
  const billingMode = useWatch({ control: form.control, name: 'billing_mode' })
  const isPercentage = billingMode === 'percentage_of_energy'

  const errors = form.formState.errors
  const fieldError = (field: 'price_chf_per_kwh' | 'percentage') => errors[field]
    ? <small className="field-error" role="alert">{t('pages.tariffs.form.errorRequired')}</small>
    : null
  const serverError = (...fields: string[]) => {
    const messages = fields.flatMap((field) => serverErrors?.[field] ?? [])
    return messages.length > 0 ? <small className="field-error" role="alert">{messages.join(' ')}</small> : null
  }

  return (
    <>
      <label>
        <span>{t('pages.tariffs.form.periodType')}</span>
        <select {...form.register('period_type')}>
          <option value="flat">{t('pages.tariffs.periodTypes.flat')}</option>
          <option value="high">{t('pages.tariffs.periodTypes.high')}</option>
          <option value="low">{t('pages.tariffs.periodTypes.low')}</option>
          <option value="band">{t('pages.tariffs.periodTypes.band')}</option>
        </select>
        <small className="muted">{t('pages.tariffs.form.periodTypeHint')}</small>
        {serverError('period_type')}
      </label>
      {periodType === 'band' && (
        <label>
          <span>{t('pages.tariffs.form.bandLabel')}</span>
          <input {...form.register('label')} placeholder={t('pages.tariffs.form.bandLabelPlaceholder')} />
          <small className="muted">{t('pages.tariffs.form.bandLabelHint')}</small>
          {serverError('label')}
        </label>
      )}
      {isPercentage ? (
        <label>
          <span>{t('pages.tariffs.form.percentage')}</span>
          <input type="number" step="0.01" min="0" {...form.register('percentage')} required />
          {fieldError('percentage')}
          {serverError('percentage')}
        </label>
      ) : (
        <label>
          <span>{t('pages.tariffs.form.pricePerKwh')}</span>
          <input type="number" step="0.00001" {...form.register('price_chf_per_kwh')} required />
          {fieldError('price_chf_per_kwh')}
          {serverError('price_chf_per_kwh')}
        </label>
      )}
      <label>
        <span>{t('pages.tariffs.form.timeFrom')}</span>
        <Controller control={form.control} name="time_from" render={({ field }) => <CivilTimeInput value={field.value} onChange={field.onChange} />} />
        {serverError('time_from')}
      </label>
      <label>
        <span>{t('pages.tariffs.form.timeTo')}</span>
        <Controller control={form.control} name="time_to" render={({ field }) => <CivilTimeInput value={field.value} onChange={field.onChange} />} />
        {periodType !== 'flat' && <small className="muted">{t('pages.tariffs.form.timeWindowHint')}</small>}
        {(errors.time_from || errors.time_to) && <small className="field-error" role="alert">{t('pages.tariffs.form.errorTimeWindow')}</small>}
        {serverError('time_to')}
      </label>
      <RecurrenceChips
        label={t('pages.tariffs.form.weekdays')}
        hint={t('pages.tariffs.form.weekdaysHint')}
        value={weekdays}
        onChange={(next) => form.setValue('weekdays', next, { shouldDirty: true })}
        options={WEEKDAY_KEYS.map((key, index) => ({
          value: index,
          label: t(`pages.tariffs.weekdaysShort.${key}` as Parameters<typeof t>[0]),
        }))}
        columns={7}
      />
      <RecurrenceChips
        label={t('pages.tariffs.form.months')}
        hint={t('pages.tariffs.form.monthsHint')}
        value={months}
        onChange={(next) => form.setValue('months', next, { shouldDirty: true })}
        options={MONTH_KEYS.map((key, index) => ({
          value: index + 1,
          label: t(`pages.tariffs.monthsShort.${key}` as Parameters<typeof t>[0]),
        }))}
        columns={6}
      />
      {serverError('weekdays', 'months', 'non_field_errors')}
    </>
  )
}

/** A drafted band in the shape the coverage preview reads. */
export function toCoverageBand(values: Omit<TariffPeriodFormValues, 'tariff' | 'billing_mode'>): CoverageBand {
  return {
    period_type: values.period_type,
    label: values.label,
    price_chf_per_kwh: values.price_chf_per_kwh || null,
    percentage: values.percentage || null,
    time_from: values.time_from || null,
    time_to: values.time_to || null,
    weekdays: values.weekdays,
    months: values.months,
  }
}

/** The band as the form stands now, in the shape the coverage preview reads. */
export function useWatchedBand(control: Control<TariffPeriodFormValues>): { band: CoverageBand, complete: boolean } {
  const periodType = useWatch({ control, name: 'period_type' })
  const label = useWatch({ control, name: 'label' })
  const timeFrom = useWatch({ control, name: 'time_from' })
  const timeTo = useWatch({ control, name: 'time_to' })
  const price = useWatch({ control, name: 'price_chf_per_kwh' })
  const percentage = useWatch({ control, name: 'percentage' })
  const weekdays = useWatch({ control, name: 'weekdays' })
  const months = useWatch({ control, name: 'months' })
  return {
    band: toCoverageBand({
      period_type: periodType, label, price_chf_per_kwh: price, percentage,
      time_from: timeFrom, time_to: timeTo, weekdays, months,
    }),
    // Both times, or neither (a band for all other hours): one time alone says nothing about coverage.
    complete: periodType === 'flat' || Boolean(timeFrom) === Boolean(timeTo),
  }
}
