import { zodResolver } from '@hookform/resolvers/zod'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCheck, faXmark } from '@fortawesome/free-solid-svg-icons'
import { useEffect } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { RecurrenceChips } from './RecurrenceChips'
import { MONTH_KEYS, WEEKDAY_KEYS } from './recurrence'
import type { Tariff, TariffPeriod, TariffPeriodInput } from '../../types/api'
import {
  defaultTariffPeriodFormValues,
  mapTariffPeriodFormValuesToInput,
  mapTariffPeriodToFormValues,
  tariffPeriodFormSchema,
  type TariffPeriodFormValues,
} from './useTariffForms'

type TariffPeriodFormModalProps = {
  isOpen: boolean
  title: string
  onClose: () => void
  onSubmit: (payload: TariffPeriodInput) => void
  initialPeriod?: TariffPeriod
  defaultTariffId?: string
  energyTariffs: Tariff[]
  isPending?: boolean
}

export function TariffPeriodFormModal({
  isOpen,
  title,
  onClose,
  onSubmit,
  initialPeriod,
  defaultTariffId,
  energyTariffs,
  isPending = false,
}: TariffPeriodFormModalProps) {
  const { t } = useTranslation()

  const form = useForm<TariffPeriodFormValues>({
    resolver: zodResolver(tariffPeriodFormSchema),
    defaultValues: defaultTariffPeriodFormValues,
  })

  useEffect(() => {
    if (initialPeriod) {
      form.reset(mapTariffPeriodToFormValues(initialPeriod))
      return
    }

    form.reset({
      ...defaultTariffPeriodFormValues,
      tariff: defaultTariffId ?? defaultTariffPeriodFormValues.tariff,
    })
  }, [defaultTariffId, form, initialPeriod, isOpen])

  // useWatch rather than form.watch(): the latter returns a fresh function on
  // every render, which the React Compiler refuses to memoize around.
  const weekdays = useWatch({ control: form.control, name: 'weekdays' })
  const months = useWatch({ control: form.control, name: 'months' })

  function submit(values: TariffPeriodFormValues) {
    onSubmit(mapTariffPeriodFormValuesToInput(values))
  }

  return (
    <FormModal isOpen={isOpen} title={title} onClose={onClose}>
      <form onSubmit={form.handleSubmit(submit)} className="form-grid">
        <label>
          <span>{t('pages.tariffs.form.tariff')}</span>
          <select {...form.register('tariff')} required>
            <option value="">{t('pages.tariffs.form.selectTariff')}</option>
            {energyTariffs.map((tariff) => (
              <option key={tariff.id} value={tariff.id}>{tariff.name}</option>
            ))}
          </select>
        </label>
        <label>
          <span>{t('pages.tariffs.form.periodType')}</span>
          <select {...form.register('period_type')}>
            <option value="flat">{t('pages.tariffs.periodTypes.flat')}</option>
            <option value="high">{t('pages.tariffs.periodTypes.high')}</option>
            <option value="low">{t('pages.tariffs.periodTypes.low')}</option>
          </select>
        </label>
        <label>
          <span>{t('pages.tariffs.form.pricePerKwh')}</span>
          <input type="number" step="0.00001" {...form.register('price_chf_per_kwh')} required />
        </label>
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

        {Object.keys(form.formState.errors).length > 0 && (
          <div className="error-banner" style={{ gridColumn: '1 / -1' }}>
            {form.formState.errors.tariff?.message
              || form.formState.errors.price_chf_per_kwh?.message
              || t('common.error')}
          </div>
        )}

        <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '1rem', justifyContent: 'flex-end', marginTop: '1rem' }}>
          <button className="button button-secondary" type="button" onClick={onClose}>
            <FontAwesomeIcon icon={faXmark} fixedWidth />
            {t('common.cancel')}
          </button>
          <button className="button button-primary" type="submit" disabled={isPending}>
            <FontAwesomeIcon icon={faCheck} fixedWidth />
            {initialPeriod ? t('pages.tariffs.savePeriod') : t('pages.tariffs.createPeriod')}
          </button>
        </div>
      </form>
    </FormModal>
  )
}
