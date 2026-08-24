import { zodResolver } from '@hookform/resolvers/zod'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCheck, faXmark } from '@fortawesome/free-solid-svg-icons'
import dayjs from 'dayjs'
import { DatePicker } from '@mui/x-date-pickers/DatePicker'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { toDayJsDateFormat } from '../../lib/appSettings'
import type { AppSettings, Tariff, TariffBillingMode, TariffInput } from '../../types/api'
import {
  defaultTariffFormValues,
  mapTariffFormValuesToInput,
  mapTariffToFormValues,
  tariffFormSchema,
  type TariffFormValues,
} from './useTariffForms'

/** Label for the fixed-price field, per billing mode that has one. */
const FIXED_PRICE_LABELS: Partial<Record<TariffBillingMode, string>> = {
  monthly_fee: 'pages.tariffs.form.monthlyFee',
  yearly_fee: 'pages.tariffs.form.yearlyFee',
  per_metering_point_monthly_fee: 'pages.tariffs.form.mpMonthlyFee',
  per_metering_point_yearly_fee: 'pages.tariffs.form.mpYearlyFee',
  shared_monthly_fee: 'pages.tariffs.form.sharedMonthlyFee',
  shared_yearly_fee: 'pages.tariffs.form.sharedYearlyFee',
}

const SHARED_FEE_MODES: TariffBillingMode[] = ['shared_monthly_fee', 'shared_yearly_fee']

type TariffFormModalProps = {
  isOpen: boolean
  title: string
  onClose: () => void
  onSubmit: (payload: TariffInput) => void
  initialTariff?: Tariff
  selectedZevId: string
  settings: AppSettings
  isPending?: boolean
}

export function TariffFormModal({
  isOpen,
  title,
  onClose,
  onSubmit,
  initialTariff,
  selectedZevId,
  settings,
  isPending = false,
}: TariffFormModalProps) {
  const { t } = useTranslation()

  const form = useForm<TariffFormValues>({
    resolver: zodResolver(tariffFormSchema),
    defaultValues: defaultTariffFormValues,
  })

  const billingMode = useWatch({
    control: form.control,
    name: 'billing_mode',
  })
  const isSharedFee = SHARED_FEE_MODES.includes(billingMode)
  const splitKey = useWatch({
    control: form.control,
    name: 'split_key',
  })
  // An existing tariff is one version of a series; its identity fields are
  // fixed. Creating a new tariff still sets them freely.
  const isVersion = Boolean(initialTariff)

  useEffect(() => {
    form.reset(initialTariff ? mapTariffToFormValues(initialTariff) : defaultTariffFormValues)
  }, [initialTariff, form, isOpen])

  function submit(values: TariffFormValues) {
    onSubmit(mapTariffFormValuesToInput(values, selectedZevId))
  }

  return (
    <FormModal isOpen={isOpen} title={title} onClose={onClose}>
      <form onSubmit={form.handleSubmit(submit)} className="form-grid">
        {/* Editing an existing tariff means editing one *version* of it. The name
            groups versions, and category/billing mode/energy type must match
            across them, so the four identity fields are shown as values rather
            than inputs. Rendering them instead of disabling them is deliberate:
            react-hook-form treats a disabled registered field as undefined, which
            would quietly blank the name on save. The values still reach the
            payload from the form state seeded by reset(). */}
        {isVersion ? (
          <div className="tariff-identity-summary" style={{ gridColumn: '1 / -1' }}>
            <div>
              <span className="tariff-detail-label">{t('pages.tariffs.form.name')}</span>
              <strong>{initialTariff?.name}</strong>
            </div>
            <div>
              <span className="tariff-detail-label">{t('pages.tariffs.form.category')}</span>
              <span>{t(`pages.tariffs.categories.${initialTariff!.category}` as Parameters<typeof t>[0])}</span>
            </div>
            <div>
              <span className="tariff-detail-label">{t('pages.tariffs.form.billingMode')}</span>
              <span>{t(`pages.tariffs.billingModes.${initialTariff!.billing_mode}` as Parameters<typeof t>[0], { defaultValue: initialTariff!.billing_mode })}</span>
            </div>
            {initialTariff?.energy_type && (
              <div>
                <span className="tariff-detail-label">{t('pages.tariffs.form.energyType')}</span>
                <span>{t(`pages.tariffs.energyTypes.${initialTariff.energy_type}` as Parameters<typeof t>[0])}</span>
              </div>
            )}
            <p className="muted" style={{ gridColumn: '1 / -1', margin: 0 }}>
              {t('pages.tariffs.form.identityLockedHint')}
            </p>
          </div>
        ) : (
          <>
            <label>
              <span>{t('pages.tariffs.form.name')}</span>
              <input {...form.register('name')} required />
            </label>
            <label>
              <span>{t('pages.tariffs.form.category')}</span>
              <select {...form.register('category')}>
                <option value="energy">{t('pages.tariffs.categories.energy')}</option>
                <option value="grid_fees">{t('pages.tariffs.categories.grid_fees')}</option>
                <option value="levies">{t('pages.tariffs.categories.levies')}</option>
                <option value="metering">{t('pages.tariffs.categories.metering')}</option>
              </select>
            </label>
            <label>
              <span>{t('pages.tariffs.form.billingMode')}</span>
              <select {...form.register('billing_mode')}>
                <option value="energy">{t('pages.tariffs.billingModes.energy')}</option>
                <option value="percentage_of_energy">{t('pages.tariffs.billingModes.percentage_of_energy')}</option>
                <option value="monthly_fee">{t('pages.tariffs.billingModes.monthly_fee')}</option>
                <option value="yearly_fee">{t('pages.tariffs.billingModes.yearly_fee')}</option>
                <option value="per_metering_point_monthly_fee">{t('pages.tariffs.billingModes.per_metering_point_monthly_fee')}</option>
                <option value="per_metering_point_yearly_fee">{t('pages.tariffs.billingModes.per_metering_point_yearly_fee')}</option>
                <option value="shared_monthly_fee">{t('pages.tariffs.billingModes.shared_monthly_fee')}</option>
                <option value="shared_yearly_fee">{t('pages.tariffs.billingModes.shared_yearly_fee')}</option>
              </select>
            </label>
            {(billingMode === 'energy' || billingMode === 'percentage_of_energy') && (
              <label>
                <span>{t('pages.tariffs.form.energyType')}</span>
                <select {...form.register('energy_type')}>
                  <option value="local">{t('pages.tariffs.energyTypes.local')}</option>
                  <option value="grid">{t('pages.tariffs.energyTypes.grid')}</option>
                  <option value="feed_in">{t('pages.tariffs.energyTypes.feed_in')}</option>
                </select>
              </label>
            )}
          </>
        )}

        {billingMode === 'percentage_of_energy' ? (
          <label>
            <span>{t('pages.tariffs.form.percentage')}</span>
            <input type="number" step="0.01" min="0" max="100" {...form.register('percentage')} required />
          </label>
        ) : billingMode !== 'energy' ? (
          <label>
            <span>{t(FIXED_PRICE_LABELS[billingMode] ?? 'pages.tariffs.form.monthlyFee')}</span>
            <input type="number" step="0.01" {...form.register('fixed_price_chf')} required />
            {isSharedFee && (
              <small className="muted">
                {t(splitKey === 'weight' ? 'pages.tariffs.form.sharedFeeHintWeight' : 'pages.tariffs.form.sharedFeeHint')}
              </small>
            )}
          </label>
        ) : null}

        {isSharedFee && (
          <label>
            <span>{t('pages.tariffs.form.splitKey')}</span>
            <select {...form.register('split_key')}>
              <option value="equal">{t('pages.tariffs.form.splitKeyEqual')}</option>
              <option value="weight">{t('pages.tariffs.form.splitKeyWeight')}</option>
            </select>
          </label>
        )}

        <label>
          <span>{t('pages.tariffs.form.validFrom')}</span>
          <Controller
            control={form.control}
            name="valid_from"
            render={({ field }) => (
              <DatePicker
                format={toDayJsDateFormat(settings.date_format_short)}
                value={field.value ? dayjs(field.value) : null}
                onChange={(val) => field.onChange(val ? val.format('YYYY-MM-DD') : '')}
                slotProps={{ textField: { size: 'small', fullWidth: true } }}
              />
            )}
          />
        </label>
        <label>
          <span>{t('pages.tariffs.form.validTo')}</span>
          <Controller
            control={form.control}
            name="valid_to"
            render={({ field }) => (
              <DatePicker
                format={toDayJsDateFormat(settings.date_format_short)}
                value={field.value ? dayjs(field.value) : null}
                onChange={(val) => field.onChange(val ? val.format('YYYY-MM-DD') : '')}
                slotProps={{ textField: { size: 'small', fullWidth: true } }}
              />
            )}
          />
        </label>
        <label>
          <span>{t('pages.tariffs.form.notes')}</span>
          <input {...form.register('notes')} />
        </label>

        {Object.keys(form.formState.errors).length > 0 && (
          <div className="error-banner" style={{ gridColumn: '1 / -1' }}>
            {form.formState.errors.name?.message
              || form.formState.errors.energy_type?.message
              || form.formState.errors.percentage?.message
              || form.formState.errors.fixed_price_chf?.message
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
            {initialTariff ? t('pages.tariffs.saveTariff') : t('pages.tariffs.createTariff')}
          </button>
        </div>
      </form>
    </FormModal>
  )
}
