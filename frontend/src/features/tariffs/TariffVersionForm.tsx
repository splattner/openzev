import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCheck, faTriangleExclamation, faXmark } from '@fortawesome/free-solid-svg-icons'
import dayjs from 'dayjs'
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModalFooter } from '../../components/FormModalFooter'
import { Notice } from '../../components/Notice'
import { useFocusFirstField } from './useFocusFirstField'
import { CivilDateInput } from '../../components/CivilDateInput'
import { formatShortDate } from '../../lib/appSettings'
import type { AppSettings, TariffPeriodType, TariffVersion, TariffVersionInput } from '../../types/api'
import type { VersionDialog } from './useTariffVersions'

type PeriodDraft = {
  period_type: TariffPeriodType
  label: string
  price_chf_per_kwh: string
  percentage: string
  time_from: string | null
  time_to: string | null
  weekdays: string
  months: string
}

type TariffVersionFormProps = {
  /** The task and the version it starts from. */
  dialog: NonNullable<VersionDialog>
  settings: AppSettings
  isPending: boolean
  /** A failure that belongs to no field: shown in the form, not only as a toast. */
  error?: string | null
  onCancel: () => void
  /** Whether anything was changed, for the pane's unsaved-input guard. */
  onDirtyChange: (dirty: boolean) => void
  onSubmitNewVersion: (id: string, payload: TariffVersionInput) => void
  onSubmitDuplicate: (id: string, payload: TariffVersionInput & { name: string }) => void
  onSubmitRename: (id: string, name: string) => void
}

function draftsFrom(source: TariffVersion): PeriodDraft[] {
  return source.periods.map((period) => ({
    period_type: period.period_type,
    // A band is named by its label; dropping it here would leave the copy
    // showing a bare time window on the contract.
    label: period.label ?? '',
    price_chf_per_kwh: period.price_chf_per_kwh != null ? String(period.price_chf_per_kwh) : '',
    percentage: period.percentage != null ? String(period.percentage) : '',
    time_from: period.time_from ?? null,
    time_to: period.time_to ?? null,
    weekdays: period.weekdays ?? '',
    // Carried through the copy or the new version keeps the price and loses
    // the season it applied in, which prices the whole year at it.
    months: period.months ?? '',
  }))
}

/** The day the source version will be closed on, if this date is adopted. */
function closesPreviousOn(source: TariffVersion, validFrom: string): string | null {
  if (!validFrom || validFrom <= source.valid_from) return null
  return dayjs(validFrom).subtract(1, 'day').format('YYYY-MM-DD')
}

function seedFor(dialog: NonNullable<VersionDialog>) {
  const { source, series, kind } = dialog
  return {
    validFrom: kind === 'rename' ? '' : dayjs().format('YYYY-MM-DD'),
    name: kind === 'duplicate' ? '' : series.name,
    fixedPrice: source.fixed_price_chf ? String(source.fixed_price_chf) : '',
    minimumPrice: source.minimum_price_chf_per_kwh ? String(source.minimum_price_chf_per_kwh) : '',
    periods: draftsFrom(source),
  }
}

/**
 * Schedule a price change, duplicate a tariff or rename it, in the detail
 * pane. Prices start from the source version, because a new version almost
 * always exists to change them and retyping HT/NT bands from scratch would be
 * busywork. Mount it fresh for each task.
 */
export function TariffVersionForm({
  dialog,
  settings,
  isPending,
  error = null,
  onCancel,
  onDirtyChange,
  onSubmitNewVersion,
  onSubmitDuplicate,
  onSubmitRename,
}: TariffVersionFormProps) {
  const { t } = useTranslation()
  const formId = useId()
  const formRef = useRef<HTMLFormElement>(null)
  useFocusFirstField(formRef)
  const seed = useMemo(() => seedFor(dialog), [dialog])
  const [validFrom, setValidFrom] = useState(seed.validFrom)
  const [name, setName] = useState(seed.name)
  const [fixedPrice, setFixedPrice] = useState(seed.fixedPrice)
  const [minimumPrice, setMinimumPrice] = useState(seed.minimumPrice)
  const [periods, setPeriods] = useState<PeriodDraft[]>(seed.periods)

  const isDirty = validFrom !== seed.validFrom
    || name !== seed.name
    || fixedPrice !== seed.fixedPrice
    || minimumPrice !== seed.minimumPrice
    || JSON.stringify(periods) !== JSON.stringify(seed.periods)
  useEffect(() => { onDirtyChange(isDirty) }, [isDirty, onDirtyChange])

  const { kind, series, source } = dialog
  const isDynamic = Boolean(source.dynamic_source)
  // A percentage tariff carries the same kind of bands an energy tariff does
  // (§5.7) — it is never dynamic, so no `!isDynamic` guard is needed for it.
  const isPercentage = series.billing_mode === 'percentage_of_energy'
  const usesPeriods = (series.billing_mode === 'energy' && !isDynamic) || isPercentage
  const usesFixedPrice = !usesPeriods && !isDynamic
  const usesMinimumPrice = isDynamic && series.energy_type === 'feed_in'

  function buildPayload(): TariffVersionInput {
    const payload: TariffVersionInput = { valid_from: validFrom }
    if (usesFixedPrice) payload.fixed_price_chf = fixedPrice || null
    if (usesMinimumPrice) payload.minimum_price_chf_per_kwh = minimumPrice || null
    if (usesPeriods) {
      payload.periods = periods.map((period) => ({
        period_type: period.period_type,
        label: period.label,
        price_chf_per_kwh: isPercentage ? null : period.price_chf_per_kwh,
        percentage: isPercentage ? period.percentage : null,
        time_from: period.time_from || null,
        time_to: period.time_to || null,
        weekdays: period.weekdays,
        months: period.months,
      }))
    }
    return payload
  }

  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (kind === 'rename') {
      onSubmitRename(source.id, name.trim())
      return
    }
    if (kind === 'duplicate') {
      onSubmitDuplicate(source.id, { ...buildPayload(), name: name.trim() })
      return
    }
    onSubmitNewVersion(source.id, buildPayload())
  }

  // What will apply from the chosen date, said before it is saved.
  const resultingPrices = usesPeriods
    ? `${periods.map((period) => (isPercentage ? period.percentage : period.price_chf_per_kwh) || '—').join(' / ')} ${
      isPercentage ? '%' : t('pages.tariffs.chfPerKwh')}`
    : `CHF ${fixedPrice || '—'}`
  const closingDate = kind === 'new-version' ? closesPreviousOn(source, validFrom) : null
  const submitDisabled = isPending
    || (kind === 'rename' && (!name.trim() || name.trim() === series.name))
    || (kind === 'duplicate' && (!name.trim() || !validFrom))
    || (kind === 'new-version' && !validFrom)

  const submitLabel = isPending
    ? t('common.saving')
    : kind === 'new-version'
      ? t('pages.tariffs.versions.schedule')
      : kind === 'duplicate'
        ? t('pages.tariffs.versions.duplicate')
        : t('common.save')

  return (
    <div className="tariff-pane-form">
      {error && <Notice tone="error">{error}</Notice>}
      <form ref={formRef} id={formId} onSubmit={submit} className="form-grid" aria-busy={isPending || undefined}>
       <fieldset className="tariff-pane-fieldset" disabled={isPending}>
        {kind === 'rename' && (
          <p className="muted grid-span-full m-0">
            {t('pages.tariffs.versions.renameHint', { count: series.version_count })}
          </p>
        )}

        {(kind === 'rename' || kind === 'duplicate') && (
          <label className="grid-span-full">
            <span>{t('pages.tariffs.form.name')}</span>
            <input value={name} onChange={(event) => setName(event.target.value)} required />
          </label>
        )}

        {kind !== 'rename' && (
          <label>
            <span>
              {kind === 'new-version'
                ? t('pages.tariffs.versions.effectiveFrom')
                : t('pages.tariffs.form.validFrom')}
            </span>
            <CivilDateInput
              value={validFrom || null}
              onChange={(iso) => setValidFrom(iso ?? '')}
            />
          </label>
        )}

        {kind === 'new-version' && (
          <p className="muted grid-span-full m-0">
            {closingDate
              ? t('pages.tariffs.versions.closesPrevious', {
                date: formatShortDate(closingDate, settings),
              })
              : t('pages.tariffs.versions.pickLaterDate', {
                date: formatShortDate(source.valid_from, settings),
              })}
          </p>
        )}

        {kind === 'new-version' && validFrom && !isDynamic && (
          <p className="muted grid-span-full m-0">
            {t('pages.tariffs.versions.resultingPrices', {
              date: formatShortDate(validFrom, settings),
              prices: resultingPrices,
            })}
          </p>
        )}

        {kind !== 'rename' && usesFixedPrice && (
          <label>
            <span>{t('pages.tariffs.versions.amountChf')}</span>
            <input
              type="number"
              step="0.01"
              value={fixedPrice}
              onChange={(event) => setFixedPrice(event.target.value)}
              required
            />
          </label>
        )}

        {kind !== 'rename' && usesMinimumPrice && (
          <label>
            <span>{t('pages.tariffs.form.minimumPrice')}</span>
            <input
              type="number"
              step="0.00001"
              min="0"
              placeholder={t('pages.tariffs.form.minimumPricePlaceholder')}
              value={minimumPrice}
              onChange={(event) => setMinimumPrice(event.target.value)}
            />
            <small className="muted">{t('pages.tariffs.form.minimumPriceHint')}</small>
          </label>
        )}

        {kind !== 'rename' && usesPeriods && (
          <div className="grid-span-full">
            <strong>{t('pages.tariffs.versions.prices')}</strong>
            {periods.length === 0 ? (
              <p className="muted mt-05">
                <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />{' '}
                {t('pages.tariffs.versions.noPricesToCopy')}
              </p>
            ) : (
              <div className="tariff-version-price-list">
                {periods.map((period, index) => (
                  <label key={`${period.period_type}-${index}`} className="tariff-version-price-row">
                    <span className="tariff-band-name">
                      {t(`pages.tariffs.periodTypes.${period.period_type}` as Parameters<typeof t>[0], {
                        defaultValue: period.period_type,
                      })}
                    </span>
                    {isPercentage ? (
                      <>
                        <input
                          type="number"
                          step="0.01"
                          min="0"
                          value={period.percentage}
                          onChange={(event) => setPeriods((current) => current.map(
                            (entry, entryIndex) => entryIndex === index
                              ? { ...entry, percentage: event.target.value }
                              : entry,
                          ))}
                          required
                        />
                        <span className="muted">%</span>
                      </>
                    ) : (
                      <>
                        <input
                          type="number"
                          step="0.00001"
                          value={period.price_chf_per_kwh}
                          onChange={(event) => setPeriods((current) => current.map(
                            (entry, entryIndex) => entryIndex === index
                              ? { ...entry, price_chf_per_kwh: event.target.value }
                              : entry,
                          ))}
                          required
                        />
                        <span className="muted">{t('pages.tariffs.chfPerKwh')}</span>
                      </>
                    )}
                  </label>
                ))}
              </div>
            )}
          </div>
        )}

       </fieldset>
      </form>
      <FormModalFooter
        formId={formId}
        onCancel={onCancel}
        isPending={submitDisabled}
        submitLabel={submitLabel}
        submitIcon={<FontAwesomeIcon icon={faCheck} fixedWidth />}
        cancelIcon={<FontAwesomeIcon icon={faXmark} fixedWidth />}
      />
    </div>
  )
}
