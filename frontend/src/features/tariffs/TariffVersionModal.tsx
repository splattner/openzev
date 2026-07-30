import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCheck, faTriangleExclamation, faXmark } from '@fortawesome/free-solid-svg-icons'
import dayjs from 'dayjs'
import { DatePicker } from '@mui/x-date-pickers/DatePicker'
import { AdapterDayjs } from '@mui/x-date-pickers/AdapterDayjs'
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { formatShortDate, toDayJsDateFormat } from '../../lib/appSettings'
import type { AppSettings, TariffVersion, TariffVersionInput } from '../../types/api'
import type { VersionDialog } from './useTariffVersions'

type PeriodDraft = {
  period_type: 'flat' | 'high' | 'low'
  price_chf_per_kwh: string
  time_from: string | null
  time_to: string | null
  weekdays: string
}

type TariffVersionModalProps = {
  dialog: VersionDialog
  settings: AppSettings
  isPending: boolean
  onClose: () => void
  onSubmitNewVersion: (id: string, payload: TariffVersionInput) => void
  onSubmitDuplicate: (id: string, payload: TariffVersionInput & { name: string }) => void
  onSubmitRename: (id: string, name: string) => void
}

function draftsFrom(source: TariffVersion): PeriodDraft[] {
  return source.periods.map((period) => ({
    period_type: period.period_type,
    price_chf_per_kwh: String(period.price_chf_per_kwh),
    time_from: period.time_from ?? null,
    time_to: period.time_to ?? null,
    weekdays: period.weekdays ?? '',
  }))
}

/** The day the source version will be closed on, if this date is adopted. */
function closesPreviousOn(source: TariffVersion, validFrom: string): string | null {
  if (!validFrom || validFrom <= source.valid_from) return null
  return dayjs(validFrom).subtract(1, 'day').format('YYYY-MM-DD')
}

export function TariffVersionModal({
  dialog,
  settings,
  isPending,
  onClose,
  onSubmitNewVersion,
  onSubmitDuplicate,
  onSubmitRename,
}: TariffVersionModalProps) {
  const { t } = useTranslation()
  const [validFrom, setValidFrom] = useState('')
  const [name, setName] = useState('')
  const [fixedPrice, setFixedPrice] = useState('')
  const [percentage, setPercentage] = useState('')
  const [periods, setPeriods] = useState<PeriodDraft[]>([])

  // Re-seed whenever the dialog target changes: prices start from the source
  // version, because a new version almost always exists to change them and
  // retyping HT/NT bands from scratch would be busywork.
  useEffect(() => {
    if (!dialog) return
    const { source, series } = dialog
    setValidFrom(dialog.kind === 'rename' ? '' : dayjs().format('YYYY-MM-DD'))
    setName(dialog.kind === 'duplicate' ? '' : series.name)
    setFixedPrice(source.fixed_price_chf ? String(source.fixed_price_chf) : '')
    setPercentage(source.percentage ? String(source.percentage) : '')
    setPeriods(draftsFrom(source))
  }, [dialog])

  if (!dialog) return null

  const { kind, series, source } = dialog
  const usesPeriods = series.billing_mode === 'energy'
  const usesPercentage = series.billing_mode === 'percentage_of_energy'
  const usesFixedPrice = !usesPeriods && !usesPercentage

  const title = kind === 'new-version'
    ? t('pages.tariffs.versions.newVersionTitle', { name: series.name })
    : kind === 'duplicate'
      ? t('pages.tariffs.versions.duplicateTitle', { name: series.name })
      : t('pages.tariffs.versions.renameTitle', { name: series.name })

  function buildPayload(): TariffVersionInput {
    const payload: TariffVersionInput = { valid_from: validFrom }
    if (usesFixedPrice) payload.fixed_price_chf = fixedPrice || null
    if (usesPercentage) payload.percentage = percentage || null
    if (usesPeriods) {
      payload.periods = periods.map((period) => ({
        period_type: period.period_type,
        price_chf_per_kwh: period.price_chf_per_kwh,
        time_from: period.time_from || null,
        time_to: period.time_to || null,
        weekdays: period.weekdays,
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

  const closingDate = kind === 'new-version' ? closesPreviousOn(source, validFrom) : null
  const submitDisabled = isPending
    || (kind === 'rename' && (!name.trim() || name.trim() === series.name))
    || (kind === 'duplicate' && (!name.trim() || !validFrom))
    || (kind === 'new-version' && !validFrom)

  return (
    <FormModal isOpen title={title} onClose={onClose} maxWidth="620px">
      <form onSubmit={submit} className="form-grid">
        {kind === 'rename' && (
          <p className="muted" style={{ gridColumn: '1 / -1', margin: 0 }}>
            {t('pages.tariffs.versions.renameHint', { count: series.version_count })}
          </p>
        )}

        {(kind === 'rename' || kind === 'duplicate') && (
          <label style={{ gridColumn: '1 / -1' }}>
            <span>{t('pages.tariffs.form.name')}</span>
            <input value={name} onChange={(event) => setName(event.target.value)} required autoFocus />
          </label>
        )}

        {kind !== 'rename' && (
          <label>
            <span>
              {kind === 'new-version'
                ? t('pages.tariffs.versions.effectiveFrom')
                : t('pages.tariffs.form.validFrom')}
            </span>
            <LocalizationProvider dateAdapter={AdapterDayjs}>
              <DatePicker
                format={toDayJsDateFormat(settings.date_format_short)}
                value={validFrom ? dayjs(validFrom) : null}
                onChange={(value) => setValidFrom(value ? value.format('YYYY-MM-DD') : '')}
                slotProps={{ textField: { size: 'small', fullWidth: true } }}
              />
            </LocalizationProvider>
          </label>
        )}

        {kind === 'new-version' && (
          <p className="muted" style={{ gridColumn: '1 / -1', margin: 0 }}>
            {closingDate
              ? t('pages.tariffs.versions.closesPrevious', {
                date: formatShortDate(closingDate, settings),
              })
              : t('pages.tariffs.versions.pickLaterDate', {
                date: formatShortDate(source.valid_from, settings),
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

        {kind !== 'rename' && usesPercentage && (
          <label>
            <span>{t('pages.tariffs.form.percentage')}</span>
            <input
              type="number"
              step="0.01"
              min="0"
              max="100"
              value={percentage}
              onChange={(event) => setPercentage(event.target.value)}
              required
            />
          </label>
        )}

        {kind !== 'rename' && usesPeriods && (
          <div style={{ gridColumn: '1 / -1' }}>
            <strong>{t('pages.tariffs.versions.prices')}</strong>
            {periods.length === 0 ? (
              <p className="muted" style={{ marginTop: '0.5rem' }}>
                <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />{' '}
                {t('pages.tariffs.versions.noPricesToCopy')}
              </p>
            ) : (
              <div className="tariff-version-price-list">
                {periods.map((period, index) => (
                  <label key={`${period.period_type}-${index}`} className="tariff-version-price-row">
                    <span className="badge badge-neutral">
                      {t(`pages.tariffs.periodTypes.${period.period_type}` as Parameters<typeof t>[0], {
                        defaultValue: period.period_type,
                      })}
                    </span>
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
                  </label>
                ))}
              </div>
            )}
          </div>
        )}

        <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '1rem', justifyContent: 'flex-end', marginTop: '1rem' }}>
          <button className="button button-secondary" type="button" onClick={onClose}>
            <FontAwesomeIcon icon={faXmark} fixedWidth />
            {t('common.cancel')}
          </button>
          <button className="button button-primary" type="submit" disabled={submitDisabled}>
            <FontAwesomeIcon icon={faCheck} fixedWidth />
            {kind === 'rename' ? t('common.save') : t('common.create')}
          </button>
        </div>
      </form>
    </FormModal>
  )
}
