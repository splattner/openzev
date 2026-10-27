import { zodResolver } from '@hookform/resolvers/zod'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCheck, faXmark } from '@fortawesome/free-solid-svg-icons'
import { useEffect, useId, useRef } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { Notice } from '../../components/Notice'
import { useFocusFirstField } from './useFocusFirstField'
import { RecurrenceChips } from './RecurrenceChips'
import { TariffBandCoverage } from './TariffBandCoverage'
import { MONTH_KEYS, WEEKDAY_KEYS } from './recurrence'
import { FormModalFooter } from '../../components/FormModalFooter'
import type { Tariff, TariffPeriod, TariffPeriodInput } from '../../types/api'
import {
  defaultTariffPeriodFormValues,
  mapTariffPeriodFormValuesToInput,
  mapTariffPeriodToFormValues,
  tariffPeriodFormSchema,
  type TariffPeriodFormValues,
} from './useTariffForms'

type TariffPeriodFormProps = {
  onSubmit: (payload: TariffPeriodInput) => void
  onCancel: () => void
  /** Whether anything was changed, for the pane's unsaved-input guard. */
  onDirtyChange: (dirty: boolean) => void
  initialPeriod?: TariffPeriod
  /** The version the band belongs to: the one the pane shows. */
  defaultTariffId?: string
  /** Energy and percentage-of-energy tariffs: the only two modes that take bands. */
  tariffs: Tariff[]
  /** Every band of every version: the owner's other bands are what this one is checked against. */
  periods: TariffPeriod[]
  isPending?: boolean
  /** A failure that belongs to no field: shown in the form, not only as a toast. */
  error?: string | null
}

/** Add or change a price band of the shown version, in the detail pane. */
export function TariffPeriodForm({
  onSubmit,
  onCancel,
  onDirtyChange,
  initialPeriod,
  defaultTariffId,
  tariffs,
  periods,
  isPending = false,
  error = null,
}: TariffPeriodFormProps) {
  const { t } = useTranslation()
  const formId = useId()
  const formRef = useRef<HTMLFormElement>(null)
  useFocusFirstField(formRef)

  const owner = tariffs.find((tariff) => tariff.id === (initialPeriod?.tariff ?? defaultTariffId))
  const form = useForm<TariffPeriodFormValues>({
    resolver: zodResolver(tariffPeriodFormSchema),
    // Seeded once, when the form opens: a refetch of the list behind it must
    // not overwrite what is being typed.
    defaultValues: initialPeriod
      ? mapTariffPeriodToFormValues(initialPeriod, owner?.billing_mode ?? 'energy')
      : {
        ...defaultTariffPeriodFormValues,
        tariff: defaultTariffId ?? defaultTariffPeriodFormValues.tariff,
        billing_mode: owner?.billing_mode ?? 'energy',
      },
  })

  const isDirty = form.formState.isDirty
  useEffect(() => { onDirtyChange(isDirty) }, [isDirty, onDirtyChange])

  // useWatch rather than form.watch(): the latter returns a fresh function on
  // every render, which the React Compiler refuses to memoize around.
  const periodType = useWatch({ control: form.control, name: 'period_type' })
  const weekdays = useWatch({ control: form.control, name: 'weekdays' })
  const months = useWatch({ control: form.control, name: 'months' })
  const billingMode = useWatch({ control: form.control, name: 'billing_mode' })
  const isPercentage = billingMode === 'percentage_of_energy'

  function submit(values: TariffPeriodFormValues) {
    onSubmit(mapTariffPeriodFormValuesToInput(values))
  }

  // The version's bands as they would be if this one were saved now.
  const timeFrom = useWatch({ control: form.control, name: 'time_from' })
  const timeTo = useWatch({ control: form.control, name: 'time_to' })
  const draft = { id: initialPeriod?.id, period_type: periodType, label: '', time_from: timeFrom || null, time_to: timeTo || null, weekdays, months }
  const siblings = periods.filter((period) => period.tariff === owner?.id && period.id !== initialPeriod?.id)
  const versionBands = [...siblings, draft]
  // A timed band without its hours yet says nothing about coverage.
  const draftComplete = periodType === 'flat' || Boolean(timeFrom && timeTo)

  const errors = form.formState.errors
  const fieldError = (field: 'price_chf_per_kwh' | 'percentage') => errors[field]
    ? <small className="field-error" role="alert">{t('pages.tariffs.form.errorRequired')}</small>
    : null

  return (
    <div className="tariff-pane-form">
      {error && <Notice tone="error">{error}</Notice>}
      <form ref={formRef} id={formId} onSubmit={form.handleSubmit(submit)} className="form-grid" aria-busy={isPending || undefined}>
       <fieldset className="tariff-pane-fieldset" disabled={isPending}>
        <label>
          <span>{t('pages.tariffs.form.periodType')}</span>
          <select {...form.register('period_type')}>
            <option value="flat">{t('pages.tariffs.periodTypes.flat')}</option>
            <option value="high">{t('pages.tariffs.periodTypes.high')}</option>
            <option value="low">{t('pages.tariffs.periodTypes.low')}</option>
            <option value="band">{t('pages.tariffs.periodTypes.band')}</option>
          </select>
          <small className="muted">{t('pages.tariffs.form.periodTypeHint')}</small>
        </label>
        {periodType === 'band' && (
          <label>
            <span>{t('pages.tariffs.form.bandLabel')}</span>
            <input {...form.register('label')} placeholder={t('pages.tariffs.form.bandLabelPlaceholder')} />
            <small className="muted">{t('pages.tariffs.form.bandLabelHint')}</small>
          </label>
        )}
        {isPercentage ? (
          <label>
            <span>{t('pages.tariffs.form.percentage')}</span>
            <input type="number" step="0.01" min="0" {...form.register('percentage')} required />
            {fieldError('percentage')}
          </label>
        ) : (
          <label>
            <span>{t('pages.tariffs.form.pricePerKwh')}</span>
            <input type="number" step="0.00001" {...form.register('price_chf_per_kwh')} required />
            {fieldError('price_chf_per_kwh')}
          </label>
        )}
        <label>
          <span>{t('pages.tariffs.form.timeFrom')}</span>
          <input type="time" {...form.register('time_from')} />
        </label>
        <label>
          <span>{t('pages.tariffs.form.timeTo')}</span>
          <input type="time" {...form.register('time_to')} />
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
        {draftComplete && <TariffBandCoverage bands={versionBands} validity={owner} showCovered />}
       </fieldset>
      </form>
      <FormModalFooter
        formId={formId}
        onCancel={onCancel}
        isPending={isPending}
        submitLabel={isPending ? t('common.saving') : initialPeriod ? t('pages.tariffs.savePeriod') : t('pages.tariffs.createPeriod')}
        submitIcon={<FontAwesomeIcon icon={faCheck} fixedWidth />}
        cancelIcon={<FontAwesomeIcon icon={faXmark} fixedWidth />}
      />
    </div>
  )
}
