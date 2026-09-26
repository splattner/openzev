import { zodResolver } from '@hookform/resolvers/zod'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCheck, faXmark } from '@fortawesome/free-solid-svg-icons'
import { useEffect } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { RecurrenceChips } from './RecurrenceChips'
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

type TariffPeriodFormModalProps = {
  isOpen: boolean
  title: string
  onClose: () => void
  onSubmit: (payload: TariffPeriodInput) => void
  initialPeriod?: TariffPeriod
  defaultTariffId?: string
  /** Energy and percentage-of-energy tariffs: the only two modes that take bands. */
  tariffs: Tariff[]
  isPending?: boolean
}

export function TariffPeriodFormModal({
  isOpen,
  title,
  onClose,
  onSubmit,
  initialPeriod,
  defaultTariffId,
  tariffs,
  isPending = false,
}: TariffPeriodFormModalProps) {
  const { t } = useTranslation()

  const form = useForm<TariffPeriodFormValues>({
    resolver: zodResolver(tariffPeriodFormSchema),
    defaultValues: defaultTariffPeriodFormValues,
  })

  useEffect(() => {
    if (initialPeriod) {
      const owner = tariffs.find((tariff) => tariff.id === initialPeriod.tariff)
      form.reset(mapTariffPeriodToFormValues(initialPeriod, owner?.billing_mode ?? 'energy'))
      return
    }

    const owner = tariffs.find((tariff) => tariff.id === defaultTariffId)
    form.reset({
      ...defaultTariffPeriodFormValues,
      tariff: defaultTariffId ?? defaultTariffPeriodFormValues.tariff,
      billing_mode: owner?.billing_mode ?? 'energy',
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tariffs is looked up, not watched
  }, [defaultTariffId, form, initialPeriod, isOpen])

  // useWatch rather than form.watch(): the latter returns a fresh function on
  // every render, which the React Compiler refuses to memoize around.
  const periodType = useWatch({ control: form.control, name: 'period_type' })
  const weekdays = useWatch({ control: form.control, name: 'weekdays' })
  const months = useWatch({ control: form.control, name: 'months' })
  const selectedTariffId = useWatch({ control: form.control, name: 'tariff' })
  const billingMode = useWatch({ control: form.control, name: 'billing_mode' })
  const isPercentage = billingMode === 'percentage_of_energy'

  // Switching the tariff dropdown to a different billing mode switches which
  // price field applies — mirroring what happens when the modal opens for a
  // specific tariff (the effect above).
  useEffect(() => {
    const owner = tariffs.find((tariff) => tariff.id === selectedTariffId)
    if (owner) form.setValue('billing_mode', owner.billing_mode)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tariffs is looked up, not watched
  }, [selectedTariffId, form])

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
            {tariffs.map((tariff) => (
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
          </label>
        ) : (
          <label>
            <span>{t('pages.tariffs.form.pricePerKwh')}</span>
            <input type="number" step="0.00001" {...form.register('price_chf_per_kwh')} required />
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

        {Object.keys(form.formState.errors).length > 0 && (
          <div className="error-banner" style={{ gridColumn: '1 / -1' }}>
            {form.formState.errors.tariff?.message
              || form.formState.errors.price_chf_per_kwh?.message
              || form.formState.errors.percentage?.message
              || t('common.error')}
          </div>
        )}

        <FormModalFooter
          onCancel={onClose}
          isPending={isPending}
          submitLabel={initialPeriod ? t('pages.tariffs.savePeriod') : t('pages.tariffs.createPeriod')}
          submitIcon={<FontAwesomeIcon icon={faCheck} fixedWidth />}
          cancelIcon={<FontAwesomeIcon icon={faXmark} fixedWidth />}
        />
      </form>
    </FormModal>
  )
}
